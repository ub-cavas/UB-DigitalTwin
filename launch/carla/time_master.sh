#!/usr/bin/env bash
# CARLA-only synchronous-mode ticker. Used whenever Autoware's CARLA bridge
# runs in external_tick mode (its default) without SUMO as the time master —
# the plain scenario needs this because e2e_simulator.launch.xml always pulls
# in autoware_carla_interface when simulator_type=carla, and that bridge
# defaults external_tick to True with no way to override it from the
# top-level launch call. Scenario scripts set CARLA_DIR, BUILD_FOLDER,
# UB_CARLA_STEP_LENGTH, and declare a TIME_MASTER_STARTED variable before
# calling this.

start_carla_time_master() {
  cd "${CARLA_DIR}"

  export BUILD_FOLDER
  export UB_CARLA_STEP_LENGTH="${UB_CARLA_STEP_LENGTH:-0.05}"
  export UB_CARLA_TIMEOUT="${UB_CARLA_TIMEOUT:-10.0}"
  export UB_CARLA_RESET_SYNC_ON_EXIT="${UB_CARLA_RESET_SYNC_ON_EXIT:-0}"

  echo "Starting CARLA-only time master with fixed delta ${UB_CARLA_STEP_LENGTH}..."
  docker compose up --build -d time-master
  TIME_MASTER_STARTED=1

  sleep 2
  if [[ "$(docker compose ps --status running -q time-master 2>/dev/null || true)" == "" ]]; then
    echo "Error: time-master exited during startup." >&2
    docker compose logs --tail=120 time-master >&2 || true
    return 1
  fi
}
