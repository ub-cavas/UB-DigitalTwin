#!/usr/bin/env bash
# Autoware container bring-up and ROS-process cleanup, shared by every
# Autoware scenario. Scenario scripts set AUTOWARE_DOCKER_DIR,
# AUTOWARE_SERVICE, UB_AUTOWARE_RMW_IMPLEMENTATION, UB_AUTOWARE_CYCLONEDDS_URI,
# and UB_AUTOWARE_CLEAN_STALE_PROCESSES before calling these.

# The full set of Autoware e2e_simulator node binaries. Both the plain
# (self-tick) and SUMO/passive (external-tick) scenarios launch
# e2e_simulator.launch.xml, so both need this list when cleaning up.
AUTOWARE_E2E_CLEANUP_PATTERNS=(
  "ros2 launch autoware_launch e2e_simulator.launch.xml"
  "/autoware/install/autoware_carla_interface/lib/autoware_carla_interface/autoware_carla_interface"
  "/opt/ros/humble/lib/rclcpp_components/component_container"
  "/opt/ros/humble/lib/rclcpp_components/component_container_mt"
  "/opt/ros/humble/lib/rviz2/rviz2"
  "/autoware/install/autoware_default_adapi/lib/autoware_default_adapi/web_server.py"
  "/autoware/install/autoware_adapi_adaptors/lib/autoware_adapi_adaptors/initial_pose_adaptor_node"
  "/autoware/install/autoware_adapi_adaptors/lib/autoware_adapi_adaptors/routing_adaptor_node"
  "/autoware/install/autoware_automatic_pose_initializer/lib/autoware_automatic_pose_initializer/autoware_automatic_pose_initializer_node"
  "/autoware/install/autoware_stop_filter/lib/autoware_stop_filter/autoware_stop_filter_node"
  "/autoware/install/autoware_pose_initializer/lib/autoware_pose_initializer/autoware_pose_initializer_node"
  "/autoware/install/autoware_topic_state_monitor/lib/autoware_topic_state_monitor/autoware_topic_state_monitor_node"
  "/autoware/install/autoware_processing_time_checker/lib/autoware_processing_time_checker/processing_time_checker_node"
  "/autoware/install/autoware_service_log_checker/lib/autoware_service_log_checker/service_log_checker_node"
  "/autoware/install/autoware_map_hash_generator/lib/autoware_map_hash_generator/map_hash_generator"
  "/autoware/install/autoware_goal_pose_visualizer/lib/autoware_goal_pose_visualizer/goal_pose_visualizer"
  "/autoware/install/autoware_external_velocity_limit_selector/lib/autoware_external_velocity_limit_selector/external_velocity_limit_selector"
  "/autoware/install/autoware_planning_validator/lib/autoware_planning_validator/planning_validator_node"
  "/autoware/install/autoware_control_validator/lib/autoware_control_validator/control_validator_node"
  "/autoware/install/autoware_remaining_distance_time_calculator/lib/autoware_remaining_distance_time_calculator/autoware_remaining_distance_time_calculator_node"
  "/autoware/install/autoware_vehicle_cmd_gate/lib/autoware_vehicle_cmd_gate/vehicle_cmd_gate"
  "/autoware/install/autoware_raw_vehicle_cmd_converter/lib/autoware_raw_vehicle_cmd_converter/autoware_raw_vehicle_cmd_converter_node"
  "/autoware/install/autoware_gyro_odometer/lib/autoware_gyro_odometer/autoware_gyro_odometer_node"
  "/autoware/install/autoware_ndt_scan_matcher/lib/autoware_ndt_scan_matcher/autoware_ndt_scan_matcher_node"
  "/autoware/install/autoware_ekf_localizer/lib/autoware_ekf_localizer/autoware_ekf_localizer_node"
  "/autoware/install/autoware_twist2accel/lib/autoware_twist2accel/autoware_twist2accel_node"
  "/autoware/install/autoware_pose_instability_detector/lib/autoware_pose_instability_detector/autoware_pose_instability_detector_node"
  "/autoware/install/autoware_localization_error_monitor/lib/autoware_localization_error_monitor/autoware_localization_error_monitor_node"
  "/autoware/install/autoware_vehicle_velocity_converter/lib/autoware_vehicle_velocity_converter/autoware_vehicle_velocity_converter_node"
  "/autoware/install/autoware_imu_corrector/lib/autoware_imu_corrector/imu_corrector_node"
  "/autoware/install/autoware_gyro_bias_estimator/lib/autoware_gyro_bias_estimator/gyro_bias_estimator_node"
  "/autoware/install/autoware_scenario_selector/lib/autoware_scenario_selector/autoware_scenario_selector_node"
  "/autoware/install/autoware_mrm_handler/lib/autoware_mrm_handler/autoware_mrm_handler_node"
  "/autoware/install/autoware_hazard_status_converter/lib/autoware_hazard_status_converter/autoware_hazard_status_converter_node"
  "/autoware/install/component_state_diagnostics/lib/component_state_diagnostics/component_state_diagnostics"
  "/autoware/install/map_projection_loader/lib/map_projection_loader/autoware_map_projection_loader_node"
  "/autoware/install/tier4_dummy_object_rviz_plugin/lib/tier4_dummy_object_rviz_plugin/empty_objects_publisher"
  "ub_carla_top_lidar_relay"
  "ub_carla_control_mode_shim"
)

