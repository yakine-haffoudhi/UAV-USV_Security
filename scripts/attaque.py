#!/usr/bin/env python3

from __future__ import annotations

import argparse
import math
import socket
import threading
import time
from datetime import datetime
from typing import Dict, Optional

from pymavlink import mavutil

_R = "\033[91m"; _G = "\033[92m"; _Y = "\033[93m"; _B = "\033[1m"; _X = "\033[0m"


# ─────────────────────────────────────────────────────────────────────────────
# PROFILS D'ATTAQUE
# ─────────────────────────────────────────────────────────────────────────────

class AttackProfile:
    name = "base"
    def __init__(self, noise_level: float = 1.0, **kw):
        self.t0 = time.time()
        self.noise_level = noise_level

    def elapsed(self): return time.time() - self.t0

    def _degrade_signal(self, s: Dict, sat_factor: float, dop_factor: float) -> Dict:
        s["sats"] = max(int(s["sats"] * sat_factor), 3)
        s["hdop"] = s["hdop"] * dop_factor * self.noise_level
        s["vdop"] = s["vdop"] * dop_factor * self.noise_level
        s["h_acc_sim"] = s.get("h_acc_sim", 2.0) * dop_factor * self.noise_level
        return s

    def compute_spoof(self, real: Dict) -> Dict:
        raise NotImplementedError


class DriftAttack(AttackProfile):
    """Dérive progressive de la position GPS."""
    name = "drift"

    def __init__(self, drift_rate_m_s=0.5, direction_deg=0.0,
                 degrade=True, noise_level=1.0, **kw):
        super().__init__(noise_level=noise_level, **kw)
        self.rate    = drift_rate_m_s
        self.dir     = math.radians(direction_deg)
        self.degrade = degrade

    def compute_spoof(self, real):
        dist  = self.rate * self.elapsed()
        d_lat = (dist * math.cos(self.dir)) / 111_111.0
        d_lon = (dist * math.sin(self.dir)) / (
            111_111.0 * math.cos(math.radians(real["lat"])))
        s = real.copy()
        s["lat"] = real["lat"] + d_lat
        s["lon"] = real["lon"] + d_lon
        s["vn"]  = real.get("vn", 0.0) + self.rate * math.cos(self.dir)
        s["ve"]  = real.get("ve", 0.0) + self.rate * math.sin(self.dir)
        if self.degrade:
            self._degrade_signal(s, sat_factor=0.55, dop_factor=2.2)
        return s


class JumpAttack(AttackProfile):
    """Saut instantané de position."""
    name = "jump"

    def __init__(self, offset_lat=0.003, offset_lon=0.003, offset_alt=0.0,
                 delay_s=5.0, noise_level=1.0, **kw):
        super().__init__(noise_level=noise_level, **kw)
        self.olat  = offset_lat
        self.olon  = offset_lon
        self.oalt  = offset_alt
        self.delay = delay_s
        self._jumped = False

    def compute_spoof(self, real):
        if self.elapsed() < self.delay:
            return real.copy()
        s = real.copy()
        s["lat"] += self.olat
        s["lon"] += self.olon
        s["alt"] += self.oalt
        s["vn"] = s["ve"] = s["vd"] = 0.0
        self._jumped = True
        self._degrade_signal(s, sat_factor=0.5, dop_factor=2.5)
        return s


class CircleAttack(AttackProfile):
    """Déplace le drone en cercle autour de sa position initiale."""
    name = "circle"

    def __init__(self, radius_m=30.0, period_s=30.0, noise_level=1.0, **kw):
        super().__init__(noise_level=noise_level, **kw)
        self.radius  = radius_m
        self.period  = period_s
        self._clat   = self._clon = None

    def compute_spoof(self, real):
        if self._clat is None:
            self._clat, self._clon = real["lat"], real["lon"]
        theta = 2 * math.pi * self.elapsed() / self.period
        s = real.copy()
        s["lat"] = self._clat + (self.radius * math.cos(theta)) / 111_111.0
        s["lon"] = self._clon + (self.radius * math.sin(theta)) / (
            111_111.0 * math.cos(math.radians(self._clat)))
        v_tan  = (2 * math.pi / self.period) * self.radius
        s["vn"] = -v_tan * math.sin(theta)
        s["ve"] =  v_tan * math.cos(theta)
        self._degrade_signal(s, sat_factor=0.7, dop_factor=1.5)
        return s


