#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: launch_ub_mr_carla_client.sh [authoritative-server-ip]

Starts the MR laptop/client side of a two-machine setup:
  - local UB-MR player
  - local CARLA + Autoware
  - remote Redis traffic bridge into UB-MR only

The remote bridge subscribes to the authoritative server Redis and forwards
traffic to UB-MR over UDP. It does not mirror traffic or ego actors into the
laptop's local CARLA instance.

Examples:
  ./scripts/launch_ub_mr_carla_client.sh 192.168.1.50
  UB_REMOTE_REDIS_HOST=192.168.1.50 ./scripts/launch_ub_mr_carla_client.sh

Useful overrides:
  UB_REMOTE_REDIS_PORT=6390
  UB_REMOTE_REDIS_PASSWORD=password
  UB_REMOTE_REDIS_CHANNEL=carla:telemetry
  UB_REMOTE_UNITY_HOST=127.0.0.1
  UB_REMOTE_UNITY_PORT=12345
  UB_LOCAL_CARLA_PORT=2000
  UB_MR_BUILD_FOLDER=0.0.7
  BUILD_FOLDER=v1.0.0
EOF
}

DRY_RUN=0
SERVER_HOST=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -n "${SERVER_HOST}" ]]; then
        echo "Only one authoritative server IP/host may be provided." >&2
        usage >&2
        exit 2
      fi
      SERVER_HOST="$1"
      shift
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${SERVER_HOST}" ]]; then
  UB_REMOTE_REDIS_HOST="${SERVER_HOST}"
fi

UB_REMOTE_REDIS_HOST="${UB_REMOTE_REDIS_HOST:-}"
if [[ -z "${UB_REMOTE_REDIS_HOST}" ]]; then
  echo "Missing authoritative server IP/host." >&2
  usage >&2
  exit 2
fi

UB_REMOTE_REDIS_PORT="${UB_REMOTE_REDIS_PORT:-${UB_REDIS_PORT:-6390}}"
UB_REMOTE_REDIS_PASSWORD="${UB_REMOTE_REDIS_PASSWORD:-${UB_REDIS_PASSWORD:-password}}"
UB_REMOTE_REDIS_CHANNEL="${UB_REMOTE_REDIS_CHANNEL:-${UB_REDIS_CHANNEL:-carla:telemetry}}"
UB_REMOTE_UNITY_HOST="${UB_REMOTE_UNITY_HOST:-127.0.0.1}"
UB_REMOTE_UNITY_PORT="${UB_REMOTE_UNITY_PORT:-12345}"
UB_REMOTE_UDP_BRIDGE_CONTAINER_NAME="${UB_REMOTE_UDP_BRIDGE_CONTAINER_NAME:-ub-mr-remote-udp-bridge}"
UB_REMOTE_UDP_BRIDGE_RETRY_SECONDS="${UB_REMOTE_UDP_BRIDGE_RETRY_SECONDS:-3}"

UB_LOCAL_CARLA_HOST="${UB_LOCAL_CARLA_HOST:-127.0.0.1}"
UB_LOCAL_CARLA_PORT="${UB_LOCAL_CARLA_PORT:-${UB_CARLA_PORT:-2000}}"
UB_LOCAL_REDIS_HOST="${UB_LOCAL_REDIS_HOST:-127.0.0.1}"
UB_LOCAL_REDIS_PORT="${UB_LOCAL_REDIS_PORT:-6390}"
UB_LOCAL_REDIS_PASSWORD="${UB_LOCAL_REDIS_PASSWORD:-password}"
UB_LOCAL_REDIS_CHANNEL="${UB_LOCAL_REDIS_CHANNEL:-carla:telemetry}"
AUTOWARE_LOCAL_CARLA_HOST="${AUTOWARE_LOCAL_CARLA_HOST:-${UB_LOCAL_CARLA_HOST}}"

# launch_ub_mr.sh uses ${UB_CARLA_EXTRA_SERVICES:-udp-bridge}; a single
# whitespace value intentionally disables that default without adding a service.
UB_LOCAL_CARLA_EXTRA_SERVICES="${UB_LOCAL_CARLA_EXTRA_SERVICES:- }"

BRIDGE_STARTER_PID=""

