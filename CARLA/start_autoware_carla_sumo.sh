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
AUTOWARE_E2E_SIMULATOR_TYPE="${AUTOWARE_E2E_SIMULATOR_TYPE:-carla}"
AUTOWARE_CARLA_POINTCLOUD_RELAY="${AUTOWARE_CARLA_POINTCLOUD_RELAY:-1}"
UB_AUTOWARE_INSTALL_PY_DEPS="${UB_AUTOWARE_INSTALL_PY_DEPS:-1}"
UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY="${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY:-0}"
UB_AUTOWARE_EGO_ONLY_PERCEPTION="${UB_AUTOWARE_EGO_ONLY_PERCEPTION:-0}"
UB_AUTOWARE_CARLA_PLANNING_PRESET="${UB_AUTOWARE_CARLA_PLANNING_PRESET:-0}"
UB_AUTOWARE_RESTORE_RUNTIME_PATCHES="${UB_AUTOWARE_RESTORE_RUNTIME_PATCHES:-1}"
UB_AUTOWARE_HOST_CONFIG_DDS="${UB_AUTOWARE_HOST_CONFIG_DDS:-1}"
UB_AUTOWARE_RMW_IMPLEMENTATION="${UB_AUTOWARE_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
UB_AUTOWARE_CYCLONEDDS_URI="${UB_AUTOWARE_CYCLONEDDS_URI:-file:///resources/cyclonedds.xml}"
UB_AUTOWARE_CLEAN_STALE_PROCESSES="${UB_AUTOWARE_CLEAN_STALE_PROCESSES:-1}"
UB_KEEP_CARLA="${UB_KEEP_CARLA:-0}"
UB_KEEP_AUTOWARE_ROS="${UB_KEEP_AUTOWARE_ROS:-0}"
UB_KEEP_SUMO="${UB_KEEP_SUMO:-0}"

UB_SUMO_CONFIG="${UB_SUMO_CONFIG:-UBAutonomousProvingGrounds.sumocfg}"
UB_SUMO_STEP_LENGTH="${UB_SUMO_STEP_LENGTH:-0.05}"
UB_SUMO_CARLA_TIMEOUT="${UB_SUMO_CARLA_TIMEOUT:-20.0}"
UB_SUMO_GUI="${UB_SUMO_GUI:-0}"
UB_SUMO_AUTO_START="${UB_SUMO_AUTO_START:-1}"
UB_SUMO_TLS_MANAGER="${UB_SUMO_TLS_MANAGER:-sumo}"
UB_SUMO_SYNC_VEHICLE_COLOR="${UB_SUMO_SYNC_VEHICLE_COLOR:-0}"
UB_SUMO_SYNC_VEHICLE_LIGHTS="${UB_SUMO_SYNC_VEHICLE_LIGHTS:-0}"
UB_SUMO_EXTRA_ARGS="${UB_SUMO_EXTRA_ARGS:-}"

DRY_RUN=0
CARLA_STARTED=0
SUMO_STARTED=0
AUTOWARE_LAUNCH_STARTED=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run] [--help]

Start single-machine UB-CARLA + SUMO + Autoware using the custom
carla-autoware-sumo-bridge. SUMO is the time master; Autoware's CARLA
interface is launched with external_tick:=True.

