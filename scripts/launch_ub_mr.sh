#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MR_DIR="${REPO_ROOT}/UB-MR"
MR_CONTAINER_NAME="${MR_CONTAINER_NAME:-ub-mr-container}"

export BUILD_FOLDER="${BUILD_FOLDER:-v1.0.0}"
export CARLA_ARGS="${CARLA_ARGS:--prefernvidia -quality-level=Epic -nosound}"
export UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY="${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY:-1}"
export UB_AUTOWARE_EGO_ONLY_PERCEPTION="${UB_AUTOWARE_EGO_ONLY_PERCEPTION:-1}"
export UB_AUTOWARE_CARLA_PLANNING_PRESET="${UB_AUTOWARE_CARLA_PLANNING_PRESET:-1}"
export AUTOWARE_PLANNING_MODULE_PRESET="${AUTOWARE_PLANNING_MODULE_PRESET:-ub_carla}"
export UB_CARLA_EXTRA_SERVICES="${UB_CARLA_EXTRA_SERVICES:-udp-bridge}"
export UB_EGO_BRIDGE="${UB_EGO_BRIDGE:-0}"
export UB_CARLA_EGO_MIRROR="${UB_CARLA_EGO_MIRROR:-0}"

UB_MR_BUILD_FOLDER="${UB_MR_BUILD_FOLDER:-0.0.7}"
UB_MR_LOCALIZATION="${UB_MR_LOCALIZATION:-1}"
UB_KEEP_MR="${UB_KEEP_MR:-0}"

DRY_RUN=0
MR_STARTED=0
MR_LOCALIZATION_STARTED=0
MR_RUN_PID=""

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run] [--help]

Start UB-MR alongside UB-CARLA and Autoware. CARLA and UB-MR are started in
the background; Autoware's ROS launch stays in the foreground for logs and
Ctrl+C cleanup.

Defaults:
  UB_MR_BUILD_FOLDER=${UB_MR_BUILD_FOLDER}
  BUILD_FOLDER=${BUILD_FOLDER}
  CARLA_ARGS=${CARLA_ARGS}
  UB_CARLA_EXTRA_SERVICES=${UB_CARLA_EXTRA_SERVICES}
  UB_EGO_BRIDGE=${UB_EGO_BRIDGE}
  UB_CARLA_EGO_MIRROR=${UB_CARLA_EGO_MIRROR}
  UB_MR_LOCALIZATION=${UB_MR_LOCALIZATION}
  UB_KEEP_MR=${UB_KEEP_MR}

Useful overrides:
  UB_MR_BUILD_FOLDER=0.0.7 $(basename "$0")
  UB_MR_LOCALIZATION=0 $(basename "$0")
  UB_KEEP_MR=1 $(basename "$0")
  BUILD_FOLDER=v1.0.0 $(basename "$0")
  CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound" $(basename "$0")
  UB_EGO_BRIDGE=1 UB_CARLA_EGO_MIRROR=1 $(basename "$0")

Options:
  --dry-run  Validate prerequisites and print the commands without starting containers.
  --help     Show this help text.
EOF
}

has_running_container() {
  docker ps --format '{{.Names}}' | grep -qx "${MR_CONTAINER_NAME}"
}

collect_preflight_failures() {
  local failures_ref="$1"
  local -n preflight_failures="${failures_ref}"

  if ! command -v docker >/dev/null 2>&1; then
    preflight_failures+=("Docker is not installed or not on PATH.")
  fi

  if [[ ! -x "${MR_DIR}/run_ub_mr.sh" ]]; then
    preflight_failures+=("Missing executable UB-MR Docker launcher: ${MR_DIR}/run_ub_mr.sh")
  fi

  if [[ ! -f "${MR_DIR}/Builds/${UB_MR_BUILD_FOLDER}/UB-MR.x86_64" ]]; then
    preflight_failures+=("Missing UB-MR player: ${MR_DIR}/Builds/${UB_MR_BUILD_FOLDER}/UB-MR.x86_64")
  fi

  if [[ ! -x "${REPO_ROOT}/scripts/launch_autoware_carla.sh" ]]; then
    preflight_failures+=("Missing executable Autoware/CARLA launcher: ${REPO_ROOT}/scripts/launch_autoware_carla.sh")
  fi

  if [[ ! -x "${REPO_ROOT}/CARLA/start_autoware_carla.sh" ]]; then
    preflight_failures+=("Missing executable restored Autoware launcher: ${REPO_ROOT}/CARLA/start_autoware_carla.sh")
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
    return 1
  fi
}

