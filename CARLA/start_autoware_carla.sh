#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

has_files() {
  local path="$1"
  [[ -d "${path}" ]] || return 1
  find "${path}" -mindepth 1 -maxdepth 2 -print -quit 2>/dev/null | grep -q .
}

BUILD_FOLDER="${BUILD_FOLDER:-v1.0.0}"
CARLA_MAP="${CARLA_MAP:-UBAutonomousProvingGrounds}"
CARLA_MAP_PATH="${CARLA_MAP_PATH:-/Game/Carla/Maps/${CARLA_MAP}}"
CARLA_ARGS="${CARLA_ARGS:--prefernvidia -quality-level=Low -nosound}"

DEFAULT_AUTOWARE_HOST_MAP_DIR="${REPO_DIR}/Autoware/host_data/maps/ub_autonomous_proving_grounds"
DEFAULT_AUTOWARE_MAP_PATH="/host_data/maps/ub_autonomous_proving_grounds"
LEGACY_AUTOWARE_HOST_MAP_DIR="${REPO_DIR}/Autoware/host_data/ub_autonomous_proving_grounds"
LEGACY_AUTOWARE_MAP_PATH="/host_data/ub_autonomous_proving_grounds"

if [[ -z "${AUTOWARE_HOST_MAP_DIR:-}" && -z "${AUTOWARE_MAP_PATH:-}" ]] && has_files "${LEGACY_AUTOWARE_HOST_MAP_DIR}" && ! has_files "${DEFAULT_AUTOWARE_HOST_MAP_DIR}"; then
  AUTOWARE_HOST_MAP_DIR="${LEGACY_AUTOWARE_HOST_MAP_DIR}"
  AUTOWARE_MAP_PATH="${LEGACY_AUTOWARE_MAP_PATH}"
fi

AUTOWARE_DOCKER_DIR="${AUTOWARE_DOCKER_DIR:-${REPO_DIR}/Autoware/ub-lincoln-docker/docker}"
AUTOWARE_HOST_MAP_DIR="${AUTOWARE_HOST_MAP_DIR:-${DEFAULT_AUTOWARE_HOST_MAP_DIR}}"
AUTOWARE_MAP_PATH="${AUTOWARE_MAP_PATH:-${DEFAULT_AUTOWARE_MAP_PATH}}"
AUTOWARE_SERVICE="${AUTOWARE_SERVICE:-autoware}"
AUTOWARE_CARLA_HOST="${AUTOWARE_CARLA_HOST:-127.0.0.1}"
AUTOWARE_VEHICLE_MODEL="${AUTOWARE_VEHICLE_MODEL:-sample_vehicle}"
AUTOWARE_SENSOR_MODEL="${AUTOWARE_SENSOR_MODEL:-awsim_sensor_kit}"
AUTOWARE_RVIZ="${AUTOWARE_RVIZ:-}"
AUTOWARE_PLANNING_MODULE_PRESET="${AUTOWARE_PLANNING_MODULE_PRESET:-}"
UB_AUTOWARE_INSTALL_PY_DEPS="${UB_AUTOWARE_INSTALL_PY_DEPS:-1}"
UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY="${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY:-0}"
UB_AUTOWARE_PATCH_CARLA_BRIDGE="${UB_AUTOWARE_PATCH_CARLA_BRIDGE:-0}"
UB_AUTOWARE_EGO_ONLY_PERCEPTION="${UB_AUTOWARE_EGO_ONLY_PERCEPTION:-0}"
UB_AUTOWARE_CARLA_PLANNING_PRESET="${UB_AUTOWARE_CARLA_PLANNING_PRESET:-0}"
UB_AUTOWARE_CARLA_SENSOR_TIMEOUT_RECOVERY="${UB_AUTOWARE_CARLA_SENSOR_TIMEOUT_RECOVERY:-0}"
UB_AUTOWARE_CONTROL_MODE_SHIM="${UB_AUTOWARE_CONTROL_MODE_SHIM:-0}"
UB_AUTOWARE_RESTORE_RUNTIME_PATCHES="${UB_AUTOWARE_RESTORE_RUNTIME_PATCHES:-1}"
UB_KEEP_CARLA="${UB_KEEP_CARLA:-0}"
UB_KEEP_AUTOWARE_ROS="${UB_KEEP_AUTOWARE_ROS:-0}"
UB_AUTOWARE_CLEAN_STALE_PROCESSES="${UB_AUTOWARE_CLEAN_STALE_PROCESSES:-1}"
UB_AUTOWARE_HOST_CONFIG_DDS="${UB_AUTOWARE_HOST_CONFIG_DDS:-1}"
UB_AUTOWARE_RMW_IMPLEMENTATION="${UB_AUTOWARE_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
UB_AUTOWARE_CYCLONEDDS_URI="${UB_AUTOWARE_CYCLONEDDS_URI:-file:///resources/cyclonedds.xml}"
UB_AUTOWARE_CAMERA_FOLLOW="${UB_AUTOWARE_CAMERA_FOLLOW:-1}"
UB_AUTOWARE_CAMERA_FOLLOW_HOST="${UB_AUTOWARE_CAMERA_FOLLOW_HOST:-127.0.0.1}"
UB_AUTOWARE_CAMERA_FOLLOW_PORT="${UB_AUTOWARE_CAMERA_FOLLOW_PORT:-2000}"
UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES="${UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES:-ego_vehicle}"
UB_AUTOWARE_CAMERA_FOLLOW_DISTANCE_M="${UB_AUTOWARE_CAMERA_FOLLOW_DISTANCE_M:-8.0}"
UB_AUTOWARE_CAMERA_FOLLOW_HEIGHT_M="${UB_AUTOWARE_CAMERA_FOLLOW_HEIGHT_M:-3.0}"
UB_AUTOWARE_CAMERA_FOLLOW_PITCH_DEG="${UB_AUTOWARE_CAMERA_FOLLOW_PITCH_DEG:--12.0}"
UB_AUTOWARE_CAMERA_FOLLOW_UPDATE_HZ="${UB_AUTOWARE_CAMERA_FOLLOW_UPDATE_HZ:-30.0}"
UB_CARLA_EXTRA_SERVICES="${UB_CARLA_EXTRA_SERVICES:-}"

DDS_REQUIRED_RMEM_MAX=10485760
DDS_REQUIRED_IPFRAG_HIGH_THRESH=134217728
DDS_REQUIRED_IPFRAG_TIME=3

DRY_RUN=0
CARLA_STARTED=0
AUTOWARE_LAUNCH_STARTED=0
CAMERA_FOLLOW_STARTED=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run] [--help]

Start rendered CARLA on the UB autonomous proving grounds map, then launch
Autoware's CARLA e2e simulator in the foreground.

