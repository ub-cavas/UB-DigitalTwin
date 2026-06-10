#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-ub-carla-container}"
LOG_PID=""

if docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  echo "Container '${CONTAINER_NAME}' is already running. Exiting!"
  exit 0
fi

cleanup() {
  if [[ -n "${LOG_PID}" ]]; then
    kill "${LOG_PID}" >/dev/null 2>&1 || true
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
CARLA_MAP_PATH="${CARLA_MAP_PATH:-/Game/Carla/Maps/UBAutonomousProvingGrounds}"
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

IMAGE_NAME="${IMAGE_NAME:-ub-carla}"

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