# The external-tick CARLA bridge process and its relays/shim, used only by
# the SUMO/passive scenario (on top of AUTOWARE_E2E_CLEANUP_PATTERNS above).
AUTOWARE_CARLA_INTERFACE_CLEANUP_PATTERNS=(
  "ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml"
  "ros2 run topic_tools relay /sensing/lidar/top/pointcloud_before_sync /sensing/lidar/concatenated/pointcloud"
  "ub_carla_imu_relay"
  "ros2 run topic_tools relay /sensing/imu/tamagawa/imu_raw /sensing/gnss/novatel/oem7/imu/data_raw"
  "ub_carla_operation_mode_shim"
)

# Union used by the SUMO/passive scenario, which launches both e2e_simulator
# and the external-tick autoware_carla_interface bridge.
AUTOWARE_SUMO_CLEANUP_PATTERNS=(
  "${AUTOWARE_E2E_CLEANUP_PATTERNS[@]}"
  "${AUTOWARE_CARLA_INTERFACE_CLEANUP_PATTERNS[@]}"
)

# $1: status message to print before cleaning up (skipped if the Autoware
#     container isn't running).
# $2: name of a bash array variable listing process-cmdline substrings to
#     match and signal (see AUTOWARE_E2E_CLEANUP_PATTERNS above).
cleanup_autoware_launch_processes() {
  local message="$1"
  local -n _cleanup_patterns="$2"

  cd "${AUTOWARE_DOCKER_DIR}"
  if [[ -z "$(docker compose ps -q "${AUTOWARE_SERVICE}" 2>/dev/null || true)" ]]; then
    return 0
  fi

  echo "${message}"
  local patterns_joined
  patterns_joined="$(printf '%s\n' "${_cleanup_patterns[@]}")"
  docker compose exec -T -e "UB_CLEANUP_PATTERNS=${patterns_joined}" "${AUTOWARE_SERVICE}" bash -lc 'python3 - <<'"'"'PY'"'"'
import os
import signal
import time

patterns = [line for line in os.environ.get("UB_CLEANUP_PATTERNS", "").split("\n") if line]

skip_pids = {os.getpid(), os.getppid()}

def matching_pids():
    matches = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid in skip_pids:
            continue
        try:
            raw = open(f"/proc/{pid}/cmdline", "rb").read()
        except OSError:
            continue
        cmdline = raw.replace(b"\0", b" ").decode(errors="replace")
        if any(pattern in cmdline for pattern in patterns):
            matches.append(pid)
    return matches

for sig, delay in ((signal.SIGINT, 2.0), (signal.SIGTERM, 1.0), (signal.SIGKILL, 0.0)):
    pids = matching_pids()
    if not pids:
        break
    print(f"Sending {sig.name} to stale Autoware launch processes: {pids}")
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
    if delay:
        time.sleep(delay)
PY'
}

# $1: name of the cleanup-patterns array to use for the pre-start stale-process sweep.
start_autoware_container() {
  local cleanup_patterns_var="$1"

  cd "${AUTOWARE_DOCKER_DIR}"

  echo "Starting Autoware Compose service: ${AUTOWARE_SERVICE}"
  export RMW_IMPLEMENTATION="${UB_AUTOWARE_RMW_IMPLEMENTATION}"
  export CYCLONEDDS_URI="${UB_AUTOWARE_CYCLONEDDS_URI}"
  docker compose up -d "${AUTOWARE_SERVICE}"

  if [[ "${UB_AUTOWARE_CLEAN_STALE_PROCESSES}" == "1" ]]; then
    cleanup_autoware_launch_processes "Cleaning stale Autoware ROS launch processes before starting." "${cleanup_patterns_var}"
  fi
}

