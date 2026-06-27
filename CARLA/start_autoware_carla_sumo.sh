#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BRIDGE_DIR="${SCRIPT_DIR}/UB-API/carla-autoware-sumo-bridge"

has_files() {
  local path="$1"
  [[ -d "${path}" ]] || return 1
  find "${path}" -mindepth 1 -maxdepth 2 -print -quit 2>/dev/null | grep -q .
}

BUILD_FOLDER="${BUILD_FOLDER:-v1.0.0}"
CARLA_MAP="${CARLA_MAP:-UBAutonomousProvingGrounds}"
CARLA_MAP_PATH="${CARLA_MAP_PATH:-/Game/Carla/Maps/${CARLA_MAP}}"
CARLA_ARGS="${CARLA_ARGS:--prefernvidia -quality-level=Epic -nosound}"

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
AUTOWARE_CARLA_PORT="${AUTOWARE_CARLA_PORT:-2000}"
AUTOWARE_VEHICLE_MODEL="${AUTOWARE_VEHICLE_MODEL:-sample_vehicle}"
AUTOWARE_SENSOR_MODEL="${AUTOWARE_SENSOR_MODEL:-awsim_sensor_kit}"
AUTOWARE_RVIZ="${AUTOWARE_RVIZ:-}"
AUTOWARE_PLANNING_MODULE_PRESET="${AUTOWARE_PLANNING_MODULE_PRESET:-}"
AUTOWARE_E2E_SIMULATOR_TYPE="${AUTOWARE_E2E_SIMULATOR_TYPE:-awsim}"
AUTOWARE_CARLA_POINTCLOUD_RELAY="${AUTOWARE_CARLA_POINTCLOUD_RELAY:-1}"
UB_AUTOWARE_CARLA_EGO_ROLE_NAME="${UB_AUTOWARE_CARLA_EGO_ROLE_NAME:-ego_vehicle}"
UB_AUTOWARE_CARLA_VEHICLE_TYPE="${UB_AUTOWARE_CARLA_VEHICLE_TYPE:-vehicle.lincoln.mkz_2020}"
# Default captured from RViz 2D Pose Estimate and converted from ROS map to CARLA coordinates.
UB_AUTOWARE_CARLA_SPAWN_POINT="${UB_AUTOWARE_CARLA_SPAWN_POINT:--214.130,3.295,0.030,0,0,0.722}"
UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD="${UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD:-False}"
UB_AUTOWARE_CARLA_OBJECTS_DEFINITION_FILE="${UB_AUTOWARE_CARLA_OBJECTS_DEFINITION_FILE:-}"
UB_AUTOWARE_CARLA_EXTERNAL_TICK_TIMEOUT="${UB_AUTOWARE_CARLA_EXTERNAL_TICK_TIMEOUT:-20.0}"
UB_AUTOWARE_INSTALL_PY_DEPS="${UB_AUTOWARE_INSTALL_PY_DEPS:-1}"
UB_AUTOWARE_HOST_CONFIG_DDS="${UB_AUTOWARE_HOST_CONFIG_DDS:-1}"
UB_AUTOWARE_RMW_IMPLEMENTATION="${UB_AUTOWARE_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
UB_AUTOWARE_CYCLONEDDS_URI="${UB_AUTOWARE_CYCLONEDDS_URI:-file:///resources/cyclonedds.xml}"
UB_AUTOWARE_CLEAN_STALE_PROCESSES="${UB_AUTOWARE_CLEAN_STALE_PROCESSES:-1}"
UB_KEEP_CARLA="${UB_KEEP_CARLA:-0}"
UB_KEEP_AUTOWARE_ROS="${UB_KEEP_AUTOWARE_ROS:-0}"
UB_KEEP_SUMO="${UB_KEEP_SUMO:-0}"
UB_TRAFFIC_ORCHESTRATOR="${UB_TRAFFIC_ORCHESTRATOR:-sumo}"
UB_KEEP_TIME_MASTER="${UB_KEEP_TIME_MASTER:-0}"

