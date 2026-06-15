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
UB_AUTOWARE_INSTALL_PY_DEPS="${UB_AUTOWARE_INSTALL_PY_DEPS:-1}"
UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY="${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY:-1}"
UB_KEEP_CARLA="${UB_KEEP_CARLA:-0}"

DRY_RUN=0
CARLA_STARTED=0

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
  UB_AUTOWARE_INSTALL_PY_DEPS=${UB_AUTOWARE_INSTALL_PY_DEPS}
  UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY=${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY}

Useful overrides:
  BUILD_FOLDER=v1.0.0 $(basename "$0")
  CARLA_ARGS="-prefernvidia -quality-level=Epic" $(basename "$0")
  AUTOWARE_SERVICE=<compose-service> $(basename "$0")
  AUTOWARE_CARLA_HOST=<host-ip> $(basename "$0")
  UB_AUTOWARE_INSTALL_PY_DEPS=0 $(basename "$0")
  UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY=0 $(basename "$0")
  UB_KEEP_CARLA=1 $(basename "$0")

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

  If Autoware uses a different Docker Compose service name:
    AUTOWARE_SERVICE=<service-name> CARLA/start_autoware_carla.sh
EOF
}

collect_preflight_failures() {
  local failures_ref="$1"
  local -n preflight_failures="${failures_ref}"

  if ! command -v docker >/dev/null 2>&1; then
    preflight_failures+=("Docker is not installed or not on PATH.")
  elif ! docker compose version >/dev/null 2>&1; then
    preflight_failures+=("Docker Compose v2 is unavailable. Install the Docker Compose plugin so 'docker compose' works.")
  fi

  if [[ ! -x "${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/CarlaUE4.sh" ]]; then
    preflight_failures+=("Missing executable CARLA build: ${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/CarlaUE4.sh")
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

  cd ${SCRIPT_DIR}
  BUILD_FOLDER=${BUILD_FOLDER} \\
  CARLA_MAP_PATH=${CARLA_MAP_PATH} \\
  CARLA_ARGS=${CARLA_ARGS} \\
  docker compose up --build -d carla redis map-loader

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
  install_python_deps:=${UB_AUTOWARE_INSTALL_PY_DEPS}
  carla_top_lidar_only:=${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY}
EOF
}

cleanup() {
  local exit_code="$?"

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
    xhost +local:root >/dev/null || echo "Warning: xhost did not grant local root X11 access. CARLA may fail to render." >&2
  fi

  echo "Starting rendered CARLA Compose stack..."
  CARLA_STARTED=1
  docker compose up --build -d carla redis map-loader
  wait_for_map_loader
}

shell_quote() {
  printf "%q" "$1"
}

launch_autoware() {
  local launch_cmd
  local exec_args=(exec)

  cd "${AUTOWARE_DOCKER_DIR}"

  echo "Starting Autoware Compose service: ${AUTOWARE_SERVICE}"
  docker compose up -d "${AUTOWARE_SERVICE}"

  if [[ ! -t 0 ]]; then
    exec_args+=(-T)
  fi

  launch_cmd="
set -eo pipefail
if [[ -f /opt/ros/humble/setup.bash ]]; then
  source /opt/ros/humble/setup.bash
fi
if [[ -f /autoware/install/setup.bash ]]; then
  source /autoware/install/setup.bash
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
if [[ $(shell_quote "${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY}") == 1 ]]; then
  AUTOWARE_SENSOR_MODEL_FOR_CARLA=$(shell_quote "${AUTOWARE_SENSOR_MODEL}") python3 - <<'PY'
import os
from pathlib import Path

sensor_model = os.environ['AUTOWARE_SENSOR_MODEL_FOR_CARLA']
config_path = Path(
    f'/autoware/install/{sensor_model}_launch/share/'
    f'{sensor_model}_launch/config/concatenate_and_time_sync_node.param.yaml'
)

if not config_path.exists():
    print(f'Warning: CARLA top-LiDAR override skipped; missing {config_path}')
else:
    backup_path = config_path.with_suffix(config_path.suffix + '.ub-original')
    if not backup_path.exists():
        backup_path.write_text(config_path.read_text())
    config_path.write_text(
        '''/**:
  ros__parameters:
    debug_mode: false
    has_static_tf_only: false
    rosbag_length: 10.0
    maximum_queue_size: 5
    timeout_sec: 0.2
    is_motion_compensated: false
    publish_synchronized_pointcloud: true
    keep_input_frame_in_synchronized_pointcloud: true
    publish_previous_but_late_pointcloud: false
    synchronized_pointcloud_postfix: pointcloud
    input_twist_topic_type: twist
    # The installed Autoware synchronizer requires at least two inputs.
    # CARLA currently spawns one LiDAR, so feed the same top cloud twice.
    input_topics: [
                    "/sensing/lidar/top/pointcloud_before_sync",
                    "/sensing/lidar/top/pointcloud_before_sync",
                ]
    output_frame: base_link
    matching_strategy:
      type: advanced
      lidar_timestamp_offsets: [0.0, 0.0]
      lidar_timestamp_noise_window: [0.02, 0.02]
'''
    )
    print(f'Applied CARLA top-LiDAR Autoware override: {config_path}')
PY
fi
ros2 launch autoware_launch e2e_simulator.launch.xml \\
  map_path:=$(shell_quote "${AUTOWARE_MAP_PATH}") \\
  vehicle_model:=$(shell_quote "${AUTOWARE_VEHICLE_MODEL}") \\
  sensor_model:=$(shell_quote "${AUTOWARE_SENSOR_MODEL}") \\
  simulator_type:=carla \\
  host:=$(shell_quote "${AUTOWARE_CARLA_HOST}") \\
  carla_map:=$(shell_quote "${CARLA_MAP}")
"

  echo "Launching Autoware. Press Ctrl+C to stop the ROS launch."
  docker compose "${exec_args[@]}" "${AUTOWARE_SERVICE}" bash -lc "${launch_cmd}"
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

start_carla
launch_autoware
