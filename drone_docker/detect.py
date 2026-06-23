#!/usr/bin/env python3

from __future__ import annotations

import argparse
import collections
import csv
import math
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, Optional

import joblib
import numpy as np
import torch
import torch.nn as nn
from pymavlink import mavutil


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

MODEL_DIR   = Path("model")
MODEL_PATH  = MODEL_DIR / "best_model.pt"
SCALER_PATH = MODEL_DIR / "scaler_tl.joblib"
THRESHOLD   = 0.5
SEQ_LEN     = 30
HIDDEN_SIZE = 64
NUM_LAYERS  = 2
DROPOUT     = 0.3
ATTN_HEADS  = 4

_DEFAULT_GEOID_SEP_M = 30.0

FEATURES = [
    "lat_deg", "lon_deg", "alt_m", "alt_ellipsoid_m",
    "eph", "epv", "hdop", "vdop",
    "s_variance_m_s", "c_variance_rad",
    "vel_m_s", "vel_n_m_s", "vel_e_m_s", "vel_d_m_s",
    "cog_rad", "satellites_used",
    "d_lat", "d_lon", "d_alt",
    "vel_from_pos", "vel_consistency",
    "noise_per_sat", "hdop_eph",
]
N_FEATURES = len(FEATURES)  # 23


# ─────────────────────────────────────────────────────────────────────────────
# ARCHITECTURE DU MODÈLE
# ─────────────────────────────────────────────────────────────────────────────

class SpatialDropout1d(nn.Module):
    def __init__(self, p: float):
        super().__init__()
        self.p = p

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if not self.training or self.p == 0:
            return x
        mask = torch.bernoulli(
            torch.full((x.size(0), 1, x.size(2)), 1 - self.p, device=x.device)
        )
        return x * mask / (1 - self.p + 1e-8)


