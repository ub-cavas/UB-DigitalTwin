#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ $# -gt 0 ]]; then
  export UB_REDIS_HOST="$1"
  export UB_MANUAL_CARLA_HOST="$1"
fi

export UB_REDIS_HOST="${UB_REDIS_HOST:-127.0.0.1}"
export UB_MANUAL_ROLE_NAME="${UB_MANUAL_ROLE_NAME:-manual_vehicle}"
export UB_MANUAL_CARLA_HOST="${UB_MANUAL_CARLA_HOST:-${UB_REDIS_HOST}}"
export UB_MANUAL_CARLA_PORT="${UB_MANUAL_CARLA_PORT:-2000}"
export UB_RENDER_CARLA_HOST="${UB_RENDER_CARLA_HOST:-127.0.0.1}"
export UB_RENDER_CARLA_PORT="${UB_RENDER_CARLA_PORT:-2100}"
export UB_RENDER_FOLLOW_ROLE_NAME="${UB_RENDER_FOLLOW_ROLE_NAME:-${UB_MANUAL_ROLE_NAME}}"
export UB_RENDER_FOLLOW_SPECTATOR="${UB_RENDER_FOLLOW_SPECTATOR:-1}"
export UB_CARLA_HOST="${UB_CARLA_HOST:-127.0.0.1}"
export UB_CARLA_PORT="${UB_CARLA_PORT:-${UB_RENDER_CARLA_PORT}}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ub-carla-client}"
export CONTAINER_NAME="${CONTAINER_NAME:-ub-carla-client-container}"
export MANUAL_CONTROL_CONTAINER_NAME="${MANUAL_CONTROL_CONTAINER_NAME:-ub-carla-client-manual-control}"
export TRAFFIC_RENDERER_CONTAINER_NAME="${TRAFFIC_RENDERER_CONTAINER_NAME:-ub-carla-client-traffic-renderer}"

if [[ -z "${CARLA_ARGS:-}" ]]; then
  export CARLA_ARGS="-quality-level=Low -nosound -carla-rpc-port=${UB_RENDER_CARLA_PORT}"
fi
export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
  export XAUTHORITY="${HOME}/.Xauthority"
fi

if command -v xhost >/dev/null 2>&1; then
  xhost +local:root >/dev/null || true
fi

exec docker compose up --build carla map-loader traffic-renderer manual-control
