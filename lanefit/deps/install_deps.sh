#!/bin/bash
# =============================================================================
# map_conflation — Step 2 tooling installer (glim, gtsam_points, FlexCloud, open3d)
# Run as root INSIDE the autoware_c container.
#
# See ../docs/SETUP.md for the full "I deleted the container" procedure. This script is
# the step that runs once you are inside a fresh container.
#
# WHY SOURCE BUILDS: the koide3 PPA ships an internally inconsistent set
# (glim 1.2.0 binary vs gtsam 4.3.0 vs gtsam_points 1.2.1) that does not link/
# compile together. We use the PPA only to pull the dependency stack (gtsam 4.3.0,
# iridescence) and build gtsam_points + glim + glim_ros2 from source, pinned to the
# exact commits verified working on 2026-06-18.
# =============================================================================
set -e
export DEBIAN_FRONTEND=noninteractive

# ---- pinned known-good commits (verified 2026-06-18) ----
GTSAM_POINTS_SHA=17578c8e8c1dc9bd55b0b8c31d2656230098977c   # v1.2.1-12-g17578c8
GLIM_SHA=88b3833229a9c3308e95065719a40acdd5f64c33           # v1.2.1-3-g88b3833
GLIM_ROS2_SHA=a62811dc3ab73076f4a43fc21005f96cd712903c      # v1.2.1-2-ga62811d
FLEXCLOUD_SHA=2dad2f49939da240dbbef3ee6e4b6239d59b93e3      # docs 1.0.2
# gtsam(notbb)=4.3.0, iridescence=1.0.2, open3d=0.19.0 come from PPA/pip below.

clone_pin() {  # url dir sha
  local url=$1 dir=$2 sha=$3
  [ -d "$dir" ] || git clone "$url" "$dir"
  git -C "$dir" fetch --all --tags --quiet || true
  git -C "$dir" checkout --quiet "$sha"
  echo "  $dir @ $(git -C "$dir" rev-parse --short HEAD)"
}

echo "=== [1/5] dependency stack via koide3 PPA ==="
apt-get update
apt-get install -y curl gpg git
curl -s https://koide3.github.io/ppa/setup_ppa.sh | bash
apt-get update
# pulls gtsam 4.3.0 (libgtsam-notbb-dev) + iridescence as deps:
apt-get install -y libiridescence-dev libboost-all-dev libglfw3-dev libmetis-dev libgtsam-points-dev
# FlexCloud build deps:
apt-get install -y libcgal-dev libgeographic-dev \
  ros-humble-rosbag2-storage-mcap ros-humble-rosbag2-storage-default-plugins
# remove the stale PPA glim binaries (we build from source instead):
apt-get remove -y ros-humble-glim ros-humble-glim-ros || true
ldconfig

echo "=== [2/5] open3d ==="
pip3 install --no-cache-dir open3d==0.19.0

echo "=== [3/5] gtsam_points (CPU) -> /usr/local (overrides PPA 1.2.1) ==="
cd /host_data
clone_pin https://github.com/koide3/gtsam_points.git gtsam_points "$GTSAM_POINTS_SHA"
cd gtsam_points
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_WITH_CUDA=OFF -DBUILD_DEMO=OFF -DBUILD_TESTS=OFF
make -j"$(nproc)" && make install && ldconfig

echo "=== [4/5] glim + glim_ros (CPU) in colcon ws ==="
mkdir -p /host_data/ws/src && cd /host_data/ws/src
clone_pin https://github.com/koide3/glim.git      glim      "$GLIM_SHA"
clone_pin https://github.com/koide3/glim_ros2.git glim_ros2 "$GLIM_ROS2_SHA"
source /opt/ros/humble/setup.bash
cd /host_data/ws
colcon build --packages-select glim glim_ros \
  --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_WITH_CUDA=OFF

# CPU run-config: default config.json selects GPU modules we didn't build.
GLIM_CFG_SRC=/host_data/ws/install/glim/share/glim/config
GLIM_CFG_DST=/host_data/glim_config_cpu
rm -rf "$GLIM_CFG_DST" && cp -r "$GLIM_CFG_SRC" "$GLIM_CFG_DST"
sed -i 's/config_odometry_gpu.json/config_odometry_cpu.json/; \
        s/config_sub_mapping_gpu.json/config_sub_mapping_cpu.json/; \
        s/config_global_mapping_gpu.json/config_global_mapping_cpu.json/' \
  "$GLIM_CFG_DST/config.json"
echo "  glim CPU config -> $GLIM_CFG_DST"

echo "=== [5/5] FlexCloud (humble patches applied in tree) in colcon ws ==="
cd /host_data/ws/src
clone_pin https://github.com/TUMFTM/FlexCloud.git FlexCloud "$FLEXCLOUD_SHA"
# Three source patches (idempotent):
#  - reuse system yaml-cpp target (avoid FetchContent duplicate-target clash)
#  - rosbag2 SerializedBagMessage field: send_timestamp -> time_stamp (humble name)
#  - rerun: spawn() GUI viewer -> save() headless .rrd (so tools run without a display)
python3 - <<'PY'
p="FlexCloud/CMakeLists.txt"; s=open(p).read()
old="FetchContent_MakeAvailable(rerun_sdk yaml-cpp CLI11)"
new=("if(NOT TARGET yaml-cpp)\n  FetchContent_MakeAvailable(yaml-cpp)\nendif()\n"
     "if(NOT TARGET yaml-cpp::yaml-cpp)\n  add_library(yaml-cpp::yaml-cpp ALIAS yaml-cpp)\nendif()\n"
     "FetchContent_MakeAvailable(rerun_sdk CLI11)")
if old in s: open(p,"w").write(s.replace(old,new)); print("  patched CMakeLists (yaml-cpp)")
else: print("  CMakeLists yaml-cpp patch already applied / anchor absent")
PY
sed -i 's/bag_msg->send_timestamp/bag_msg->time_stamp/g' \
  FlexCloud/include/flexcloud/rosbag_reader.hpp
sed -i 's#this->rec_.spawn().exit_on_failure();#this->rec_.save("/tmp/flexcloud_georef.rrd").exit_on_failure();#' \
  FlexCloud/src/georeferencing.cpp
sed -i 's#this->rec_.spawn().exit_on_failure();#this->rec_.save("/tmp/flexcloud_keyframe.rrd").exit_on_failure();#' \
  FlexCloud/src/keyframe_interpolation.cpp
cd /host_data/ws
colcon build --packages-select flexcloud \
  --cmake-args -DCMAKE_BUILD_TYPE=Release -DCMAKE_MODULE_PATH=/usr/share/cmake/geographiclib

echo
echo "=== DONE. Verify with: ==="
echo "  source /opt/ros/humble/setup.bash && source /host_data/ws/install/setup.bash"
echo "  python3 -c 'import open3d; print(open3d.__version__)'"
echo "  ros2 run glim_ros glim_rosbag --ros-args -p config_path:=/host_data/glim_config_cpu  # Ctrl-C after modules load"
echo "  ros2 run flexcloud georeferencing --help"