Defaults:
  BUILD_FOLDER=${BUILD_FOLDER}
  CARLA_MAP=${CARLA_MAP}
  CARLA_ARGS=${CARLA_ARGS}
  AUTOWARE_MAP_PATH=${AUTOWARE_MAP_PATH}
  AUTOWARE_SERVICE=${AUTOWARE_SERVICE}
  AUTOWARE_CARLA_HOST=${AUTOWARE_CARLA_HOST}
  AUTOWARE_VEHICLE_MODEL=${AUTOWARE_VEHICLE_MODEL}
  AUTOWARE_SENSOR_MODEL=${AUTOWARE_SENSOR_MODEL}
  AUTOWARE_RVIZ=${AUTOWARE_RVIZ:-<manual launch default>}
  AUTOWARE_PLANNING_MODULE_PRESET=${AUTOWARE_PLANNING_MODULE_PRESET:-<manual launch default>}
  UB_AUTOWARE_INSTALL_PY_DEPS=${UB_AUTOWARE_INSTALL_PY_DEPS}
  UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY=${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY}
  UB_AUTOWARE_PATCH_CARLA_BRIDGE=${UB_AUTOWARE_PATCH_CARLA_BRIDGE}
  UB_AUTOWARE_EGO_ONLY_PERCEPTION=${UB_AUTOWARE_EGO_ONLY_PERCEPTION}
  UB_AUTOWARE_CARLA_PLANNING_PRESET=${UB_AUTOWARE_CARLA_PLANNING_PRESET}
  UB_AUTOWARE_CARLA_SENSOR_TIMEOUT_RECOVERY=${UB_AUTOWARE_CARLA_SENSOR_TIMEOUT_RECOVERY}
  UB_AUTOWARE_CONTROL_MODE_SHIM=${UB_AUTOWARE_CONTROL_MODE_SHIM}
  UB_AUTOWARE_RESTORE_RUNTIME_PATCHES=${UB_AUTOWARE_RESTORE_RUNTIME_PATCHES}
  UB_AUTOWARE_CLEAN_STALE_PROCESSES=${UB_AUTOWARE_CLEAN_STALE_PROCESSES}
  UB_AUTOWARE_HOST_CONFIG_DDS=${UB_AUTOWARE_HOST_CONFIG_DDS}
  UB_AUTOWARE_RMW_IMPLEMENTATION=${UB_AUTOWARE_RMW_IMPLEMENTATION}
  UB_AUTOWARE_CYCLONEDDS_URI=${UB_AUTOWARE_CYCLONEDDS_URI}
  UB_AUTOWARE_CAMERA_FOLLOW=${UB_AUTOWARE_CAMERA_FOLLOW}
  UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES=${UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES}
  UB_AUTOWARE_CAMERA_FOLLOW_UPDATE_HZ=${UB_AUTOWARE_CAMERA_FOLLOW_UPDATE_HZ}
  UB_CARLA_EXTRA_SERVICES=${UB_CARLA_EXTRA_SERVICES:-<none>}
  UB_KEEP_AUTOWARE_ROS=${UB_KEEP_AUTOWARE_ROS}

Useful overrides:
  BUILD_FOLDER=v1.0.0 $(basename "$0")
  CARLA_ARGS="-prefernvidia -quality-level=Epic" $(basename "$0")
  AUTOWARE_SERVICE=<compose-service> $(basename "$0")
  AUTOWARE_CARLA_HOST=<host-ip> $(basename "$0")
  AUTOWARE_RVIZ=false $(basename "$0")
  AUTOWARE_PLANNING_MODULE_PRESET=ub_carla $(basename "$0")
  UB_AUTOWARE_INSTALL_PY_DEPS=0 $(basename "$0")
  UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY=1 $(basename "$0")
  UB_AUTOWARE_PATCH_CARLA_BRIDGE=1 $(basename "$0")
  UB_AUTOWARE_EGO_ONLY_PERCEPTION=1 $(basename "$0")
  UB_AUTOWARE_CARLA_PLANNING_PRESET=1 $(basename "$0")
  UB_AUTOWARE_CARLA_SENSOR_TIMEOUT_RECOVERY=1 $(basename "$0")
  UB_AUTOWARE_CONTROL_MODE_SHIM=1 $(basename "$0")
  UB_AUTOWARE_RESTORE_RUNTIME_PATCHES=0 $(basename "$0")
  UB_AUTOWARE_CLEAN_STALE_PROCESSES=0 $(basename "$0")
  UB_AUTOWARE_HOST_CONFIG_DDS=0 $(basename "$0")
  UB_AUTOWARE_RMW_IMPLEMENTATION=rmw_cyclonedds_cpp $(basename "$0")
  UB_AUTOWARE_CYCLONEDDS_URI=file:///resources/cyclonedds.xml $(basename "$0")
  UB_AUTOWARE_CAMERA_FOLLOW=0 $(basename "$0")
  UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES=ego_vehicle $(basename "$0")
  UB_CARLA_EXTRA_SERVICES="traffic-publisher udp-bridge" $(basename "$0")
  UB_KEEP_CARLA=1 $(basename "$0")
  UB_KEEP_AUTOWARE_ROS=1 $(basename "$0")

Options:
  --dry-run  Validate prerequisites and print the commands without starting CARLA.
  --help     Show this help text.
EOF
}

setup_hint() {
  cat <<EOF

Setup hints:
  CARLA build:
    bash scripts/install_ub_carla.sh ${BUILD_FOLDER}

  Autoware submodule, image, and UB HD map:
    cd Autoware
    ./setup_autoware.sh

  Autoware DDS host settings:
    cd ${AUTOWARE_DOCKER_DIR}
    ../scripts/host_config_dds.bash

  If Autoware uses a different Docker Compose service name:
    AUTOWARE_SERVICE=<service-name> CARLA/start_autoware_carla.sh
EOF
}

collect_dds_host_config_failures() {
  local failures_ref="$1"
  local -n dds_failures_ref="${failures_ref}"
  local value

  if [[ "${UB_AUTOWARE_HOST_CONFIG_DDS}" != "1" || "${UB_AUTOWARE_RMW_IMPLEMENTATION}" != "rmw_cyclonedds_cpp" ]]; then
    return 0
  fi

  value="$(sysctl -n net.core.rmem_max 2>/dev/null || true)"
  if [[ ! "${value}" =~ ^[0-9]+$ || "${value}" -lt "${DDS_REQUIRED_RMEM_MAX}" ]]; then
    dds_failures_ref+=("net.core.rmem_max is ${value:-unreadable}; CycloneDDS needs at least ${DDS_REQUIRED_RMEM_MAX}.")
  fi

  value="$(sysctl -n net.ipv4.ipfrag_time 2>/dev/null || true)"
  if [[ ! "${value}" =~ ^[0-9]+$ || "${value}" -gt "${DDS_REQUIRED_IPFRAG_TIME}" ]]; then
    dds_failures_ref+=("net.ipv4.ipfrag_time is ${value:-unreadable}; Autoware DDS setup expects ${DDS_REQUIRED_IPFRAG_TIME}.")
  fi

  value="$(sysctl -n net.ipv4.ipfrag_high_thresh 2>/dev/null || true)"
  if [[ ! "${value}" =~ ^[0-9]+$ || "${value}" -lt "${DDS_REQUIRED_IPFRAG_HIGH_THRESH}" ]]; then
    dds_failures_ref+=("net.ipv4.ipfrag_high_thresh is ${value:-unreadable}; Autoware DDS setup expects at least ${DDS_REQUIRED_IPFRAG_HIGH_THRESH}.")
  fi

  if ! ip link show lo 2>/dev/null | grep -qw MULTICAST; then
    dds_failures_ref+=("loopback interface lo does not have multicast enabled.")
  fi
}

