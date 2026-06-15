#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}/CARLA"

export CARLA_ARGS="${CARLA_ARGS:--RenderOffScreen -quality-level=Low -nosound}"
export UB_TRAFFIC_NO_RENDERING="${UB_TRAFFIC_NO_RENDERING:-1}"
export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
  export XAUTHORITY="${HOME}/.Xauthority"
fi

if command -v xhost >/dev/null 2>&1; then
  xhost +local:root >/dev/null || true
fi

exec docker compose up --build carla redis map-loader traffic-publisher