UB_SUMO_CONFIG="${UB_SUMO_CONFIG:-UBAutonomousProvingGrounds.sumocfg}"
UB_SUMO_STEP_LENGTH="${UB_SUMO_STEP_LENGTH:-0.05}"
UB_SUMO_GUI="${UB_SUMO_GUI:-1}"
UB_SUMO_AUTO_START="${UB_SUMO_AUTO_START:-1}"
UB_SUMO_TLS_MANAGER="${UB_SUMO_TLS_MANAGER:-sumo}"
UB_SUMO_SYNC_VEHICLE_COLOR="${UB_SUMO_SYNC_VEHICLE_COLOR:-0}"
UB_SUMO_SYNC_VEHICLE_LIGHTS="${UB_SUMO_SYNC_VEHICLE_LIGHTS:-0}"
UB_SUMO_EXTRA_ARGS="${UB_SUMO_EXTRA_ARGS:-}"

DRY_RUN=0
CARLA_STARTED=0
SUMO_STARTED=0
TIME_MASTER_STARTED=0
AUTOWARE_LAUNCH_STARTED=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run] [--help]

Start single-machine UB-CARLA + Autoware using the custom
autoware_carla_interface in passive mode. With UB_TRAFFIC_ORCHESTRATOR=sumo,
SUMO is the time master. With UB_TRAFFIC_ORCHESTRATOR=none, a CARLA-only
time-master service ticks CARLA.

Defaults:
  BUILD_FOLDER=${BUILD_FOLDER}
  CARLA_MAP=${CARLA_MAP}
  CARLA_ARGS=${CARLA_ARGS}
  UB_TRAFFIC_ORCHESTRATOR=${UB_TRAFFIC_ORCHESTRATOR}
  UB_SUMO_CONFIG=${UB_SUMO_CONFIG}
  UB_SUMO_STEP_LENGTH=${UB_SUMO_STEP_LENGTH}
  UB_SUMO_GUI=${UB_SUMO_GUI}
  UB_SUMO_AUTO_START=${UB_SUMO_AUTO_START}
  UB_SUMO_TLS_MANAGER=${UB_SUMO_TLS_MANAGER}
  AUTOWARE_MAP_PATH=${AUTOWARE_MAP_PATH}
  AUTOWARE_SERVICE=${AUTOWARE_SERVICE}
  AUTOWARE_CARLA_HOST=${AUTOWARE_CARLA_HOST}
  AUTOWARE_CARLA_PORT=${AUTOWARE_CARLA_PORT}
  AUTOWARE_VEHICLE_MODEL=${AUTOWARE_VEHICLE_MODEL}
  AUTOWARE_SENSOR_MODEL=${AUTOWARE_SENSOR_MODEL}
  AUTOWARE_E2E_SIMULATOR_TYPE=${AUTOWARE_E2E_SIMULATOR_TYPE}
  AUTOWARE_CARLA_POINTCLOUD_RELAY=${AUTOWARE_CARLA_POINTCLOUD_RELAY}
  UB_AUTOWARE_CARLA_EGO_ROLE_NAME=${UB_AUTOWARE_CARLA_EGO_ROLE_NAME}
  UB_AUTOWARE_CARLA_VEHICLE_TYPE=${UB_AUTOWARE_CARLA_VEHICLE_TYPE}
  UB_AUTOWARE_CARLA_SPAWN_POINT=${UB_AUTOWARE_CARLA_SPAWN_POINT}
  UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD=${UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD}
  UB_AUTOWARE_CARLA_OBJECTS_DEFINITION_FILE=${UB_AUTOWARE_CARLA_OBJECTS_DEFINITION_FILE:-<package default>}
  UB_AUTOWARE_CARLA_EXTERNAL_TICK_TIMEOUT=${UB_AUTOWARE_CARLA_EXTERNAL_TICK_TIMEOUT}

