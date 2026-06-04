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
docker compose build
```

> Durée : ~30-60 min (compilation ArduPilot + Gazebo + asv_wave_sim)  

---

## Lancer le conteneur

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

mode GUIDED
arm throttle force
```

### Terminal 3 — QGroundControl

```bash
~/scripts/start_qgc.sh
```

QGroundControl se connecte automatiquement sur `udp:127.0.0.1:14550` et affiche la carte + télémétrie.

### Terminal 4 — Détecteur IA

```bash
python3 detect.py \
    --connection udp:0.0.0.0:14553 \
    --model-dir model \
```

### Terminal 5 — Attaque GPS drift

```bash
python3 ~/attacks/attaque.py \
    --mode-both \
    --connection udp:0.0.0.0:14551 \
    --forward-host 127.0.0.1 \
    --forward-port 14553 \
    --attack drift \
    --drift-rate 1.5 \
    --pre-attack-delay 20
```

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

# Modification
docker cp attacks/attaque.py drone-lab:/home/drone/attacks/attaque.py

```
