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
bash scripts/install_ub_carla.sh v1.1.0
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
./launch/launch_autoware_carla.sh
```

This wrapper defaults to these CARLA settings:
`CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound"`,

The local launcher starts CARLA, the map loader, the spectator camera follower,
and Autoware. Redis is supplied by the remote server. In UB-MR's Main Menu,
connect to that server's address for traffic reception and ego publication.
Local Redis services remain available through `UB_CARLA_EXTRA_SERVICES` when
explicitly requested, or through `scripts/launch_carla_redis_server.sh` when
running an authoritative server.

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
./scripts/launch_autoware_carla_sumo.sh
```

This wrapper uses the existing
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
./scripts/launch_autoware_carla_passive.sh
```

Use this to validate the passive bridge before adding SUMO or another traffic
orchestrator. The time-master service is the only process that calls
`world.tick()`; the bridge runs with `external_tick:=True`.





**3. Multi-Agent Server**
```bash
# No Graphics
bash scripts/launch_carla_redis_server.sh
# Graphics
CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound" \
UB_TRAFFIC_NO_RENDERING=0 \
./scripts/launch_carla_redis_server.sh
```

**4. Multi-Agent Manual Client**
```bash
# Local Host
./scripts/launch_carla_redis_manual_client.sh 127.0.0.1
# Remote Host (required)
./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
```

**5. UB-MR**
```bash
# Starts UB-MR, the UB-MR localization bridge, UB-CARLA, and Autoware.
./launch/launch_ub_mr.sh
# Light graphics
CARLA_ARGS="-prefernvidia -quality-level=low -nosound" bash launch/launch_ub_mr.sh
```

This wrapper defaults to `UB_MR_BUILD_FOLDER=0.0.8`, `BUILD_FOLDER=v1.1.0`,
`CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound"`, and
`UB_CARLA_EXTRA_SERVICES=""`. It does not start local Redis, a UDP bridge, or
CARLA traffic by default. Connect to the remote server through UB-MR's Main Menu.

Autoware maps are selected by the same `BUILD_FOLDER`, under
`Autoware/host_data/maps/ub_autonomous_proving_grounds/<BUILD_FOLDER>/`.
Each folder needs `lanelet2_map.osm`, `pointcloud_map.pcd`, and
`map_projector_info.yaml`. See [versioned map setup](CARLA/CARLA_README.md)
for keeping old and new map sets and using custom paths.

Useful MR overrides:

```bash
UB_MR_BUILD_FOLDER=0.0.7 ./launch/launch_ub_mr.sh
UB_MR_LOCALIZATION=0 ./launch/launch_ub_mr.sh
UB_KEEP_MR=1 ./launch/launch_ub_mr.sh
BUILD_FOLDER=v1.0.0 ./launch/launch_ub_mr.sh
CARLA_ARGS="-RenderOffScreen -quality-level=Low -nosound" ./launch/launch_ub_mr.sh
UB_CARLA_EXTRA_SERVICES="traffic-publisher udp-bridge" ./launch/launch_ub_mr.sh
```

For Unity editor development, launch the project with the ROS 2 Humble and
CycloneDDS environment configured:

```bash
./launch/launch_ub_mr_dev.sh
```

The launcher finds the repository automatically and reads the required Unity
version from the project. It searches common Linux Unity Hub installation paths
and then `Unity` on `PATH`. For a custom installation, use
`UNITY_EDITOR=/path/to/Editor/Unity ./launch/launch_ub_mr_dev.sh`.
`ROS_DOMAIN_ID` defaults to `0`; `--dry-run` previews the launch without starting
Unity or restarting ROS discovery. Extra arguments are forwarded to Unity.

In another terminal, start the localization bridge for the editor:

```bash
./launch/launch_mr_pkg_dev.sh             # CARLA: simulation time from /clock
./launch/launch_mr_pkg_dev.sh --physical  # Physical vehicle: system time
```

Run only the bridge matching your setup. The launcher sources ROS 2 Humble and
the same CycloneDDS helper, defaults `ROS_DOMAIN_ID` to `0`, and runs the checked-out
mr_pkg Python source without requiring a colcon build. Use `--dry-run` to preview
the command. This DDS configuration uses loopback for Autoware on the same host.
The default runs `carla_localization`; `--physical` runs `autoware_localization`
with its existing MGRS-to-local coordinate conversion and configured map origin.
Physical mode requires `sudo apt install python3-pyproj` and the Unity agent's
ROS clock setting should also use system time. Both bridges preserve incoming
odometry timestamps.

For direct bounding-box injection, import and select
`UB-MR/Agents/agent-LincolnMKZ-CARLA-Boxes.json` (simulation clock) or
`UB-MR/Agents/agent-LincolnMKZ-Physical-Boxes.json` (system clock).
These replace `LincolnMKZ-Simple`; both publish `/virtual_obstacles` at 30 Hz
within 1,000 m. Use the matching localization bridge above and enable the Autoware
perception profile. For CARLA boxes, run
`UB_MR_PERCEPTION_PROFILE=1 AUTOWARE_RVIZ=true ./launch/launch_autoware_carla.sh`.

For a **Unity editor LiDAR-modification test**, start the editor and localization
bridge above, then launch CARLA/Autoware with:

```bash
./launch/launch_autoware_carla_ub_mr_lidar.sh
```

Import `UB-MR/Agents/agent-LincolnMKZ-CARLA-LiDAR.json` into Unity's agent folder
and select **LincolnMKZ-CARLA-LiDAR** for a new session. This configures **LiDAR
modification**, **Simulation /clock**, input
`/sensing/lidar/top/pointcloud_before_sync`, and the CARLA top-sensor mounting pose
(Unity position `x=0, y=3.1, z=1.394`, zero rotation). The physical Lincoln agent's
`pointcloud_raw_ex` topic does not receive scans from this CARLA bridge.
The test launcher routes Unity's `/sensing/lidar/top/pointcloud_before_sync_modified`
output into Autoware, enables the UB-MR perception profile, and defaults RViz on.
Perception receives no scans until Unity publishes; it does not fall back to the
original cloud. Compare the original and modified topics in RViz to check virtual
returns before checking detector output. In LiDAR mode, `/virtual_obstacles`
should have no publisher.

The standalone `CARLA/start_autoware_carla.sh` is unchanged. This opt-in launcher
checks the expected relay assignment and runs a temporary copy with only its input
topic changed, then removes that copy on exit. It retains the original launcher's
setup and cleanup. `--dry-run` checks and previews the launch. Use the regular
`launch_autoware_carla.sh` for standalone CARLA or direct bounding-box tests.

### Authoritative CARLA + manual client

Start the authoritative CARLA server, Redis, map loader, traffic publisher, and ego renderer:

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

For the Unity Editor/client, use **UB-MR Main Menu → Server connection** to enter
the Redis server address, port, channel and password. This connects traffic and
ego publishing directly, without a local UDP bridge. See
[UB-MR server connection](UB-MR/docs/server-connection.md).