Useful overrides:
  UB_SUMO_CONFIG=Town01.sumocfg $(basename "$0")
  UB_TRAFFIC_ORCHESTRATOR=none $(basename "$0")
  UB_SUMO_GUI=0 $(basename "$0")
  UB_SUMO_EXTRA_ARGS="--debug" $(basename "$0")
  UB_AUTOWARE_CARLA_SPAWN_POINT="-214.130,3.295,0.030,0,0,0.722" $(basename "$0")
  UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD=False $(basename "$0")
  UB_AUTOWARE_CARLA_OBJECTS_DEFINITION_FILE=/host_data/custom_objects.json $(basename "$0")
  AUTOWARE_RVIZ=false $(basename "$0")
  UB_KEEP_CARLA=1 UB_KEEP_SUMO=1 $(basename "$0")

Options:
  --dry-run  Validate prerequisites and print commands without starting containers.
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
EOF
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

  if ! find "${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/PythonAPI/carla/dist" -maxdepth 1 -type f -name 'carla-*-cp310-*.whl' -print -quit 2>/dev/null | grep -q .; then
    preflight_failures+=("Missing CARLA Python cp310 wheel under ${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/PythonAPI/carla/dist.")
  fi

  case "${UB_TRAFFIC_ORCHESTRATOR}" in
    sumo|none) ;;
    *)
      preflight_failures+=("Unsupported UB_TRAFFIC_ORCHESTRATOR=${UB_TRAFFIC_ORCHESTRATOR}; expected 'sumo' or 'none'.")
      ;;
  esac

  if [[ "${UB_TRAFFIC_ORCHESTRATOR}" == "sumo" && ! -f "${BRIDGE_DIR}/Sumo/examples/${UB_SUMO_CONFIG}" ]]; then
    preflight_failures+=("Missing SUMO config: ${BRIDGE_DIR}/Sumo/examples/${UB_SUMO_CONFIG}")
  fi

  if [[ ! -d "${BRIDGE_DIR}/autoware_carla_interface" ]]; then
    preflight_failures+=("Missing custom autoware_carla_interface package: ${BRIDGE_DIR}/autoware_carla_interface")
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
    preflight_failures+=("Missing /tmp/.X11-unix. CARLA and SUMO GUI need the host X11 socket mounted into Docker.")
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

  cd ${SCRIPT_DIR}
  BUILD_FOLDER=${BUILD_FOLDER} \\
  CARLA_MAP_PATH=${CARLA_MAP_PATH} \\
  CARLA_ARGS=${CARLA_ARGS} \\
  docker compose up --build -d carla map-loader

  cd ${SCRIPT_DIR}
EOF

  if [[ "${UB_TRAFFIC_ORCHESTRATOR}" == "sumo" ]]; then
    cat <<EOF

  cd ${SCRIPT_DIR}
  UB_SUMO_CONFIG=${UB_SUMO_CONFIG} \\
  UB_SUMO_STEP_LENGTH=${UB_SUMO_STEP_LENGTH} \\
  UB_SUMO_GUI=${UB_SUMO_GUI} \\
  UB_SUMO_AUTO_START=${UB_SUMO_AUTO_START} \\
  UB_SUMO_TLS_MANAGER=${UB_SUMO_TLS_MANAGER} \\
  docker compose up --build -d sumo-bridge
EOF
  else
    cat <<EOF

  cd ${SCRIPT_DIR}
  UB_CARLA_STEP_LENGTH=${UB_SUMO_STEP_LENGTH} \\
  docker compose up --build -d time-master
