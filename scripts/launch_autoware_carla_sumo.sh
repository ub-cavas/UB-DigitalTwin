#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export BUILD_FOLDER="${BUILD_FOLDER:-v1.0.0}"
export CARLA_MAP="${CARLA_MAP:-UBAutonomousProvingGrounds}"
export CARLA_ARGS="${CARLA_ARGS:--prefernvidia -quality-level=Epic -nosound}"
export UB_SUMO_CONFIG="${UB_SUMO_CONFIG:-UBAutonomousProvingGrounds.sumocfg}"
export UB_SUMO_STEP_LENGTH="${UB_SUMO_STEP_LENGTH:-0.05}"
export UB_SUMO_GUI="${UB_SUMO_GUI:-1}"
export UB_SUMO_AUTO_START="${UB_SUMO_AUTO_START:-1}"
export UB_SUMO_TLS_MANAGER="${UB_SUMO_TLS_MANAGER:-sumo}"
export AUTOWARE_VEHICLE_MODEL="${AUTOWARE_VEHICLE_MODEL:-sample_vehicle}"
export AUTOWARE_SENSOR_MODEL="${AUTOWARE_SENSOR_MODEL:-awsim_sensor_kit}"
export AUTOWARE_E2E_SIMULATOR_TYPE="${AUTOWARE_E2E_SIMULATOR_TYPE:-awsim}"

exec "${REPO_ROOT}/CARLA/start_autoware_carla_sumo.sh" "$@"
