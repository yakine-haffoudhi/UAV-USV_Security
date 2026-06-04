# syntax=docker/dockerfile:1
# =============================================================================
# Drone Security — IMT Atlantique
#
#  Build : docker build -t drone-lab .
#  Run   : docker compose up -d
#  VNC   : http://localhost:6080/vnc.html
#
# =============================================================================

FROM ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive

ENV TZ=Europe/Paris \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    DISPLAY=:1 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    MESA_GL_VERSION_OVERRIDE=3.3 \
    QT_X11_NO_MITSHM=1 \
    XDG_RUNTIME_DIR=/tmp/runtime-drone \
    GZ_VERSION=harmonic


# ── 1. Système de base ────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        locales tzdata ca-certificates gnupg lsb-release \
        curl wget git nano sudo \
        build-essential cmake pkg-config ccache \
        net-tools iproute2 iputils-ping netcat \
    && locale-gen en_US.UTF-8 && update-locale LANG=en_US.UTF-8 \
    && ln -fs /usr/share/zoneinfo/Europe/Paris /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*


# ── 2. Bureau XFCE4 + TigerVNC + noVNC + supervisor ──────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        xfce4 xfce4-terminal xfce4-taskmanager xfce4-notifyd \
        dbus-x11 x11-xserver-utils xterm \
        tigervnc-standalone-server tigervnc-common \
        novnc websockify supervisor \
        fonts-liberation fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*


# ── 3. Python + stack ML / MAVLink ───────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-dev python3-setuptools \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
        pymavlink \
        "numpy<2" pandas scikit-learn joblib \
        matplotlib future \
        opencv-python-headless

RUN pip3 install --no-cache-dir \
        torch torchvision --index-url https://download.pytorch.org/whl/cpu

RUN pip3 install --no-cache-dir "numpy<2"


# ── 4. Utilisateur 'drone' ────────────────────────────────────────────────────
RUN useradd -m -s /bin/bash drone \
    && echo "drone:drone" | chpasswd \
    && echo "drone ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers \
    && usermod -aG sudo drone \
    && mkdir -p /tmp/runtime-drone \
    && chown drone:drone /tmp/runtime-drone \
    && chmod 700 /tmp/runtime-drone


