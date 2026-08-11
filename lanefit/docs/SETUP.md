# Setup: what your data and your container need

Two sets of prerequisites. [Input data](#input-data) is what your rosbag and `.xodr`
have to provide, and the `audit` stage checks all of it in the first seconds of a run.
[The tooling container](#the-tooling-container) is what has to be installed for the
pipeline to work at all, along with the runbook for rebuilding it from nothing.

The install steps themselves are in [`README.md`](../README.md).

---

## Input data

Topic names are configurable, through `topics.*` and `georeference.ins_topic` in
[`config/default.yaml`](../config/default.yaml). Everything else here is a hard
requirement.

### rosbag (ROS 2, sqlite3)

- **LiDAR**, a `sensor_msgs/PointCloud2` with an `intensity` field and a per-point time
  field named `time_stamp`, `t` or `time`. Intensity is what the width measurement runs
  on; without it there is nothing to measure.
- **IMU**, a full 3-axis `sensor_msgs/Imu`. The audit rejects NaN-axis decoys, such as
  CAN yaw-rate sensors that publish as IMUs while only populating one axis.
- **GNSS**, a NovAtel `INSPVAX` topic with RTK-fixed epochs. The default `ins_direct`
  georeferencing also reads the high-rate `INSPVA` pose stream.
- **`/tf_static`**, covering the IMU to LiDAR chain. Extrinsics are derived from it
  rather than hardcoded.

### xodr

OpenDRIVE 1.4 or newer, with a `<geoReference>` PROJ string in the header. That string
is what the point cloud gets georeferenced into, so without it the pipeline has no
common frame and stops.

Geometry may use line, arc and spiral. `paramPoly3` is not implemented yet; the audit's
geometry census tells you whether your map uses it. Elevations may be all zero, since
matching is XY-only.

### RTK coverage decides your georeferencing method

Continuous RTK-fixed coverage is what makes `ins_direct` the better choice, and it is
the default. The audit reports the RTK-fixed share so you know before you commit to a
method. Recordings without that coverage should set `georeference.method: flexcloud`,
which runs SLAM and rubber-sheets the result onto whatever GNSS there is.

---

## The tooling container

lanefit is pure Python, but its stages drive heavyweight tooling that has to exist in
the execution environment. In the reference setup that environment is a Docker
container. Verified 2026-06-18; everything is CPU-only.

| component | version / commit | provides | installed by |
|---|---|---|---|
| Ubuntu | 22.04 | base image | container image |
| ROS 2 | humble | `rclpy`, `rosbag2_py`, message definitions | container image |
| novatel_oem7_msgs | in image | INSPVAX / INSPVA deserialization | container image |
| gtsam (notbb) | 4.3.0 | glim math backend | koide3 PPA |
| iridescence | 1.0.2 | glim dependency | koide3 PPA |
| gtsam_points | `17578c8` | glim registration | source build, [koide3/gtsam_points](https://github.com/koide3/gtsam_points) |
| glim | `88b3833` | LiDAR-inertial SLAM | source build, [koide3/glim](https://github.com/koide3/glim) |
| glim_ros2 | `a62811d` | ROS 2 wrapper for glim | source build, [koide3/glim_ros2](https://github.com/koide3/glim_ros2) |
| FlexCloud | `2dad2f4` + 3 patches | georeferencing: Umeyama and rubber-sheeting | source build, [TUMFTM/FlexCloud](https://github.com/TUMFTM/FlexCloud) |
| open3d | 0.19.0 | PCD IO, binary_compressed with intensity | pip |
| pyproj | >= 3.3 | CRS projection | in image |
| scipy / numpy / matplotlib / PIL / yaml | any recent | math and figures | in image / pip |
| carla (python pkg) | matching your CARLA | validate-stage map readback, optional | pip / CARLA dist |

apt packages pulled alongside the PPA stack: `libiridescence-dev`, `libboost-all-dev`,
`libglfw3-dev`, `libmetis-dev`, `libgtsam-points-dev`. FlexCloud build deps:
`libcgal-dev`, `libgeographic-dev`, `ros-humble-rosbag2-storage-mcap`,
`ros-humble-rosbag2-storage-default-plugins`.

Python 3.10 or newer. lanefit's own declared dependencies are `numpy`, `scipy`,
`pyyaml`, `pyproj`, `matplotlib` and `pillow` (see `pyproject.toml`), plus `open3d`. A
ROS 2 humble image already ships most of them.

> [!NOTE]
> **`deps/install_deps.sh` is the source of truth for the pinned commits.** The SHAs
> live in its header. If this table and the script ever disagree, the script is right.

The three FlexCloud patches, applied idempotently by the installer: reuse the system
yaml-cpp target to avoid a FetchContent duplicate-target clash, rename the rosbag2
`SerializedBagMessage` field `send_timestamp` to humble's `time_stamp`, and swap
rerun's `spawn()` GUI viewer for a headless `save()` so the tools run without a display.

### Why source builds, and don't "fix" it back to the PPA

The koide3 apt PPA is internally inconsistent. The prebuilt `ros-humble-glim` 1.2.0 was
compiled against gtsam 4.2, but the PPA now ships gtsam 4.3.0 and gtsam_points 1.2.1.
They do not work together: you get a runtime `undefined symbol:
gtsam::PreintegratedImuMeasurements`, glim v1.2.1 source will not compile against
4.3.0, and glim master needs a gtsam_points newer than 1.2.1. Building gtsam_points,
glim and glim_ros2 from the pinned commits above against PPA gtsam 4.3.0 is the only
consistent combination found. Full diagnosis: `notes/step2_tooling.md`.

If a CUDA toolkit is ever added to the image, rebuild with `-DBUILD_WITH_CUDA=ON` and
install the matching `libgtsam-points-cudaX.Y-dev` for GPU odometry. The container
currently sees the NVIDIA driver but has no `nvcc`.

---

## Rebuilding after container loss

If the `autoware_c` container is deleted, by `dc_down`, `docker rm`, an image repull or
a machine reinstall, follow this. Budget 15 to 25 minutes, most of it the gtsam_points
and glim compiles.

### What survives, what doesn't

The container has two storage areas:

| location | survives container deletion? | what's there |
|---|---|---|
| `/host_data` (bind mount to `~/ub-lincoln-docker/docker_data/host_data`) | **YES** | source trees, colcon `build/` and `install/`, `glim_config_cpu`, the rosbag, the xodr, this doc, the installer |
| container root FS (`/usr`, `/usr/local`, apt, pip) | **NO** | gtsam 4.3.0 (apt), iridescence (apt), CGAL, open3d (pip), **gtsam_points install in `/usr/local`** |

So after a deletion the source and colcon trees are still on disk, but the runtime
libraries they link against are gone. The installer reinstalls those and rebuilds. It
is idempotent and safe to re-run: it reuses the existing source clones and pinned
commits.

### Steps

```bash
# 1. Recreate the container (host shell)
cd ~/ub-lincoln-docker/docker
./dc_up.sh          # docker compose up -d, pulls ubcavas/autoware-lincoln:latest if needed

# 2. Enter it
./dc_bash.sh        # = docker compose exec -it autoware /bin/bash

# 3. Inside the container, run the pinned installer
#    (bin/lanefit syncs the package to /host_data/lanefit; rsync it manually if
#     you have not run the wrapper yet)
bash /host_data/lanefit/deps/install_deps.sh
```

The installer:

1. Sets up the koide3 PPA and installs the dependency stack (gtsam 4.3.0, iridescence)
   plus the FlexCloud deps (CGAL, GeographicLib dev, mcap storage). Removes the broken
   PPA glim binaries.
2. `pip install open3d==0.19.0`.
3. Builds **gtsam_points** at its pinned commit, CPU-only, into `/usr/local`.
4. Builds **glim** and **glim_ros** at their pinned commits in `/host_data/ws`, and
   regenerates the CPU run-config `/host_data/glim_config_cpu`.
5. Builds **FlexCloud** at its pinned commit with the three humble-compat patches
   re-applied.

### Verify after install

```bash
source /opt/ros/humble/setup.bash && source /host_data/ws/install/setup.bash
python3 -c 'import open3d; print("open3d", open3d.__version__)'
ros2 run flexcloud georeferencing --help
ros2 run glim_ros glim_rosbag --ros-args -p config_path:=/host_data/glim_config_cpu
#   ^ should log "load libodometry_estimation_cpu.so" and similar, then wait. Ctrl-C to stop.
#   If it says "failed to open libodometry_estimation_gpu.so" instead, the config_path
#   flag was omitted; the default config is GPU.
```

### If a rebuild fails on a stale colcon cache

A `build/` dir from a previous container can hold stale CMake paths:

```bash
cd /host_data/ws
rm -rf build/glim build/glim_ros build/flexcloud install/glim install/glim_ros install/flexcloud
# then re-run the installer, which will rebuild cleanly
```

---

## Host side

Only `docker`, `rsync` and bash, for `bin/lanefit`. Configure it with
`LANEFIT_CONTAINER` (default `autoware_c`) and `LANEFIT_HOST_DATA` (default
`/home/poison/ub-lincoln-docker/docker_data/host_data`).