# Builds the custom autoware_carla_interface package that the SUMO/passive
# scenario mounts into the Autoware container.
build_mounted_autoware_bridge() {
  cd "${AUTOWARE_DOCKER_DIR}"

  echo "Building mounted custom autoware_carla_interface in the Autoware container..."
  docker compose exec -T "${AUTOWARE_SERVICE}" bash -lc '
set -euo pipefail
if [[ ! -f /autoware/src/universe/autoware_universe/simulator/autoware_carla_interface/package.xml ]]; then
  echo "Missing mounted autoware_carla_interface package at /autoware/src/universe/autoware_universe/simulator/autoware_carla_interface" >&2
  echo "Recreate the Autoware container so docker-compose.yml mounts UB_AUTOWARE_CARLA_INTERFACE_PATH." >&2
  exit 1
fi
'

  local install_deps_cmd=""
  if [[ "${UB_AUTOWARE_INSTALL_PY_DEPS}" == "1" ]]; then
    install_deps_cmd='
python3 - <<'"'"'PY'"'"' || python3 -m pip install --upgrade carla==0.9.16 transforms3d==0.4.2
import carla
import transforms3d

def version_tuple(version):
    parts = []
    for part in version.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts)

if version_tuple(transforms3d.__version__) < (0, 4, 2):
    raise SystemExit(f"transforms3d {transforms3d.__version__} is older than 0.4.2")
PY
'
  fi

  docker compose exec -T "${AUTOWARE_SERVICE}" bash -lc "
set -eo pipefail
export RMW_IMPLEMENTATION=$(shell_quote "${UB_AUTOWARE_RMW_IMPLEMENTATION}")
export CYCLONEDDS_URI=$(shell_quote "${UB_AUTOWARE_CYCLONEDDS_URI}")
source /opt/ros/humble/setup.bash
${install_deps_cmd}
cd /autoware
rm -rf build/autoware_carla_interface install/autoware_carla_interface
colcon build --symlink-install --packages-select autoware_carla_interface
source /autoware/install/setup.bash
ros2 pkg prefix autoware_carla_interface
ros2 pkg prefix ub_lincoln_vehicle_launch
ros2 pkg prefix ub_lincoln_sensor_kit_launch
"
}