# ── 5. ArduPilot SITL (ArduCopter + ArduRover) ───────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-dev libpython3-dev \
    && rm -rf /var/lib/apt/lists/*

USER drone
WORKDIR /home/drone

RUN git clone https://github.com/ArduPilot/ardupilot.git --depth 1 \
    && cd ardupilot \
    && git submodule update --init --recursive --depth 1

RUN cd /home/drone/ardupilot \
    && USER=drone Tools/environment_install/install-prereqs-ubuntu.sh -y

RUN . /home/drone/.profile \
    && cd /home/drone/ardupilot \
    && ./waf configure --board sitl \
    && ./waf copter \
    && ./waf rover

USER root


# ── 6. Gazebo Harmonic ───────────────────────────────────────────────────────
RUN wget -qO /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg \
        https://packages.osrfoundation.org/gazebo.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] \
        http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/gazebo-stable.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gz-harmonic \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
        mesa-utils libgles2-mesa-dev libegl1-mesa-dev \
        libgl1-mesa-dri libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*


# ── 7. Plugin ardupilot_gazebo ────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgz-sim8-dev rapidjson-dev libopencv-dev \
        libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
        gstreamer1.0-plugins-bad gstreamer1.0-libav gstreamer1.0-gl \
    && rm -rf /var/lib/apt/lists/*

USER drone
RUN git clone https://github.com/ArduPilot/ardupilot_gazebo --depth 1 \
    && cd ardupilot_gazebo \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    && make -j$(nproc)
USER root


# ── 8. asv_wave_sim (vagues FFT maritimes) ───────────────────────────────────
RUN pip3 install --no-cache-dir colcon-common-extensions

RUN apt-get update && apt-get install -y --no-install-recommends \
        libboost-iostreams-dev libboost-system-dev \
        libboost-filesystem-dev libboost-thread-dev \
        libboost-program-options-dev \
        libfftw3-dev libcgal-dev \
    && rm -rf /var/lib/apt/lists/*

USER drone
RUN mkdir -p /home/drone/gz_ws/src \
    && cd /home/drone/gz_ws/src \
    && git clone https://github.com/srmainwaring/asv_wave_sim.git --depth 1

RUN cd /home/drone/gz_ws \
    && colcon build \
        --symlink-install \
        --merge-install \
        --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release
USER root


# ── 9. SITL_Models (BlueBoat, iris…) ─────────────────────────────────────────
USER drone
RUN git clone https://github.com/ArduPilot/SITL_Models.git --depth 1 \
        /home/drone/SITL_Models
USER root


# ── 10. QGroundControl ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        libfuse2 libxcb-xinerama0 libxkbcommon-x11-0 libxcb-cursor0 \
        libegl1 libglib2.0-0 libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q --tries=3 --timeout=120 \
        "https://d176tv9ibo4jno.cloudfront.net/latest/QGroundControl-x86_64.AppImage" \
        -O /tmp/QGroundControl.AppImage \
    && chmod +x /tmp/QGroundControl.AppImage \
    && cd /opt \
    && /tmp/QGroundControl.AppImage --appimage-extract \
    && mv /opt/squashfs-root /opt/QGroundControl \
    && rm /tmp/QGroundControl.AppImage \
    && ln -s /opt/QGroundControl/AppRun /usr/local/bin/QGroundControl


# ── 11. Outils réseau ────────────────────────────────────────────────────────
RUN apt-get update \
    && echo "wireshark-common wireshark-common/install-setuid boolean true" \
        | debconf-set-selections \
    && apt-get install -y --no-install-recommends wireshark tshark tcpdump \
    && dpkg-reconfigure -f noninteractive wireshark-common \
    && usermod -aG wireshark drone \
    && rm -rf /var/lib/apt/lists/*


# ── 12. Répertoires ──────────────────────────────────────────────────────────
RUN mkdir -p \
        /home/drone/scripts \
        /home/drone/worlds \
        /home/drone/attacks \
        /home/drone/model \
        /home/drone/logs \
        /home/drone/data \
        /home/drone/.vnc \
    && chown -R drone:drone /home/drone


# ── 13. Profil d'environnement ───────────────────────────────────────────────
RUN <<'DEOF'
cat > /etc/profile.d/drone-lab.sh << 'FILE_EOF'
#!/bin/bash
export DISPLAY="${DISPLAY:-:1}"
export LIBGL_ALWAYS_SOFTWARE=1
export MESA_GL_VERSION_OVERRIDE=3.3
export QT_X11_NO_MITSHM=1
export XDG_RUNTIME_DIR=/tmp/runtime-drone
export GZ_VERSION=harmonic
export PATH="$PATH:/home/drone/ardupilot/Tools/autotest"
export GZ_SIM_SYSTEM_PLUGIN_PATH="/home/drone/ardupilot_gazebo/build:/home/drone/gz_ws/install/lib${GZ_SIM_SYSTEM_PLUGIN_PATH:+:$GZ_SIM_SYSTEM_PLUGIN_PATH}"
export GZ_SIM_RESOURCE_PATH="/home/drone/ardupilot_gazebo/models:/home/drone/ardupilot_gazebo/worlds:/home/drone/gz_ws/src/asv_wave_sim/gz-waves-models/models:/home/drone/gz_ws/src/asv_wave_sim/gz-waves-models/world_models:/home/drone/gz_ws/src/asv_wave_sim/gz-waves-models/worlds:/home/drone/SITL_Models/Gazebo/models:/home/drone/SITL_Models/Gazebo/worlds${GZ_SIM_RESOURCE_PATH:+:$GZ_SIM_RESOURCE_PATH}"
export LD_LIBRARY_PATH="/home/drone/gz_ws/install/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
FILE_EOF
chmod +x /etc/profile.d/drone-lab.sh
echo '. /etc/profile.d/drone-lab.sh' >> /home/drone/.bashrc
chown drone:drone /home/drone/.bashrc
DEOF


# ── 14. VNC xstartup + supervisord ───────────────────────────────────────────
RUN <<'DEOF'
cat > /home/drone/.vnc/xstartup << 'FILE_EOF'
#!/bin/bash
export DISPLAY=:1
export HOME=/home/drone
export USER=drone
export XDG_RUNTIME_DIR=/tmp/runtime-drone
export LIBGL_ALWAYS_SOFTWARE=1
export MESA_GL_VERSION_OVERRIDE=3.3
export QT_X11_NO_MITSHM=1
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
[ -f /etc/profile.d/drone-lab.sh ] && . /etc/profile.d/drone-lab.sh
xset -dpms 2>/dev/null || true
xset s off  2>/dev/null || true
exec startxfce4
FILE_EOF
chmod +x /home/drone/.vnc/xstartup

cat > /etc/supervisor/conf.d/drone-lab.conf << 'FILE_EOF'
[supervisord]
nodaemon=true
user=root
logfile=/home/drone/logs/supervisord.log
logfile_maxbytes=10MB
loglevel=info
pidfile=/tmp/supervisord.pid

[unix_http_server]
file=/tmp/supervisor.sock

[supervisorctl]
serverurl=unix:///tmp/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface

[program:vncserver]
command=/usr/bin/vncserver :1 -geometry 1920x1080 -depth 24 -fg -SecurityTypes None
user=drone
environment=HOME="/home/drone",USER="drone",DISPLAY=":1",LIBGL_ALWAYS_SOFTWARE="1",MESA_GL_VERSION_OVERRIDE="3.3",QT_X11_NO_MITSHM="1",XDG_RUNTIME_DIR="/tmp/runtime-drone"
autostart=true
autorestart=true
startsecs=5
priority=10
stdout_logfile=/home/drone/logs/vnc.log
stderr_logfile=/home/drone/logs/vnc_err.log
stdout_logfile_maxbytes=5MB

[program:novnc]
command=/usr/bin/websockify --web /usr/share/novnc/ 6080 localhost:5901
user=drone
autostart=true
autorestart=true
startsecs=10
priority=20
stdout_logfile=/home/drone/logs/novnc.log
stderr_logfile=/home/drone/logs/novnc_err.log
stdout_logfile_maxbytes=5MB

[program:xfce]
command=/home/drone/.vnc/xstartup
user=drone
environment=HOME="/home/drone",USER="drone",DISPLAY=":1",LIBGL_ALWAYS_SOFTWARE="1",MESA_GL_VERSION_OVERRIDE="3.3",QT_X11_NO_MITSHM="1",XDG_RUNTIME_DIR="/tmp/runtime-drone"
autostart=true
autorestart=false
startsecs=8
priority=30
stdout_logfile=/home/drone/logs/xfce.log
stderr_logfile=/home/drone/logs/xfce_err.log
stdout_logfile_maxbytes=5MB
FILE_EOF
DEOF


# ── 15. Entrypoint ───────────────────────────────────────────────────────────
RUN <<'DEOF'
cat > /entrypoint.sh << 'FILE_EOF'
#!/bin/bash
export DISPLAY=:1
export HOME=/home/drone
export USER=drone
export XDG_RUNTIME_DIR=/tmp/runtime-drone
export LIBGL_ALWAYS_SOFTWARE=1
export MESA_GL_VERSION_OVERRIDE=3.3
export QT_X11_NO_MITSHM=1

mkdir -p /tmp/runtime-drone && chmod 700 /tmp/runtime-drone
mkdir -p /home/drone/logs /home/drone/data
chown drone:drone /home/drone/logs /home/drone/data 2>/dev/null || true
[ -f /home/drone/.profile ] && . /home/drone/.profile 2>/dev/null || true

echo ""
echo "  VNC : http://localhost:6080/vnc.html"
echo ""
echo "  Terminal 1 : . /etc/profile.d/drone-lab.sh"
echo "               gz sim -v4 -r ~/worlds/blueboat_waves.sdf"
echo ""
echo "  Terminal 2 : cd ~/ardupilot/Rover"
echo "               sim_vehicle.py -v Rover -f rover-skid --model JSON --console --map \\"
echo "                 --out=udp:127.0.0.1:14550 --out=udp:127.0.0.1:14551 --out=udp:127.0.0.1:14552 \\"
echo "                 --custom-location=48.3500,-4.5000,0,0"
echo ""
echo "  Terminal 3 : QGroundControl"
echo ""
echo "  Terminal 4 : python3 ~/attacks/attaque.py --drift-rate 0.5 --direction 90"
echo "  Terminal 5 : cd ~/ && python3 detect.py --connection udp:0.0.0.0:14551 --threshold 0.72"
echo ""

exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/drone-lab.conf
FILE_EOF
chmod +x /entrypoint.sh
DEOF


# ── 16. Scripts de lancement ─────────────────────────────────────────────────
RUN <<'DEOF'
cat > /home/drone/scripts/start_sim.sh << 'FILE_EOF'
#!/bin/bash
# Lance Gazebo + ArduRover SITL (USV BlueBoat, Mer de Brest)
. /etc/profile.d/drone-lab.sh
[ -f /home/drone/.profile ] && . /home/drone/.profile 2>/dev/null || true

pkill -f "gz sim" 2>/dev/null; pkill -f "sim_vehicle" 2>/dev/null; sleep 2

echo "[1/2] Gazebo Harmonic + BlueBoat..."
gz sim -v 2 -r /home/drone/worlds/blueboat_waves.sdf &
GZ_PID=$!
sleep 20
if ! kill -0 $GZ_PID 2>/dev/null; then echo "[ERR] Gazebo crash."; exit 1; fi
echo "      Gazebo OK."

echo "[2/2] ArduRover SITL (JSON)..."
cd /home/drone/ardupilot/Rover
sim_vehicle.py -v Rover -f rover-skid --model JSON --console --map \
    --out=udp:127.0.0.1:14550 \
    --out=udp:127.0.0.1:14551 \
    --out=udp:127.0.0.1:14552 \
    --custom-location=48.3500,-4.5000,0,0
FILE_EOF

cat > /home/drone/scripts/start_qgc.sh << 'FILE_EOF'
#!/bin/bash
export DISPLAY=:1 HOME=/home/drone QT_X11_NO_MITSHM=1
export LIBGL_ALWAYS_SOFTWARE=1 MESA_GL_VERSION_OVERRIDE=3.3
sleep 8
/opt/QGroundControl/AppRun
FILE_EOF

chmod +x /home/drone/scripts/*.sh
DEOF


# ── 17. Monde Gazebo — USV BlueBoat (Mer de Brest) ───────────────────────────
RUN <<'DEOF'
cat > /home/drone/worlds/blueboat_waves.sdf << 'FILE_EOF'
<?xml version="1.0" ?>
<sdf version="1.9">
  <world name="blueboat_waves">
    <physics name="rtf1" type="ignored">
      <max_step_size>0.004</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>250</real_time_update_rate>
    </physics>
    <plugin filename="gz-sim-physics-system"           name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system"     name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system"           name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-imu-system"    name="gz::sim::systems::Imu"/>
    <plugin filename="gz-sim-navsat-system" name="gz::sim::systems::NavSat"/>
    <plugin filename="gz-sim-buoyancy-system" name="gz::sim::systems::Buoyancy">
      <graded_buoyancy><default_fluid_density>1025</default_fluid_density></graded_buoyancy>
    </plugin>
    <plugin filename="ArduPilotPlugin" name="gz::sim::systems::ArduPilotPlugin">
      <fdm_addr>127.0.0.1</fdm_addr>
      <listen_addr>127.0.0.1</listen_addr>
      <fdm_port_in>9002</fdm_port_in>
      <fdm_port_out>9003</fdm_port_out>
      <connectionTimeoutMaxCount>50</connectionTimeoutMaxCount>
      <lock_step>true</lock_step>
    </plugin>
    <spherical_coordinates>
      <surface_model>EARTH_WGS84</surface_model>
      <world_frame_orientation>ENU</world_frame_orientation>
      <latitude_deg>48.3500</latitude_deg>
      <longitude_deg>-4.5000</longitude_deg>
      <elevation>0</elevation>
      <heading_deg>0</heading_deg>
    </spherical_coordinates>
    <light type="directional" name="sun">
      <cast_shadows>true</cast_shadows>
      <pose>0 0 500 0 0 0</pose>
      <diffuse>1 1 1 1</diffuse><specular>0.3 0.3 0.3 1</specular>
      <direction>-0.5 0.2 -0.9</direction>
      <attenuation><range>2000</range><constant>0.9</constant><linear>0.01</linear><quadratic>0.001</quadratic></attenuation>
    </light>
    <ambient>0.3 0.4 0.5 1</ambient>
    <background>0.2 0.4 0.7 1</background>
    <wind><linear_velocity>5.0 0 0</linear_velocity></wind>
    <include><uri>model://waves</uri><pose>0 0 0 0 0 0</pose></include>
    <include>
      <uri>model://blueboat</uri>
      <name>blueboat</name>
      <pose degrees="true">0 0 0.1 0 0 0</pose>
    </include>
    <model name="buoy_nord">
      <static>true</static><pose>0 100 0 0 0 0</pose>
      <link name="link">
        <visual name="v">
          <geometry><cylinder><radius>0.4</radius><length>1.2</length></cylinder></geometry>
          <material><ambient>1 0.2 0 1</ambient><diffuse>1 0.2 0 1</diffuse></material>
        </visual>
      </link>
    </model>
    <model name="buoy_est">
      <static>true</static><pose>100 0 0 0 0 0</pose>
      <link name="link">
        <visual name="v">
          <geometry><cylinder><radius>0.4</radius><length>1.2</length></cylinder></geometry>
          <material><ambient>0 0.4 1 1</ambient><diffuse>0 0.4 1 1</diffuse></material>
        </visual>
      </link>
    </model>
  </world>
</sdf>
FILE_EOF
DEOF


# ── 18. Fichiers externes (COPY depuis build context) ─────────────────────────
COPY --chown=drone:drone detect.py          /home/drone/detect.py
COPY --chown=drone:drone attacks/attaque.py /home/drone/attacks/attaque.py
COPY --chown=drone:drone model/best_model.pt    /home/drone/model/best_model.pt
COPY --chown=drone:drone model/scaler_tl.joblib /home/drone/model/scaler_tl.joblib


# ── 19. Permissions ──────────────────────────────────────────────────────────
RUN chown -R drone:drone /home/drone \
    && chmod +x /home/drone/scripts/*.sh \
    && chmod +x /home/drone/.vnc/xstartup \
    && chmod 700 /home/drone/.vnc \
    && chmod +x /home/drone/attacks/attaque.py \
    && chmod +x /home/drone/detect.py


EXPOSE 5900 6080 14550/udp 14551/udp 14552/udp
WORKDIR /home/drone
USER root
ENTRYPOINT ["/entrypoint.sh"]
