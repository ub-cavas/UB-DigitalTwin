#!/usr/bin/env bash
set -euo pipefail

SUMO_ROOT="${UB_SUMO_ROOT:-/opt/carla-autoware-sumo-bridge/Sumo}"
SUMO_CONFIG="${UB_SUMO_CONFIG:-UBAutonomousProvingGrounds.sumocfg}"
SUMO_CFG_PATH="${SUMO_ROOT}/examples/${SUMO_CONFIG}"
CARLA_PYTHON_TARGET="${CARLA_PYTHON_TARGET:-/tmp/ub-carla-python}"

if [[ ! -f "${SUMO_CFG_PATH}" ]]; then
  echo "Error: SUMO config not found: ${SUMO_CFG_PATH}" >&2
  echo "Set UB_SUMO_CONFIG to a file under ${SUMO_ROOT}/examples." >&2
  exit 1
fi

if [[ -z "${SUMO_HOME:-}" ]]; then
  echo "Error: SUMO_HOME is not set." >&2
  exit 1
fi

if [[ ! -d "${SUMO_HOME}/tools" ]]; then
  echo "Error: SUMO tools directory not found at ${SUMO_HOME}/tools." >&2
  exit 1
fi

CARLA_WHEEL="$(find /carla/PythonAPI/carla/dist -maxdepth 1 -type f -name 'carla-*-cp310-*.whl' 2>/dev/null | head -n 1 || true)"
if [[ -z "${CARLA_WHEEL}" ]]; then
  echo "Error: CARLA Python wheel not found under /carla/PythonAPI/carla/dist." >&2
  exit 1
fi

if [[ ! -d "${CARLA_PYTHON_TARGET}/carla" ]]; then
  python3 -m pip install --no-index --target "${CARLA_PYTHON_TARGET}" "${CARLA_WHEEL}" >/dev/null
fi

export PYTHONPATH="${CARLA_PYTHON_TARGET}:${SUMO_ROOT}:${SUMO_HOME}/tools${PYTHONPATH:+:${PYTHONPATH}}"

ARGS=(
  "${SUMO_CFG_PATH}"
  --carla-host "${UB_CARLA_HOST:-127.0.0.1}"
  --carla-port "${UB_CARLA_PORT:-2000}"
  --step-length "${UB_SUMO_STEP_LENGTH:-0.05}"
  --tls-manager "${UB_SUMO_TLS_MANAGER:-sumo}"
)

case "${UB_SUMO_GUI:-1}" in
  1|true|True|TRUE|yes|Yes|YES)
    ARGS+=(--sumo-gui)
    case "${UB_SUMO_AUTO_START:-1}" in
      1|true|True|TRUE|yes|Yes|YES)
        ARGS+=(--sumo-auto-start)
        ;;
    esac
    ;;
esac

case "${UB_SUMO_SYNC_VEHICLE_COLOR:-0}" in
  1|true|True|TRUE|yes|Yes|YES)
    ARGS+=(--sync-vehicle-color)
    ;;
esac

case "${UB_SUMO_SYNC_VEHICLE_LIGHTS:-0}" in
  1|true|True|TRUE|yes|Yes|YES)
    ARGS+=(--sync-vehicle-lights)
    ;;
esac

if [[ -n "${UB_SUMO_EXTRA_ARGS:-}" ]]; then
  read -r -a EXTRA_ARGS <<< "${UB_SUMO_EXTRA_ARGS}"
  ARGS+=("${EXTRA_ARGS[@]}")
fi

echo "Starting CARLA-SUMO synchronization:"
printf '  %q' python3 "${SUMO_ROOT}/run_synchronization.py" "${ARGS[@]}"
echo

exec python3 -u "${SUMO_ROOT}/run_synchronization.py" "${ARGS[@]}"
