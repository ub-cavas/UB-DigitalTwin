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

4. Set up Mixed Reality
```bash
# Full setup (recommended)
bash scripts/setup_ub_mr.sh

# Partial setup = Unity player only, without pulling the Docker runtime image. Use this only if you plan to edit the UB-MR runtime docker image and build + test frequently
./scripts/download_ub_mr_release.sh
```

## Usage

Launch scripts live under `launch/`: one file per scenario at the top level,
with shared plumbing (X11 setup, docker-compose helpers, preflight checks,
Autoware DDS/container bring-up) organized underneath in `launch/lib/`,
`launch/carla/`, `launch/sumo/`, and `launch/autoware/`.

**0. Basic (UB-CARLA only)**
```bash
# No Graphics
bash launch/carla.sh
# Graphics
CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound" bash launch/carla.sh
```

**1. AV (CARLA + Autoware)**
```bash
# One command replacement for:
#   1. launch/carla.sh
#   2. Autoware/ub-lincoln-docker/docker/dc_up.sh
#   3. Autoware/ub-lincoln-docker/docker/dc_bash.sh
#   4. ros2 launch autoware_launch e2e_simulator.launch.xml ...
./launch/autoware-carla.sh
```

This launcher defaults to these CARLA settings:
`CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound"`,


It also runs the same Autoware DDS host setup as `dc_up.sh` before starting
containers. In an interactive terminal, `sudo` may prompt for your password.
For non-interactive runs, run this once first:

```bash
cd Autoware/ub-lincoln-docker/docker
../scripts/host_config_dds.bash
```

The Autoware container and launcher both pin ROS 2 to CycloneDDS:
`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` and
`CYCLONEDDS_URI=file:///resources/cyclonedds.xml`. This keeps the automated
path consistent with the interactive `dc_bash.sh` workflow.

The rendered CARLA spectator follows the Autoware-controlled CARLA vehicle
behind `role_name=ego_vehicle` by default. For a custom ego role, set
`UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES=<role-name>`.

**2. AV + SUMO Traffic (CARLA + SUMO + Autoware)**
```bash
# Starts rendered UB-CARLA, visible SUMO GUI, SUMO/CARLA synchronization,
# the Autoware container, the custom autoware_carla_interface, and Autoware.
./launch/autoware-carla-sumo.sh
```

This launcher uses the existing
`CARLA/UB-API/carla-autoware-sumo-bridge` workflow. SUMO is the time master and
the Autoware CARLA interface is launched with `external_tick:=True`. The
launcher starts that interface explicitly, then runs Autoware e2e with
`AUTOWARE_E2E_SIMULATOR_TYPE=awsim` by default so Autoware does not include a
second CARLA interface. The launcher relays the CARLA bridge's
`/sensing/lidar/top/pointcloud_before_sync` output into
`/sensing/lidar/concatenated/pointcloud` for Autoware localization.

**2a. AV Passive Bridge Test (CARLA + Autoware, no traffic orchestrator)**
```bash
# Starts rendered UB-CARLA, a CARLA-only time-master ticker, the mounted
# custom autoware_carla_interface, and Autoware.
./launch/autoware-carla-passive.sh
```

Use this to validate the passive bridge before adding SUMO or another traffic
orchestrator. The time-master service is the only process that calls
`world.tick()`; the bridge runs with `external_tick:=True`.

This is `launch/autoware-carla-sumo.sh` with `UB_TRAFFIC_ORCHESTRATOR=none`
forced on — it delegates to that same launcher.

**3. Multi-Agent Server**
```bash
# No Graphics
bash launch/carla-redis-server.sh
# Graphics
CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound" \
UB_TRAFFIC_NO_RENDERING=0 \
./launch/carla-redis-server.sh
```

**4. Multi-Agent Manual Client**
```bash
# Local Host
./launch/carla-redis-manual-client.sh 127.0.0.1
# Remote Host (required)
./launch/carla-redis-manual-client.sh <authoritative-carla-host>
```

**5. UB-MR**
```bash
# Starts UB-MR, the UB-MR localization bridge, UB-CARLA, and Autoware.
./launch/ub-mr.sh
# Light graphics
CARLA_ARGS="-prefernvidia -quality-level=low -nosound" bash launch/ub-mr.sh
```

This launcher defaults to `UB_MR_BUILD_FOLDER=0.0.7`, `BUILD_FOLDER=v1.0.0`,
`CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound"`, and
`UB_CARLA_EXTRA_SERVICES="udp-bridge"`. It does not start CARLA traffic by
default.

Useful MR overrides:

```bash
UB_MR_BUILD_FOLDER=0.0.7 ./launch/ub-mr.sh
UB_MR_LOCALIZATION=0 ./launch/ub-mr.sh
UB_KEEP_MR=1 ./launch/ub-mr.sh
BUILD_FOLDER=v1.0.0 ./launch/ub-mr.sh
CARLA_ARGS="-RenderOffScreen -quality-level=Low -nosound" ./launch/ub-mr.sh
UB_CARLA_EXTRA_SERVICES="traffic-publisher udp-bridge" ./launch/ub-mr.sh
```

**6. UB-MR two-machine client** (local UB-MR + CARLA/Autoware, remote authoritative Redis)
```bash
./launch/ub-mr-carla-client.sh <authoritative-server-ip>
```

### Authoritative CARLA + manual client

Start the authoritative CARLA server, Redis, map loader, and traffic publisher:

```bash
./launch/carla-redis-server.sh
```

In a second terminal, start the local rendered CARLA client, Redis traffic renderer, and keyboard-controlled manual CARLA client:

```bash
./launch/carla-redis-manual-client.sh 127.0.0.1
```

The manual vehicle is controlled through the authoritative CARLA API and is published to Redis by the authoritative CARLA traffic publisher like any other traffic actor. The local client opens a CARLA graphics window and mirrors server-side Redis traffic into it.

Manual controls require keyboard focus on the `CARLA Manual Control` window:
`W/Up` throttle, `S/Down` brake, `A/D` steer, `Space` full brake, `Q` reverse, `F` toggle authoritative-server chase camera, `Esc` quit.

Useful manual-client overrides:

```bash
./launch/carla-redis-manual-client.sh <authoritative-carla-host>
UB_MANUAL_ROLE_NAME=manual_vehicle ./launch/carla-redis-manual-client.sh <authoritative-carla-host>
UB_MANUAL_BLUEPRINT=vehicle.lincoln.mkz_2020 ./launch/carla-redis-manual-client.sh <authoritative-carla-host>
UB_MANUAL_COLOR=0,0,255 ./launch/carla-redis-manual-client.sh <authoritative-carla-host>
UB_MANUAL_MAX_KMH=60 ./launch/carla-redis-manual-client.sh <authoritative-carla-host>
UB_MANUAL_FOLLOW_SPECTATOR=0 ./launch/carla-redis-manual-client.sh <authoritative-carla-host>
UB_MANUAL_SPAWN_INDEX=0 ./launch/carla-redis-manual-client.sh <authoritative-carla-host>
```

Useful server overrides:

```bash
CARLA_ARGS="-RenderOffScreen -quality-level=Low -nosound" ./launch/carla-redis-server.sh
UB_TRAFFIC_NO_RENDERING=1 ./launch/carla-redis-server.sh
UB_TRAFFIC_MANAGER_PORT=8002 ./launch/carla-redis-server.sh
UB_TRAFFIC_PUBLISH_HZ=60 ./launch/carla-redis-server.sh
BUILD_FOLDER=v1.0.0 ./launch/carla-redis-server.sh
CARLA_MAP_PATH= ./launch/carla-redis-server.sh
```
