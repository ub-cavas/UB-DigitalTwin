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

if [[ $# -gt 0 ]]; then
  shift
fi

CARLA_ARGS=("$@")

if [[ ${#CARLA_ARGS[@]} -eq 0 ]]; then
  CARLA_ARGS=(-prefernvidia -quality-level=Low -nosound)
fi

HOST_BUILD_DIR="${SCRIPT_DIR}/Builds/${BUILD_FOLDER}"

if [[ ! -d "${HOST_BUILD_DIR}" ]]; then
  echo "Error: build directory '${HOST_BUILD_DIR}' does not exist."
  echo "Usage: $0 [build-folder-name-under-Builds] [CarlaUE4.sh args...]"
  echo "Example: $0 v1.0.0 -prefernvidia -quality-level=Low -nosound"
  echo "Example: $0 v1.0.0 -RenderOffScreen -nosound"
  exit 1
fi

if [[ -z "${DISPLAY:-}" ]]; then
  echo "Warning: DISPLAY is not set. Use -RenderOffScreen or run from a graphical session."
else
  xhost +local:root
fi

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