Defaults:
  BUILD_FOLDER=${BUILD_FOLDER}
  CARLA_MAP=${CARLA_MAP}
  CARLA_ARGS=${CARLA_ARGS}
  UB_SUMO_CONFIG=${UB_SUMO_CONFIG}
  UB_SUMO_STEP_LENGTH=${UB_SUMO_STEP_LENGTH}
  UB_SUMO_CARLA_TIMEOUT=${UB_SUMO_CARLA_TIMEOUT}
  UB_SUMO_GUI=${UB_SUMO_GUI}
  UB_SUMO_AUTO_START=${UB_SUMO_AUTO_START}
  UB_SUMO_TLS_MANAGER=${UB_SUMO_TLS_MANAGER}
  AUTOWARE_MAP_PATH=${AUTOWARE_MAP_PATH}
  AUTOWARE_SERVICE=${AUTOWARE_SERVICE}
  AUTOWARE_VEHICLE_MODEL=${AUTOWARE_VEHICLE_MODEL}
  AUTOWARE_SENSOR_MODEL=${AUTOWARE_SENSOR_MODEL}
  AUTOWARE_E2E_SIMULATOR_TYPE=${AUTOWARE_E2E_SIMULATOR_TYPE}
  AUTOWARE_CARLA_POINTCLOUD_RELAY=${AUTOWARE_CARLA_POINTCLOUD_RELAY}
  UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY=${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY}
  UB_AUTOWARE_EGO_ONLY_PERCEPTION=${UB_AUTOWARE_EGO_ONLY_PERCEPTION}
  UB_AUTOWARE_CARLA_PLANNING_PRESET=${UB_AUTOWARE_CARLA_PLANNING_PRESET}
  UB_AUTOWARE_RESTORE_RUNTIME_PATCHES=${UB_AUTOWARE_RESTORE_RUNTIME_PATCHES}

Useful overrides:
  UB_SUMO_CONFIG=Town01.sumocfg $(basename "$0")
  UB_SUMO_GUI=0 $(basename "$0")
  UB_SUMO_EXTRA_ARGS="--debug" $(basename "$0")
  AUTOWARE_RVIZ=false $(basename "$0")
  AUTOWARE_E2E_SIMULATOR_TYPE=carla $(basename "$0")
  AUTOWARE_PLANNING_MODULE_PRESET=ub_carla $(basename "$0")
  UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY=0 $(basename "$0")
  UB_AUTOWARE_EGO_ONLY_PERCEPTION=0 $(basename "$0")
  UB_AUTOWARE_CARLA_PLANNING_PRESET=0 $(basename "$0")
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

  if [[ ! -f "${BRIDGE_DIR}/Sumo/examples/${UB_SUMO_CONFIG}" ]]; then
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
  UB_SUMO_CONFIG=${UB_SUMO_CONFIG} \\
  UB_SUMO_STEP_LENGTH=${UB_SUMO_STEP_LENGTH} \\
  UB_SUMO_CARLA_TIMEOUT=${UB_SUMO_CARLA_TIMEOUT} \\
  UB_SUMO_GUI=${UB_SUMO_GUI} \\
  UB_SUMO_AUTO_START=${UB_SUMO_AUTO_START} \\
  UB_SUMO_TLS_MANAGER=${UB_SUMO_TLS_MANAGER} \\
  docker compose up --build -d sumo-bridge

  cd ${AUTOWARE_DOCKER_DIR}
  docker compose up -d ${AUTOWARE_SERVICE}
  docker compose cp ${BRIDGE_DIR}/autoware_carla_interface \\
    ${AUTOWARE_SERVICE}:/autoware/src/universe/autoware_universe/simulator/autoware_carla_interface
  docker compose exec ${AUTOWARE_SERVICE} bash -lc 'colcon build --symlink-install --packages-select autoware_carla_interface'
  docker compose exec ${AUTOWARE_SERVICE} bash -lc 'python3 ub_carla_top_lidar_relay ... & ros2 launch autoware_launch e2e_simulator.launch.xml simulator_type:=carla external_tick:=True ...'
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
  export UB_SUMO_CARLA_TIMEOUT
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

