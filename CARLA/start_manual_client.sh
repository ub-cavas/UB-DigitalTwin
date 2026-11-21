#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: start_manual_client.sh [--log-network|--no-log-network]
                              [--log-dir DIRECTORY] [--network-interface IFACE]

Starts manual control against an already running CARLA world.
Uses UB-MR's shared network recorder, CSV schema, summaries and plots.
Recording defaults to UB_EXPERIMENT_ENABLED, or enabled if unset.
--log-dir selects the host output parent (default: Client-Logs/manual-control/experiments).
--network-interface selects host-wide byte counters: interface name, auto, or none.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --log-network) export UB_EXPERIMENT_ENABLED=1; shift ;;
    --no-log-network) export UB_EXPERIMENT_ENABLED=0; shift ;;
    --log-dir|--network-interface)
      if [[ $# -lt 2 || -z "$2" || "$2" == -* ]]; then
        echo "Error: $1 requires a value." >&2
        exit 2
      fi
      if [[ "$1" == --log-dir ]]; then
        if [[ "$2" == /* ]]; then
          export UB_EXPERIMENT_HOST_DIR="$2"
        else
          export UB_EXPERIMENT_HOST_DIR="${PWD}/$2"
        fi
      else
        export UB_EXPERIMENT_INTERFACE="$2"
      fi
      shift 2
      ;;
    *) usage >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}/CARLA"

export UB_EXPERIMENT_ENABLED="${UB_EXPERIMENT_ENABLED:-1}"
export UB_MANUAL_CLIENT_ID="${UB_MANUAL_CLIENT_ID:-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')}"
export UB_MANUAL_ROLE_NAME="${UB_MANUAL_ROLE_NAME:-manual_vehicle:${UB_MANUAL_CLIENT_ID}}"
export UB_MANUAL_ACTOR_REDIS_KEY="${UB_MANUAL_ACTOR_REDIS_KEY:-carla:manual_control:actor:${UB_MANUAL_CLIENT_ID}}"
export UB_RENDER_MANUAL_ACTOR_REDIS_KEY="${UB_RENDER_MANUAL_ACTOR_REDIS_KEY:-${UB_MANUAL_ACTOR_REDIS_KEY}}"
export UB_EXPERIMENT_CONTROLLER="${UB_EXPERIMENT_CONTROLLER:-keyboard}"
export UB_EXPERIMENT_HOST_NAME="${UB_EXPERIMENT_HOST_NAME:-$(hostname)}"
export UB_EXPERIMENT_HOST_UID="$(id -u)"
export UB_EXPERIMENT_HOST_GID="$(id -g)"
export UB_CLIENT_LOG_ROOT="${UB_CLIENT_LOG_ROOT:-${REPO_ROOT}/Client-Logs}"
export UB_CLIENT_LOG_HOST_DIR="${UB_CLIENT_LOG_HOST_DIR:-${UB_CLIENT_LOG_ROOT}/manual-control}"
export UB_EXPERIMENT_HOST_DIR="${UB_EXPERIMENT_HOST_DIR:-${UB_CLIENT_LOG_HOST_DIR}/experiments}"
mkdir -p "${UB_CLIENT_LOG_HOST_DIR}"
mkdir -p "${UB_EXPERIMENT_HOST_DIR}"
export UB_EXPERIMENT_HOST_DIR="$(cd "${UB_EXPERIMENT_HOST_DIR}" && pwd)"

export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
  export XAUTHORITY="${HOME}/.Xauthority"
fi

if command -v xhost >/dev/null 2>&1; then
  xhost +local:root >/dev/null || true
fi

docker compose run --build --rm --no-deps manual-control 2>&1 \
  | tee -a "${UB_CLIENT_LOG_HOST_DIR}/manual-control.log"
