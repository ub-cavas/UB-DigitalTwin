# UB Digital Twin

## Setup Instructions

1. Clone this repo and submodules
```bash
# SSH
git clone --recurse-submodules git@github.com:ub-cavas/UB-DigitalTwin.git
# HTTPS
git clone --recurse-submodules https://github.com/ub-cavas/UB-DigitalTwin.git
```

2. Run the CARLA Installer Script (Packaged Version)
```bash
bash scripts/install_ub_carla.sh v1.0.0
```

3. Build the Runtime Containers (CARLA Server, Redis Server, Python-API)
```bash
docker build -f CARLA/Dockerfile -t ub-carla CARLA
docker build -f CARLA/UB-API/redis-networking/Dockerfile -t ub-carla-redis-networking CARLA/UB-API/redis-networking
```

## CARLA Docker Compose Stack

The Compose stack includes CARLA, Redis, map loading, and Redis networking sidecars.

### Authoritative CARLA + manual client

Start the authoritative CARLA server, Redis, map loader, and traffic publisher:

```bash
cd CARLA
./start_carla_server.sh
```

In a second terminal, start the keyboard-controlled manual CARLA client:

```bash
cd CARLA
./start_manual_client.sh
```

The manual vehicle is controlled through the CARLA API and is published to Redis by the authoritative CARLA traffic publisher like any other traffic actor. The authoritative CARLA spectator is not locked to the manual vehicle by default.

Manual controls require keyboard focus on the `CARLA Manual Control` window:
`W/Up` throttle, `S/Down` brake, `A/D` steer, `Space` full brake, `Q` reverse, `F` toggle authoritative-server chase camera, `Esc` quit.

Useful manual-client overrides:

```bash
UB_MANUAL_CARLA_HOST=<authoritative-carla-host> ./start_manual_client.sh
UB_MANUAL_ROLE_NAME=manual_vehicle ./start_manual_client.sh
UB_MANUAL_BLUEPRINT=vehicle.lincoln.mkz_2020 ./start_manual_client.sh
UB_MANUAL_COLOR=0,0,255 ./start_manual_client.sh
UB_MANUAL_MAX_KMH=60 ./start_manual_client.sh
UB_MANUAL_FOLLOW_SPECTATOR=0 ./start_manual_client.sh
UB_MANUAL_SPAWN_INDEX=0 ./start_manual_client.sh
```

Useful server overrides:

```bash
CARLA_ARGS="-RenderOffScreen -quality-level=Low -nosound" ./start_carla_server.sh
UB_TRAFFIC_NO_RENDERING=1 ./start_carla_server.sh
UB_TRAFFIC_MANAGER_PORT=8002 ./start_carla_server.sh
BUILD_FOLDER=v1.0.0 ./start_carla_server.sh
CARLA_MAP_PATH= ./start_carla_server.sh
```

### Direct Compose commands

```bash
cd CARLA
export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
xhost +local:root

# CARLA + Redis + map loader only
docker compose up --build

# Headless/offscreen CARLA + Redis + map loader
CARLA_ARGS="-RenderOffScreen -nosound" 
docker compose up --build

# CARLA + Redis + traffic publisher + UDP bridge for UB-MR client
CARLA_ARGS="-quality=Low -nosound" 
docker compose --profile ub-mr up --build
```

### Visualization CARLA client

On a separate driver/client machine, start a local CARLA window, mirror authoritative Redis traffic into it, and run the manual-control client against the authoritative CARLA server:

```bash
cd CARLA
./start_carla_client.sh <authoritative-carla-host>
```

This opens a local CARLA window on the client machine. The renderer connects to Redis on the authoritative CARLA server and mirrors the server's published traffic into the local visual CARLA instance. The manual-control client sends driving commands to the authoritative CARLA server. The renderer automatically attaches the local visual CARLA spectator to the mirrored manual-control vehicle, so the driver can see where they are driving and see server-side NPC traffic.

To test this on one machine, use two terminals. The authoritative server stays on CARLA RPC port `2000`; the local visualization client uses CARLA RPC port `2100` by default. The server helper defaults to offscreen/low/no-rendering mode so the local visualization client owns the rendered CARLA window.