class ResidualLSTMBlock(nn.Module):
    def __init__(self, input_size: int, hidden_size: int, dropout: float = 0.5):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, batch_first=True, bidirectional=True)
        self.norm = nn.LayerNorm(hidden_size * 2)
        self.spatial_drop = SpatialDropout1d(dropout * 0.6)
        self.drop = nn.Dropout(dropout)
        self.proj = (
            nn.Linear(input_size, hidden_size * 2)
            if input_size != hidden_size * 2
            else nn.Identity()
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        out = self.norm(out)
        out = self.spatial_drop(out)
        residual = self.proj(x)
        if residual.size(1) != out.size(1):
            min_len = min(residual.size(1), out.size(1))
            residual = residual[:, :min_len, :]
            out = out[:, :min_len, :]
        return self.drop(out + residual)


class GPSSpoofingDetector(nn.Module):
    def __init__(
        self,
        n_features: int = 23,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.5,
        attention_heads: int = 4,
    ):
        super().__init__()
        self.input_norm = nn.LayerNorm(n_features)
        self.input_proj = nn.Sequential(
            nn.Linear(n_features, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout * 0.5),
        )
        self.lstm_blocks = nn.ModuleList()
        current_size = hidden_size
        for _ in range(num_layers):
            self.lstm_blocks.append(ResidualLSTMBlock(current_size, hidden_size, dropout))
            current_size = hidden_size * 2
        self.attention = nn.MultiheadAttention(
            embed_dim=current_size,
            num_heads=attention_heads,
            dropout=dropout * 0.6,
            batch_first=True,
        )
        self.attn_drop = nn.Dropout(dropout * 0.5)
        self.attn_norm = nn.LayerNorm(current_size)
        feat_dim = current_size * 3
        self.classifier = nn.Sequential(
            nn.Linear(feat_dim, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, hidden_size // 2),
            nn.GELU(),
            nn.Dropout(dropout * 0.5),
            nn.Linear(hidden_size // 2, 2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.input_norm(x.float())
        x = self.input_proj(x)
        for block in self.lstm_blocks:
            x = block(x)
        attn_out, _ = self.attention(x, x, x)
        x = self.attn_norm(x + self.attn_drop(attn_out))
        mean_p = x.mean(dim=1)
        max_p  = x.max(dim=1)[0]
        last_p = x[:, -1, :]
        x = torch.cat([mean_p, max_p, last_p], dim=1)
        return self.classifier(x)


# ─────────────────────────────────────────────────────────────────────────────
# HAVERSINE
# ─────────────────────────────────────────────────────────────────────────────

_EARTH_R = 6_371_000.0

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTEUR DE FEATURES (23 features GPS)
# ─────────────────────────────────────────────────────────────────────────────

class FeatureExtractor:
    def __init__(self, geoid_sep_m: float = _DEFAULT_GEOID_SEP_M):
        self._lock = threading.Lock()
        self._gps:    Optional[object] = None
        self._gpos:   Optional[object] = None
        self._ekf:    Optional[object] = None
        self._prev:   Optional[Dict]   = None
        self._prev_ts_ms: Optional[float] = None
        self._geoid_sep = geoid_sep_m
        self._vel_history: collections.deque = collections.deque(maxlen=10)

    def update_gps(self, msg)  -> None:
        with self._lock: self._gps  = msg
    def update_gpos(self, msg) -> None:
        with self._lock: self._gpos = msg
    def update_ekf(self, msg)  -> None:
        with self._lock: self._ekf  = msg

    def extract(self) -> Optional[Dict]:
        with self._lock:
            gps     = self._gps
            gpos    = self._gpos
            ekf     = self._ekf
            prev    = self._prev
            prev_ts = self._prev_ts_ms

        if gps is None:
            return None

        ts_ms = gps.time_usec / 1000.0

        lat_deg = gps.lat / 1e7
        lon_deg = gps.lon / 1e7
        alt_m   = gps.alt / 1000.0

        raw_ae = getattr(gps, "alt_ellipsoid", None)
        if raw_ae is not None and raw_ae != gps.alt:
            alt_ellipsoid_m = raw_ae / 1000.0
        else:
            alt_ellipsoid_m = alt_m + self._geoid_sep

        hdop = gps.eph / 100.0 if gps.eph < 65535 else 99.9
        vdop = gps.epv / 100.0 if gps.epv < 65535 else 99.9

        h_acc_raw = getattr(gps, "h_acc", None)
        v_acc_raw = getattr(gps, "v_acc", None)
        eph = (h_acc_raw / 1000.0) if (h_acc_raw and h_acc_raw < 65535000) else hdop * 3.0
        epv = (v_acc_raw / 1000.0) if (v_acc_raw and v_acc_raw < 65535000) else vdop * 3.0

        vel_m_s = gps.vel / 100.0 if gps.vel < 65535 else 0.0
        cog_raw = gps.cog if gps.cog < 65535 else 0
        cog_rad = math.radians(cog_raw / 100.0)
        satellites_used = float(gps.satellites_visible)

        if gpos is not None:
            vel_n_m_s = gpos.vx / 100.0
            vel_e_m_s = gpos.vy / 100.0
            vel_d_m_s = gpos.vz / 100.0
        else:
            vel_n_m_s = vel_m_s * math.cos(cog_rad)
            vel_e_m_s = vel_m_s * math.sin(cog_rad)
            vel_d_m_s = 0.0

        if ekf is not None:
            s_variance_m_s = float(ekf.velocity_variance)
            c_variance_rad = float(ekf.compass_variance)
        else:
            s_variance_m_s = float(np.var(list(self._vel_history))) if len(self._vel_history) >= 3 else 0.01
            c_variance_rad = 0.0

        if prev is not None and prev_ts is not None:
            dt = max((ts_ms - prev_ts) / 1000.0, 1e-3)
            d_lat = lat_deg - prev["lat_deg"]
            d_lon = lon_deg - prev["lon_deg"]
            d_alt = alt_m   - prev["alt_m"]
            dist_m = haversine_m(prev["lat_deg"], prev["lon_deg"], lat_deg, lon_deg)
            vel_from_pos = dist_m / dt
        else:
            d_lat = d_lon = d_alt = 0.0
            vel_from_pos = vel_m_s

        vel_consistency = abs(vel_m_s - vel_from_pos)
        noise_per_sat   = eph / satellites_used if satellites_used > 0 else eph
        hdop_eph        = (hdop / eph) if eph > 1e-6 else 0.0

        row = {
            "lat_deg":         lat_deg,
            "lon_deg":         lon_deg,
            "alt_m":           alt_m,
            "alt_ellipsoid_m": alt_ellipsoid_m,
            "eph":             eph,
            "epv":             epv,
            "hdop":            hdop,
            "vdop":            vdop,
            "s_variance_m_s":  s_variance_m_s,
            "c_variance_rad":  c_variance_rad,
            "vel_m_s":         vel_m_s,
            "vel_n_m_s":       vel_n_m_s,
            "vel_e_m_s":       vel_e_m_s,
            "vel_d_m_s":       vel_d_m_s,
            "cog_rad":         cog_rad,
            "satellites_used": satellites_used,
            "d_lat":           d_lat,
            "d_lon":           d_lon,
            "d_alt":           d_alt,
            "vel_from_pos":    vel_from_pos,
            "vel_consistency": vel_consistency,
            "noise_per_sat":   noise_per_sat,
            "hdop_eph":        hdop_eph,
            "_ts_ms":          ts_ms,
            "_lat_raw":        lat_deg,
            "_lon_raw":        lon_deg,
            "_alt_raw":        alt_m,
            "_sats":           satellites_used,
        }

        with self._lock:
            self._prev       = row
            self._prev_ts_ms = ts_ms
            self._vel_history.append(vel_m_s)

        return row


# ─────────────────────────────────────────────────────────────────────────────
# DÉTECTEUR (fenêtre glissante + inférence CNN-LSTM)
# ─────────────────────────────────────────────────────────────────────────────

class Detector:
    def __init__(self, model_path: Path, scaler_path: Path,
                 seq_len: int = SEQ_LEN, step: int = 1):
        self.seq_len = seq_len
        self.step    = step
        self.device  = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.scaler  = joblib.load(scaler_path)
        self.model   = GPSSpoofingDetector(
            n_features=N_FEATURES,
            hidden_size=HIDDEN_SIZE,
            num_layers=NUM_LAYERS,
            dropout=DROPOUT,
            attention_heads=ATTN_HEADS,
        )
        state = torch.load(model_path, map_location=self.device, weights_only=False)
        self.model.load_state_dict(state)
        self.model.to(self.device)
        self.model.eval()

        self._window: Deque[np.ndarray] = collections.deque(maxlen=seq_len)
        self._last_prob  = 0.0
        self._last_label = 0
        self._n_since_infer = 0

    def push(self, row: Dict) -> Optional[float]:
        vec = np.array([row[f] for f in FEATURES], dtype=np.float32)
        vec = np.nan_to_num(vec, nan=0.0, posinf=5.0, neginf=-5.0)
        self._window.append(vec)
        self._n_since_infer += 1

        if len(self._window) < self.seq_len:
            return None

        if self._n_since_infer < self.step:
            return self._last_prob if self._last_prob > 0 else None
        self._n_since_infer = 0

        X = np.stack(self._window)
        X = self.scaler.transform(X)
        X = np.clip(X, -10, 10).astype(np.float32)
        t = torch.from_numpy(X).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = self.model(t)
            prob   = torch.softmax(logits, dim=1)[0, 1].item()

        self._last_prob  = prob
        self._last_label = int(prob >= THRESHOLD)
        return prob


# ─────────────────────────────────────────────────────────────────────────────
# AFFICHAGE
# ─────────────────────────────────────────────────────────────────────────────

_RESET  = "\033[0m"
_RED    = "\033[91m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_CYAN   = "\033[96m"
_BOLD   = "\033[1m"

def _bar(prob: float, width: int = 20) -> str:
    filled = int(prob * width)
    color  = _RED if prob >= THRESHOLD else _GREEN
    return color + "█" * filled + "░" * (width - filled) + _RESET

def _status_line(ts, lat, lon, alt, sats, prob, label, window_fill,
                 vel_consistency=None, noise_per_sat=None, hdop=None) -> str:
    if prob is None:
        status = f"{_YELLOW}BUFFERING ({window_fill}/{SEQ_LEN}){_RESET}"
    else:
        tag    = f"{_RED}{_BOLD}⚠  SPOOFED{_RESET}" if label else f"{_GREEN}✓  CLEAN  {_RESET}"
        status = f"{tag}  [{_bar(prob)}] {prob*100:5.1f}%"
    qual = ""
    if hdop is not None:       qual += f"  HDOP:{hdop:.2f}"
    if noise_per_sat is not None: qual += f"  nps:{noise_per_sat:.3f}"
    if vel_consistency is not None: qual += f"  |ΔV|:{vel_consistency:.2f}m/s"
    return (
        f"\r[{ts}] "
        f"Lat:{lat:10.6f}  Lon:{lon:11.6f}  Alt:{alt:7.1f}m  "
        f"Sats:{sats:2d}  │  {status}{_CYAN}{qual}{_RESET}   "
    )


# ─────────────────────────────────────────────────────────────────────────────
# LISTENER MAVLink (thread)
# ─────────────────────────────────────────────────────────────────────────────

def _listen_mavlink(conn_str, extractor, stop_event):
    print(f"  Connecting to MAVLink: {conn_str} …")
    mav = mavutil.mavlink_connection(conn_str, autoreconnect=True)
    mav.wait_heartbeat(timeout=30)
    print(f"  Heartbeat received — system {mav.target_system}, component {mav.target_component}")
    mav.mav.request_data_stream_send(
        mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_ALL, 10, 1,
    )
    while not stop_event.is_set():
        msg = mav.recv_match(
            type=["GPS_RAW_INT", "GLOBAL_POSITION_INT", "EKF_STATUS_REPORT"],
            blocking=True, timeout=1.0,
        )
        if msg is None:
            continue
        t = msg.get_type()
        if   t == "GPS_RAW_INT":         extractor.update_gps(msg)
        elif t == "GLOBAL_POSITION_INT":  extractor.update_gpos(msg)
        elif t == "EKF_STATUS_REPORT":    extractor.update_ekf(msg)


# ─────────────────────────────────────────────────────────────────────────────
# CSV LOGGER
# ─────────────────────────────────────────────────────────────────────────────

class CsvLogger:
    def __init__(self, path: str):
        self._file   = open(path, "w", newline="")
        self._writer = csv.DictWriter(
            self._file, fieldnames=FEATURES + ["timestamp_ms", "spoof_prob", "spoof_label"])
        self._writer.writeheader()

    def log(self, row: Dict, prob: Optional[float], label: int) -> None:
        record = {f: row.get(f, 0.0) for f in FEATURES}
        record["timestamp_ms"] = row.get("_ts_ms", 0.0)
        record["spoof_prob"]   = round(prob, 4) if prob is not None else ""
        record["spoof_label"]  = label if prob is not None else ""
        self._writer.writerow(record)
        self._file.flush()

    def close(self) -> None:
        self._file.close()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="GPS Spoofing Detector v2 — temps réel")
    parser.add_argument("--connection",  default="udp:0.0.0.0:14553")
    parser.add_argument("--model-dir",   default=str(MODEL_DIR))
    parser.add_argument("--seq-len",     type=int,   default=SEQ_LEN)
    parser.add_argument("--step",        type=int,   default=1)
    parser.add_argument("--save",        default=None)
    parser.add_argument("--threshold",   type=float, default=THRESHOLD)
    parser.add_argument("--geoid-sep",   type=float, default=_DEFAULT_GEOID_SEP_M)
    args = parser.parse_args()

    model_dir   = Path(args.model_dir)
    model_path  = model_dir / "best_model.pt"
    scaler_path = model_dir / "scaler_tl.joblib"

    for pth in (model_path, scaler_path):
        if not pth.exists():
            print(f"[ERROR] Fichier introuvable: {pth}"); sys.exit(1)

    print("\n" + "=" * 70)
    print("  GPS SPOOFING DETECTOR v2 — Temps réel (MAVLink)")
    print("=" * 70)
    print(f"  Modèle     : {model_path}")
    print(f"  Scaler     : {scaler_path}")
    print(f"  Seuil      : {args.threshold}")
    print(f"  Fenêtre    : {args.seq_len} trames  (step={args.step})")
    print(f"  Géoïde sep : {args.geoid_sep:.1f}m")
    if args.save: print(f"  Log CSV    : {args.save}")
    print("=" * 70)

    print("\n  Chargement du modèle …", end=" ", flush=True)
    detector  = Detector(model_path, scaler_path, seq_len=args.seq_len, step=args.step)
    extractor = FeatureExtractor(geoid_sep_m=args.geoid_sep)
    stop_evt  = threading.Event()
    logger    = CsvLogger(args.save) if args.save else None

    threading.Thread(
        target=_listen_mavlink,
        args=(args.connection, extractor, stop_evt),
        daemon=True,
    ).start()
    print("OK")
    print("\n  En attente de données GPS … (Ctrl-C pour arrêter)\n")

    stats = {"total": 0, "spoof": 0}
    last_ts_ms = 0.0

    try:
        while True:
            row = extractor.extract()
            if row is None:
                time.sleep(0.05); continue
            ts_ms = row["_ts_ms"]
            if ts_ms == last_ts_ms:
                time.sleep(0.02); continue
            last_ts_ms = ts_ms

            prob  = detector.push(row)
            label = detector._last_label if prob is not None else 0

            if prob is not None:
                stats["total"] += 1
                if label: stats["spoof"] += 1

            if logger: logger.log(row, prob, label)

            ts_str = datetime.utcnow().strftime("%H:%M:%S.%f")[:-3]
            print(_status_line(
                ts_str,
                row["_lat_raw"], row["_lon_raw"], row["_alt_raw"],
                int(row["_sats"]), prob, label, len(detector._window),
                vel_consistency=row.get("vel_consistency"),
                noise_per_sat=row.get("noise_per_sat"),
                hdop=row.get("hdop"),
            ), end="", flush=True)

            if prob is not None and label:
                spoof_pct = 100.0 * stats["spoof"] / max(stats["total"], 1)
                print(
                    f"\n  {_RED}{_BOLD}[ALERT]{_RESET} GPS SPOOFING DÉTECTÉ — "
                    f"p={prob:.3f}  |  {stats['spoof']}/{stats['total']} ({spoof_pct:.1f}%)"
                )
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n\n  Arrêt …")
    finally:
        stop_evt.set()
        if logger: logger.close(); print(f"  Données sauvegardées : {args.save}")
        total = stats["total"]; spoof = stats["spoof"]
        if total:
            print(f"\n  Résumé : {total} inférences | "
                  f"{spoof} spoofed ({100*spoof/total:.1f}%) | "
                  f"{total-spoof} clean ({100*(total-spoof)/total:.1f}%)")
        print("  Terminé.\n")


if __name__ == "__main__":
    main()
