#!/usr/bin/env bash
# CARLA docker-compose stack bring-up. Scenario scripts set CARLA_DIR,
# BUILD_FOLDER, CARLA_ARGS, CARLA_MAP_PATH, CARLA_MAP, and declare a
# CARLA_STARTED variable before calling start_carla. Optional:
#   CARLA_BASE_SERVICES     extra required compose services beyond
#                           carla+map-loader (e.g. "redis"), space-separated.
#   CARLA_X11_WARN_MESSAGE  xhost failure warning text.
#   UB_CARLA_EXTRA_SERVICES user-overridable extra compose services.

start_carla() {
  local services=(carla map-loader)
  local extra=()

  cd "${CARLA_DIR}"

  export BUILD_FOLDER
  export CARLA_ARGS
  export CARLA_MAP_PATH
  setup_x11 "${CARLA_X11_WARN_MESSAGE:-xhost did not grant local root X11 access. CARLA may fail to render.}"

  if [[ -n "${CARLA_BASE_SERVICES:-}" ]]; then
    read -r -a extra <<< "${CARLA_BASE_SERVICES}"
    services+=("${extra[@]}")
  fi
  if [[ -n "${UB_CARLA_EXTRA_SERVICES:-}" ]]; then
    read -r -a extra <<< "${UB_CARLA_EXTRA_SERVICES}"
    services+=("${extra[@]}")
  fi

  echo "Starting rendered CARLA Compose stack..."
  CARLA_STARTED=1
  docker compose up --build -d "${services[@]}"
  wait_for_one_shot_container map-loader
  echo "CARLA map loaded: ${CARLA_MAP}"
  wait_for_container_stable carla
}
