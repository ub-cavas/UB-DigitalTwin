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