EOF
  fi

  cat <<EOF

  cd ${AUTOWARE_DOCKER_DIR}
  docker compose up -d ${AUTOWARE_SERVICE}
  # autoware_carla_interface is mounted by the Autoware Compose service.
  docker compose exec ${AUTOWARE_SERVICE} bash -lc 'test -f /autoware/src/universe/autoware_universe/simulator/autoware_carla_interface/package.xml'
  docker compose exec ${AUTOWARE_SERVICE} bash -lc 'cd /autoware && colcon build --symlink-install --packages-select autoware_carla_interface'
  docker compose exec ${AUTOWARE_SERVICE} bash -lc 'ros2 launch autoware_carla_interface ... external_tick:=True vehicle_type:=${UB_AUTOWARE_CARLA_VEHICLE_TYPE} spawn_point:=${UB_AUTOWARE_CARLA_SPAWN_POINT} & ros2 run topic_tools relay ... & ros2 launch autoware_launch e2e_simulator.launch.xml simulator_type:=awsim ...'
EOF
}

shell_quote() {
  printf "%q" "$1"
}

configure_autoware_host_dds() {
  if [[ "${UB_AUTOWARE_HOST_CONFIG_DDS}" != "1" || "${UB_AUTOWARE_RMW_IMPLEMENTATION}" != "rmw_cyclonedds_cpp" ]]; then
    return 0
  fi

  if [[ ! -x "${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash" ]]; then
    echo "Warning: missing executable Autoware host DDS setup script: ${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash" >&2
    return 0
  fi

  echo "Applying Autoware host DDS settings. sudo may prompt for your password."
  "${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash"
}

wait_for_map_loader() {
  local map_loader_id=""
  local status=""

  cd "${SCRIPT_DIR}"
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

  cd "${SCRIPT_DIR}"
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
  echo "Error: CARLA container is not running: status=${status}, exit_code=${exit_code}" >&2
  docker compose logs --tail=120 carla >&2 || true
  return 1
}

start_carla() {
  cd "${SCRIPT_DIR}"

  export BUILD_FOLDER
  export CARLA_ARGS
  export CARLA_MAP_PATH
  export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
  if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
    export XAUTHORITY="${HOME}/.Xauthority"
  fi

  if command -v xhost >/dev/null 2>&1; then
    xhost +local:root >/dev/null || echo "Warning: xhost did not grant local root X11 access. CARLA or SUMO GUI may fail to render." >&2
  fi

  echo "Starting rendered CARLA Compose stack..."
  CARLA_STARTED=1
  docker compose up --build -d carla map-loader
  wait_for_map_loader
  echo "Checking CARLA stays alive after map load..."
  for _ in {1..8}; do
    sleep 1
    assert_carla_running
  done
}

start_sumo_bridge() {
  cd "${SCRIPT_DIR}"

  export BUILD_FOLDER
  export DISPLAY
  export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
  if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
    export XAUTHORITY="${HOME}/.Xauthority"
  fi
  export UB_SUMO_CONFIG
  export UB_SUMO_STEP_LENGTH
  export UB_SUMO_GUI
  export UB_SUMO_AUTO_START
  export UB_SUMO_TLS_MANAGER
  export UB_SUMO_SYNC_VEHICLE_COLOR
  export UB_SUMO_SYNC_VEHICLE_LIGHTS
  export UB_SUMO_EXTRA_ARGS

  echo "Starting CARLA-SUMO bridge with SUMO config ${UB_SUMO_CONFIG}..."
  docker compose up --build -d sumo-bridge
  SUMO_STARTED=1

  sleep 2
  if [[ "$(docker compose ps --status running -q sumo-bridge 2>/dev/null || true)" == "" ]]; then
    echo "Error: sumo-bridge exited during startup." >&2
    docker compose logs --tail=120 sumo-bridge >&2 || true
    return 1
  fi
}

start_carla_time_master() {
  cd "${SCRIPT_DIR}"

  export BUILD_FOLDER
  export UB_CARLA_STEP_LENGTH="${UB_SUMO_STEP_LENGTH}"
  export UB_CARLA_TIMEOUT="${UB_CARLA_TIMEOUT:-10.0}"
  export UB_CARLA_RESET_SYNC_ON_EXIT="${UB_CARLA_RESET_SYNC_ON_EXIT:-0}"

  echo "Starting CARLA-only time master with fixed delta ${UB_CARLA_STEP_LENGTH}..."
  docker compose up --build -d time-master
  TIME_MASTER_STARTED=1

  sleep 2
  if [[ "$(docker compose ps --status running -q time-master 2>/dev/null || true)" == "" ]]; then
    echo "Error: time-master exited during startup." >&2
    docker compose logs --tail=120 time-master >&2 || true
    return 1
  fi
}

