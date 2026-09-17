#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/autoware_map_paths.sh"

fixture="$(mktemp -d)"
trap 'rm -rf "${fixture}"' EXIT
REPO_DIR="${fixture}"
host_root="${REPO_DIR}/Autoware/host_data"
map_root="${host_root}/maps/ub_autonomous_proving_grounds"
mkdir -p "${map_root}" "${host_root}/custom"
for filename in lanelet2_map.osm pointcloud_map.pcd map_projector_info.yaml; do
  echo fixture > "${map_root}/${filename}"
done
unset AUTOWARE_HOST_MAP_DIR AUTOWARE_MAP_PATH

(
  BUILD_FOLDER=v1.1.0
  configure_autoware_map_paths
  [[ "${AUTOWARE_HOST_MAP_DIR}" == "${map_root}/v1.1.0" ]]
  [[ "${AUTOWARE_MAP_PATH}" == /host_data/maps/ub_autonomous_proving_grounds/v1.1.0 ]]
  failures=()
  collect_autoware_map_failures failures
  [[ ${#failures[@]} == 3 ]]
)
(
  BUILD_FOLDER=v1.0.0
  configure_autoware_map_paths
  [[ "${AUTOWARE_HOST_MAP_DIR}" == "${map_root}" ]]
  failures=()
  collect_autoware_map_failures failures
  [[ ${#failures[@]} == 0 ]]
)
mkdir "${map_root}/v1.0.0"
(
  BUILD_FOLDER=v1.0.0
  configure_autoware_map_paths
  [[ "${AUTOWARE_HOST_MAP_DIR}" == "${map_root}/v1.0.0" ]]
  failures=()
  collect_autoware_map_failures failures
  [[ ${#failures[@]} == 3 ]]
)
for filename in lanelet2_map.osm pointcloud_map.pcd map_projector_info.yaml; do
  cp "${map_root}/${filename}" "${map_root}/v1.0.0/"
done
(
  BUILD_FOLDER=v1.0.0
  configure_autoware_map_paths
  failures=()
  collect_autoware_map_failures failures
  [[ ${#failures[@]} == 0 ]]
)
(
  BUILD_FOLDER=v1.1.0 AUTOWARE_HOST_MAP_DIR="${host_root}/custom"
  configure_autoware_map_paths
  [[ "${AUTOWARE_MAP_PATH}" == /host_data/custom ]]
)
(
  BUILD_FOLDER=v1.1.0 AUTOWARE_MAP_PATH=/host_data/custom
  configure_autoware_map_paths
  [[ "${AUTOWARE_HOST_MAP_DIR}" == "${host_root}/custom" ]]
)
(
  BUILD_FOLDER=v1.1.0 AUTOWARE_HOST_MAP_DIR=/custom/host AUTOWARE_MAP_PATH=/custom/container
  configure_autoware_map_paths
  [[ "${AUTOWARE_HOST_MAP_DIR}" == /custom/host && "${AUTOWARE_MAP_PATH}" == /custom/container ]]
)
(
  BUILD_FOLDER=v1.1.0 AUTOWARE_HOST_MAP_DIR=/custom/host
  if configure_autoware_map_paths 2>/dev/null; then exit 1; fi
)
echo 'Autoware map selection: all checks passed'
