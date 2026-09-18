Run UB-CARLA
-----------------------------

One-command rendered CARLA + Autoware
-----------------------------

From the repository root, install the packaged CARLA build and Autoware assets:

```bash
bash scripts/install_ub_carla.sh v1.1.0

cd Autoware
./setup_autoware.sh v1.1.0
```

Launchers default to `CARLA/Builds/v1.1.0`. Set `BUILD_FOLDER` to use another
installed build (or pass the build folder as the first argument to
`run_ub_carla.sh`).

Keep a separate Autoware map set for each packaged CARLA build:

```text
Autoware/host_data/maps/ub_autonomous_proving_grounds/
  v1.0.0/
    lanelet2_map.osm
    pointcloud_map.pcd
    map_projector_info.yaml
  v1.1.0/
    lanelet2_map.osm
    pointcloud_map.pcd
    map_projector_info.yaml
```

`BUILD_FOLDER` selects both the CARLA build and its map directory for the
Autoware, UB-MR, LiDAR, passive, and SUMO launchers. For example:

```bash
BUILD_FOLDER=v1.0.0 ./launch/launch_ub_mr.sh
# Uses v1.1.0 and its matching map files by default:
./launch/launch_ub_mr.sh
```

Download releases with `scripts/install_ub_carla.sh VERSION` (from the repository
root). It uses these public folders without a Google login, API key, `gdown`,
or GitHub release metadata; only Python 3.10+ is required:

- [CARLA builds](https://drive.google.com/drive/folders/1dCVDd7S98pTDgj6CzOwHFzPWFqo9Gcrv):
  one `UB-CARLA-v1.1.0.zip` (or `v1.1.0.zip`) per version. Archives may contain
  a top-level build folder or the build files directly.
- [Autoware maps](https://drive.google.com/drive/folders/1sGHwToKv8zCPXMBhPDRDJAsTEKW5T0Uy):
  a folder named `v1.1.0` per version, containing `lanelet2_map.osm`,
  `pointcloud_map.pcd`, and `map_projector_info.yaml` directly inside it.

```bash
# Install the matching pair (1.1.0 and v1.1.0 are equivalent):
bash scripts/install_ub_carla.sh 1.1.0
# Check public upload availability without downloading:
bash scripts/install_ub_carla.sh v1.1.0 --check
# Download only the maps, e.g. for a manually installed CARLA build:
bash scripts/install_ub_carla.sh v1.1.0 --maps-only
# Install an older matching pair:
bash scripts/install_ub_carla.sh --version v1.0.0
```

The default version is `BUILD_FOLDER`, or `v1.1.0` when unset. `--tag` is an
alias for `--version`; `latest` is not used. Missing uploads produce an error
without selecting an older release. Retry the same command when uploading
finishes. Complete local components are reused independently, so an existing
CARLA build does not prevent downloading missing maps. Nonempty incomplete
installations are preserved: move them aside or finish them manually before
retrying. Empty version directories are accepted. Downloads are staged and
validated before installation; older versions are never replaced.

`Autoware/setup_autoware.sh VERSION` uses this same maps-only download before
setting up Autoware. Its `--build_local` option remains available. New downloads
go into versioned directories only; the unversioned map layout is still a
launcher fallback for v1.0.0 when no v1.0.0 directory exists.

You can also copy matching map files into a versioned folder manually. Reuse
`map_projector_info.yaml` only if projection settings are unchanged. Preflight
requires all three files to be nonempty.

For custom maps under `Autoware/host_data`, set either `AUTOWARE_HOST_MAP_DIR`
(absolute host path) or `AUTOWARE_MAP_PATH` (path under `/host_data` in the
container); the other path is derived automatically. For a custom Docker
mount outside that tree, supply both paths and configure the mount yourself.
Restart the launcher after changing map files.

Then launch rendered CARLA on `UBAutonomousProvingGrounds` and run the Autoware
CARLA simulator launch in the foreground:

```bash
cd ../CARLA
./start_autoware_carla.sh
```

The launcher uses `docker compose up --build -d carla redis map-loader`, waits
for the map loader to finish, starts the Autoware Compose service, and runs:

```bash
ros2 launch autoware_launch e2e_simulator.launch.xml \
  map_path:=/host_data/maps/ub_autonomous_proving_grounds/v1.1.0 \
  vehicle_model:=sample_vehicle \
  sensor_model:=awsim_sensor_kit \
  simulator_type:=carla \
  host:=127.0.0.1 \
  carla_map:=UBAutonomousProvingGrounds
```

Check prerequisites without starting containers:

```bash
./start_autoware_carla.sh --dry-run
```

Common overrides:

```bash
CARLA_ARGS="-prefernvidia -quality-level=Epic" ./start_autoware_carla.sh
AUTOWARE_SERVICE=<compose-service-name> ./start_autoware_carla.sh
AUTOWARE_CARLA_HOST=<host-ip-visible-from-autoware> ./start_autoware_carla.sh
UB_AUTOWARE_INSTALL_PY_DEPS=0 ./start_autoware_carla.sh
UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY=0 ./start_autoware_carla.sh
UB_KEEP_CARLA=1 ./start_autoware_carla.sh
```

By default, the launcher verifies and installs the required Autoware-container
Python packages (`carla==0.9.16`, `transforms3d==0.4.2`) before running the ROS
launch.

Before launching ROS, the launcher also installs
`raw_vehicle_cmd_converter.ub_lincoln.param.yaml` and the three
`ub_lincoln_{accel,brake,steer}_map.csv` files from the bridge source mounted by
Docker Compose into Autoware's installed package share directory. It refreshes
these files on every launch, including after replacing the image or recreating
the container, and stops with an explicit error if any source file is missing.
This also applies to `launch/launch_ub_mr.sh` and
`launch/launch_autoware_carla.sh`, which delegate to this launcher. Keep the
repository bridge files available at `UB_AUTOWARE_CARLA_INTERFACE_PATH` (or its
Compose default). This is startup installation; the files are not baked into
the image, so manually launching ROS without this launcher does not perform it.

NDT is enabled during pose initialization so the scan matcher is activated and
provides continuous pose corrections to the EKF. Both the CARLA/Autoware and
UB-MR launchers leave the operation-mode availability override disabled by
default, so Auto availability reflects Autoware's diagnostics.

It also enables `UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY=1` by default. This patches
the running Autoware container's sensor-kit synchronizer for the current CARLA
bridge, which spawns one top LiDAR while Autoware expects multiple pointcloud
inputs.

Manual Autoware Install + Setup
-----------------------------

Autoware Install + Setup

1.) Follow the autoware (docker) install steps here: https://github.com/ub-cavas/ub-lincoln-docker/tree/main

2.) Download the map files for your CARLA version from the [public Autoware map folder](https://drive.google.com/drive/folders/1sGHwToKv8zCPXMBhPDRDJAsTEKW5T0Uy), or run `bash scripts/install_ub_carla.sh v1.1.0 --maps-only` from the repository root.

3.) The downloaded files should be located at: "/host_data/maps/ub_autonomous_proving_grounds/v1.1.0" (inside Docker)

4.) Install updated dependencies to the autoware container 

`pip3 install carla==0.9.16`

`pip3 install --upgrade transforms3d`

CARLA Install + Setup

1.) Download the packaged version:  
2.) Extract the files somewhere on your PC (we recommend ~/Desktop/)

Co-Simulation (Autoware + CARLA)

1.) Start the CARLA server

`./CarlaUE4.sh -prefernvidia`

2.) Launch Autoware

`ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=/host_data/maps/ub_autonomous_proving_grounds/v1.1.0 vehicle_model:=sample_vehicle sensor_model:=awsim_sensor_kit simulator_type:=carla carla_map:=UBAutonomousProvingGrounds`

3.) Run the camera script

`cd UB-API`

`python3 camera_follow.py`

4.) Wait for RVIZ2 to launch and for the ego-vehicle to localize itself

5.) Set a goal position

6.) Select the "Auto" button in RVIZ

7.) The ego-vehicle should navigate to the designated goal position using autoware

8.) Spawn traffic

`cd UB-API/Traffic`

`python3 spawn_traffic.py`


Edit UB-CARLA in Unreal Engine 
----------------------------
cd /carla
make launch

