#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INJECTION=lidar
ARGS=()
usage() {
  cat <<'EOF'
Usage: launch_autoware_carla_ub_mr_lidar.sh [--injection lidar|boxes|both] [--dry-run] [--help]

Configure explicit UB-MR perception and exec the regular map-profile launcher.
Default: lidar. boxes uses the original top cloud; lidar and both wait for
Unity's modified cloud, with no original-cloud fallback. Select/import the
matching LincolnMKZ-CARLA-LiDAR, -Boxes or -Both Unity agent separately.
The CLI never changes Unity's saved agent. Start editor localization separately
with launch_mr_pkg_dev.sh. Other map, RViz, planning and box-topic environment
overrides remain available.
EOF
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --injection)
      [[ $# -ge 2 && "$2" =~ ^(lidar|boxes|both)$ ]] || { echo '--injection requires lidar, boxes, or both.' >&2; exit 2; }
      INJECTION="$2"; shift 2 ;;
    --dry-run) ARGS+=(--dry-run); shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Match the standard CARLA wrapper's defaults, but require the single relay
# and real sensor perception for this explicitly selected UB-MR workflow.
export CARLA_ARGS="${CARLA_ARGS:--prefernvidia -quality-level=Epic -nosound}"
export UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY=1
export UB_MR_PERCEPTION_PROFILE=1
export UB_AUTOWARE_EGO_ONLY_PERCEPTION=0
export UB_AUTOWARE_CARLA_PUBLISH_DETECTED_OBJECTS=0
export UB_AUTOWARE_CARLA_PLANNING_PRESET="${UB_AUTOWARE_CARLA_PLANNING_PRESET:-1}"
export AUTOWARE_PLANNING_MODULE_PRESET="${AUTOWARE_PLANNING_MODULE_PRESET:-ub_carla}"
export AUTOWARE_RVIZ="${AUTOWARE_RVIZ:-true}"

export UB_AUTOWARE_CARLA_TOP_LIDAR_SOURCE_TOPIC=/sensing/lidar/top/pointcloud_before_sync
if [[ "${INJECTION}" != boxes ]]; then
  export UB_AUTOWARE_CARLA_TOP_LIDAR_SOURCE_TOPIC=/sensing/lidar/top/pointcloud_before_sync_modified
fi
echo "UB-MR injection: ${INJECTION}; relay: ${UB_AUTOWARE_CARLA_TOP_LIDAR_SOURCE_TOPIC} -> /sensing/lidar/concatenated/pointcloud"
echo 'Select the matching Unity recognition mode/preset before starting a new session.'
exec "${REPO_ROOT}/launch/launch_autoware_carla.sh" "${ARGS[@]}"
