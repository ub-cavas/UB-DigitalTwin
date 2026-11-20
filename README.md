# UB Digital Twin

To build or update CARLA point-cloud and Lanelet maps, see
[Map-Reconstruction](Map-Reconstruction/README.md).

## Setup Instructions

1. Clone this repo and submodules
```bash
# SSH
git clone --recurse-submodules git@github.com:ub-cavas/UB-DigitalTwin.git
# HTTPS
git clone --recurse-submodules https://github.com/ub-cavas/UB-DigitalTwin.git
```

2. Download the CARLA build and matching Autoware maps
```bash
bash scripts/install_ub_carla.sh v1.1.0
# Build the Runtime Containers (CARLA Server, Redis Server, Python-API)
docker build -f CARLA/Dockerfile -t ub-carla CARLA
docker build -f CARLA/UB-API/redis-networking/Dockerfile -t ub-carla-redis-networking .
```

UB-MR and CARLA clients share experiment logging and graphs. See
[client experiment logging](docs/experiment-logging.md) for keyboard, wheel,
joystick, drive-sim and Mustang hooks, Docker output paths, and the reusable API.

The installer uses the public release folders and accepts `1.1.0` or `v1.1.0`.
It installs CARLA into `CARLA/Builds/v1.1.0/` and maps into
`Autoware/host_data/maps/ub_autonomous_proving_grounds/v1.1.0/`.
Existing complete installations are reused. Check an upload without downloading:

```bash
bash scripts/install_ub_carla.sh v1.1.0 --check
```

3. Set up Autoware (from the repository root)
```bash
bash Autoware/setup_autoware.sh v1.1.0
```

Autoware setup uses the same map downloader and skips maps already installed.
See [release download details](CARLA/CARLA_README.md) for maps-only downloads,
public folder naming, and other versions.

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

# Select the generated Town10HD map, including its matching spawn point.
./launch/launch_autoware_carla.sh --map town10hd --dry-run
./launch/launch_autoware_carla.sh --map town10hd
```

UB remains the default. Use `--list-maps` to see available profiles or
`--map-config FILE` for a custom map. See [map configurations](launch/maps/README.md)
for configuration fields and environment overrides.

This wrapper defaults to these CARLA settings:
`CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound"`,

The local launcher starts CARLA, the map loader, the spectator camera follower,
and Autoware. Redis is supplied by the remote server. In UB-MR's Main Menu,
connect to that server's address for traffic reception and ego publication.
Local Redis services remain available through `UB_CARLA_EXTRA_SERVICES` when
explicitly requested, or through `launch/launch_carla_redis_server.sh` when
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
bash launch/launch_carla_redis_server.sh
# Graphics
CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound" \
UB_TRAFFIC_NO_RENDERING=0 \
./launch/launch_carla_redis_server.sh

# Stop the server and its supporting services from another terminal
./launch/stop_carla_redis_server.sh
```

**4. Multi-Agent Manual Client**
```bash
# GCP/IAP (opens and closes its own tunnel; argument is the Redis password)
./scripts/launch_carla_redis_manual_client.sh --iap 'your-shared-password'
# Local Host
./scripts/launch_carla_redis_manual_client.sh 127.0.0.1
# Direct Remote Host
./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
```

**5. UB-MR**
```bash
# Latest UB-MR player only, using the existing ub-mr Docker image
./launch/launch_ub_mr.sh
# Select a player release
./launch/launch_ub_mr.sh --version v0.0.9
# UB-MR plus CARLA and map-loader
./launch/launch_ub_mr.sh --carla
# Full stack: UB-MR, CARLA, Autoware, and container localization
./launch/launch_ub_mr.sh --auto
# Same full stack with a managed Redis IAP tunnel
./launch/launch_ub_mr.sh --auto --iap
# Unity editor, optionally with CARLA or the full stack
./launch/launch_ub_mr.sh --dev
./launch/launch_ub_mr.sh --dev --carla
./launch/launch_ub_mr.sh --dev --auto -- -batchmode
```

The default now starts only UB-MR. Player release selection is `--version TAG`
then nonempty `UB_MR_BUILD_FOLDER`, then nonempty `UB_MR_RELEASE`, then `latest`.
Concrete cached releases launch offline. `latest` resolves GitHub's current
release tag each time and reuses only its cache. Cache lookup prefers
`UB-MR/Builds/TAG/UB-MR.x86_64`, then the numeric leading-`v` alias (for example
`v0.0.9` and `0.0.9`). Missing players are installed with the existing
`UB-MR/download_unity_player.sh TAG`, then verified at those same paths.
Unrelated cached builds are never selected. `IMAGE_NAME` retains the existing
runtime override and defaults to `ub-mr` for the player; no runtime image is
pulled or tagged by this launcher.

Only selected components need their prerequisites: player mode needs Docker and
the existing UB-MR runtime image; missing builds additionally need the downloader,
`curl`, `tar` and `unzip`; resolving latest also needs Python 3. Editor mode needs
ROS 2 Humble, project files and Unity, without requiring Docker. `--carla` needs
Docker Compose v2 and the CARLA build, without Autoware or its maps. `--auto`
uses the existing Autoware/CARLA launcher's prerequisites and teardown. Managed
child sessions use Linux `setsid` and GNU `env` signal handling.

`BUILD_FOLDER` selects CARLA independently (default `v1.1.0`), with
`CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound"` and
`UB_CARLA_EXTRA_SERVICES=""`. No local Redis, UDP bridge or traffic starts by
default. CARLA-only mode starts `carla`, `map-loader` and explicitly requested
extra services, preserving running selected services and cleaning up only its
own services. `--auto` uses the existing delegate's lifecycle. Autoware maps
follow `BUILD_FOLDER` under
`Autoware/host_data/maps/ub_autonomous_proving_grounds/<BUILD_FOLDER>/`;
see [versioned map setup](CARLA/CARLA_README.md).

