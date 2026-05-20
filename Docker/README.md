# UAV/USV Security — Docker

> Environnement de simulation et d'attaque MAVLink sur ArduPilot SITL  

---

## Structure du projet

```
uav-docker/
├── Dockerfile              ← Image principale (Ubuntu 22.04 + ArduPilot + outils)
├── docker-compose.yml      ← Orchestration : drone / USV / attaquant
├── README.md
│
├── scripts/
│   ├── entrypoint.sh       ← Menu interactif (point d'entrée du conteneur)
│   ├── start_copter.sh     ← Lance ArduCopter SITL
│   ├── start_rover.sh      ← Lance ArduRover SITL (bateau)
│   ├── gps_spoofing.py     ← Attaque GPS UAV (trajectoire circulaire)
│   ├── gps_spoof_usv.py    ← Attaque GPS USV (dérive progressive)
│   ├── view_mavlink.py     ← Décode une capture .pcap MAVLink
│   └── arp_attack.sh       ← ARP Spoofing (MitM)
│
├── missions/
│   ├── mission_test.txt    ← Mission 3 waypoints (Canberra, test UAV)
│   └── mission_brest.txt   ← Mission USV (rade de Brest)
│
└── config/
    ├── mavlink.lua         ← Dissector Wireshark (à copier dans ~/.local/…)
    └── usv_params.parm     ← Paramètres bateau pour ArduRover
```

---

## Construction de l'image

```bash
# Depuis le répertoire uav-docker/
docker build -t uav-lab:1.0 .

# Avec cache désactivé (rebuild complet)
docker build --no-cache -t uav-lab:1.0 .
```

> La compilation d'ArduPilot prend **15–30 min**.

---

## Lancement rapide

### Option A — Menu interactif (conteneur unique)

```bash
docker run -it --rm \
    --cap-add NET_ADMIN \
    --cap-add NET_RAW \
    -p 14550:14550/udp \
    -p 14551:14551/udp \
    -p 14552:14552/udp \
    uav-lab:1.0
```

Le menu vous propose tous les scénarios disponibles.

### Option B — Docker Compose (3 conteneurs)

```bash
# Lancer tous les services
docker-compose up -d

# Accéder au terminal du drone
docker exec -it uav-drone bash

# Accéder au terminal de l'attaquant
docker exec -it uav-attacker bash

# Arrêter tout
docker-compose down
```

---

## Scénarios disponibles

### 1. Simulation UAV (ArduCopter)

```bash
docker run -it uav-lab:1.0 copter
```

Dans MAVProxy :
```
> mode GUIDED
> arm throttle
> takeoff 40
> wp load /opt/uav-lab/missions/mission_test.txt
> mode AUTO
```

### 2. Simulation USV (ArduRover — rade de Brest)

```bash
docker run -it uav-lab:1.0 rover
```

Dans MAVProxy :
```
> param set FRAME_CLASS 2
> arm throttle
> mode GUIDED
> wp load /opt/uav-lab/missions/mission_brest.txt
> mode AUTO
```

### 3. GPS Spoofing UAV

Dans un deuxième terminal, pendant que le SITL tourne :
```bash
# D'abord, dans MAVProxy :
> param set GPS1_TYPE 14

# Puis dans un autre terminal :
docker exec -it uav-drone python3 /opt/uav-lab/scripts/gps_spoofing.py
```

Options disponibles :
```
--connection     URL MAVLink (défaut: udp:127.0.0.1:14551)
--radius         Rayon du cercle (défaut: 50000 ≈ 500 m)
--altitude       Altitude de spoofing (défaut: 30 m)
--step           Pas angulaire (défaut: 10°)
--interval       Intervalle d'envoi (défaut: 0.5 s)
```

### 4. GPS Drift Spoofing USV

```bash
docker run -it uav-lab:1.0 gps_usv

# Ou avec options :
docker exec -it uav-usv python3 /opt/uav-lab/scripts/gps_spoof_usv.py \
    --drift-rate 0.5 \
    --direction 90 \
    --pre-attack 10
```

### 5. Déni de service (flood ICMP)

```bash
docker run -it --cap-add NET_RAW uav-lab:1.0 dos
```

### 6. Man-in-the-Middle (ARP Spoofing)

Nécessite le réseau docker-compose avec les 3 conteneurs :
```bash
docker exec -it uav-attacker bash
> ./scripts/arp_attack.sh 192.168.56.101 192.168.56.102
```

### 7. Capture de trafic MAVLink

```bash
# Capturer
docker exec -it uav-drone bash
> tcpdump -i lo -X 'udp port 14550' -w /opt/uav-lab/captures/cap.pcap

# Analyser
docker exec -it uav-drone python3 /opt/uav-lab/scripts/view_mavlink.py \
    /opt/uav-lab/captures/cap.pcap --stats
```

---

## Connexion QGroundControl

QGroundControl (sur la machine hôte) se connecte au drone simulé via UDP :

| Champ          | Valeur                    |
|----------------|---------------------------|
| Type           | UDP                       |
| Adresse        | `127.0.0.1`               |
| Port           | `14550`                   |

---

## Ports réseau

| Port  | Proto | Usage                              |
|-------|-------|------------------------------------|
| 14550 | UDP   | MAVLink → GCS (QGroundControl)     |
| 14551 | UDP   | MAVLink → scripts d'attaque UAV    |
| 14552 | UDP   | MAVLink → scripts d'attaque USV    |
| 14553 | UDP   | MAVLink → GCS (USV, compose)       |

---

## Dépendances Python installées

| Paquet       | Version  | Rôle                            |
|--------------|----------|---------------------------------|
| pymavlink    | 2.4.41   | Parsing et envoi MAVLink        |
| MAVProxy     | 1.8.70   | Proxy + console CLI MAVLink     |
| scapy        | latest   | Forge de paquets réseau         |
| pyshark      | latest   | Analyse pcap (wraps tshark)     |
| numpy        | latest   | Calculs géographiques           |
| colorama     | latest   | Affichage terminal couleur      |

---

## Outils système inclus

- `tcpdump` / `tshark` — capture réseau
- `hping3` — flood ICMP / DoS
- `arpspoof` (dsniff) — ARP spoofing MitM
- `nmap` — scan réseau
- `wireshark-common` — parsers Wireshark