cleanup_autoware_launch_processes() {
  cd "${AUTOWARE_DOCKER_DIR}"
  if [[ -z "$(docker compose ps -q "${AUTOWARE_SERVICE}" 2>/dev/null || true)" ]]; then
    return 0
  fi

  echo "${1:-Stopping Autoware ROS launch processes.}"
  docker compose exec -T "${AUTOWARE_SERVICE}" bash -lc '
pkill -INT -f "ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml" || true
pkill -INT -f "ros2 launch autoware_launch e2e_simulator.launch.xml" || true
pkill -INT -f "[r]os2 run topic_tools relay /sensing/lidar/top/pointcloud_before_sync /sensing/lidar/concatenated/pointcloud" || true
pkill -INT -f "[t]opic_tools/relay /sensing/lidar/top/pointcloud_before_sync /sensing/lidar/concatenated/pointcloud" || true
pkill -INT -f "ub_carla_top_lidar_relay" || true
sleep 2
pkill -TERM -f "ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml" || true
pkill -TERM -f "ros2 launch autoware_launch e2e_simulator.launch.xml" || true
pkill -TERM -f "[r]os2 run topic_tools relay /sensing/lidar/top/pointcloud_before_sync /sensing/lidar/concatenated/pointcloud" || true
pkill -TERM -f "[t]opic_tools/relay /sensing/lidar/top/pointcloud_before_sync /sensing/lidar/concatenated/pointcloud" || true
pkill -TERM -f "ub_carla_top_lidar_relay" || true
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

install_custom_autoware_bridge() {
  cd "${AUTOWARE_DOCKER_DIR}"

  echo "Installing custom autoware_carla_interface into the Autoware container..."
  docker compose exec -T "${AUTOWARE_SERVICE}" bash -lc '
set -euo pipefail
mkdir -p /autoware/src/universe/autoware_universe/simulator
rm -rf /autoware/src/universe/autoware_universe/simulator/autoware_carla_interface
'
  docker compose cp "${BRIDGE_DIR}/autoware_carla_interface" "${AUTOWARE_SERVICE}:/autoware/src/universe/autoware_universe/simulator/autoware_carla_interface"

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
  local carla_launch_args=""
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
  if [[ "${AUTOWARE_E2E_SIMULATOR_TYPE}" == "carla" ]]; then
    carla_launch_args+=" \\
  host:=$(shell_quote "${AUTOWARE_CARLA_HOST}") \\
  carla_map:=$(shell_quote "${CARLA_MAP}") \\
  fixed_delta_seconds:=$(shell_quote "${UB_SUMO_STEP_LENGTH}") \\
  external_tick:=True"
  fi

launch_cmd="
set -eo pipefail
export RMW_IMPLEMENTATION=$(shell_quote "${UB_AUTOWARE_RMW_IMPLEMENTATION}")
export CYCLONEDDS_URI=$(shell_quote "${UB_AUTOWARE_CYCLONEDDS_URI}")
source /opt/ros/humble/setup.bash
source /autoware/install/setup.bash

if [[ $(shell_quote "${UB_AUTOWARE_RESTORE_RUNTIME_PATCHES}") == \"1\" ]]; then
  python3 - <<'PY'
from pathlib import Path

restore_paths = [
    Path('/autoware/install/awsim_sensor_kit_launch/share/awsim_sensor_kit_launch/launch/lidar.launch.xml'),
    Path('/autoware/install/autoware_launch/share/autoware_launch/launch/autoware.launch.xml'),
]

for path in restore_paths:
    backup = path.with_suffix(path.suffix + '.ub-original')
    if backup.exists():
        path.write_text(backup.read_text())
        print(f'Restored Autoware runtime file from UB backup: {path}')
PY
fi

if [[ $(shell_quote "${UB_AUTOWARE_CARLA_PLANNING_PRESET}") == \"1\" ]]; then
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
    target_path.write_text('\\n'.join(lines) + '\\n')
    print(
        'Prepared CARLA planning preset without traffic-light/crosswalk '
        f'behavior modules: {target_path}'
    )
PY
fi

if [[ $(shell_quote "${UB_AUTOWARE_EGO_ONLY_PERCEPTION}") == \"1\" ]]; then
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
        f'value={quote}{dollar}(var data_path){quote}/>\\n'
    )
    empty_objects_arg = (
        f'      <arg name={quote}use_empty_dynamic_object_publisher{quote} '
        f'value={quote}true{quote}/>\\n'
    )
    traffic_light_arg = (
        f'      <arg name={quote}use_traffic_light_recognition{quote} '
        f'value={quote}false{quote}/>\\n'
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

if [[ $(shell_quote "${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY}") == \"1\" ]]; then
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
fi

BRIDGE_PID=
RELAY_PID=

cleanup_bridge_processes() {
  if [[ -n \"\${BRIDGE_PID}\" ]]; then
    kill \${BRIDGE_PID} 2>/dev/null || true
  fi
  if [[ -n \"\${RELAY_PID}\" ]]; then
    kill \${RELAY_PID} 2>/dev/null || true
  fi
}
trap cleanup_bridge_processes EXIT

if [[ $(shell_quote "${AUTOWARE_E2E_SIMULATOR_TYPE}") == \"carla\" ]]; then
  echo \"Autoware e2e simulator_type:=carla will launch autoware_carla_interface with external_tick:=True.\"
else
  ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml \\
    host:=$(shell_quote "${AUTOWARE_CARLA_HOST}") \\
    carla_map:=$(shell_quote "${CARLA_MAP}") \\
    fixed_delta_seconds:=$(shell_quote "${UB_SUMO_STEP_LENGTH}") \\
    external_tick:=True &
  BRIDGE_PID=\$!

  sleep 5
  if ! kill -0 \${BRIDGE_PID} 2>/dev/null; then
    echo \"Error: autoware_carla_interface exited before Autoware launch started.\" >&2
    wait \${BRIDGE_PID} || true
    exit 1
  fi
fi

if [[ $(shell_quote "${AUTOWARE_CARLA_POINTCLOUD_RELAY}") == \"1\" ]]; then
python3 - <<'PY' &
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import PointCloud2
import tf2_ros

SOURCE_TOPIC = '/sensing/lidar/top/pointcloud_before_sync'
OUTPUT_TOPIC = '/sensing/lidar/concatenated/pointcloud'
TARGET_FRAME = 'base_link'

rclpy.init()
node = rclpy.create_node('ub_carla_top_lidar_relay')
tf_buffer = tf2_ros.Buffer()
tf_listener = tf2_ros.TransformListener(tf_buffer, node)
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
tf_ready = False
reported_waiting_for_tf = False

def relay(message):
    global tf_ready, reported_waiting_for_tf
    if not tf_ready:
        if tf_buffer.can_transform(TARGET_FRAME, message.header.frame_id, Time()):
            tf_ready = True
            node.get_logger().info(
                f'TF ready; relaying {SOURCE_TOPIC} -> {OUTPUT_TOPIC}'
            )
        else:
            if not reported_waiting_for_tf:
                reported_waiting_for_tf = True
                node.get_logger().info(
                    f'Waiting for TF {TARGET_FRAME} <- {message.header.frame_id} before relaying'
                )
            return
    publisher.publish(message)

node.create_subscription(PointCloud2, SOURCE_TOPIC, relay, source_qos)
node.get_logger().info(f'Relay armed for {SOURCE_TOPIC} -> {OUTPUT_TOPIC}')
try:
    rclpy.spin(node)
except (KeyboardInterrupt, ExternalShutdownException):
    pass
finally:
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
PY
RELAY_PID=\$!
fi

ros2 launch autoware_launch e2e_simulator.launch.xml \\
  map_path:=$(shell_quote "${AUTOWARE_MAP_PATH}") \\
  vehicle_model:=$(shell_quote "${AUTOWARE_VEHICLE_MODEL}") \\
  sensor_model:=$(shell_quote "${AUTOWARE_SENSOR_MODEL}") \\
  simulator_type:=$(shell_quote "${AUTOWARE_E2E_SIMULATOR_TYPE}")${carla_launch_args}${optional_launch_args}
"

  echo "Launching Autoware with passive CARLA ticking. Press Ctrl+C to stop the ROS launch."
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
start_sumo_bridge
start_autoware_container
install_custom_autoware_bridge
launch_autoware
