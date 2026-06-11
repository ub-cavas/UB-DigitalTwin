#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-ub-carla-container}"
REDIS_CONTAINER_NAME="${REDIS_CONTAINER_NAME:-ub-carla-redis}"
REDIS_CLIENT_CONTAINER_NAME="${REDIS_CLIENT_CONTAINER_NAME:-ub-carla-redis-client}"
UB_REDIS_ROLE="${UB_REDIS_ROLE:-none}"
UB_REDIS_HOST="${UB_REDIS_HOST:-127.0.0.1}"
UB_REDIS_PORT="${UB_REDIS_PORT:-6390}"
UB_REDIS_PASSWORD="${UB_REDIS_PASSWORD:-password}"
UB_REDIS_CHANNEL="${UB_REDIS_CHANNEL:-carla:telemetry}"
UB_CARLA_HOST="${UB_CARLA_HOST:-127.0.0.1}"
UB_CARLA_PORT="${UB_CARLA_PORT:-2000}"
UB_CARLA_ASYNC="${UB_CARLA_ASYNC:-1}"
UB_UNITY_HOST="${UB_UNITY_HOST:-127.0.0.1}"
UB_UNITY_PORT="${UB_UNITY_PORT:-12345}"
REDIS_IMAGE="${REDIS_IMAGE:-redis:7-alpine}"
REDIS_CLIENT_IMAGE="${REDIS_CLIENT_IMAGE:-ub-carla-redis-networking}"
LOG_PID=""
REDIS_CLIENT_LOG_PID=""
REDIS_SIDECAR_STARTED=0
REDIS_CLIENT_SIDECAR_STARTED=0

if docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  echo "Container '${CONTAINER_NAME}' is already running. Exiting!"
  exit 0
fi

if [[ "${UB_REDIS_ROLE}" != "none" ]]; then
  if docker ps --format '{{.Names}}' | grep -qx "${REDIS_CONTAINER_NAME}"; then
    echo "Container '${REDIS_CONTAINER_NAME}' is already running. Exiting!"
    exit 0
  fi

  if docker ps --format '{{.Names}}' | grep -qx "${REDIS_CLIENT_CONTAINER_NAME}"; then
    echo "Container '${REDIS_CLIENT_CONTAINER_NAME}' is already running. Exiting!"
    exit 0
  fi
fi

cleanup() {
  if [[ -n "${LOG_PID}" ]]; then
    kill "${LOG_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${REDIS_CLIENT_LOG_PID}" ]]; then
    kill "${REDIS_CLIENT_LOG_PID}" >/dev/null 2>&1 || true
  fi
  if [[ "${REDIS_CLIENT_SIDECAR_STARTED}" -eq 1 ]]; then
    docker rm -f "${REDIS_CLIENT_CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi
  if [[ "${REDIS_SIDECAR_STARTED}" -eq 1 ]]; then
    docker rm -f "${REDIS_CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}

terminate() {
  cleanup
  exit 143
}

trap cleanup EXIT
trap terminate INT TERM

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_FOLDER="${1:-v1.0.0}"
CARLA_MAP_PATH="${CARLA_MAP_PATH-/Game/Carla/Maps/UBAutonomousProvingGrounds}"
CARLA_MAP_NAME="${CARLA_MAP_PATH##*/}"

