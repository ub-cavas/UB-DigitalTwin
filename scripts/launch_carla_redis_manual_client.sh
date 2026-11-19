#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: launch_carla_redis_manual_client.sh [logging-options] [authoritative-server-ip]
       launch_carla_redis_manual_client.sh [logging-options] --iap <redis-password>

Starts a local rendered CARLA client, mirrors server traffic and UB-MR egos
from an existing authoritative Redis/CARLA server, and starts manual control.
If an IP is provided, it is used for both UB_REDIS_HOST and
UB_MANUAL_CARLA_HOST.

With --iap, opens a GCP/IAP SSH tunnel before starting the client and closes
it when the client exits. The password is for Redis; gcloud handles SSH login.
Requires an authenticated gcloud CLI and OpenSSH on the client machine.

Logging options (same recorder and plots as UB-MR):
  --log-network                Enable network statistics and control timings.
  --no-log-network             Disable recording, overriding the environment.
  --log-dir DIRECTORY          Host output parent (default: Client-Logs/manual-control/experiments).
  --network-interface IFACE    Host byte counters: interface name, auto, or none.
Recording defaults to UB_EXPERIMENT_ENABLED, or enabled if unset.
Interface counters include other host processes and transport overhead.

IAP defaults (override with environment variables):
  UB_IAP_INSTANCE          carla
  UB_IAP_PROJECT           buf-prj-digitaltwin-svxz
  UB_IAP_ZONE              us-central1-a
  UB_IAP_REDIS_HOST        127.0.0.1 (Redis bind address on the VM)
  UB_IAP_REDIS_PORT        6390
  UB_IAP_CARLA_HOST        127.0.0.1
  UB_IAP_CARLA_PORT        2000
  UB_IAP_CARLA_STREAMING_PORT  2001 (same local and remote port)
  UB_REDIS_PORT            16390 (local forwarded port in IAP mode)
  UB_MANUAL_CARLA_PORT     12000 (local forwarded port in IAP mode)

Examples:
  ./scripts/launch_carla_redis_manual_client.sh --iap 'your-shared-password'
  ./scripts/launch_carla_redis_manual_client.sh 192.168.1.50
  UB_REDIS_HOST=192.168.1.50 UB_MANUAL_CARLA_HOST=192.168.1.50 ./scripts/launch_carla_redis_manual_client.sh
EOF
}

USE_IAP=0
SERVER_HOST=""
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
    --iap)
      if [[ $# -lt 2 || -z "$2" || "${USE_IAP}" == 1 ]]; then
        echo "Error: --iap requires one nonempty Redis password argument." >&2
        exit 2
      fi
      USE_IAP=1
      export UB_REDIS_PASSWORD="$2"
      shift 2
      ;;
    -*) usage >&2; exit 2 ;;
    *)
      if [[ -n "${SERVER_HOST}" ]]; then
        usage >&2
        exit 2
      fi
      SERVER_HOST="$1"
      shift
      ;;
  esac
done

if [[ "${USE_IAP}" == 1 ]]; then
  if [[ -n "${SERVER_HOST}" ]]; then
    echo "Error: use either --iap or an authoritative server IP." >&2
    exit 2
  fi
  export UB_REDIS_HOST=127.0.0.1
  export UB_REDIS_PORT="${UB_REDIS_PORT:-16390}"
  export UB_MANUAL_CARLA_HOST=127.0.0.1
  export UB_MANUAL_CARLA_PORT="${UB_MANUAL_CARLA_PORT:-12000}"
  # The CARLA endpoint is loopback, but IAP carries WAN traffic over HTTPS.
  # Route interface counters toward gcloud's IAP gateway instead of localhost.
  export UB_EXPERIMENT_NETWORK_HOST="${UB_EXPERIMENT_NETWORK_HOST:-tunnel.cloudproxy.app}"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${REPO_ROOT}/launch/lib/iap_tunnel.sh"
cd "${REPO_ROOT}/CARLA"

export UB_EXPERIMENT_ENABLED="${UB_EXPERIMENT_ENABLED:-1}"
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