print_dry_run() {
  cat <<EOF
Dry run passed for UB-MR launcher. The launcher would run:

  cd ${MR_DIR}
  ./run_ub_mr.sh ${UB_MR_BUILD_FOLDER} /app/ub-mr.sh

Then, if UB_MR_LOCALIZATION=1:

  docker exec -d ${MR_CONTAINER_NAME} bash -lc 'ros2 launch mr_pkg carla_localization.launch.py'

Then it would delegate to:

  BUILD_FOLDER=${BUILD_FOLDER} \\
  CARLA_ARGS=${CARLA_ARGS} \\
  UB_CARLA_EXTRA_SERVICES="${UB_CARLA_EXTRA_SERVICES}" \\
  UB_EGO_BRIDGE=${UB_EGO_BRIDGE} \\
  UB_CARLA_EGO_MIRROR=${UB_CARLA_EGO_MIRROR} \\
  ${REPO_ROOT}/scripts/launch_autoware_carla.sh --dry-run

UB-MR launch settings:
  ub_mr_build_folder=${UB_MR_BUILD_FOLDER}
  ub_mr_player=${MR_DIR}/Builds/${UB_MR_BUILD_FOLDER}/UB-MR.x86_64
  ub_mr_localization=${UB_MR_LOCALIZATION}
  ub_keep_mr=${UB_KEEP_MR}
  carla_build_folder=${BUILD_FOLDER}
  carla_extra_services=${UB_CARLA_EXTRA_SERVICES}
  ego_bridge=${UB_EGO_BRIDGE}
  carla_ego_mirror=${UB_CARLA_EGO_MIRROR}
EOF
}

wait_for_mr_container() {
  echo "Waiting for ${MR_CONTAINER_NAME} to start..."
  for _ in {1..60}; do
    if has_running_container; then
      echo "UB-MR container is running."
      return 0
    fi

    if [[ -n "${MR_RUN_PID}" ]] && ! kill -0 "${MR_RUN_PID}" >/dev/null 2>&1; then
      echo "Error: UB-MR launcher exited before the container started." >&2
      wait "${MR_RUN_PID}" || true
      return 1
    fi

    sleep 1
  done

  echo "Error: timed out waiting for ${MR_CONTAINER_NAME}." >&2
  return 1
}

start_mr() {
  if has_running_container; then
    echo "UB-MR container '${MR_CONTAINER_NAME}' is already running; reusing it."
    return 0
  fi

  echo "Starting UB-MR player build ${UB_MR_BUILD_FOLDER}..."
  (
    cd "${MR_DIR}"
    exec ./run_ub_mr.sh "${UB_MR_BUILD_FOLDER}" /app/ub-mr.sh
  ) &
  MR_RUN_PID="$!"
  MR_STARTED=1

  wait_for_mr_container
}

start_mr_localization() {
  if [[ "${UB_MR_LOCALIZATION}" != "1" ]]; then
    return 0
  fi

  echo "Starting UB-MR CARLA localization bridge."
  docker exec -d "${MR_CONTAINER_NAME}" bash -lc '
set -eo pipefail
source /app/ub-mr-env.sh
ROS_ENV_SCRIPT="${UB_MR_ROS_ENV_SCRIPT:-/app/Scripts/host_ros2_env.bash}"
if [[ -f "${ROS_ENV_SCRIPT}" ]]; then
  source "${ROS_ENV_SCRIPT}"
fi
exec ros2 launch mr_pkg carla_localization.launch.py
'
  MR_LOCALIZATION_STARTED=1
}

stop_mr_localization() {
  if [[ "${MR_LOCALIZATION_STARTED}" -ne 1 ]]; then
    return 0
  fi

  if has_running_container; then
    echo "Stopping UB-MR localization bridge."
    docker exec "${MR_CONTAINER_NAME}" bash -lc '
pkill -INT -f "ros2 launch mr_pkg carla_localization.launch.py" || true
sleep 1
pkill -TERM -f "ros2 launch mr_pkg carla_localization.launch.py" || true
pkill -TERM -f "mr_pkg.*carla_localization" || true
' >/dev/null 2>&1 || true
  fi
  MR_LOCALIZATION_STARTED=0
}

cleanup() {
  local exit_code="$?"

  if [[ "${UB_KEEP_MR}" != "1" ]]; then
    stop_mr_localization

    if [[ "${MR_STARTED}" -eq 1 ]]; then
      echo "Stopping UB-MR container. Set UB_KEEP_MR=1 to leave it running."
      docker rm -f "${MR_CONTAINER_NAME}" >/dev/null 2>&1 || true
      MR_STARTED=0
    fi
  fi

  if [[ -n "${MR_RUN_PID}" && "${UB_KEEP_MR}" != "1" ]] && ! wait "${MR_RUN_PID}" >/dev/null 2>&1; then
    true
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
  echo
  echo "Delegated Autoware/CARLA dry run:"
  exec "${REPO_ROOT}/scripts/launch_autoware_carla.sh" --dry-run
fi

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

start_mr
start_mr_localization

"${REPO_ROOT}/scripts/launch_autoware_carla.sh"
