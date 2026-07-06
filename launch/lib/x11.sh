#!/usr/bin/env bash
# X11/XAUTHORITY resolution + xhost grant, shared by every scenario that
# renders a CARLA/SUMO GUI on the host display.

resolve_xauthority() {
  export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
  if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
    export XAUTHORITY="${HOME}/.Xauthority"
  fi
}

# $1: "silent" to ignore a failed xhost grant, or a warning message to print
# to stderr on failure (defaults to a generic warning).
setup_x11() {
  local on_failure="${1:-}"

  resolve_xauthority

  if command -v xhost >/dev/null 2>&1; then
    if [[ "${on_failure}" == "silent" ]]; then
      xhost +local:root >/dev/null || true
    else
      xhost +local:root >/dev/null || echo "Warning: ${on_failure:-xhost did not grant local root X11 access.}" >&2
    fi
  fi
}
