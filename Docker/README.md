# Drone Security Lab — Docker
 
Simulation 3D Gazebo + ArduRover SITL + attaque GPS + détection IA, le tout dans un conteneur Docker accessible via navigateur.

---

## Structure du projet

```
drone_docker/
├── Dockerfile            ← image complète (autosuffisante)
├── docker-compose.yml    ← lancement simplifié
├── .dockerignore
├── detect.py             ← détecteur IA BiLSTM (temps réel)
├── attacks/
│   └── attaque.py        ← GPS drift spoofer
└── model/
    ├── best_model.pt     ← poids PyTorch
    └── scaler_tl.joblib  ← scaler sklearn
```

---

## Prérequis

- Docker Engine 20.10+
- 20 Go d'espace disque libre
- 8 Go de RAM recommandés

---

## Build

```bash
cd drone_docker
docker build -t drone-lab .
```

> Durée : ~30-60 min (compilation ArduPilot + Gazebo + asv_wave_sim)  

**Build sans cache (repartir de zéro) :**
```bash
docker build --no-cache -t drone-lab .
```

---

## Lancer le conteneur

```bash
docker run -d --name drone-lab \
    -p 5900:5900 \
    -p 6080:6080 \
    -p 14550:14550/udp \
    -p 14551:14551/udp \
    -p 14552:14552/udp \
    --shm-size=512m \
    drone-lab:latest
```

Ou avec Docker Compose :
```bash
docker compose up -d
```

---

## Accès VNC

Ouvrir dans le navigateur :
```
http://localhost:6080/vnc.html
```
Cliquer **Connect** — pas de mot de passe.

VNC natif (port 5900) : `localhost:5900`

---

## Scénario de démonstration

Ouvrir **5 terminaux** dans le bureau VNC :

### Terminal 1 — Simulation Gazebo + ArduRover

```bash
~/scripts/start_sim.sh
```

Lance Gazebo Harmonic (BlueBoat + vagues FFT) et ArduRover SITL couplés via JSON.  
Attendre ~35 secondes que tout démarre.

### Terminal 2 — Configuration MAVProxy

Dans la console MAVProxy qui s'ouvre avec le Terminal 1 :

```
param set FRAME_CLASS 2
param set FRAME_TYPE 1
param set SIM_WAVE_ENABLE 1
param set SIM_WAVE_AMP 0.5
param set SIM_WAVE_DIR 180
param set SIM_WIND_SPD 5
param set SIM_WIND_DIR 270
param set ARMING_CHECK 0
arm throttle
mode GUIDED
```

### Terminal 3 — QGroundControl

```bash
~/scripts/start_qgc.sh
```

QGroundControl se connecte automatiquement sur `udp:127.0.0.1:14550` et affiche la carte + télémétrie.

### Terminal 4 — Attaque GPS drift

```bash
# Dérive vers l'Est à 0.5 m/s (déclenchement après 10s)
python3 ~/attacks/attaque.py --drift-rate 0.5 --direction 90

# Dérive rapide vers le Nord
python3 ~/attacks/attaque.py --drift-rate 2.0 --direction 0

# Dérive lente vers le Sud-Est, déclenchement après 30s
python3 ~/attacks/attaque.py --drift-rate 0.3 --direction 135 --pre-attack 30
```

### Terminal 5 — Détecteur IA

```bash
cd ~/
python3 detect.py \
    --connection udp:0.0.0.0:14551 \
    --threshold 0.72 \
    --save ~/logs/detection.csv
```

---

## Ports utilisés

| Port | Protocole | Usage |
|---|---|---|
| 5900 | TCP | VNC natif |
| 6080 | TCP | noVNC (navigateur) |
| 14550 | UDP | MAVLink → QGroundControl |
| 14551 | UDP | MAVLink → Détecteur IA |
| 14552 | UDP | MAVLink → Script d'attaque |

---


## Commandes utiles

```bash
# Voir les logs du conteneur
docker logs -f drone-lab

# Ouvrir un terminal dans le conteneur
docker exec -it drone-lab bash

# Arrêter
docker stop drone-lab

# Redémarrer
docker start drone-lab

# Supprimer le conteneur
docker rm -f drone-lab

# Supprimer l'image
docker rmi drone-lab

# Tout nettoyer (conteneur + image + cache)
docker rm -f drone-lab
docker rmi drone-lab
docker system prune -af --volumes
```
