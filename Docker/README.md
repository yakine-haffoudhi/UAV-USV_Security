# UAV/USV Security Lab

## Structure du projet

```
uav-usv-lab/
├── base/                        ← image commune (Python, MAVProxy, Wireshark)
│   └── Dockerfile
├── ardupilot-uav/               ← ArduCopter SITL
│   └── Dockerfile
├── ardupilot-usv-gazebo/        ← ArduRover SITL + Gazebo Harmonic
│   └── Dockerfile
├── qgroundcontrol/              ← QGroundControl GCS
│   ├── Dockerfile
│   └── QGroundControl-x86_64.AppImage   ← à télécharger avant le build
├── attacker/                    ← GPS Spoof 
│   └── Dockerfile
├── shared/
│   ├── missions/                ← fichiers .txt partagés entre containers
│   └── scripts/                 ← scripts personnalisés montés dans attacker
├── captures/                    ← captures pcap (créé automatiquement)
└── docker-compose.yml
```

## Architecture réseau

```
┌─────────────── mavlink-net 172.20.0.0/24 ───────────────┐
│                                                           │
│  ardupilot-uav       ardupilot-usv-gazebo  qgroundcontrol│
│  172.20.0.10         172.20.0.11           172.20.0.12   │
│  :14550 :14551       :14560 :14561                       │
│                                                           │
│  attacker  172.20.0.20 ──────── 172.21.0.20              │
│                         attacker-net 172.21.0.0/24        │
└───────────────────────────────────────────────────────────┘
```

## Étape 1 — Pré-requis : télécharger QGroundControl

```bash
cd ~/uav-usv-lab
wget "https://d176tv9ibo4jno.cloudfront.net/latest/QGroundControl-x86_64.AppImage" \
     -O qgroundcontrol/QGroundControl-x86_64.AppImage
```

## Étape 2 — Construire toutes les images

```bash
# Base d'abord
docker compose build base

# Puis tout le reste
docker compose build
```

## Étape 3 — Démarrer

```bash
# Simulation complète (UAV + USV + GCS)
docker compose up

# Uniquement UAV + GCS
docker compose up ardupilot-uav qgroundcontrol

# Uniquement USV 2D + GCS
docker compose up ardupilot-usv-gazebo qgroundcontrol

# USV en 3D Gazebo (modifier command: rover → gazebo dans compose)
docker compose up ardupilot-usv-gazebo
```

## Étape 4 — Attaques GPS

```bash
# Drift USV (0.5 m/s vers l'Est, observation 10s avant)
docker compose run --rm attacker spoof-usv

# Drift USV rapide (2 m/s, observation 5s)
docker compose run --rm attacker spoof-usv-fast

# Circle UAV — activer d'abord GPS1_TYPE=14 :
#   docker exec -it uav-sitl /opt/lab/start.sh mavproxy
#   > param set GPS1_TYPE 14
docker compose run --rm attacker spoof-uav
```

## Capture et analyse MAVLink

```bash
# Capturer 
docker compose run --rm attacker capture eth0

# Lire une capture
docker compose run --rm attacker read --file /opt/lab/captures/mavlink_*.pcap

# Filtrer sur des types de messages
docker compose run --rm attacker read \
    --file /opt/lab/captures/mavlink_*.pcap \
    --types GPS_RAW_INT HEARTBEAT ATTITUDE
```

## MAVProxy manuel

```bash
# Connexion MAVProxy vers UAV
docker compose run --rm attacker mavproxy-uav

# Connexion MAVProxy vers USV
docker compose run --rm attacker mavproxy-usv

# Shell dans le container UAV
docker exec -it uav-sitl bash
```

## QGroundControl avec interface graphique

```bash
# Sur l'hôte Linux : autoriser X11
xhost +local:docker

# Relancer QGC avec GUI
QGC_MODE=gcs docker compose up qgroundcontrol
```

Connexion dans QGC :
- UDP entrant port **14550** → UAV
- UDP entrant port **14560** → USV
