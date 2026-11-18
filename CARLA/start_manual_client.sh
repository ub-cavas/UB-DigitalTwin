#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

export UB_EXPERIMENT_ENABLED="${UB_EXPERIMENT_ENABLED:-1}"
export UB_EXPERIMENT_CONTROLLER="${UB_EXPERIMENT_CONTROLLER:-keyboard}"
export UB_EXPERIMENT_HOST_NAME="${UB_EXPERIMENT_HOST_NAME:-$(hostname)}"
export UB_EXPERIMENT_HOST_UID="$(id -u)"
export UB_EXPERIMENT_HOST_GID="$(id -g)"
export UB_EXPERIMENT_HOST_DIR="${UB_EXPERIMENT_HOST_DIR:-${PWD}/Logs/experiments}"
mkdir -p "${UB_EXPERIMENT_HOST_DIR}"
export UB_EXPERIMENT_HOST_DIR="$(cd "${UB_EXPERIMENT_HOST_DIR}" && pwd)"

export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
  export XAUTHORITY="${HOME}/.Xauthority"
fi

if command -v xhost >/dev/null 2>&1; then
  xhost +local:root >/dev/null || true
fi

exec docker compose run --rm --no-deps manual-control
