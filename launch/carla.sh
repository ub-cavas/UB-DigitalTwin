#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}/CARLA"

export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
export CARLA_ARGS="${CARLA_ARGS:--RenderOffScreen -quality-level=Low -nosound}"
export CARLA_MAP_PATH="${CARLA_MAP_PATH-/Game/Carla/Maps/UBAutonomousProvingGrounds}"
xhost +local:root

exec docker compose up --build carla map-loader
