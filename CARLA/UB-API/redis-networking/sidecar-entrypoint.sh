#!/usr/bin/env bash
set -euo pipefail

ROLE="${UB_REDIS_ROLE:-none}"
CARLA_PYTHON_TARGET="${CARLA_PYTHON_TARGET:-/tmp/ub-carla-python}"

install_carla_python() {
  local carla_wheel
  carla_wheel="$(find /carla/PythonAPI/carla/dist -maxdepth 1 -type f -name 'carla-*-cp310-*.whl' 2>/dev/null | head -n 1 || true)"

  if [[ -z "${carla_wheel}" ]]; then
    echo "Error: CARLA Python wheel not found under /carla/PythonAPI/carla/dist." >&2
    echo "Mount a packaged CARLA build at /carla when running Redis networking roles." >&2
    exit 1
  fi

  if [[ ! -d "${CARLA_PYTHON_TARGET}/carla" ]]; then
    python3 -m pip install --no-index --target "${CARLA_PYTHON_TARGET}" "${carla_wheel}" >/dev/null
  fi

  export PYTHONPATH="${CARLA_PYTHON_TARGET}${PYTHONPATH:+:${PYTHONPATH}}"
}

case "${ROLE}" in
  none)
    echo "UB_REDIS_ROLE=none; no Redis networking client started."
    exit 0
    ;;
  traffic-publisher)
    install_carla_python
    TRAFFIC_ARGS=(
      --host "${UB_CARLA_HOST:-127.0.0.1}"
      --port "${UB_CARLA_PORT:-2000}"
      --tm-port "${UB_TRAFFIC_MANAGER_PORT:-8001}"
    )

    ASYNC_REQUESTED=0
    for arg in "$@"; do
      if [[ "${arg}" == "--asynch" || "${arg}" == "--async" ]]; then
        ASYNC_REQUESTED=1
        break
      fi
    done

    case "${UB_CARLA_ASYNC:-1}" in
      0|false|False|FALSE|no|No|NO)
        ;;
      *)
        if [[ "${ASYNC_REQUESTED}" -eq 0 ]]; then
          TRAFFIC_ARGS+=(--asynch)
        fi
        ;;
    esac

    case "${UB_TRAFFIC_NO_RENDERING:-0}" in
      1|true|True|TRUE|yes|Yes|YES)
        TRAFFIC_ARGS+=(--no-rendering)
        ;;
    esac

    exec python3 generate_traffic_modified.py "${TRAFFIC_ARGS[@]}" "$@"
    ;;
  traffic-renderer)
    install_carla_python
    exec python3 multi_traffic_renderer.py "$@"
    ;;
  camera-follow)
    install_carla_python
    export PYTHONPATH="/opt/ub-carla-util${PYTHONPATH:+:${PYTHONPATH}}"
    exec python3 -u /opt/ub-carla-util/camera_follow_sync.py \
      --host "${UB_CAMERA_FOLLOW_HOST:-127.0.0.1}" \
      --port "${UB_CAMERA_FOLLOW_PORT:-2000}" \
      --role-names "${UB_CAMERA_FOLLOW_ROLE_NAMES:-ego_vehicle,hero,actor,autopilot}" \
      --wait-seconds "${UB_CAMERA_FOLLOW_WAIT_SECONDS:-0}" \
      --distance "${UB_CAMERA_FOLLOW_DISTANCE_M:-8.0}" \
      --height "${UB_CAMERA_FOLLOW_HEIGHT_M:-3.0}" \
      --pitch "${UB_CAMERA_FOLLOW_PITCH_DEG:--12.0}" \
      --update-hz "${UB_CAMERA_FOLLOW_UPDATE_HZ:-30.0}"
    ;;
  multi-agent-renderer)
    install_carla_python
    exec python3 multi_agent_renderer.py "$@"
    ;;
  udp-bridge)
    install_carla_python
    exec python3 traffic_bridge.py "$@"
    ;;
  manual-control)
    install_carla_python
    exec python3 manual_control.py "$@"
    ;;
  *)
    echo "Error: unsupported UB_REDIS_ROLE='${ROLE}'." >&2
    echo "Supported roles: none, traffic-publisher, traffic-renderer, camera-follow, multi-agent-renderer, udp-bridge, manual-control" >&2
    exit 2
    ;;
esac