```bash
UB_MR_BUILD_FOLDER=0.0.9 ./launch/launch_ub_mr.sh
UB_MR_LOCALIZATION=0 ./launch/launch_ub_mr.sh --auto
UB_KEEP_MR=1 ./launch/launch_ub_mr.sh --carla
UB_KEEP_CARLA=1 ./launch/launch_ub_mr.sh --carla
BUILD_FOLDER=v1.0.0 ./launch/launch_ub_mr.sh --auto
CARLA_ARGS="-RenderOffScreen -quality-level=Low -nosound" ./launch/launch_ub_mr.sh --carla
UB_CARLA_EXTRA_SERVICES="redis traffic-publisher udp-bridge" ./launch/launch_ub_mr.sh --carla
```

Primary editor/player exit ends the session; companion failures also end it.
`UB_KEEP_MR=1` retains an owned player and localization, while closing attached
launcher processes and IAP. Reused containers must mount the selected player
build and are never removed. `UB_KEEP_CARLA=1` retains CARLA services;
`UB_KEEP_AUTOWARE_ROS` keeps its existing delegate behavior. Container
localization starts only for player mode with CARLA and
`UB_MR_LOCALIZATION=1` (default). Editor localization remains a separate workflow.

The editor version comes from `ProjectSettings/ProjectVersion.txt`, searching
common Linux Unity Hub locations then `Unity` on `PATH`. Set
`UNITY_EDITOR=/path/to/Editor/Unity` for a custom installation.
`ROS_DOMAIN_ID` defaults to `0`. Pass Unity arguments after `--`; `--version`
cannot be combined with `--dev`. `launch_ub_mr_dev.sh` is a compatibility wrapper
that also preserves legacy trailing Unity arguments without `--`.

Editor logs default to `Client-Logs/ub-mr/unity-editor.log`, using
`UB_CLIENT_LOG_ROOT` / `UB_CLIENT_LOG_DIR` overrides. Explicit Unity `-logFile`
or `-logFile=...` arguments take precedence. Editor experiment directories use
`UB_EXPERIMENT_DIR`, then `UB_EXPERIMENT_HOST_DIR`, then `UB_MR_METRICS_DIR`,
then the client log directory's `experiments` folder. Player logging retains the
runtime's `UB_MR_LOG_DIR`, `UB_CLIENT_LOG_ROOT` and `UB_EXPERIMENT_HOST_DIR`
contracts.

With `--iap`, the launcher opens exactly one Redis forward before starting
clients and closes it on exit or Ctrl+C, including with `UB_KEEP_MR=1`.
Authenticated `gcloud` and `ssh` are required only for actual IAP execution.
In **Main Menu → Server connection**, use `127.0.0.1`, port `16390`, your
Redis channel (normally `carla:telemetry`) and the remote Redis password.
Override `UB_IAP_INSTANCE`, `UB_IAP_PROJECT`, `UB_IAP_ZONE`,
`UB_IAP_REDIS_HOST`, `UB_IAP_REDIS_PORT` or `UB_IAP_LOCAL_REDIS_PORT` as needed.
VM defaults are `carla` / `buf-prj-digitaltwin-svxz` / `us-central1-a`.
CARLA ports `2000`/`2001` remain available locally. The manual-driver launcher
continues to accept its password after `--iap`.

