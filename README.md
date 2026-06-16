# UB Digital Twin

## Setup Instructions

1. Clone this repo and submodules
```bash
# SSH
git clone --recurse-submodules git@github.com:ub-cavas/UB-DigitalTwin.git
# HTTPS
git clone --recurse-submodules https://github.com/ub-cavas/UB-DigitalTwin.git
```

2. Set up CARLA (Packaged Version)
```bash
bash scripts/install_ub_carla.sh v1.0.0
# Build the Runtime Containers (CARLA Server, Redis Server, Python-API)
docker build -f CARLA/Dockerfile -t ub-carla CARLA
docker build -f CARLA/UB-API/redis-networking/Dockerfile -t ub-carla-redis-networking CARLA/UB-API/redis-networking
```

3. Set up Autoware
```bash
cd Autoware
bash Autoware/setup_autoware.sh
```

## Usage

**0. Basic (UB-CARLA only)**
```bash
# No Graphics
bash scripts/launch_carla.sh
# Graphics
CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound" bash scripts/launch_carla.sh
```

**1. AV (CARLA + Autoware)**
```bash
# One command replacement for:
#   1. scripts/launch_carla.sh
#   2. Autoware/ub-lincoln-docker/docker/dc_up.sh
#   3. Autoware/ub-lincoln-docker/docker/dc_bash.sh
#   4. ros2 launch autoware_launch e2e_simulator.launch.xml ...
./scripts/launch_autoware_carla.sh
```

This wrapper defaults to these CARLA settings:
`CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound"`,


It also runs the same Autoware DDS host setup as `dc_up.sh` when `sudo` is
already available. If `sudo` needs a password, run this once first:

```bash
cd Autoware/ub-lincoln-docker/docker
../scripts/host_config_dds.bash
```

The Autoware container and launcher both pin ROS 2 to CycloneDDS:
`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` and
`CYCLONEDDS_URI=file:///resources/cyclonedds.xml`. This keeps the automated
path consistent with the interactive `dc_bash.sh` workflow.


**2. Multi-Agent Server**
```bash
# No Graphics
bash scripts/launch_carla_redis_server.sh
# Graphics
CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound" \
UB_TRAFFIC_NO_RENDERING=0 \
./scripts/launch_carla_redis_server.sh
```

**3. Multi-Agent Manual Client**
```bash
# Local Host
./scripts/launch_carla_redis_manual_client.sh 127.0.0.1
# Remote Host (required)
./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
```


### Authoritative CARLA + manual client

Start the authoritative CARLA server, Redis, map loader, and traffic publisher:

```bash
./scripts/launch_carla_redis_server.sh
```

In a second terminal, start the local rendered CARLA client, Redis traffic renderer, and keyboard-controlled manual CARLA client:

```bash
./scripts/launch_carla_redis_manual_client.sh 127.0.0.1
```

The manual vehicle is controlled through the authoritative CARLA API and is published to Redis by the authoritative CARLA traffic publisher like any other traffic actor. The local client opens a CARLA graphics window and mirrors server-side Redis traffic into it.

Manual controls require keyboard focus on the `CARLA Manual Control` window:
`W/Up` throttle, `S/Down` brake, `A/D` steer, `Space` full brake, `Q` reverse, `F` toggle authoritative-server chase camera, `Esc` quit.

Useful manual-client overrides:

```bash
./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_ROLE_NAME=manual_vehicle ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_BLUEPRINT=vehicle.lincoln.mkz_2020 ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_COLOR=0,0,255 ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_MAX_KMH=60 ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_FOLLOW_SPECTATOR=0 ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_SPAWN_INDEX=0 ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
```

Useful server overrides:

```bash
CARLA_ARGS="-RenderOffScreen -quality-level=Low -nosound" ./scripts/launch_carla_redis_server.sh
UB_TRAFFIC_NO_RENDERING=1 ./scripts/launch_carla_redis_server.sh
UB_TRAFFIC_MANAGER_PORT=8002 ./scripts/launch_carla_redis_server.sh
UB_TRAFFIC_PUBLISH_HZ=60 ./scripts/launch_carla_redis_server.sh
BUILD_FOLDER=v1.0.0 ./scripts/launch_carla_redis_server.sh
CARLA_MAP_PATH= ./scripts/launch_carla_redis_server.sh
```