if [[ -n "${SERVER_HOST}" ]]; then
  export UB_REDIS_HOST="${SERVER_HOST}"
  export UB_MANUAL_CARLA_HOST="${SERVER_HOST}"
fi

export UB_REDIS_HOST="${UB_REDIS_HOST:-127.0.0.1}"
export UB_MANUAL_ROLE_NAME="${UB_MANUAL_ROLE_NAME:-manual_vehicle}"
export UB_MANUAL_CARLA_HOST="${UB_MANUAL_CARLA_HOST:-${UB_REDIS_HOST}}"
export UB_MANUAL_CARLA_PORT="${UB_MANUAL_CARLA_PORT:-2000}"
export UB_RENDER_CARLA_HOST="${UB_RENDER_CARLA_HOST:-127.0.0.1}"
export UB_RENDER_CARLA_PORT="${UB_RENDER_CARLA_PORT:-2100}"
export UB_RENDER_FOLLOW_ROLE_NAME="${UB_RENDER_FOLLOW_ROLE_NAME:-${UB_MANUAL_ROLE_NAME}}"
export UB_RENDER_FOLLOW_SPECTATOR="${UB_RENDER_FOLLOW_SPECTATOR:-1}"
# Driving needs a responsive view. Interpolation still absorbs WAN jitter;
# avoid layering the slow spectator camera filters on top of it.
export UB_RENDER_INTERPOLATION_DELAY_MS="${UB_RENDER_INTERPOLATION_DELAY_MS:-75}"
export UB_RENDER_ACTOR_SMOOTHING="${UB_RENDER_ACTOR_SMOOTHING:-0.70}"
export UB_RENDER_CAMERA_SMOOTHING="${UB_RENDER_CAMERA_SMOOTHING:-0.75}"
export UB_RENDER_CAMERA_TARGET_SMOOTHING="${UB_RENDER_CAMERA_TARGET_SMOOTHING:-1.0}"
export UB_RENDER_CAMERA_YAW_SMOOTHING="${UB_RENDER_CAMERA_YAW_SMOOTHING:-0.35}"
export UB_RENDER_CAMERA_HIGH_SPEED_DAMPING="${UB_RENDER_CAMERA_HIGH_SPEED_DAMPING:-0}"
export UB_RENDER_CAMERA_POSITION_DEADBAND_M="${UB_RENDER_CAMERA_POSITION_DEADBAND_M:-0}"
export UB_RENDER_CAMERA_YAW_DEADBAND_DEG="${UB_RENDER_CAMERA_YAW_DEADBAND_DEG:-0}"
export UB_CARLA_HOST="${UB_CARLA_HOST:-127.0.0.1}"
export UB_CARLA_PORT="${UB_CARLA_PORT:-${UB_RENDER_CARLA_PORT}}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ub-carla-client}"
export CONTAINER_NAME="${CONTAINER_NAME:-ub-carla-client-container}"
export MANUAL_CONTROL_CONTAINER_NAME="${MANUAL_CONTROL_CONTAINER_NAME:-ub-carla-client-manual-control}"
export TRAFFIC_RENDERER_CONTAINER_NAME="${TRAFFIC_RENDERER_CONTAINER_NAME:-ub-carla-client-traffic-renderer}"

if [[ -z "${CARLA_ARGS:-}" ]]; then
  export CARLA_ARGS="-quality-level=Low -nosound -carla-rpc-port=${UB_RENDER_CARLA_PORT}"
fi

if [[ "${USE_IAP}" == "1" ]]; then
  trap ub_iap_cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  ub_iap_start manual "${UB_REDIS_PORT}" "${UB_MANUAL_CARLA_PORT}"
fi

export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
  export XAUTHORITY="${HOME}/.Xauthority"
fi

if command -v xhost >/dev/null 2>&1; then
  xhost +local:root >/dev/null || true
fi

# Keep the shell alive for tunnel cleanup, and preserve client diagnostics.
# pipefail retains Docker's exit status if startup or manual control fails.
docker compose up --build carla map-loader traffic-renderer manual-control 2>&1 \
  | tee -a "${UB_CLIENT_LOG_HOST_DIR}/manual-control.log"
