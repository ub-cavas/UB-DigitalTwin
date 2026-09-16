#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_LAUNCHER="${REPO_ROOT}/CARLA/start_autoware_carla.sh"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: launch_autoware_carla_ub_mr_lidar.sh [--dry-run] [--help]

Start CARLA and Autoware for a UB-MR LiDAR test. Start Unity and the CARLA
localization bridge separately with launch_ub_mr_dev.sh and launch_mr_pkg_dev.sh.

Unity agent settings:
  Agent: LincolnMKZ-CARLA-LiDAR (import the matching JSON from UB-MR/Agents)
  Recognition: LiDAR modification
  Clock: Simulation /clock
  LiDAR input: /sensing/lidar/top/pointcloud_before_sync
  LiDAR position (Unity): x=0, y=3.1, z=1.394; rotation=0

Routes /sensing/lidar/top/pointcloud_before_sync_modified to Autoware's
/sensing/lidar/concatenated/pointcloud. Perception waits for Unity's output;
there is no fallback to the original cloud. Direct-box mode is not selected
automatically: configure the agent before starting a session.

The standalone CARLA launcher is never edited. A temporary copy beside it
changes only the relay source and is removed on exit. The source layout is
checked before launch. This uses the existing UB-MR perception profile to
keep sensor perception enabled and CARLA ground-truth replacement disabled.

Other CARLA/Autoware environment overrides remain available, including
AUTOWARE_RVIZ (defaults to true).

  --dry-run  Check routing and preview the underlying launch without starting it.
  --help     Show this help.
EOF
}

for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: ${arg}" >&2; usage >&2; exit 2 ;;
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

# Keep the temporary script in CARLA so its BASH_SOURCE-relative paths resolve
# exactly as in the original. No installed Autoware routing files are patched
# by this adapter; the existing launcher's setup and cleanup still run normally.
TEMP_LAUNCHER="$(mktemp "${REPO_ROOT}/CARLA/.ub-mr-lidar-launch.XXXXXX.sh")"
cleanup() { rm -f -- "${TEMP_LAUNCHER}"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

/usr/bin/python3 - "${SOURCE_LAUNCHER}" "${TEMP_LAUNCHER}" <<'PY'
from pathlib import Path
import sys

source, destination = map(Path, sys.argv[1:])
text = source.read_text()
original = "SOURCE_TOPIC = '/sensing/lidar/top/pointcloud_before_sync'"
modified = "SOURCE_TOPIC = '/sensing/lidar/top/pointcloud_before_sync_modified'"
if text.splitlines().count(original) != 1 or modified in text:
    raise SystemExit(
        'Unsupported CARLA launcher relay layout. Expected exactly one original '
        'top-LiDAR SOURCE_TOPIC assignment. Review the UB-MR adapter before launching.'
    )
destination.write_text(text.replace(original, modified, 1))
PY

bash -n "${TEMP_LAUNCHER}"
echo "UB-MR LiDAR routing: /sensing/lidar/top/pointcloud_before_sync -> Unity -> /sensing/lidar/top/pointcloud_before_sync_modified -> /sensing/lidar/concatenated/pointcloud"
echo "Unity must publish the modified cloud for Autoware perception to receive scans."
if [[ "${DRY_RUN}" == 1 ]]; then
  bash "${TEMP_LAUNCHER}" --dry-run
else
  bash "${TEMP_LAUNCHER}"
fi