if [[ $# -gt 0 ]]; then
  shift
fi

CARLA_ARGS=()

for arg in "$@"; do
  if [[ "${arg}" == /Game/Carla/Maps/* ]]; then
    CARLA_MAP_NAME="${arg##*/}"
    continue
  fi
  CARLA_ARGS+=("${arg}")
done

if [[ ${#CARLA_ARGS[@]} -eq 0 ]]; then
  CARLA_ARGS=(-prefernvidia -quality-level=Low -nosound)
fi

HOST_BUILD_DIR="${SCRIPT_DIR}/Builds/${BUILD_FOLDER}"
CARLA_PYTHON_TARGET="${CARLA_PYTHON_TARGET:-/tmp/ub-carla-python-${BUILD_FOLDER}}"
REDIS_CLIENT_CARLA_PYTHON_TARGET="${REDIS_CLIENT_CARLA_PYTHON_TARGET:-/tmp/ub-carla-python-${BUILD_FOLDER}}"

if [[ ! -d "${HOST_BUILD_DIR}" ]]; then
  echo "Error: build directory '${HOST_BUILD_DIR}' does not exist."
  echo "Usage: $0 [build-folder-name-under-Builds] [CarlaUE4.sh args...]"
  echo "Example: $0 v1.0.0 -prefernvidia -quality-level=Low -nosound"
  echo "Example: $0 v1.0.0 -RenderOffScreen -nosound"
  echo "Set CARLA_MAP_PATH= to disable the default map argument."
  exit 1
fi

if [[ -z "${DISPLAY:-}" ]]; then
  echo "Warning: DISPLAY is not set. Use -RenderOffScreen or run from a graphical session."
else
  xhost +local:root
fi

load_carla_map() {
  if [[ -z "${CARLA_MAP_NAME}" ]]; then
    return 0
  fi

  for _ in {1..120}; do
    if ss -ltn | grep -q ':2000 '; then
      break
    fi
    sleep 1
  done

  if ! ss -ltn | grep -q ':2000 '; then
    echo "Error: timed out waiting for CARLA server port 2000." >&2
    return 1
  fi

  echo "Requesting CARLA map load: ${CARLA_MAP_NAME}"

  docker exec -i \
    -e CARLA_MAP_NAME="${CARLA_MAP_NAME}" \
    -e CARLA_PYTHON_TARGET="${CARLA_PYTHON_TARGET}" \
    "${CONTAINER_ID}" \
    bash -s <<'SH'
set -euo pipefail

CARLA_WHEEL="$(find /carla/PythonAPI/carla/dist -maxdepth 1 -type f -name 'carla-*-cp310-*.whl' 2>/dev/null | head -n 1 || true)"

if [[ -z "${CARLA_WHEEL}" ]]; then
  echo "Error: CARLA Python wheel not found under /carla/PythonAPI/carla/dist." >&2
  exit 1
fi

python3 - <<'PY'
import sys

if sys.version_info[:2] != (3, 10):
    raise SystemExit(f"Error: container python3 must be 3.10 for the CARLA cp310 wheel, got {sys.version.split()[0]}")
PY

if [[ ! -d "${CARLA_PYTHON_TARGET}/carla" ]]; then
  python3 -m pip install --no-index --target "${CARLA_PYTHON_TARGET}" "${CARLA_WHEEL}" >/dev/null
fi

PYTHONPATH="${CARLA_PYTHON_TARGET}" python3 - <<'PY'
import os
import sys
import time

import carla

map_name = os.environ["CARLA_MAP_NAME"]
client = carla.Client("localhost", 2000)
client.set_timeout(2.0)

last_error = None
for _ in range(90):
    try:
        world = client.get_world()
        if world.get_map().name.endswith(map_name):
            print(f"CARLA map already loaded: {world.get_map().name}")
            sys.exit(0)

        print(f"Loading CARLA map: {map_name}")
        sys.stdout.flush()
        client.set_timeout(120.0)
        world = client.load_world(map_name)
        print(f"CARLA map loaded: {world.get_map().name}")
        sys.exit(0)
    except RuntimeError as exc:
        last_error = exc
        time.sleep(1.0)

print(f"Error: timed out loading CARLA map '{map_name}': {last_error}", file=sys.stderr)
sys.exit(1)
PY
SH
}

start_redis_sidecar() {
  if [[ "${UB_REDIS_ROLE}" == "none" ]]; then
    return 0
  fi

  echo "Starting Redis sidecar '${REDIS_CONTAINER_NAME}' on ${UB_REDIS_HOST}:${UB_REDIS_PORT}"

  REDIS_ARGS=(redis-server --bind "${UB_REDIS_HOST}" --port "${UB_REDIS_PORT}")
  if [[ -n "${UB_REDIS_PASSWORD}" ]]; then
    REDIS_ARGS+=(--requirepass "${UB_REDIS_PASSWORD}")
  fi

  docker run --rm -d \
    --net=host \
    --name "${REDIS_CONTAINER_NAME}" \
    "${REDIS_IMAGE}" \
    "${REDIS_ARGS[@]}" >/dev/null
  REDIS_SIDECAR_STARTED=1

  for _ in {1..30}; do
    if [[ -n "${UB_REDIS_PASSWORD}" ]]; then
      if docker exec "${REDIS_CONTAINER_NAME}" redis-cli -h "${UB_REDIS_HOST}" -p "${UB_REDIS_PORT}" -a "${UB_REDIS_PASSWORD}" ping >/dev/null 2>&1; then
        return 0
      fi
    else
      if docker exec "${REDIS_CONTAINER_NAME}" redis-cli -h "${UB_REDIS_HOST}" -p "${UB_REDIS_PORT}" ping >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 1
  done

  echo "Error: timed out waiting for Redis sidecar." >&2
  return 1
}

start_redis_client_sidecar() {
  if [[ "${UB_REDIS_ROLE}" == "none" ]]; then
    return 0
  fi

  echo "Starting Redis networking client '${REDIS_CLIENT_CONTAINER_NAME}' with role '${UB_REDIS_ROLE}'"

  docker run --rm -d \
    --net=host \
    --name "${REDIS_CLIENT_CONTAINER_NAME}" \
    -e UB_REDIS_ROLE="${UB_REDIS_ROLE}" \
    -e UB_REDIS_HOST="${UB_REDIS_HOST}" \
    -e UB_REDIS_PORT="${UB_REDIS_PORT}" \
    -e UB_REDIS_PASSWORD="${UB_REDIS_PASSWORD}" \
    -e UB_REDIS_CHANNEL="${UB_REDIS_CHANNEL}" \
    -e UB_CARLA_HOST="${UB_CARLA_HOST}" \
    -e UB_CARLA_PORT="${UB_CARLA_PORT}" \
    -e UB_CARLA_ASYNC="${UB_CARLA_ASYNC}" \
    -e UB_UNITY_HOST="${UB_UNITY_HOST}" \
    -e UB_UNITY_PORT="${UB_UNITY_PORT}" \
    -e CARLA_PYTHON_TARGET="${REDIS_CLIENT_CARLA_PYTHON_TARGET}" \
    -v "${HOST_BUILD_DIR}:/carla:ro" \
    "${REDIS_CLIENT_IMAGE}" >/dev/null
  REDIS_CLIENT_SIDECAR_STARTED=1

  docker logs -f "${REDIS_CLIENT_CONTAINER_NAME}" &
  REDIS_CLIENT_LOG_PID="$!"

  sleep 2
  if ! docker ps --format '{{.Names}}' | grep -qx "${REDIS_CLIENT_CONTAINER_NAME}"; then
    echo "Error: Redis networking client exited unexpectedly." >&2
    docker logs "${REDIS_CLIENT_CONTAINER_NAME}" >&2 || true
    return 1
  fi
}

IMAGE_NAME="${IMAGE_NAME:-ub-carla}"

start_redis_sidecar

CONTAINER_ID="$(docker run --rm -d \
  --net=host \
  --name "${CONTAINER_NAME}" \
  --runtime=nvidia \
  -e DISPLAY="${DISPLAY:-}" \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=all \
  -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
  -v "${HOST_BUILD_DIR}:/carla:rw" \
  "${IMAGE_NAME}" "${CARLA_ARGS[@]}")"

docker logs -f "${CONTAINER_ID}" &
LOG_PID="$!"

load_carla_map
start_redis_client_sidecar

set +e
EXIT_CODE="$(docker wait "${CONTAINER_ID}" 2>/dev/null)"
WAIT_STATUS="$?"
set -e

kill "${LOG_PID}" >/dev/null 2>&1 || true
LOG_PID=""

if [[ "${WAIT_STATUS}" -ne 0 || -z "${EXIT_CODE}" ]]; then
  exit "${WAIT_STATUS}"
fi

exit "${EXIT_CODE}"