start_remote_traffic_bridge() {
  cd "${REPO_ROOT}/CARLA"
  docker compose build udp-bridge

  while true; do
    echo "Starting remote Redis traffic bridge from ${UB_REMOTE_REDIS_HOST}:${UB_REMOTE_REDIS_PORT} to UB-MR ${UB_REMOTE_UNITY_HOST}:${UB_REMOTE_UNITY_PORT}..."
    UB_REDIS_HOST="${UB_REMOTE_REDIS_HOST}" \
    UB_REDIS_PORT="${UB_REMOTE_REDIS_PORT}" \
    UB_REDIS_PASSWORD="${UB_REMOTE_REDIS_PASSWORD}" \
    UB_REDIS_CHANNEL="${UB_REMOTE_REDIS_CHANNEL}" \
    UB_UNITY_HOST="${UB_REMOTE_UNITY_HOST}" \
    UB_UNITY_PORT="${UB_REMOTE_UNITY_PORT}" \
    UB_EGO_BRIDGE=0 \
    UB_CARLA_EGO_MIRROR=0 \
    docker compose run -T --rm --name "${UB_REMOTE_UDP_BRIDGE_CONTAINER_NAME}" --no-deps udp-bridge

    echo "Remote Redis traffic bridge exited; retrying in ${UB_REMOTE_UDP_BRIDGE_RETRY_SECONDS}s."
    sleep "${UB_REMOTE_UDP_BRIDGE_RETRY_SECONDS}"
  done
}

cleanup() {
  local exit_code="$?"

  if [[ -n "${BRIDGE_STARTER_PID}" ]]; then
    kill "${BRIDGE_STARTER_PID}" >/dev/null 2>&1 || true
    wait "${BRIDGE_STARTER_PID}" >/dev/null 2>&1 || true
    BRIDGE_STARTER_PID=""
  fi

  docker rm -f "${UB_REMOTE_UDP_BRIDGE_CONTAINER_NAME}" >/dev/null 2>&1 || true

  exit "${exit_code}"
}

print_dry_run() {
  cat <<EOF
Dry run for MR CARLA client launcher:

  local_mr_and_carla:
    UB_REDIS_HOST=${UB_LOCAL_REDIS_HOST}
    UB_REDIS_PORT=${UB_LOCAL_REDIS_PORT}
    UB_CARLA_HOST=${UB_LOCAL_CARLA_HOST}
    UB_CARLA_PORT=${UB_LOCAL_CARLA_PORT}
    AUTOWARE_CARLA_HOST=${AUTOWARE_LOCAL_CARLA_HOST}
    UB_CARLA_EXTRA_SERVICES=<empty>
    ${REPO_ROOT}/scripts/launch_ub_mr.sh --dry-run

  remote_traffic_to_ub_mr:
    cd ${REPO_ROOT}/CARLA
    UB_REDIS_HOST=${UB_REMOTE_REDIS_HOST}
    UB_REDIS_PORT=${UB_REMOTE_REDIS_PORT}
    UB_REDIS_CHANNEL=${UB_REMOTE_REDIS_CHANNEL}
    UB_UNITY_HOST=${UB_REMOTE_UNITY_HOST}
    UB_UNITY_PORT=${UB_REMOTE_UNITY_PORT}
    UB_EGO_BRIDGE=0
    UB_CARLA_EGO_MIRROR=0
    docker compose run -T --rm --name ${UB_REMOTE_UDP_BRIDGE_CONTAINER_NAME} --no-deps udp-bridge
EOF
}

if [[ "${DRY_RUN}" -eq 1 ]]; then
  print_dry_run
  echo
  UB_REDIS_HOST="${UB_LOCAL_REDIS_HOST}" \
  UB_REDIS_PORT="${UB_LOCAL_REDIS_PORT}" \
  UB_REDIS_PASSWORD="${UB_LOCAL_REDIS_PASSWORD}" \
  UB_REDIS_CHANNEL="${UB_LOCAL_REDIS_CHANNEL}" \
  UB_CARLA_HOST="${UB_LOCAL_CARLA_HOST}" \
  UB_CARLA_PORT="${UB_LOCAL_CARLA_PORT}" \
  AUTOWARE_CARLA_HOST="${AUTOWARE_LOCAL_CARLA_HOST}" \
  UB_CARLA_EXTRA_SERVICES="${UB_LOCAL_CARLA_EXTRA_SERVICES}" \
  "${REPO_ROOT}/scripts/launch_ub_mr.sh" --dry-run
  exit 0
fi

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

start_remote_traffic_bridge &
BRIDGE_STARTER_PID="$!"

UB_REDIS_HOST="${UB_LOCAL_REDIS_HOST}" \
UB_REDIS_PORT="${UB_LOCAL_REDIS_PORT}" \
UB_REDIS_PASSWORD="${UB_LOCAL_REDIS_PASSWORD}" \
UB_REDIS_CHANNEL="${UB_LOCAL_REDIS_CHANNEL}" \
UB_CARLA_HOST="${UB_LOCAL_CARLA_HOST}" \
UB_CARLA_PORT="${UB_LOCAL_CARLA_PORT}" \
AUTOWARE_CARLA_HOST="${AUTOWARE_LOCAL_CARLA_HOST}" \
UB_CARLA_EXTRA_SERVICES="${UB_LOCAL_CARLA_EXTRA_SERVICES}" \
"${REPO_ROOT}/scripts/launch_ub_mr.sh"
