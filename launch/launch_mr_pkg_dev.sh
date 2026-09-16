#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROS_ENV_SCRIPT="${REPO_ROOT}/UB-MR/Scripts/host_ros2_env.bash"
LOCALIZATION_NODE=carla_localization
USE_SIM_TIME=true
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: launch_mr_pkg_dev.sh [--physical] [--dry-run] [--help]

Run mr_pkg localization from source with ROS 2 Humble and the same local
CycloneDDS environment as launch_ub_mr_dev.sh. No colcon build is required.
The repository location is resolved from this script.

Default:     carla_localization with use_sim_time:=true (CARLA /clock).
--physical:  autoware_localization with use_sim_time:=false (system time).
             Requires python3-pyproj for the MGRS-to-local conversion.

ROS_DOMAIN_ID defaults to 0 and can be overridden in the environment.
The shared DDS configuration uses loopback for Autoware on the same host.

  --dry-run  Show the environment and command without starting anything.
  --help     Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --physical) LOCALIZATION_NODE=autoware_localization; USE_SIM_TIME=false ;;
    --dry-run) DRY_RUN=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

NODE_SCRIPT="${REPO_ROOT}/UB-MR/submodules/mr_pkg/mr_pkg/${LOCALIZATION_NODE}.py"
if [[ ! -r "${ROS_ENV_SCRIPT}" || ! -r "${NODE_SCRIPT}" ]]; then
  echo "Error: localization sources or ROS environment helper are missing. Initialize the UB-MR and mr_pkg submodules first." >&2
  exit 1
fi
if [[ ! -r /opt/ros/humble/setup.bash ]]; then
  echo "Error: ROS 2 Humble setup was not found at /opt/ros/humble/setup.bash." >&2
  exit 1
fi

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
# Use the system Python that matches ROS Humble, even in an active virtualenv.
COMMAND=(/usr/bin/python3 "${NODE_SCRIPT}" --ros-args -p "use_sim_time:=${USE_SIM_TIME}")
echo "Localization: ${LOCALIZATION_NODE} (use_sim_time:=${USE_SIM_TIME})"
echo "ROS_DOMAIN_ID: ${ROS_DOMAIN_ID}"
if [[ "${DRY_RUN}" == 1 ]]; then
  printf 'Source environment: %s\n' "${ROS_ENV_SCRIPT}"
  printf 'Command:'
  printf ' %q' "${COMMAND[@]}"
  printf '\n'
  exit 0
fi

cd "${REPO_ROOT}"
# The helper sources Humble, configures CycloneDDS and restarts ROS discovery.
# ROS setup scripts expect unset variables to be allowed.
set +u
source "${ROS_ENV_SCRIPT}"
set -u

if [[ "${LOCALIZATION_NODE}" == autoware_localization ]] &&
   ! /usr/bin/python3 -c 'from pyproj import Transformer, database; from pyproj.aoi import AreaOfInterest' 2>/dev/null; then
  echo "Error: physical localization requires pyproj for system Python. Install it with: sudo apt install python3-pyproj" >&2
  exit 1
fi

exec "${COMMAND[@]}"
