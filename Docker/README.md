# UAV/USV Security — Docker

> Environnement de simulation et d'attaque MAVLink sur ArduPilot SITL  

---

## Contenu 

```
 1. ArduPilot SITL    — simulateur drone/bateau
 2. QGroundControl    — station de contrôle au sol (GCS)
 3. MAVProxy          — proxy et console MAVLink
 4. Wireshark/tshark  — capture réseau + dissecteur MAVLink
 5. Gazebo Harmonic   — simulation 3D USV avec vagues (asv_wave_sim)
 6. GPS Spoof USV     — attaque de dérive progressive
```

---
## Construction de l'image

```bash
 docker build -t uav-usv-lab
```

> La compilation d'ArduPilot prend **25–40 min**.

---

## Lancement 
```bash
docker run -it --rm \
    --cap-add NET_ADMIN --cap-add NET_RAW \
    -p 14550:14550/udp -p 14551:14551/udp \
    -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix \
    uav-usv-lab
```


