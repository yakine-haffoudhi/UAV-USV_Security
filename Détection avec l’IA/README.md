# GPS Spoofing Detection

Détection en temps réel des attaques GPS sur drones/bateaux autonomes via analyse du flux MAVLink.

---

## Architecture du modèle

```
MAVLink (UDP) → FeatureExtractor (23 features) → BiLSTM × 2 → Multi-Head Attention → Classifier
```

| Composant | Détail |
|---|---|
| **Entrée** | Fenêtre glissante de 30 trames GPS+EKF |
| **BiLSTM** | 2 couches, hidden=64, bidirectionnel + connexions résiduelles |
| **Attention** | Multi-Head (4 têtes) sur la séquence BiLSTM |
| **Sortie** | Probabilité de spoofing ∈ [0, 1] |
| **Seuil** | 0.72 (configurable via `--threshold`) |

---

## Les 23 features extraites

| Catégorie | Features |
|---|---|
| Position | `lat_deg`, `lon_deg`, `alt_m`, `alt_ellipsoid_m` |
| Précision GPS | `eph`, `epv`, `hdop`, `vdop` |
| Vitesse (EKF) | `vel_m_s`, `vel_n_m_s`, `vel_e_m_s`, `vel_d_m_s`, `cog_rad` |
| Variances EKF | `s_variance_m_s`, `c_variance_rad` |
| Satellites | `satellites_used` |
| Features dérivées | `d_lat`, `d_lon`, `d_alt`, `vel_from_pos`, `vel_consistency`, `noise_per_sat`, `hdop_eph` |

Les features dérivées sont la clé de la détection : `vel_consistency = |vel_GPS - vel_from_position|` diverge fortement lors d'un spoofing.

---

## Performances

| Métrique | Valeur |
|---|---|
| AUC-ROC | 0.893 |
| Recall | 85.9 % |
| Précision | 67.9 % |
| Seuil optimal | 0.72 |

---

## Lancement

```bash
# Dérive rapide vers le Nord
python3 ~/attacks/attaque.py --drift-rate 2.0 --direction 0

# Dérive lente vers le Sud-Est, déclenche après 30s
python3 ~/attacks/attaque.py --drift-rate 0.3 --direction 135 --pre-attack 30


# Terminal détection
cd ~/
python3 detect.py --connection udp:0.0.0.0:14551 --threshold 0.72 \
    --save ~/logs/detection.csv
```

**Options :**

| Option | Défaut | Description |
|---|---|---|
| `--connection` | `udp:0.0.0.0:14551` | Port MAVLink écouté |
| `--threshold` | `0.5` | Seuil de décision (0.72 recommandé) |
| `--seq-len` | `30` | Taille de la fenêtre (trames) |
| `--step` | `1` | Inférence toutes les N trames |
| `--save` | aucun | Chemin CSV de sauvegarde |
| `--geoid-sep` | `30.0` | Séparation géoïde locale (m) |

---

## Sortie terminal

```
[21:03:12.441] Lat: 48.350012  Lon: -4.499987  Alt:   0.0m  Sats:10  | ✓  CLEAN   [████████░░░░░░░░░░░░]  42.1%
[21:03:45.112] Lat: 48.350891  Lon: -4.498234  Alt:   0.0m  Sats:10  | ⚠  SPOOFED [█████████████░░░░░░░]  64.7%

  [ALERT] GPS SPOOFING DETECTED — p=0.947 | 3/8 (37.5%)
```

---

## Fichiers modèle

| Fichier | Rôle |
|---|---|
| `model/best_model.pt` | Poids PyTorch du BiLSTM entraîné |
| `model/scaler_tl.joblib` | StandardScaler (normalisation des 23 features) |

---

Le détecteur reçoit le flux MAVLink sur le port 14551 et lève une alerte dès que la probabilité de spoofing dépasse le seuil.