class ReplayAttack(AttackProfile):
    """Rejoue un enregistrement de position passée."""
    name = "replay"

    def __init__(self, buffer_s=20.0, noise_level=1.0, **kw):
        super().__init__(noise_level=noise_level, **kw)
        self.buffer_s    = buffer_s
        self._buf        = []
        self._recording  = True
        self._rep_start  = 0.0

    def compute_spoof(self, real):
        t = self.elapsed()
        if self._recording:
            self._buf.append(real.copy())
            if t >= self.buffer_s and len(self._buf) > 5:
                self._recording = False
                self._rep_start = t
                print(f"\n  {_Y}[REPLAY] {len(self._buf)} frames — replay démarré{_X}")
            return real.copy()
        idx = int(((t - self._rep_start) / self.buffer_s) * len(self._buf)) % len(self._buf)
        s = self._buf[idx].copy()
        self._degrade_signal(s, sat_factor=0.8, dop_factor=1.3)
        return s


class SatDropAttack(AttackProfile):
    """Chute brutale du nombre de satellites (brouillage)."""
    name = "sat_drop"

    def __init__(self, min_sats=3, hdop_boost=4.0, noise_level=1.0, **kw):
        super().__init__(noise_level=noise_level, **kw)
        self.min_sats   = min_sats
        self.hdop_boost = hdop_boost

    def compute_spoof(self, real):
        s = real.copy()
        s["sats"]      = self.min_sats
        s["hdop"]      = real["hdop"] * self.hdop_boost * self.noise_level
        s["vdop"]      = real["vdop"] * self.hdop_boost * self.noise_level
        s["h_acc_sim"] = real.get("h_acc_sim", 2.0) * self.hdop_boost * self.noise_level
        return s


class VelocitySpoof(AttackProfile):
    """Injecte des vitesses fausses sans changer la position."""
    name = "velocity_spoof"

    def __init__(self, speed_mult=3.0, noise_level=1.0, **kw):
        super().__init__(noise_level=noise_level, **kw)
        self.mult = speed_mult

    def compute_spoof(self, real):
        s = real.copy()
        s["vn"] = real.get("vn", 0) * self.mult
        s["ve"] = real.get("ve", 0) * self.mult
        s["vd"] = real.get("vd", 0) * self.mult
        self._degrade_signal(s, sat_factor=0.9, dop_factor=1.2)
        return s


PROFILES = {
    "drift":          DriftAttack,
    "jump":           JumpAttack,
    "circle":         CircleAttack,
    "replay":         ReplayAttack,
    "sat_drop":       SatDropAttack,
    "velocity_spoof": VelocitySpoof,
}


# ─────────────────────────────────────────────────────────────────────────────
# PROXY MitM → détecteur
# ─────────────────────────────────────────────────────────────────────────────