cleanup_autoware_launch_processes() {
  cd "${AUTOWARE_DOCKER_DIR}"
  if [[ -z "$(docker compose ps -q "${AUTOWARE_SERVICE}" 2>/dev/null || true)" ]]; then
    return 0
  fi

  echo "${1:-Stopping Autoware ROS launch processes.}"
  docker compose exec -T "${AUTOWARE_SERVICE}" bash -lc '
pkill -INT -f "ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml" || true
pkill -INT -f "ros2 launch autoware_launch e2e_simulator.launch.xml" || true
pkill -INT -f "ros2 run topic_tools relay /sensing/lidar/top/pointcloud_before_sync /sensing/lidar/concatenated/pointcloud" || true
sleep 2
pkill -TERM -f "ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml" || true
pkill -TERM -f "ros2 launch autoware_launch e2e_simulator.launch.xml" || true
pkill -TERM -f "ros2 run topic_tools relay /sensing/lidar/top/pointcloud_before_sync /sensing/lidar/concatenated/pointcloud" || true
pkill -TERM -f "/autoware/install/autoware_carla_interface/lib/autoware_carla_interface/autoware_carla_interface" || true
' >/dev/null 2>&1 || true
}

start_autoware_container() {
  cd "${AUTOWARE_DOCKER_DIR}"

  echo "Starting Autoware Compose service: ${AUTOWARE_SERVICE}"
  export RMW_IMPLEMENTATION="${UB_AUTOWARE_RMW_IMPLEMENTATION}"
  export CYCLONEDDS_URI="${UB_AUTOWARE_CYCLONEDDS_URI}"
  docker compose up -d "${AUTOWARE_SERVICE}"

  if [[ "${UB_AUTOWARE_CLEAN_STALE_PROCESSES}" == "1" ]]; then
    cleanup_autoware_launch_processes "Cleaning stale Autoware ROS launch processes before starting."
  fi
}

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
colcon build --symlink-install --packages-select autoware_carla_interface
source /autoware/install/setup.bash
ros2 pkg prefix autoware_carla_interface
"
}

