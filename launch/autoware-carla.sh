#!/usr/bin/env bash
set -euo pipefail

LAUNCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${LAUNCH_DIR}/.." && pwd)"
CARLA_DIR="${REPO_ROOT}/CARLA"

source "${LAUNCH_DIR}/lib/common.sh"
source "${LAUNCH_DIR}/lib/x11.sh"
source "${LAUNCH_DIR}/lib/preflight.sh"
source "${LAUNCH_DIR}/lib/compose.sh"
source "${LAUNCH_DIR}/carla/stack.sh"
source "${LAUNCH_DIR}/carla/camera_follow.sh"
source "${LAUNCH_DIR}/carla/time_master.sh"
source "${LAUNCH_DIR}/autoware/dds.sh"
source "${LAUNCH_DIR}/autoware/container.sh"
source "${LAUNCH_DIR}/autoware/launch.sh"

BUILD_FOLDER="${BUILD_FOLDER:-v1.0.0}"
CARLA_MAP="${CARLA_MAP:-UBAutonomousProvingGrounds}"
CARLA_MAP_PATH="${CARLA_MAP_PATH:-/Game/Carla/Maps/${CARLA_MAP}}"
CARLA_ARGS="${CARLA_ARGS:--prefernvidia -quality-level=Epic -nosound}"
CARLA_BASE_SERVICES="redis"

DEFAULT_AUTOWARE_HOST_MAP_DIR="${REPO_ROOT}/Autoware/host_data/maps/ub_autonomous_proving_grounds"
DEFAULT_AUTOWARE_MAP_PATH="/host_data/maps/ub_autonomous_proving_grounds"
LEGACY_AUTOWARE_HOST_MAP_DIR="${REPO_ROOT}/Autoware/host_data/ub_autonomous_proving_grounds"
LEGACY_AUTOWARE_MAP_PATH="/host_data/ub_autonomous_proving_grounds"

if [[ -z "${AUTOWARE_HOST_MAP_DIR:-}" && -z "${AUTOWARE_MAP_PATH:-}" ]] && has_files "${LEGACY_AUTOWARE_HOST_MAP_DIR}" && ! has_files "${DEFAULT_AUTOWARE_HOST_MAP_DIR}"; then
  AUTOWARE_HOST_MAP_DIR="${LEGACY_AUTOWARE_HOST_MAP_DIR}"
  AUTOWARE_MAP_PATH="${LEGACY_AUTOWARE_MAP_PATH}"
fi

AUTOWARE_DOCKER_DIR="${AUTOWARE_DOCKER_DIR:-${REPO_ROOT}/Autoware/ub-lincoln-docker/docker}"
AUTOWARE_HOST_MAP_DIR="${AUTOWARE_HOST_MAP_DIR:-${DEFAULT_AUTOWARE_HOST_MAP_DIR}}"
AUTOWARE_MAP_PATH="${AUTOWARE_MAP_PATH:-${DEFAULT_AUTOWARE_MAP_PATH}}"
AUTOWARE_SERVICE="${AUTOWARE_SERVICE:-autoware}"
AUTOWARE_CARLA_HOST="${AUTOWARE_CARLA_HOST:-127.0.0.1}"
AUTOWARE_VEHICLE_MODEL="${AUTOWARE_VEHICLE_MODEL:-sample_vehicle}"
AUTOWARE_SENSOR_MODEL="${AUTOWARE_SENSOR_MODEL:-awsim_sensor_kit}"
AUTOWARE_RVIZ="${AUTOWARE_RVIZ:-}"
AUTOWARE_PLANNING_MODULE_PRESET="${AUTOWARE_PLANNING_MODULE_PRESET:-ub_carla}"
UB_AUTOWARE_INSTALL_PY_DEPS="${UB_AUTOWARE_INSTALL_PY_DEPS:-1}"
UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY="${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY:-1}"
UB_AUTOWARE_PATCH_CARLA_BRIDGE="${UB_AUTOWARE_PATCH_CARLA_BRIDGE:-0}"
UB_AUTOWARE_EGO_ONLY_PERCEPTION="${UB_AUTOWARE_EGO_ONLY_PERCEPTION:-1}"
UB_AUTOWARE_CARLA_PLANNING_PRESET="${UB_AUTOWARE_CARLA_PLANNING_PRESET:-1}"
# e2e_simulator.launch.xml auto-includes autoware_carla_interface with no args
# when simulator_type=carla, so its spawn_point otherwise defaults to "None"
# (random) — anywhere except this calibrated point is outside the recorded
# HD map's coverage, so NDT never has anything to localize against. Captured
# from RViz 2D Pose Estimate and converted from ROS map to CARLA coordinates.
UB_AUTOWARE_CARLA_SPAWN_POINT="${UB_AUTOWARE_CARLA_SPAWN_POINT:--214.130,3.295,0.030,0,0,0.722}"
UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD="${UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD:-False}"
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
UB_CARLA_STEP_LENGTH="${UB_CARLA_STEP_LENGTH:-0.05}"
UB_CARLA_TIMEOUT="${UB_CARLA_TIMEOUT:-10.0}"
UB_CARLA_RESET_SYNC_ON_EXIT="${UB_CARLA_RESET_SYNC_ON_EXIT:-0}"
UB_KEEP_TIME_MASTER="${UB_KEEP_TIME_MASTER:-0}"

CARLA_STARTED=0
TIME_MASTER_STARTED=0
AUTOWARE_LAUNCH_STARTED=0
CAMERA_FOLLOW_STARTED=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run] [--help]

Start rendered CARLA on the UB autonomous proving grounds map, a CARLA-only
time master (Autoware's e2e_simulator.launch.xml always pulls in the CARLA
bridge when simulator_type=carla, and that bridge defaults to
external_tick=True with no way to override it from this launch call, so
something has to tick CARLA in synchronous mode), then launch Autoware's
CARLA e2e simulator in the foreground.