Terminal 1:

```bash
cd CARLA
./start_carla_server.sh
```

Terminal 2:

```bash
cd CARLA
./start_carla_client.sh 127.0.0.1
```

For visualization only, without the manual-control client:

```bash
./start_visual_client.sh <authoritative-carla-host>
```

On one machine, run:

```bash
./start_visual_client.sh 127.0.0.1
```

Both client helpers use separate Compose project/container names from the authoritative stack. They set `UB_RENDER_CARLA_PORT=2100` and launch the local CARLA window with `-carla-rpc-port=2100`; override `UB_RENDER_CARLA_PORT` if you need another local visualization port. The client camera first follows the exact actor id published by the manual-control client through Redis key `carla:manual_control:actor`, then falls back to `UB_MANUAL_ROLE_NAME`, which defaults to `manual_vehicle`. Override `UB_RENDER_FOLLOW_ROLE_NAME` only if you want the client camera to follow a different published vehicle role.

When the camera attaches correctly, the logs should include:

```text
Published manual actor metadata to Redis key carla:manual_control:actor
Publishing manual traffic actor id=<id> role_name=manual_vehicle
Loaded manual actor ID=<id> from Redis key carla:manual_control:actor
Following mirrored traffic vehicle ID=<id> role_name=manual_vehicle
```

If the renderer keeps printing `Waiting for mirrored manual traffic actor`, the manual vehicle is not reaching the authoritative traffic publisher or Redis stream yet.

Equivalent direct Compose command:

```bash
UB_REDIS_HOST=<authoritative-carla-host> \
UB_MANUAL_CARLA_HOST=<authoritative-carla-host> \
UB_RENDER_CARLA_HOST=127.0.0.1 \
UB_RENDER_CARLA_PORT=2100 \
UB_CARLA_PORT=2100 \
COMPOSE_PROJECT_NAME=ub-carla-client \
CONTAINER_NAME=ub-carla-client-container \
MANUAL_CONTROL_CONTAINER_NAME=ub-carla-client-manual-control \
TRAFFIC_RENDERER_CONTAINER_NAME=ub-carla-client-traffic-renderer \
CARLA_ARGS="-quality-level=Low -nosound -carla-rpc-port=2100" \
docker compose up --build carla map-loader traffic-renderer manual-control
```

Set `UB_RENDER_FOLLOW_SPECTATOR=0` to disable following the manual vehicle.

If the local client CARLA window exits with `VK_ERROR_DEVICE_LOST`, the GPU likely cannot sustain two rendered CARLA instances. Stop both stacks, restart the server with the default `./start_carla_server.sh`, then start the client with the default `./start_carla_client.sh 127.0.0.1`. Avoid overriding either side back to `Epic` on one machine.

### UB-MR Bridge

```bash
# Send UDP bridge traffic to UB-MR on another machine
UB_UNITY_HOST=<ub-mr-machine-ip> docker compose --profile ub-mr up --build

# Remote UB-MR bidirectional mode:
CARLA_ARGS="-quality=Low -nosound" \
UB_UNITY_HOST=<ub-mr-machine-ip> \
UB_UNITY_PORT=12345 \
UB_EGO_LISTEN_HOST=0.0.0.0 \
UB_EGO_LISTEN_PORT=12346 \
docker compose --profile ub-mr up --build
```

Optional sidecar profiles:
```bash
docker compose --profile traffic-publisher up --build
docker compose --profile udp-bridge up --build
docker compose --profile manual-control up --build
docker compose --profile traffic-renderer up --build
docker compose --profile multi-agent-renderer up --build
```

## Autoware

Install Autoware
```bash
cd Autoware
./setup_autoware.sh
```

Start Autoware
```bash
./dc_up.sh
./dc_bash.sh

# From in the container...

# First time only
python3 -m pip install carla==0.9.16
python3 -m pip install --upgrade transforms3d


ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=/host_data/maps/ub_autonomous_proving_grounds vehicle_model:=sample_vehicle sensor_model:=awsim_sensor_kit simulator_type:=carla carla_map:=UBAutonomousProvingGrounds
```