class MavProxy:
    def __init__(self, fwd_host, fwd_port, src_system=1):
        self._addr = (fwd_host, fwd_port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._out  = mavutil.mavlink_connection(
            f"udpout:{fwd_host}:{fwd_port}", source_system=src_system)
        self._lock  = threading.Lock()
        self._spoof = None

    def set_spoof(self, spoof):
        with self._lock: self._spoof = spoof

    def forward(self, msg, real_gps=None):
        with self._lock: spoof = self._spoof
        t = msg.get_type()

        if t == "GPS_RAW_INT" and spoof is not None:
            vel = math.sqrt(spoof.get("vn", 0)**2 + spoof.get("ve", 0)**2)
            hdop_mav = min(int(spoof.get("hdop", msg.eph / 100.0) * 100), 65534)
            vdop_mav = min(int(spoof.get("vdop", msg.epv / 100.0) * 100), 65534)
            sats_mav = max(int(spoof.get("sats", msg.satellites_visible)), 3)
            try:
                self._out.mav.gps_raw_int_send(
                    msg.time_usec, msg.fix_type,
                    int(spoof["lat"] * 1e7),
                    int(spoof["lon"] * 1e7),
                    int(spoof["alt"] * 1000),
                    hdop_mav, vdop_mav,
                    int(vel * 100),
                    msg.cog,
                    sats_mav,
                )
            except Exception:
                pass

        elif t == "GLOBAL_POSITION_INT" and spoof is not None:
            try:
                self._out.mav.global_position_int_send(
                    msg.time_boot_ms,
                    int(spoof["lat"] * 1e7),
                    int(spoof["lon"] * 1e7),
                    int(spoof["alt"] * 1000),
                    msg.relative_alt,
                    int(spoof.get("vn", 0) * 100),
                    int(spoof.get("ve", 0) * 100),
                    int(spoof.get("vd", 0) * 100),
                    msg.hdg,
                )
            except Exception:
                pass
        else:
            buf = msg.get_msgbuf()
            if buf:
                try: self._sock.sendto(bytes(buf), self._addr)
                except Exception: pass


# ─────────────────────────────────────────────────────────────────────────────
# CONTRÔLEUR DRONE
# ─────────────────────────────────────────────────────────────────────────────

class DroneController:
    def __init__(self, mav: mavutil.mavfile, rate_hz: float = 4.0):
        self.mav     = mav
        self.rate    = rate_hz
        self._lock   = threading.Lock()
        self._target: Optional[Dict] = None
        self._active = threading.Event()
        self._stop   = threading.Event()
        self._sent   = 0

    def set_target(self, spoof: Optional[Dict]):
        with self._lock:
            self._target = spoof.copy() if spoof else None
        if spoof: self._active.set()
        else:     self._active.clear()

    def _set_guided_mode(self):
        GUIDED = 15  # ArduRover GUIDED = 15
        hb = self.mav.recv_match(type="HEARTBEAT", blocking=True, timeout=2.0)
        if hb and hb.custom_mode != GUIDED:
            print(f"\n  {_Y}[CTRL] Passage en mode GUIDED…{_X}", end=" ", flush=True)
            self.mav.set_mode(GUIDED)
            time.sleep(0.8)
            hb2 = self.mav.recv_match(type="HEARTBEAT", blocking=True, timeout=2.0)
            print("OK" if (hb2 and hb2.custom_mode == GUIDED) else "MANUEL REQUIS")

    def _send(self, spoof: Dict) -> bool:
        TYPE_MASK = 0b0000_1111_1000
        try:
            self.mav.mav.set_position_target_global_int_send(
                int(time.time() * 1000) & 0xFFFFFFFF,
                self.mav.target_system, self.mav.target_component,
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                TYPE_MASK,
                int(spoof["lat"] * 1e7),
                int(spoof["lon"] * 1e7),
                float(spoof.get("rel_alt", 10.0)),
                float(spoof.get("vn", 0.0)),
                float(spoof.get("ve", 0.0)),
                float(spoof.get("vd", 0.0)),
                0.0, 0.0, 0.0, 0.0, 0.0,
            )
            self._sent += 1
            return True
        except Exception as exc:
            print(f"\n  [CTRL] Erreur: {exc}")
            return False

    def run(self):
        period = 1.0 / self.rate
        time.sleep(1.5)
        self._set_guided_mode()
        last = 0.0
        while not self._stop.is_set():
            self._active.wait(timeout=0.5)
            now = time.time()
            if now - last < period:
                time.sleep(0.005)
                continue
            last = now
            with self._lock: t = self._target
            if t: self._send(t)

    def stop(self): self._stop.set(); self._active.set()

    @property
    def sent_count(self): return self._sent


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_gps(msg) -> Optional[Dict]:
    try:
        return {
            "lat":       msg.lat / 1e7,
            "lon":       msg.lon / 1e7,
            "alt":       msg.alt / 1000.0,
            "rel_alt":   10.0,
            "vn": 0.0, "ve": 0.0, "vd": 0.0,
            "hdop":      msg.eph / 100.0 if msg.eph < 65535 else 9.99,
            "vdop":      msg.epv / 100.0 if msg.epv < 65535 else 9.99,
            "sats":      int(msg.satellites_visible),
            "fix":       int(msg.fix_type),
            "h_acc_sim": 2.0,
        }
    except Exception:
        return None


def _dist_m(lat1, lon1, lat2, lon2):
    dlat = (lat2 - lat1) * 111_111.0
    dlon = (lon2 - lon1) * 111_111.0 * math.cos(math.radians(lat1))
    return math.sqrt(dlat**2 + dlon**2)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="GPS Spoofing Simulator — ArduCopter/ArduRover SITL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mg = p.add_mutually_exclusive_group()
    mg.add_argument("--mode-sitl",  action="store_true", help="Drone bouge seulement")
    mg.add_argument("--mode-proxy", action="store_true", help="Proxy détecteur seulement")
    mg.add_argument("--mode-both",  action="store_true", help="Drone + proxy (défaut)")

    p.add_argument("--connection",       default="udp:0.0.0.0:14552")
    p.add_argument("--forward-host",     default="127.0.0.1")
    p.add_argument("--forward-port",     type=int, default=14553)
    p.add_argument("--attack",           default="drift", choices=list(PROFILES.keys()))
    p.add_argument("--duration",         type=float, default=0)
    p.add_argument("--pre-attack-delay", type=float, default=20.0)
    p.add_argument("--control-rate",     type=float, default=4.0)
    p.add_argument("--no-degrade",       action="store_true")
    p.add_argument("--noise-level",      type=float, default=1.0)
    # Paramètres des profils
    p.add_argument("--drift-rate",  type=float, default=0.5)
    p.add_argument("--direction",   type=float, default=0.0)
    p.add_argument("--offset-lat",  type=float, default=0.003)
    p.add_argument("--offset-lon",  type=float, default=0.003)
    p.add_argument("--offset-alt",  type=float, default=0.0)
    p.add_argument("--delay",       type=float, default=5.0)
    p.add_argument("--radius",      type=float, default=30.0)
    p.add_argument("--period",      type=float, default=30.0)
    p.add_argument("--min-sats",    type=int,   default=3)
    p.add_argument("--speed-mult",  type=float, default=3.0)
    p.add_argument("--buffer",      type=float, default=20.0)

    args = p.parse_args()

    if args.mode_sitl:    sim_mode = "sitl"
    elif args.mode_proxy: sim_mode = "proxy"
    else:                 sim_mode = "both"

    do_control = sim_mode in ("sitl", "both")
    do_proxy   = sim_mode in ("proxy", "both")

    print("\n" + "=" * 70)
    print("  GPS SPOOFING SIMULATOR — ArduCopter/ArduRover SITL")
    print("=" * 70)
    print(f"  Mode     : {sim_mode.upper()}")
    print(f"  Attaque  : {_R}{_B}{args.attack.upper()}{_X}")
    print(f"  Proxy    : {'→ port ' + str(args.forward_port) if do_proxy else '✗'}")
    print("=" * 70)

    degrade = not args.no_degrade
    kw = {"noise_level": args.noise_level}
    if args.attack == "drift":
        kw.update({"drift_rate_m_s": args.drift_rate, "direction_deg": args.direction, "degrade": degrade})
    elif args.attack == "jump":
        kw.update({"offset_lat": args.offset_lat, "offset_lon": args.offset_lon,
                   "offset_alt": args.offset_alt, "delay_s": args.delay})
    elif args.attack == "circle":
        kw.update({"radius_m": args.radius, "period_s": args.period})
    elif args.attack == "replay":
        kw.update({"buffer_s": args.buffer})
    elif args.attack == "sat_drop":
        kw.update({"min_sats": args.min_sats})
    elif args.attack == "velocity_spoof":
        kw.update({"speed_mult": args.speed_mult})

    profile       = PROFILES[args.attack](**kw)
    profile_armed = False

    print(f"\n  Connexion: {args.connection} …", end=" ", flush=True)
    mav = mavutil.mavlink_connection(args.connection, autoreconnect=True)
    mav.wait_heartbeat(timeout=30)
    print("OK")

    mav.mav.request_data_stream_send(
        mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_ALL, 10, 1)

    proxy      = MavProxy(args.forward_host, args.forward_port,
                          src_system=mav.target_system) if do_proxy else None
    controller = None
    if do_control:
        controller = DroneController(mav, rate_hz=args.control_rate)
        threading.Thread(target=controller.run, daemon=True).start()

    print(f"\n  Pré-attaque : {args.pre_attack_delay:.0f}s | Attaque : {args.attack}")
    print("  En attente … (Ctrl-C pour arrêter)\n")

    real_gps: Optional[Dict] = None
    t_start   = time.time()
    _last_disp = 0.0

    try:
        while True:
            if args.duration > 0 and (time.time() - t_start) > args.duration:
                break

            msg = mav.recv_match(
                type=["GPS_RAW_INT", "GLOBAL_POSITION_INT", "HEARTBEAT"],
                blocking=True, timeout=1.0)
            if msg is None:
                continue

            mt = msg.get_type()
            if mt == "GPS_RAW_INT":
                g = _parse_gps(msg)
                if g: real_gps = g
            elif mt == "GLOBAL_POSITION_INT" and real_gps is not None:
                real_gps["vn"]      = msg.vx / 100.0
                real_gps["ve"]      = msg.vy / 100.0
                real_gps["vd"]      = msg.vz / 100.0
                real_gps["rel_alt"] = msg.relative_alt / 1000.0

            if real_gps is None:
                if proxy: proxy.forward(msg)
                continue

            elapsed = time.time() - t_start
            pre     = elapsed < args.pre_attack_delay

            if pre:
                if proxy: proxy.set_spoof(None); proxy.forward(msg)
                if controller: controller.set_target(None)
            else:
                if not profile_armed:
                    profile.t0 = time.time(); profile_armed = True
                    print(f"\n\n  {_R}{_B}[ATTACK START]{_X} {args.attack.upper()}\n")

                spoof = profile.compute_spoof(real_gps)
                if proxy: proxy.set_spoof(spoof); proxy.forward(msg, real_gps)
                if controller: controller.set_target(spoof)

            now = time.time()
            if now - _last_disp < 0.20: continue
            _last_disp = now
            ts = datetime.utcnow().strftime("%H:%M:%S")

            if pre:
                rem = args.pre_attack_delay - elapsed
                print(f"\r[{ts}] {_G}PRE-ATTACK{_X}  "
                      f"lat={real_gps['lat']:.5f}  lon={real_gps['lon']:.5f}  "
                      f"sats={real_gps['sats']}  hdop={real_gps['hdop']:.2f}  "
                      f"attaque dans {rem:.0f}s   ", end="", flush=True)
            else:
                sp   = profile.compute_spoof(real_gps)
                dist = _dist_m(real_gps["lat"], real_gps["lon"], sp["lat"], sp["lon"])
                ctrl = f"  cmds={controller.sent_count}" if controller else ""
                sat_delta  = real_gps["sats"] - sp.get("sats", real_gps["sats"])
                hdop_ratio = sp.get("hdop", real_gps["hdop"]) / max(real_gps["hdop"], 0.01)
                print(f"\r[{ts}] {_R}{_B}ATTACK{_X}  "
                      f"Δpos={dist:6.1f}m  Δsats=-{sat_delta}  HDOP×{hdop_ratio:.1f}  "
                      f"real=({real_gps['lat']:.5f},{real_gps['lon']:.5f})  "
                      f"spoof=({sp['lat']:.5f},{sp['lon']:.5f}){ctrl}   ",
                      end="", flush=True)

    except KeyboardInterrupt:
        print("\n\n  Arrêt …")
    finally:
        if controller: controller.stop()
        print("  Terminé.\n")


if __name__ == "__main__":
    main()