print_dds_host_config_failures() {
  local failures_ref="$1"
  local -n dds_failures_ref="${failures_ref}"
  local failure

  echo "Autoware host DDS settings are not applied:"
  for failure in "${dds_failures_ref[@]}"; do
    echo "  - ${failure}"
  done
}

configure_autoware_host_dds() {
  local dds_failures=()

  if [[ "${UB_AUTOWARE_HOST_CONFIG_DDS}" != "1" || "${UB_AUTOWARE_RMW_IMPLEMENTATION}" != "rmw_cyclonedds_cpp" ]]; then
    return 0
  fi

  if [[ ! -x "${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash" ]]; then
    echo "Warning: missing executable Autoware host DDS setup script: ${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash" >&2
    return 0
  fi

  collect_dds_host_config_failures dds_failures
  if [[ ${#dds_failures[@]} -eq 0 ]]; then
    return 0
  fi

  print_dds_host_config_failures dds_failures >&2

  if ! command -v sudo >/dev/null 2>&1; then
    echo "Error: sudo is required to apply Autoware host DDS settings." >&2
    setup_hint >&2
    return 1
  fi

  if [[ -t 0 ]]; then
    echo "Applying Autoware host DDS settings. sudo may prompt for your password."
    "${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash"
  elif sudo -n true 2>/dev/null; then
    echo "Applying Autoware host DDS settings..."
    "${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash"
  else
    echo "Error: sudo needs a password, but this launcher is not attached to an interactive terminal." >&2
    echo "Run this once in a terminal before launching:" >&2
    echo "  cd ${AUTOWARE_DOCKER_DIR} && ../scripts/host_config_dds.bash" >&2
    return 1
  fi

  dds_failures=()
  collect_dds_host_config_failures dds_failures
  if [[ ${#dds_failures[@]} -gt 0 ]]; then
    echo "Error: Autoware host DDS settings are still invalid after setup." >&2
    print_dds_host_config_failures dds_failures >&2
    return 1
  fi
}

collect_preflight_failures() {
  local failures_ref="$1"
  local -n preflight_failures="${failures_ref}"

  if ! command -v docker >/dev/null 2>&1; then
    preflight_failures+=("Docker is not installed or not on PATH.")
  elif ! docker compose version >/dev/null 2>&1; then
    preflight_failures+=("Docker Compose v2 is unavailable. Install the Docker Compose plugin so 'docker compose' works.")
  elif ! docker info >/dev/null 2>&1; then
    preflight_failures+=("Docker daemon is unreachable or this user cannot access /var/run/docker.sock.")
  fi

  if [[ ! -x "${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/CarlaUE4.sh" ]]; then
    preflight_failures+=("Missing executable CARLA build: ${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/CarlaUE4.sh")
  fi

  if [[ "${UB_AUTOWARE_CAMERA_FOLLOW}" == "1" ]]; then
    if ! find "${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/PythonAPI/carla/dist" -maxdepth 1 -type f -name 'carla-*-cp310-*.whl' -print -quit 2>/dev/null | grep -q .; then
      preflight_failures+=("Missing CARLA Python wheel under ${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/PythonAPI/carla/dist for camera follow.")
    fi
  fi

  if [[ ! -d "${AUTOWARE_DOCKER_DIR}" ]]; then
    preflight_failures+=("Missing Autoware Docker directory: ${AUTOWARE_DOCKER_DIR}")
  elif [[ ! -f "${AUTOWARE_DOCKER_DIR}/compose.yml" && ! -f "${AUTOWARE_DOCKER_DIR}/docker-compose.yml" && ! -f "${AUTOWARE_DOCKER_DIR}/docker-compose.yaml" ]]; then
    preflight_failures+=("Autoware Docker directory does not contain a Compose file: ${AUTOWARE_DOCKER_DIR}")
  fi

  if ! has_files "${AUTOWARE_HOST_MAP_DIR}"; then
    preflight_failures+=("Missing or empty Autoware UB HD map directory: ${AUTOWARE_HOST_MAP_DIR}")
  fi

  if [[ -z "${DISPLAY:-}" ]]; then
    preflight_failures+=("DISPLAY is not set. Run from a graphical Linux session or configure X11 forwarding.")
  fi

  if [[ ! -d /tmp/.X11-unix ]]; then
    preflight_failures+=("Missing /tmp/.X11-unix. Rendered CARLA needs the host X11 socket mounted into Docker.")
  fi
}

run_preflight() {
  local failures=()
  collect_preflight_failures failures

  if [[ ${#failures[@]} -gt 0 ]]; then
    echo "Preflight failed:"
    local failure
    for failure in "${failures[@]}"; do
      echo "  - ${failure}"
    done
    setup_hint
    return 1
  fi
}

print_dry_run() {
  cat <<EOF
Dry run passed. The launcher would run:

  cd ${AUTOWARE_DOCKER_DIR}
  ../scripts/host_config_dds.bash  # runs before containers start when host DDS settings are not already applied

  cd ${SCRIPT_DIR}
  BUILD_FOLDER=${BUILD_FOLDER} \\
  CARLA_MAP_PATH=${CARLA_MAP_PATH} \\
  CARLA_ARGS=${CARLA_ARGS} \\
  UB_CARLA_EXTRA_SERVICES=${UB_CARLA_EXTRA_SERVICES:-<none>} \\
  docker compose up --build -d carla redis map-loader ${UB_CARLA_EXTRA_SERVICES}

  cd ${AUTOWARE_DOCKER_DIR}
  docker compose up -d ${AUTOWARE_SERVICE}
  docker compose exec ${AUTOWARE_SERVICE} bash -lc 'ros2 launch autoware_launch e2e_simulator.launch.xml ...'

Autoware launch arguments:
  map_path:=${AUTOWARE_MAP_PATH}
  vehicle_model:=${AUTOWARE_VEHICLE_MODEL}
  sensor_model:=${AUTOWARE_SENSOR_MODEL}
  simulator_type:=carla
  host:=${AUTOWARE_CARLA_HOST}
  carla_map:=${CARLA_MAP}
  external_tick:=False
  rviz:=${AUTOWARE_RVIZ:-<omitted; manual launch default>}
  planning_module_preset:=${AUTOWARE_PLANNING_MODULE_PRESET:-<omitted; manual launch default>}
  install_python_deps:=${UB_AUTOWARE_INSTALL_PY_DEPS}
  carla_top_lidar_only:=${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY}
  patch_carla_bridge:=${UB_AUTOWARE_PATCH_CARLA_BRIDGE}
  ego_only_perception:=${UB_AUTOWARE_EGO_ONLY_PERCEPTION}
  carla_planning_preset:=${UB_AUTOWARE_CARLA_PLANNING_PRESET}
  carla_sensor_timeout_recovery:=${UB_AUTOWARE_CARLA_SENSOR_TIMEOUT_RECOVERY}
  control_mode_shim:=${UB_AUTOWARE_CONTROL_MODE_SHIM}
  restore_runtime_patches:=${UB_AUTOWARE_RESTORE_RUNTIME_PATCHES}
  clean_stale_processes:=${UB_AUTOWARE_CLEAN_STALE_PROCESSES}
  host_config_dds:=${UB_AUTOWARE_HOST_CONFIG_DDS}
  rmw_implementation:=${UB_AUTOWARE_RMW_IMPLEMENTATION}
  cyclonedds_uri:=${UB_AUTOWARE_CYCLONEDDS_URI}
  camera_follow:=${UB_AUTOWARE_CAMERA_FOLLOW}
  camera_follow_role_names:=${UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES}
EOF
}

cleanup_autoware_launch_processes() {
  local message="${1:-Cleaning Autoware ROS launch processes.}"

  cd "${AUTOWARE_DOCKER_DIR}"
  if [[ -z "$(docker compose ps -q "${AUTOWARE_SERVICE}" 2>/dev/null || true)" ]]; then
    return 0
  fi

  echo "${message}"
  docker compose exec -T "${AUTOWARE_SERVICE}" bash -lc 'python3 - <<'"'"'PY'"'"'
import os
import signal
import time

patterns = [
    "ros2 launch autoware_launch e2e_simulator.launch.xml",
    "/autoware/install/autoware_carla_interface/lib/autoware_carla_interface/autoware_carla_interface",
    "/opt/ros/humble/lib/rclcpp_components/component_container",
    "/opt/ros/humble/lib/rclcpp_components/component_container_mt",
    "/opt/ros/humble/lib/rviz2/rviz2",
    "/autoware/install/autoware_default_adapi/lib/autoware_default_adapi/web_server.py",
    "/autoware/install/autoware_adapi_adaptors/lib/autoware_adapi_adaptors/initial_pose_adaptor_node",
    "/autoware/install/autoware_adapi_adaptors/lib/autoware_adapi_adaptors/routing_adaptor_node",
    "/autoware/install/autoware_automatic_pose_initializer/lib/autoware_automatic_pose_initializer/autoware_automatic_pose_initializer_node",
    "/autoware/install/autoware_stop_filter/lib/autoware_stop_filter/autoware_stop_filter_node",
    "/autoware/install/autoware_pose_initializer/lib/autoware_pose_initializer/autoware_pose_initializer_node",
    "/autoware/install/autoware_topic_state_monitor/lib/autoware_topic_state_monitor/autoware_topic_state_monitor_node",
    "/autoware/install/autoware_processing_time_checker/lib/autoware_processing_time_checker/processing_time_checker_node",
    "/autoware/install/autoware_service_log_checker/lib/autoware_service_log_checker/service_log_checker_node",
    "/autoware/install/autoware_map_hash_generator/lib/autoware_map_hash_generator/map_hash_generator",
    "/autoware/install/autoware_goal_pose_visualizer/lib/autoware_goal_pose_visualizer/goal_pose_visualizer",
    "/autoware/install/autoware_external_velocity_limit_selector/lib/autoware_external_velocity_limit_selector/external_velocity_limit_selector",
    "/autoware/install/autoware_planning_validator/lib/autoware_planning_validator/planning_validator_node",
    "/autoware/install/autoware_control_validator/lib/autoware_control_validator/control_validator_node",
    "/autoware/install/autoware_remaining_distance_time_calculator/lib/autoware_remaining_distance_time_calculator/autoware_remaining_distance_time_calculator_node",
    "/autoware/install/autoware_vehicle_cmd_gate/lib/autoware_vehicle_cmd_gate/vehicle_cmd_gate",
    "/autoware/install/autoware_raw_vehicle_cmd_converter/lib/autoware_raw_vehicle_cmd_converter/autoware_raw_vehicle_cmd_converter_node",
    "/autoware/install/autoware_gyro_odometer/lib/autoware_gyro_odometer/autoware_gyro_odometer_node",
    "/autoware/install/autoware_ndt_scan_matcher/lib/autoware_ndt_scan_matcher/autoware_ndt_scan_matcher_node",
    "/autoware/install/autoware_ekf_localizer/lib/autoware_ekf_localizer/autoware_ekf_localizer_node",
    "/autoware/install/autoware_twist2accel/lib/autoware_twist2accel/autoware_twist2accel_node",
    "/autoware/install/autoware_pose_instability_detector/lib/autoware_pose_instability_detector/autoware_pose_instability_detector_node",
    "/autoware/install/autoware_localization_error_monitor/lib/autoware_localization_error_monitor/autoware_localization_error_monitor_node",
    "/autoware/install/autoware_vehicle_velocity_converter/lib/autoware_vehicle_velocity_converter/autoware_vehicle_velocity_converter_node",
    "/autoware/install/autoware_imu_corrector/lib/autoware_imu_corrector/imu_corrector_node",
    "/autoware/install/autoware_gyro_bias_estimator/lib/autoware_gyro_bias_estimator/gyro_bias_estimator_node",
    "/autoware/install/autoware_scenario_selector/lib/autoware_scenario_selector/autoware_scenario_selector_node",
    "/autoware/install/autoware_mrm_handler/lib/autoware_mrm_handler/autoware_mrm_handler_node",
    "/autoware/install/autoware_hazard_status_converter/lib/autoware_hazard_status_converter/autoware_hazard_status_converter_node",
    "/autoware/install/component_state_diagnostics/lib/component_state_diagnostics/component_state_diagnostics",
    "/autoware/install/map_projection_loader/lib/map_projection_loader/autoware_map_projection_loader_node",
    "/autoware/install/tier4_dummy_object_rviz_plugin/lib/tier4_dummy_object_rviz_plugin/empty_objects_publisher",
    "ub_carla_top_lidar_relay",
    "ub_carla_control_mode_shim",
]

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

cleanup() {
  local exit_code="$?"

  if [[ "${CAMERA_FOLLOW_STARTED}" -eq 1 ]]; then
    echo "Stopping CARLA spectator camera follow."
    cd "${SCRIPT_DIR}"
    docker compose stop camera-follow >/dev/null 2>&1 || true
    docker compose rm -f camera-follow >/dev/null 2>&1 || true
    CAMERA_FOLLOW_STARTED=0
  fi

  if [[ "${AUTOWARE_LAUNCH_STARTED}" -eq 1 && "${UB_KEEP_AUTOWARE_ROS}" != "1" ]]; then
    cleanup_autoware_launch_processes "Stopping Autoware ROS launch processes. Set UB_KEEP_AUTOWARE_ROS=1 to leave them running." || true
  fi

  if [[ "${CARLA_STARTED}" -eq 1 && "${UB_KEEP_CARLA}" != "1" ]]; then
    echo "Stopping CARLA Compose stack. Set UB_KEEP_CARLA=1 to leave it running."
    cd "${SCRIPT_DIR}"
    docker compose down >/dev/null 2>&1 || true
  fi

  exit "${exit_code}"
}

wait_for_map_loader() {
  local map_loader_id=""
  local status=""

  for _ in {1..30}; do
    map_loader_id="$(docker compose ps -a -q map-loader 2>/dev/null || true)"
    if [[ -n "${map_loader_id}" ]]; then
      break
    fi
    sleep 1
  done

  if [[ -z "${map_loader_id}" ]]; then
    echo "Error: map-loader container was not created." >&2
    docker compose ps >&2 || true
    return 1
  fi

  echo "Waiting for CARLA map loader to finish..."
  status="$(docker wait "${map_loader_id}")"

  if [[ "${status}" != "0" ]]; then
    echo "Error: map-loader exited with status ${status}." >&2
    docker compose logs map-loader >&2 || true
    return 1
  fi

  echo "CARLA map loaded: ${CARLA_MAP}"
}

assert_carla_running() {
  local carla_id=""
  local running=""
  local status=""
  local exit_code=""

  carla_id="$(docker compose ps -q carla 2>/dev/null || true)"
  if [[ -z "${carla_id}" ]]; then
    echo "Error: CARLA container was not created." >&2
    docker compose ps >&2 || true
    return 1
  fi

  running="$(docker inspect -f '{{.State.Running}}' "${carla_id}")"
  if [[ "${running}" == "true" ]]; then
    return 0
  fi

  status="$(docker inspect -f '{{.State.Status}}' "${carla_id}")"
  exit_code="$(docker inspect -f '{{.State.ExitCode}}' "${carla_id}")"
  echo "Error: CARLA container is not running after map load: status=${status}, exit_code=${exit_code}" >&2
  docker compose logs --tail=120 carla >&2 || true
  return 1
}

wait_for_carla_stable() {
  echo "Checking CARLA stays alive after map load..."
  for _ in {1..8}; do
    sleep 1
    assert_carla_running
  done
}

start_carla() {
  local carla_services=(carla redis map-loader)
  local extra_services=()

  cd "${SCRIPT_DIR}"

  export BUILD_FOLDER
  export CARLA_ARGS
  export CARLA_MAP_PATH
  export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
  if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
    export XAUTHORITY="${HOME}/.Xauthority"
  fi

  if command -v xhost >/dev/null 2>&1; then
    xhost +local:root >/dev/null || echo "Warning: xhost did not grant local root X11 access. CARLA may fail to render." >&2
  fi

  echo "Starting rendered CARLA Compose stack..."
  CARLA_STARTED=1
  if [[ -n "${UB_CARLA_EXTRA_SERVICES}" ]]; then
    read -r -a extra_services <<< "${UB_CARLA_EXTRA_SERVICES}"
    carla_services+=("${extra_services[@]}")
  fi
  docker compose up --build -d "${carla_services[@]}"
  wait_for_map_loader
  wait_for_carla_stable
}

start_camera_follow() {
  if [[ "${UB_AUTOWARE_CAMERA_FOLLOW}" != "1" ]]; then
    return 0
  fi

  cd "${SCRIPT_DIR}"
  export BUILD_FOLDER
  export UB_AUTOWARE_CAMERA_FOLLOW_HOST
  export UB_AUTOWARE_CAMERA_FOLLOW_PORT
  export UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES
  export UB_AUTOWARE_CAMERA_FOLLOW_DISTANCE_M
  export UB_AUTOWARE_CAMERA_FOLLOW_HEIGHT_M
  export UB_AUTOWARE_CAMERA_FOLLOW_PITCH_DEG
  export UB_AUTOWARE_CAMERA_FOLLOW_UPDATE_HZ
  echo "Starting CARLA spectator camera follow for role_name(s): ${UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES}"
  docker compose up --build -d camera-follow
  CAMERA_FOLLOW_STARTED=1

  sleep 1
  if [[ -z "$(docker compose ps -q camera-follow 2>/dev/null || true)" ]]; then
    echo "Warning: CARLA spectator camera follow container was not created." >&2
    docker compose logs --tail=80 camera-follow >&2 || true
    CAMERA_FOLLOW_STARTED=0
  elif [[ "$(docker compose ps --status running -q camera-follow 2>/dev/null || true)" == "" ]]; then
    echo "Warning: CARLA spectator camera follow container exited during startup." >&2
    docker compose logs --tail=80 camera-follow >&2 || true
    CAMERA_FOLLOW_STARTED=0
  fi
}

shell_quote() {
  printf "%q" "$1"
}

launch_autoware() {
  local launch_cmd
  local exec_args=(exec)
  local optional_launch_args=""

  cd "${AUTOWARE_DOCKER_DIR}"

  echo "Starting Autoware Compose service: ${AUTOWARE_SERVICE}"
  export RMW_IMPLEMENTATION="${UB_AUTOWARE_RMW_IMPLEMENTATION}"
  export CYCLONEDDS_URI="${UB_AUTOWARE_CYCLONEDDS_URI}"
  docker compose up -d "${AUTOWARE_SERVICE}"

  if [[ "${UB_AUTOWARE_CLEAN_STALE_PROCESSES}" == "1" ]]; then
    cleanup_autoware_launch_processes "Cleaning stale Autoware ROS launch processes before starting."
  fi

  if [[ "${UB_AUTOWARE_CARLA_SENSOR_TIMEOUT_RECOVERY}" == "1" ]]; then
    docker compose exec -T "${AUTOWARE_SERVICE}" bash -lc 'python3 - <<'"'"'PY'"'"'
from pathlib import Path

path = Path("/autoware/install/autoware_carla_interface/share/autoware_carla_interface/autoware_carla_interface.launch.xml")
if not path.exists():
    print(f"Warning: CARLA external-tick patch skipped; missing {path}")
else:
    backup = path.with_suffix(path.suffix + ".ub-original")
    if not backup.exists():
        backup.write_text(path.read_text())
    text = backup.read_text()
    old = "<arg name=\"external_tick\" default=\"True\"/>"
    new = "<arg name=\"external_tick\" default=\"False\"/>"
    if new in text:
        pass
    elif old in text:
        path.write_text(text.replace(old, new, 1))
        print(f"Disabled passive CARLA external tick for standalone launch: {path}")
    else:
        print(f"Warning: external_tick default pattern not found in {path}")
PY'
  fi

  if [[ ! -t 0 ]]; then
    exec_args+=(-T)
  fi

  if [[ -n "${AUTOWARE_RVIZ}" ]]; then
    optional_launch_args+=" \\
  rviz:=$(shell_quote "${AUTOWARE_RVIZ}")"
  fi
  if [[ -n "${AUTOWARE_PLANNING_MODULE_PRESET}" ]]; then
    optional_launch_args+=" \\
  planning_module_preset:=$(shell_quote "${AUTOWARE_PLANNING_MODULE_PRESET}")"
  fi

launch_cmd="
set -eo pipefail
export RMW_IMPLEMENTATION=$(shell_quote "${UB_AUTOWARE_RMW_IMPLEMENTATION}")
export CYCLONEDDS_URI=$(shell_quote "${UB_AUTOWARE_CYCLONEDDS_URI}")
if [[ \"\${RMW_IMPLEMENTATION}\" != \"rmw_cyclonedds_cpp\" ]]; then
  echo \"Error: expected CycloneDDS RMW, got RMW_IMPLEMENTATION=\${RMW_IMPLEMENTATION}\" >&2
  exit 1
fi
if [[ \"\${CYCLONEDDS_URI}\" == file://* && ! -f \"\${CYCLONEDDS_URI#file://}\" ]]; then
  echo \"Error: CYCLONEDDS_URI points to a missing file: \${CYCLONEDDS_URI}\" >&2
  exit 1
fi
if [[ -f /opt/ros/humble/setup.bash ]]; then
  source /opt/ros/humble/setup.bash
fi
if [[ -f /autoware/install/setup.bash ]]; then
  source /autoware/install/setup.bash
fi
UB_BACKGROUND_PIDS=\"\"
if [[ $(shell_quote "${UB_AUTOWARE_RESTORE_RUNTIME_PATCHES}") == 1 ]]; then
  python3 - <<'PY'
from pathlib import Path

restore_paths = [
    Path('/autoware/install/awsim_sensor_kit_launch/share/awsim_sensor_kit_launch/launch/lidar.launch.xml'),
    Path('/autoware/build/autoware_carla_interface/src/autoware_carla_interface/carla_ros.py'),
    Path('/autoware/build/autoware_carla_interface/src/autoware_carla_interface/carla_autoware.py'),
    Path('/autoware/install/autoware_launch/share/autoware_launch/launch/autoware.launch.xml'),
]

for path in restore_paths:
    backup = path.with_suffix(path.suffix + '.ub-original')
    if backup.exists():
        path.write_text(backup.read_text())
        print(f'Restored Autoware runtime file from UB backup: {path}')
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_INSTALL_PY_DEPS}") == 1 ]]; then
  python3 - <<'PY' || python3 -m pip install --upgrade carla==0.9.16 transforms3d==0.4.2
import carla
import transforms3d

def version_tuple(version):
    parts = []
    for part in version.split('.'):
        digits = ''.join(ch for ch in part if ch.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts)

if version_tuple(transforms3d.__version__) < (0, 4, 2):
    raise SystemExit(f'transforms3d {transforms3d.__version__} is older than 0.4.2')
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_CARLA_SENSOR_TIMEOUT_RECOVERY}") == 1 ]]; then
  python3 - <<'PY'
from pathlib import Path

path = Path('/autoware/build/autoware_carla_interface/src/autoware_carla_interface/carla_autoware.py')
if not path.exists():
    print(f'Warning: CARLA sensor timeout recovery patch skipped; missing {path}')
else:
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())
    text = backup.read_text()
    changed = False

    if 'import logging\n' not in text:
        old = 'import random\n'
        new = 'import logging\nimport random\n'
        if old in text:
            text = text.replace(old, new, 1)
            changed = True
        else:
            print(f'Warning: logging import patch pattern not found in {path}')

    old = (
        '            try:\n'
        '                ego_action = self.sensor()\n'
        '            except SensorReceivedNoData as e:\n'
        '                raise RuntimeError(e)\n'
        '            self.ego_actor.apply_control(ego_action)\n'
    )
    new = (
        '            try:\n'
        '                ego_action = self.sensor()\n'
        '            except SensorReceivedNoData as e:\n'
        '                if self.external_tick:\n'
        '                    raise RuntimeError(e)\n'
        '                logging.warning(str(e) + \'; ticking world and retrying\')\n'
        '                CarlaDataProvider.get_world().tick()\n'
        '                return\n'
        '            self.ego_actor.apply_control(ego_action)\n'
    )
    if new in text:
        pass
    elif old in text:
        text = text.replace(old, new, 1)
        changed = True
    else:
        print(f'Warning: sensor timeout recovery patch pattern not found in {path}')

    if changed:
        path.write_text(text)
        print(f'Applied CARLA sensor timeout recovery patch: {path}')
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_CARLA_PLANNING_PRESET}") == 1 ]]; then
  AUTOWARE_PLANNING_MODULE_PRESET_FOR_CARLA=$(shell_quote "${AUTOWARE_PLANNING_MODULE_PRESET:-ub_carla}") python3 - <<'PY'
import os
from pathlib import Path

preset_name = os.environ['AUTOWARE_PLANNING_MODULE_PRESET_FOR_CARLA']
preset_dir = Path('/autoware/install/autoware_launch/share/autoware_launch/config/planning/preset')
source_path = preset_dir / 'default_preset.yaml'
target_path = preset_dir / f'{preset_name}_preset.yaml'

if not source_path.exists():
    print(f'Warning: CARLA planning preset skipped; missing {source_path}')
else:
    text = source_path.read_text()
    disabled_modules = {
        'launch_crosswalk_module',
        'launch_walkway_module',
        'launch_traffic_light_module',
        'launch_virtual_traffic_light_module',
    }
    lines = text.splitlines()
    for index, line in enumerate(lines[:-1]):
        stripped = line.strip()
        if not stripped.startswith('name: '):
            continue
        module_name = stripped.split(':', 1)[1].strip()
        if module_name not in disabled_modules:
            continue
        default_line_index = index + 1
        if 'default:' in lines[default_line_index]:
            indent = lines[default_line_index].split('default:', 1)[0]
            lines[default_line_index] = f'{indent}default: ' + repr('false')
    target_path.write_text('\n'.join(lines) + '\n')
    print(
        'Prepared CARLA planning preset without traffic-light/crosswalk '
        f'behavior modules: {target_path}'
    )
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY}") == 1 ]]; then
  AUTOWARE_SENSOR_MODEL_FOR_CARLA=$(shell_quote "${AUTOWARE_SENSOR_MODEL}") python3 - <<'PY'
import os
from pathlib import Path

sensor_model = os.environ['AUTOWARE_SENSOR_MODEL_FOR_CARLA']
launch_path = Path(
    f'/autoware/install/{sensor_model}_launch/share/'
    f'{sensor_model}_launch/launch/lidar.launch.xml'
)

if not launch_path.exists():
    print(f'Warning: CARLA top-LiDAR override skipped; missing {launch_path}')
else:
    backup_path = launch_path.with_suffix(launch_path.suffix + '.ub-original')
    if not backup_path.exists():
        backup_path.write_text(launch_path.read_text())
    text = backup_path.read_text()
    quote = chr(34)
    old = f'<arg name={quote}use_concat_filter{quote} default={quote}true{quote}/>'
    new = f'<arg name={quote}use_concat_filter{quote} default={quote}false{quote}/>'
    if old in text:
        launch_path.write_text(text.replace(old, new, 1))
        print(f'Disabled Autoware multi-LiDAR concat filter for CARLA: {launch_path}')
    elif new in text:
        print(f'Autoware multi-LiDAR concat filter already disabled for CARLA: {launch_path}')
    else:
        print(f'Warning: use_concat_filter default not found in {launch_path}')
PY
  python3 - <<'PY' &
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from sensor_msgs.msg import PointCloud2

SOURCE_TOPIC = '/sensing/lidar/top/pointcloud_before_sync'
OUTPUT_TOPIC = '/sensing/lidar/concatenated/pointcloud'

rclpy.init()
node = rclpy.create_node('ub_carla_top_lidar_relay')
source_qos = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
)
output_qos = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
)
publisher = node.create_publisher(PointCloud2, OUTPUT_TOPIC, output_qos)

def relay(message):
    publisher.publish(message)

node.create_subscription(PointCloud2, SOURCE_TOPIC, relay, source_qos)
node.get_logger().info(f'Relaying {SOURCE_TOPIC} -> {OUTPUT_TOPIC}')
try:
    rclpy.spin(node)
except (KeyboardInterrupt, ExternalShutdownException):
    pass
finally:
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
PY
  UB_BACKGROUND_PIDS=\"\${UB_BACKGROUND_PIDS} \$!\"
fi
if [[ $(shell_quote "${UB_AUTOWARE_PATCH_CARLA_BRIDGE}") == 1 ]]; then
  python3 - <<'PY'
from pathlib import Path

source_root = Path('/autoware/build/autoware_carla_interface/src/autoware_carla_interface')
carla_ros_path = source_root / 'carla_ros.py'
carla_autoware_path = source_root / 'carla_autoware.py'
quote = chr(34)

def patch_file(path, replacements):
    if not path.exists():
        print(f'Warning: CARLA bridge patch skipped; missing {path}')
        return
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())
    text = backup.read_text()
    changed = False
    for old, new in replacements:
        if new in text:
            continue
        if old not in text:
            print(f'Warning: CARLA bridge patch pattern not found in {path}: {old!r}')
            continue
        text = text.replace(old, new, 1)
        changed = True
    if changed:
        path.write_text(text)
        print(f'Applied CARLA bridge runtime patch: {path}')

patch_file(
    carla_ros_path,
    [
        (
            'from autoware_vehicle_msgs.msg import ControlModeReport\n',
            'from autoware_vehicle_msgs.msg import ControlModeReport\n'
            'from autoware_vehicle_msgs.srv import ControlModeCommand\n',
        ),
        (
            '        self.current_control = carla.VehicleControl()\n',
            '        self.sub_control_mode_override = self.ros2_node.create_subscription(\n'
            '            ControlModeReport, \'/ub/carla/control_mode\', self.control_mode_override_callback, 1\n'
            '        )\n'
            '        self.srv_control_mode = self.ros2_node.create_service(\n'
            '            ControlModeCommand, \'/control/control_mode_request\', self.control_mode_request_callback\n'
            '        )\n'
            '        self.current_control_mode = ControlModeReport.MANUAL\n'
            '        self.current_control = carla.VehicleControl(brake=1.0, hand_brake=True)\n'
            '        self.received_control_cmd = False\n',
        ),
        (
            '    def control_callback(self, in_cmd):\n'
            ,
            '    def control_mode_override_callback(self, msg):\n'
            '        self.current_control_mode = msg.mode\n\n'
            '    def control_mode_request_callback(self, request, response):\n'
            '        # Accept Autoware operation-mode control ownership requests.\n'
            '        if request.mode == ControlModeCommand.Request.AUTONOMOUS:\n'
            '            self.current_control_mode = ControlModeReport.AUTONOMOUS\n'
            '        elif request.mode == ControlModeCommand.Request.MANUAL:\n'
            '            self.current_control_mode = ControlModeReport.MANUAL\n'
            '            self.current_control = carla.VehicleControl(brake=1.0, hand_brake=True)\n'
            '        else:\n'
            '            self.current_control_mode = request.mode\n'
            '        response.success = True\n'
            '        return response\n\n'
            '    def control_callback(self, in_cmd):\n'
        ),
        (
            '        out_cmd = carla.VehicleControl()\n',
            '        if self.current_control_mode != ControlModeReport.AUTONOMOUS:\n'
            '            return\n'
            '        out_cmd = carla.VehicleControl()\n',
        ),
        (
            '        out_cmd.brake = in_cmd.actuation.brake_cmd\n'
            '        self.current_control = out_cmd\n',
            '        out_cmd.brake = in_cmd.actuation.brake_cmd\n'
            '        out_cmd.hand_brake = False\n'
            '        self.received_control_cmd = True\n'
            '        self.current_control = out_cmd\n',
        ),
        (
            f'            ControlModeReport, {quote}/vehicle/status/control_mode{quote}, 1\n',
            f'            ControlModeReport, {quote}/ub/carla/status/control_mode_raw{quote}, 1\n',
        ),
        (
            '        out_ctrl_mode.stamp = out_vel_state.header.stamp\n'
            '        out_ctrl_mode.mode = ControlModeReport.AUTONOMOUS\n',
            '        out_ctrl_mode.stamp = out_vel_state.header.stamp\n'
            '        out_ctrl_mode.mode = self.current_control_mode\n',
        ),
    ],
)

patch_file(
    carla_autoware_path,
    [
        (
            '        self.interface.physics_control = self.ego_actor.get_physics_control()\n\n'
            '        self.sensor_wrapper = SensorWrapper(self.interface)\n',
            '        self.interface.physics_control = self.ego_actor.get_physics_control()\n'
            '        self.ego_actor.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))\n'
            '        self.ego_actor.set_target_angular_velocity(carla.Vector3D(0.0, 0.0, 0.0))\n'
            '        self.ego_actor.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))\n\n'
            '        self.sensor_wrapper = SensorWrapper(self.interface)\n',
        ),
    ],
)
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_EGO_ONLY_PERCEPTION}") == 1 ]]; then
  python3 - <<'PY'
from pathlib import Path

path = Path('/autoware/install/autoware_launch/share/autoware_launch/launch/autoware.launch.xml')
if not path.exists():
    print(f'Warning: ego-only perception patch skipped; missing {path}')
else:
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())
    text = backup.read_text()
    quote = chr(34)
    dollar = chr(36)
    data_path_arg = (
        f'      <arg name={quote}data_path{quote} '
        f'value={quote}{dollar}(var data_path){quote}/>\n'
    )
    empty_objects_arg = (
        f'      <arg name={quote}use_empty_dynamic_object_publisher{quote} '
        f'value={quote}true{quote}/>\n'
    )
    traffic_light_arg = (
        f'      <arg name={quote}use_traffic_light_recognition{quote} '
        f'value={quote}false{quote}/>\n'
    )
    changed = False
    if traffic_light_arg not in text and empty_objects_arg in text:
        text = text.replace(empty_objects_arg, empty_objects_arg + traffic_light_arg, 1)
        changed = True
    if empty_objects_arg in text:
        path.write_text(text)
        if changed:
            print(f'Disabled CARLA traffic-light recognition: {path}')
        print(f'Ego-only empty object publisher already enabled: {path}')
    elif data_path_arg in text:
        path.write_text(text.replace(data_path_arg, data_path_arg + empty_objects_arg + traffic_light_arg, 1))
        print(f'Enabled ego-only perception for CARLA: {path}')
    else:
        print(f'Warning: perception include data_path arg not found in {path}')
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_CONTROL_MODE_SHIM}") == 1 ]]; then
python3 - <<'PY' &
import rclpy
from rclpy.executors import ExternalShutdownException
from autoware_vehicle_msgs.msg import ControlModeReport
from autoware_vehicle_msgs.msg import HazardLightsCommand
from autoware_vehicle_msgs.msg import TurnIndicatorsCommand
from autoware_vehicle_msgs.srv import ControlModeCommand
from tier4_system_msgs.msg import OperationModeAvailability

rclpy.init()
node = rclpy.create_node('ub_carla_control_mode_shim')
mode = ControlModeReport.MANUAL
status_pub = node.create_publisher(ControlModeReport, '/vehicle/status/control_mode', 1)
override_pub = node.create_publisher(ControlModeReport, '/ub/carla/control_mode', 1)
hazard_pub = node.create_publisher(HazardLightsCommand, '/control/command/hazard_lights_cmd', 1)
turn_pub = node.create_publisher(TurnIndicatorsCommand, '/control/command/turn_indicators_cmd', 1)
availability_pub = node.create_publisher(
    OperationModeAvailability, '/system/operation_mode/availability', 1
)

def publish_mode():
    msg = ControlModeReport()
    msg.stamp = node.get_clock().now().to_msg()
    msg.mode = mode
    status_pub.publish(msg)
    override_pub.publish(msg)

    hazard = HazardLightsCommand()
    hazard.stamp = msg.stamp
    hazard.command = HazardLightsCommand.DISABLE
    hazard_pub.publish(hazard)

    turn = TurnIndicatorsCommand()
    turn.stamp = msg.stamp
    turn.command = TurnIndicatorsCommand.DISABLE
    turn_pub.publish(turn)

    availability = OperationModeAvailability()
    availability.stamp = msg.stamp
    availability.stop = True
    availability.autonomous = True
    availability.local = True
    availability.remote = True
    availability.emergency_stop = True
    availability.comfortable_stop = False
    availability.pull_over = False
    availability_pub.publish(availability)

def on_request(request, response):
    global mode
    if request.mode == ControlModeCommand.Request.AUTONOMOUS:
        mode = ControlModeReport.AUTONOMOUS
    elif request.mode == ControlModeCommand.Request.MANUAL:
        mode = ControlModeReport.MANUAL
    else:
        mode = request.mode
    publish_mode()
    response.success = True
    return response

node.create_service(ControlModeCommand, '/control/control_mode_request', on_request)
node.create_timer(0.05, publish_mode)
node.get_logger().info(
    'Providing /control/control_mode_request, /vehicle/status/control_mode, '
    '/control/command/hazard_lights_cmd, /control/command/turn_indicators_cmd, '
    'and simulator operation-mode availability'
)
try:
    rclpy.spin(node)
except (KeyboardInterrupt, ExternalShutdownException):
    pass
finally:
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
PY
UB_BACKGROUND_PIDS=\"\${UB_BACKGROUND_PIDS} \$!\"
fi
trap 'for pid in \${UB_BACKGROUND_PIDS:-}; do kill \${pid} 2>/dev/null || true; done' EXIT
ros2 launch autoware_launch e2e_simulator.launch.xml \\
  map_path:=$(shell_quote "${AUTOWARE_MAP_PATH}") \\
  vehicle_model:=$(shell_quote "${AUTOWARE_VEHICLE_MODEL}") \\
  sensor_model:=$(shell_quote "${AUTOWARE_SENSOR_MODEL}") \\
  simulator_type:=carla \\
  host:=$(shell_quote "${AUTOWARE_CARLA_HOST}") \\
  carla_map:=$(shell_quote "${CARLA_MAP}") \\
  external_tick:=False${optional_launch_args}
"

  echo "Launching Autoware. Press Ctrl+C to stop the ROS launch."
  AUTOWARE_LAUNCH_STARTED=1
  set +e
  docker compose "${exec_args[@]}" "${AUTOWARE_SERVICE}" bash -lc "${launch_cmd}"
  local launch_status=$?
  set -e

  if [[ "${UB_KEEP_AUTOWARE_ROS}" != "1" ]]; then
    cleanup_autoware_launch_processes "Stopping Autoware ROS launch processes. Set UB_KEEP_AUTOWARE_ROS=1 to leave them running."
    AUTOWARE_LAUNCH_STARTED=0
  fi

  return "${launch_status}"
}

for arg in "$@"; do
  case "${arg}" in
    --dry-run)
      DRY_RUN=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      usage >&2
      exit 2
      ;;
  esac
done

run_preflight

if [[ "${DRY_RUN}" -eq 1 ]]; then
  print_dry_run
  exit 0
fi

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

configure_autoware_host_dds
start_carla
start_camera_follow
launch_autoware