launch_autoware() {
  local exec_args=(exec)
  local optional_bridge_args=""
  local optional_launch_args=""
  local launch_cmd

  cd "${AUTOWARE_DOCKER_DIR}"

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
  if [[ -n "${UB_AUTOWARE_CARLA_OBJECTS_DEFINITION_FILE}" ]]; then
    optional_bridge_args+=" \\
  objects_definition_file:=$(shell_quote "${UB_AUTOWARE_CARLA_OBJECTS_DEFINITION_FILE}")"
  fi

launch_cmd="
set -eo pipefail
export RMW_IMPLEMENTATION=$(shell_quote "${UB_AUTOWARE_RMW_IMPLEMENTATION}")
export CYCLONEDDS_URI=$(shell_quote "${UB_AUTOWARE_CYCLONEDDS_URI}")
source /opt/ros/humble/setup.bash
source /autoware/install/setup.bash

ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml \\
  host:=$(shell_quote "${AUTOWARE_CARLA_HOST}") \\
  port:=$(shell_quote "${AUTOWARE_CARLA_PORT}") \\
  carla_map:=$(shell_quote "${CARLA_MAP}") \\
  fixed_delta_seconds:=$(shell_quote "${UB_SUMO_STEP_LENGTH}") \\
  ego_vehicle_role_name:=$(shell_quote "${UB_AUTOWARE_CARLA_EGO_ROLE_NAME}") \\
  vehicle_type:=$(shell_quote "${UB_AUTOWARE_CARLA_VEHICLE_TYPE}") \\
  spawn_point:=$(shell_quote "${UB_AUTOWARE_CARLA_SPAWN_POINT}") \\
  project_spawn_point_to_road:=$(shell_quote "${UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD}") \\
  external_tick:=True \\
  external_tick_timeout:=$(shell_quote "${UB_AUTOWARE_CARLA_EXTERNAL_TICK_TIMEOUT}")${optional_bridge_args} &
BRIDGE_PID=\$!
RELAY_PID=

cleanup_bridge_processes() {
  kill \${BRIDGE_PID} 2>/dev/null || true
  if [[ -n \"\${RELAY_PID}\" ]]; then
    kill \${RELAY_PID} 2>/dev/null || true
  fi
}
trap cleanup_bridge_processes EXIT

sleep 5
if ! kill -0 \${BRIDGE_PID} 2>/dev/null; then
  echo \"Error: autoware_carla_interface exited before Autoware launch started.\" >&2
  wait \${BRIDGE_PID} || true
  exit 1
fi

if [[ $(shell_quote "${AUTOWARE_CARLA_POINTCLOUD_RELAY}") == \"1\" ]]; then
  ros2 run topic_tools relay \\
    /sensing/lidar/top/pointcloud_before_sync \\
    /sensing/lidar/concatenated/pointcloud &
  RELAY_PID=\$!
fi

ros2 launch autoware_launch e2e_simulator.launch.xml \\
  map_path:=$(shell_quote "${AUTOWARE_MAP_PATH}") \\
  vehicle_model:=$(shell_quote "${AUTOWARE_VEHICLE_MODEL}") \\
  sensor_model:=$(shell_quote "${AUTOWARE_SENSOR_MODEL}") \\
  simulator_type:=$(shell_quote "${AUTOWARE_E2E_SIMULATOR_TYPE}")${optional_launch_args}
"

  echo "Launching passive CARLA interface and Autoware. Press Ctrl+C to stop the ROS launch."
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

cleanup() {
  local exit_code="$?"

  if [[ "${AUTOWARE_LAUNCH_STARTED}" -eq 1 && "${UB_KEEP_AUTOWARE_ROS}" != "1" ]]; then
    cleanup_autoware_launch_processes "Stopping Autoware ROS launch processes. Set UB_KEEP_AUTOWARE_ROS=1 to leave them running." || true
    AUTOWARE_LAUNCH_STARTED=0
  fi

  if [[ "${SUMO_STARTED}" -eq 1 && "${UB_KEEP_SUMO}" != "1" ]]; then
    echo "Stopping SUMO bridge. Set UB_KEEP_SUMO=1 to leave it running."
    cd "${SCRIPT_DIR}"
    docker compose stop sumo-bridge >/dev/null 2>&1 || true
    docker compose rm -f sumo-bridge >/dev/null 2>&1 || true
    SUMO_STARTED=0
  fi

  if [[ "${TIME_MASTER_STARTED}" -eq 1 && "${UB_KEEP_TIME_MASTER}" != "1" ]]; then
    echo "Stopping CARLA-only time master. Set UB_KEEP_TIME_MASTER=1 to leave it running."
    cd "${SCRIPT_DIR}"
    docker compose stop time-master >/dev/null 2>&1 || true
    docker compose rm -f time-master >/dev/null 2>&1 || true
    TIME_MASTER_STARTED=0
  fi

  if [[ "${CARLA_STARTED}" -eq 1 && "${UB_KEEP_CARLA}" != "1" ]]; then
    echo "Stopping CARLA Compose stack. Set UB_KEEP_CARLA=1 to leave it running."
    cd "${SCRIPT_DIR}"
    docker compose down >/dev/null 2>&1 || true
    CARLA_STARTED=0
  fi

  exit "${exit_code}"
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
if [[ "${UB_TRAFFIC_ORCHESTRATOR}" == "sumo" ]]; then
  start_sumo_bridge
else
  start_carla_time_master
fi
start_autoware_container
build_mounted_autoware_bridge
launch_autoware
