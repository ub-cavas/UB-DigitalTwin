#!/usr/bin/env bash
# CARLA spectator camera-follow compose service. Scenario scripts set CARLA_DIR,
# BUILD_FOLDER, and the UB_AUTOWARE_CAMERA_FOLLOW_* env vars, and declare a
# CAMERA_FOLLOW_STARTED variable before calling start_camera_follow.

start_camera_follow() {
  if [[ "${UB_AUTOWARE_CAMERA_FOLLOW}" != "1" ]]; then
    return 0
  fi

  cd "${CARLA_DIR}"
  export BUILD_FOLDER
  export UB_AUTOWARE_CAMERA_FOLLOW_HOST
  export UB_AUTOWARE_CAMERA_FOLLOW_PORT
  export UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES
  export UB_AUTOWARE_CAMERA_FOLLOW_DISTANCE_M
  export UB_AUTOWARE_CAMERA_FOLLOW_HEIGHT_M
  export UB_AUTOWARE_CAMERA_FOLLOW_PITCH_DEG
  export UB_AUTOWARE_CAMERA_FOLLOW_UPDATE_HZ

  echo "Starting CARLA spectator camera follow for role_name(s): ${UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES}"
  docker compose up --build -d camera-follow
  CAMERA_FOLLOW_STARTED=1

  sleep 1
  if [[ -z "$(docker compose ps -q camera-follow 2>/dev/null || true)" ]]; then
    echo "Warning: CARLA spectator camera follow container was not created." >&2
    docker compose logs --tail=80 camera-follow >&2 || true
    CAMERA_FOLLOW_STARTED=0
  elif [[ "$(docker compose ps --status running -q camera-follow 2>/dev/null || true)" == "" ]]; then
    echo "Warning: CARLA spectator camera follow container exited during startup." >&2
    docker compose logs --tail=80 camera-follow >&2 || true
    CAMERA_FOLLOW_STARTED=0
  fi
}