`--dry-run` previews the selected commands and IAP without starting applications,
tunnels, downloads or ROS discovery, creating logs, or changing executable modes.
Latest remains explicitly unresolved during a dry run; a missing player is shown
as a planned download. `--auto --dry-run` also runs the delegate's read-only
preflight. Start the editor with `--iap` for the LiDAR and bounding-box workflows
below; local CARLA/ROS remain separate from remote Redis.

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
./launch/launch_carla_redis_server.sh
```

Stop these services from another terminal with:

```bash
./launch/stop_carla_redis_server.sh
```

The stop script keeps containers for reuse. If you set `COMPOSE_PROJECT_NAME`
when launching, use the same value when stopping.

Full telemetry payload logging is disabled by default; `telemetry.log` retains
start and stop events. Set `UB_TELEMETRY_LOG_PAYLOADS=1` when launching to enable
payload logs for debugging. These logs can grow rapidly. After updating the
code, run the launcher again to rebuild and recreate the networking containers.
Existing log files are not truncated by this setting.

In a second terminal, start the local rendered CARLA client, Redis traffic renderer, and keyboard-controlled manual CARLA client:

```bash
./scripts/launch_carla_redis_manual_client.sh 127.0.0.1
```

The manual vehicle is controlled through the authoritative CARLA API and is published to Redis by the authoritative CARLA traffic publisher like any other traffic actor. The local client opens a CARLA graphics window and mirrors server-side Redis traffic into it.

For the GCP server, use the launcher's managed IAP tunnel instead:

```bash
./scripts/launch_carla_redis_manual_client.sh --iap 'your-shared-password'
```

Optional network-statistics logging uses UB-MR's shared recorder and plotter:

```bash
./scripts/launch_carla_redis_manual_client.sh --iap 'your-shared-password' --log-network
# Skip recording for this session:
./scripts/launch_carla_redis_manual_client.sh --iap 'your-shared-password' --no-log-network
```

Logs default to `Client-Logs/manual-control/experiments/run-*` and include `metrics.csv`, metadata,
`summary.json`, recording status, and PNG graphs generated on clean shutdown.
Use `--log-dir DIRECTORY` to select the output parent and `--network-interface`
to select host byte counters. Managed IAP logging selects the interface toward
the IAP gateway; its counters cover host traffic including other processes.
Docker manual launchers retain recording enabled by default; native keyboard
and wheel clients opt in with `--log-network`. See
[shared client experiment logging](docs/experiment-logging.md) for measurements,
scope, setup, and native-client examples.

All client logs live under the repository-root `Client-Logs/` folder:

| Client | Experiment logs | Runtime logs |
| --- | --- | --- |
| UB-MR player/editor | `Client-Logs/ub-mr/experiments/` | `ub-mr-player.log` or `unity-editor.log` under `Client-Logs/ub-mr/` |
| Manual CARLA | `Client-Logs/manual-control/experiments/` | `manual-control.log` and Redis `telemetry.log` under `Client-Logs/manual-control/` |

Set `UB_CLIENT_LOG_ROOT=/absolute/path` to relocate the shared root. Existing
per-client output overrides are still supported. Logs are excluded from Git.

This targets instance `carla` in project `buf-prj-digitaltwin-svxz`, zone
`us-central1-a`. It forwards Redis through local port `16390` and the remote
CARLA API through `12000`, and remote CARLA world-state streaming through
`2001`, while local CARLA renders on `2100`. The streaming forward is needed
for vehicle spawning and control even with local rendering. The tunnel
closes when the launcher exits. Authenticate gcloud before launching; the
password argument is for Redis. See [server/client setup](CARLA/SERVER_CLIENT_SETUP.md)
for VM and Redis bind-address overrides.

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
CARLA_ARGS="-RenderOffScreen -quality-level=Low -nosound" ./launch/launch_carla_redis_server.sh
UB_TRAFFIC_NO_RENDERING=1 ./launch/launch_carla_redis_server.sh
UB_TRAFFIC_MANAGER_PORT=8002 ./launch/launch_carla_redis_server.sh
UB_TRAFFIC_PUBLISH_HZ=60 ./launch/launch_carla_redis_server.sh
BUILD_FOLDER=v1.0.0 ./launch/launch_carla_redis_server.sh
CARLA_MAP_PATH= ./launch/launch_carla_redis_server.sh
```

For the Unity Editor/client, use **UB-MR Main Menu → Server connection** to enter
the Redis server address, port, channel and password. This connects traffic and
ego publishing directly, without a local UDP bridge. See
[UB-MR server connection](UB-MR/docs/server-connection.md).