Defaults:
  BUILD_FOLDER=${BUILD_FOLDER}
  CARLA_MAP=${CARLA_MAP}
  CARLA_ARGS=${CARLA_ARGS}
  UB_CARLA_STEP_LENGTH=${UB_CARLA_STEP_LENGTH}
  UB_CARLA_TIMEOUT=${UB_CARLA_TIMEOUT}
  UB_CARLA_RESET_SYNC_ON_EXIT=${UB_CARLA_RESET_SYNC_ON_EXIT}
  UB_KEEP_TIME_MASTER=${UB_KEEP_TIME_MASTER}
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
  UB_AUTOWARE_CARLA_SPAWN_POINT=${UB_AUTOWARE_CARLA_SPAWN_POINT}
  UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD=${UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD}
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
  UB_AUTOWARE_CARLA_SPAWN_POINT="-214.130,3.295,0.030,0,0,0.722" $(basename "$0")
  UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD=True $(basename "$0")
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
  UB_CARLA_STEP_LENGTH=0.05 $(basename "$0")
  UB_KEEP_TIME_MASTER=1 $(basename "$0")

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
    AUTOWARE_SERVICE=<service-name> launch/autoware-carla.sh
EOF
}

collect_preflight_failures() {
  local failures_ref="$1"
  local -n preflight_failures="${failures_ref}"

  collect_docker_preflight_failures preflight_failures

  if [[ ! -x "${CARLA_DIR}/Builds/${BUILD_FOLDER}/CarlaUE4.sh" ]]; then
    preflight_failures+=("Missing executable CARLA build: ${CARLA_DIR}/Builds/${BUILD_FOLDER}/CarlaUE4.sh")
  fi

  if [[ "${UB_AUTOWARE_CAMERA_FOLLOW}" == "1" ]]; then
    if ! find "${CARLA_DIR}/Builds/${BUILD_FOLDER}/PythonAPI/carla/dist" -maxdepth 1 -type f -name 'carla-*-cp310-*.whl' -print -quit 2>/dev/null | grep -q .; then
      preflight_failures+=("Missing CARLA Python wheel under ${CARLA_DIR}/Builds/${BUILD_FOLDER}/PythonAPI/carla/dist for camera follow.")
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

print_dry_run() {
  cat <<EOF
Dry run passed. The launcher would run:

  cd ${AUTOWARE_DOCKER_DIR}
  ../scripts/host_config_dds.bash  # runs before containers start when host DDS settings are not already applied

  cd ${CARLA_DIR}
  BUILD_FOLDER=${BUILD_FOLDER} \\
  CARLA_MAP_PATH=${CARLA_MAP_PATH} \\
  CARLA_ARGS=${CARLA_ARGS} \\
  UB_CARLA_EXTRA_SERVICES=${UB_CARLA_EXTRA_SERVICES:-<none>} \\
  docker compose up --build -d carla redis map-loader ${UB_CARLA_EXTRA_SERVICES}

  cd ${CARLA_DIR}
  UB_CARLA_STEP_LENGTH=${UB_CARLA_STEP_LENGTH} \\
  docker compose up --build -d time-master

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
  rviz:=${AUTOWARE_RVIZ:-<omitted; manual launch default>}
  planning_module_preset:=${AUTOWARE_PLANNING_MODULE_PRESET:-<omitted; manual launch default>}
  install_python_deps:=${UB_AUTOWARE_INSTALL_PY_DEPS}
  carla_top_lidar_only:=${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY}
  patch_carla_bridge:=${UB_AUTOWARE_PATCH_CARLA_BRIDGE}
  ego_only_perception:=${UB_AUTOWARE_EGO_ONLY_PERCEPTION}
  carla_planning_preset:=${UB_AUTOWARE_CARLA_PLANNING_PRESET}
  carla_spawn_point:=${UB_AUTOWARE_CARLA_SPAWN_POINT}
  carla_project_spawn_point_to_road:=${UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD}
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

cleanup() {
  local exit_code="$?"

  if [[ "${CAMERA_FOLLOW_STARTED}" -eq 1 ]]; then
    echo "Stopping CARLA spectator camera follow."
    stop_compose_service camera-follow
    CAMERA_FOLLOW_STARTED=0
  fi

  if [[ "${AUTOWARE_LAUNCH_STARTED}" -eq 1 && "${UB_KEEP_AUTOWARE_ROS}" != "1" ]]; then
    cleanup_autoware_launch_processes "Stopping Autoware ROS launch processes. Set UB_KEEP_AUTOWARE_ROS=1 to leave them running." AUTOWARE_E2E_CLEANUP_PATTERNS || true
    AUTOWARE_LAUNCH_STARTED=0
  fi

  if [[ "${TIME_MASTER_STARTED}" -eq 1 && "${UB_KEEP_TIME_MASTER}" != "1" ]]; then
    echo "Stopping CARLA-only time master. Set UB_KEEP_TIME_MASTER=1 to leave it running."
    stop_compose_service time-master
    TIME_MASTER_STARTED=0
  fi

  if [[ "${CARLA_STARTED}" -eq 1 && "${UB_KEEP_CARLA}" != "1" ]]; then
    echo "Stopping CARLA Compose stack. Set UB_KEEP_CARLA=1 to leave it running."
    cd "${CARLA_DIR}"
    docker compose down >/dev/null 2>&1 || true
  fi

  exit "${exit_code}"
}

parse_common_args "$@"

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
start_carla_time_master
start_camera_follow
start_autoware_container AUTOWARE_E2E_CLEANUP_PATTERNS
launch_autoware_plain
