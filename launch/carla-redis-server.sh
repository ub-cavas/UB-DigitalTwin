#!/usr/bin/env bash
set -euo pipefail

LAUNCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${LAUNCH_DIR}/.." && pwd)"
source "${LAUNCH_DIR}/lib/x11.sh"

cd "${REPO_ROOT}/CARLA"

export CARLA_ARGS="${CARLA_ARGS:--RenderOffScreen -quality-level=Low -nosound}"
export UB_TRAFFIC_NO_RENDERING="${UB_TRAFFIC_NO_RENDERING:-1}"
setup_x11 silent

exec docker compose up --build carla redis map-loader traffic-publisher
