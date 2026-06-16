#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Defaults for the UB CARLA integration. Each value can still be overridden by
# exporting it before running this wrapper.
export CARLA_ARGS="${CARLA_ARGS:--prefernvidia -quality-level=Epic -nosound}"
export UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY="${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY:-1}"
export UB_AUTOWARE_EGO_ONLY_PERCEPTION="${UB_AUTOWARE_EGO_ONLY_PERCEPTION:-1}"
export UB_AUTOWARE_CARLA_PLANNING_PRESET="${UB_AUTOWARE_CARLA_PLANNING_PRESET:-1}"
export AUTOWARE_PLANNING_MODULE_PRESET="${AUTOWARE_PLANNING_MODULE_PRESET:-ub_carla}"

exec "${REPO_ROOT}/CARLA/start_autoware_carla.sh" "$@"