# Backports three upstream CenterPoint fixes missing from the pinned Autoware
# image. The old code initializes its shuffle table before creating the CUDA
# stream, processes uncleared point buffers on the first inference, and checks
# the destination index before reading by source index. The resulting reads of
# uninitialized device data are timing/architecture-sensitive: they can appear
# harmless on one GPU and abort with cudaErrorIllegalAddress on another.
#
# The source and build marker live inside the container. A successful build is
# therefore cached for the container lifetime and is repeated after the
# container is recreated. Set UB_AUTOWARE_PATCH_CENTERPOINT_CUDA=0 to opt out.
patch_and_build_autoware_centerpoint() {
  if [[ "${UB_AUTOWARE_PATCH_CENTERPOINT_CUDA}" != "1" ]]; then
    echo "Skipping Autoware CenterPoint CUDA compatibility fixes."
    return 0
  fi

  cd "${AUTOWARE_DOCKER_DIR}"

  echo "Checking Autoware CenterPoint CUDA compatibility fixes..."
  docker compose exec -T "${AUTOWARE_SERVICE}" bash -lc '
set -euo pipefail
source_path=/autoware/src/universe/autoware_universe/perception/autoware_lidar_centerpoint
marker_path=/autoware/build/autoware_lidar_centerpoint/.ub-centerpoint-cuda-fixes-v1

if [[ -f "${marker_path}" ]]; then
  echo "CenterPoint CUDA compatibility fixes are already built."
  exit 0
fi

UB_CENTERPOINT_SOURCE_PATH="${source_path}" python3 - <<'"'"'PY'"'"'
import os
from pathlib import Path

source_dir = Path(os.environ["UB_CENTERPOINT_SOURCE_PATH"])
centerpoint_path = source_dir / "lib/centerpoint_trt.cpp"
preprocess_path = source_dir / "lib/preprocess/preprocess_kernel.cu"

for path in (centerpoint_path, preprocess_path):
    if not path.is_file():
        raise SystemExit(f"Missing CenterPoint source file: {path}")
    backup = path.with_suffix(path.suffix + ".ub-original")
    if not backup.exists():
        backup.write_text(path.read_text())

centerpoint = centerpoint_path.read_text()

constructor_old = """: config_(config)
{
  vg_ptr_ = std::make_unique<VoxelGenerator>(densification_param, config_);
  post_proc_ptr_ = std::make_unique<PostProcessCUDA>(config_);

  initPtr();
  initTrt(encoder_param, head_param);

  cudaStreamCreate(&stream_);
}
"""
constructor_new = """: config_(config)
{
  cudaStreamCreate(&stream_);

  vg_ptr_ = std::make_unique<VoxelGenerator>(densification_param, config_);
  post_proc_ptr_ = std::make_unique<PostProcessCUDA>(config_);

  initPtr();
  initTrt(encoder_param, head_param);
}
"""

constructor_start = centerpoint.find(": config_(config)")
stream_create = centerpoint.find("cudaStreamCreate(&stream_);", constructor_start)
voxel_generator = centerpoint.find("vg_ptr_ =", constructor_start)
if min(constructor_start, stream_create, voxel_generator) < 0:
    raise SystemExit(f"Could not locate CenterPoint constructor markers in {centerpoint_path}")
if stream_create > voxel_generator:
    if constructor_old not in centerpoint:
        raise SystemExit(f"Unsupported CenterPoint constructor layout in {centerpoint_path}")
    centerpoint = centerpoint.replace(constructor_old, constructor_new, 1)
    print("Moved CenterPoint CUDA stream creation before asynchronous initialization.")

count_line = (
    "  const std::size_t count = "
    "vg_ptr_->generateSweepPoints(points_aux_d_.get(), stream_);\n"
)
clear_points = """  const auto points_capacity_size =
    config_.cloud_capacity_ * config_.point_feature_size_;
  CHECK_CUDA_ERROR(cudaMemsetAsync(
    points_aux_d_.get(), 0, points_capacity_size * sizeof(float), stream_));
  CHECK_CUDA_ERROR(cudaMemsetAsync(
    points_d_.get(), 0, points_capacity_size * sizeof(float), stream_));
"""
if "points_aux_d_.get(), 0, points_capacity_size" not in centerpoint:
    if count_line not in centerpoint:
        raise SystemExit(f"Could not locate CenterPoint point generation in {centerpoint_path}")
    centerpoint = centerpoint.replace(count_line, clear_points + count_line, 1)
    print("Added deterministic clearing for CenterPoint point buffers.")

centerpoint_path.write_text(centerpoint)

preprocess = preprocess_path.read_text()
wrong_index_check = "  if (dst_idx >= points_size) {"
fixed_index_check = "  if (src_idx >= points_size) {"
if fixed_index_check not in preprocess:
    if wrong_index_check not in preprocess:
        raise SystemExit(f"Could not locate CenterPoint shuffle index check in {preprocess_path}")
    preprocess = preprocess.replace(wrong_index_check, fixed_index_check, 1)
    preprocess_path.write_text(preprocess)
    print("Corrected CenterPoint shuffle source-index validation.")

updated = centerpoint_path.read_text()
if updated.find("cudaStreamCreate(&stream_);") > updated.find("vg_ptr_ ="):
    raise SystemExit("CenterPoint CUDA stream fix did not apply")
if "points_aux_d_.get(), 0, points_capacity_size" not in updated:
    raise SystemExit("CenterPoint buffer clearing fix did not apply")
if fixed_index_check not in preprocess_path.read_text():
    raise SystemExit("CenterPoint shuffle index fix did not apply")
PY

echo "Building patched autoware_lidar_centerpoint (first run for this container)..."
cd /autoware
set +u
source /opt/ros/humble/setup.bash
source /autoware/install/setup.bash
set -u
colcon build --symlink-install --packages-select autoware_lidar_centerpoint \
  --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF
touch "${marker_path}"
echo "Built and cached Autoware CenterPoint CUDA compatibility fixes."
'
}
