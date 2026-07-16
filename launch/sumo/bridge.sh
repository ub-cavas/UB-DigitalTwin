#!/usr/bin/env bash
# SUMO/time-master orchestration for the CARLA+SUMO+Autoware scenario.
# Scenario scripts set CARLA_DIR, BRIDGE_DIR, BUILD_FOLDER, the UB_SUMO_* env
# vars, UB_TRAFFIC_ORCHESTRATOR, and declare SUMO_STARTED/TIME_MASTER_STARTED
# variables before calling these.

collect_sumo_preflight_failures() {
  local -n _sumo_preflight_failures="$1"

  case "${UB_TRAFFIC_ORCHESTRATOR}" in
    sumo|none) ;;
    *)
      _sumo_preflight_failures+=("Unsupported UB_TRAFFIC_ORCHESTRATOR=${UB_TRAFFIC_ORCHESTRATOR}; expected 'sumo' or 'none'.")
      ;;
  esac

  if [[ "${UB_TRAFFIC_ORCHESTRATOR}" == "sumo" && ! -f "${BRIDGE_DIR}/Sumo/examples/${UB_SUMO_CONFIG}" ]]; then
    _sumo_preflight_failures+=("Missing SUMO config: ${BRIDGE_DIR}/Sumo/examples/${UB_SUMO_CONFIG}")
  fi
}

start_sumo_bridge() {
  cd "${CARLA_DIR}"

  export BUILD_FOLDER
  export DISPLAY
  resolve_xauthority
  export UB_SUMO_CONFIG
  export UB_SUMO_STEP_LENGTH
  export UB_SUMO_GUI
  export UB_SUMO_AUTO_START
  export UB_SUMO_TLS_MANAGER
  export UB_SUMO_SYNC_VEHICLE_COLOR
  export UB_SUMO_SYNC_VEHICLE_LIGHTS
  export UB_SUMO_EMPTY_TRAFFIC
  export UB_SUMO_EXTRA_ARGS
  export UB_TRAFFIC_MANAGER_PORT

  echo "Starting CARLA-SUMO bridge with SUMO config ${UB_SUMO_CONFIG}..."
  docker compose up --build -d sumo-bridge
  SUMO_STARTED=1

  sleep 2
  if [[ "$(docker compose ps --status running -q sumo-bridge 2>/dev/null || true)" == "" ]]; then
    echo "Error: sumo-bridge exited during startup." >&2
    docker compose logs --tail=120 sumo-bridge >&2 || true
    return 1
  fi
}

# Dispatches to start_sumo_bridge or start_carla_time_master (carla/time_master.sh)
# based on UB_TRAFFIC_ORCHESTRATOR ("sumo" or "none"). When orchestrator=none,
# the time master's tick rate is pinned to UB_SUMO_STEP_LENGTH so it matches
# the fixed_delta_seconds the bridge is launched with.
start_traffic_orchestrator() {
  if [[ "${UB_TRAFFIC_ORCHESTRATOR}" == "sumo" ]]; then
    start_sumo_bridge
  else
    UB_CARLA_STEP_LENGTH="${UB_SUMO_STEP_LENGTH}" start_carla_time_master
  fi
}
