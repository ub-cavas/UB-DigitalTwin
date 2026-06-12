#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
  export XAUTHORITY="${HOME}/.Xauthority"
fi

if command -v xhost >/dev/null 2>&1; then
  xhost +local:root >/dev/null || true
fi

exec docker compose run --rm --no-deps manual-control
