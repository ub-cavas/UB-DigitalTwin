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

# Tiled maps must have at least one nonempty PCD and a metadata file.
mkdir -p "${host_root}/tiled/pointcloud_map.pcd"
for filename in lanelet2_map.osm map_projector_info.yaml; do
  echo fixture > "${host_root}/tiled/${filename}"
done
(
  BUILD_FOLDER=v1.1.0 AUTOWARE_HOST_MAP_DIR="${host_root}/tiled"
  failures=()
  collect_autoware_map_failures failures
  [[ ${#failures[@]} == 2 ]]
)
echo fixture > "${host_root}/tiled/pointcloud_map.pcd/tile_0_0.pcd"
(
  BUILD_FOLDER=v1.1.0 AUTOWARE_HOST_MAP_DIR="${host_root}/tiled"
  failures=()
  collect_autoware_map_failures failures
  [[ ${#failures[@]} == 1 && "${failures[0]}" == *metadata* ]]
)
printf 'x_resolution: 20\ny_resolution: 20\ntile_0_0.pcd: [0, 0]\n' > "${host_root}/tiled/pointcloud_map_metadata.yaml"
(
  BUILD_FOLDER=v1.1.0 AUTOWARE_HOST_MAP_DIR="${host_root}/tiled"
  failures=()
  collect_autoware_map_failures failures
  [[ ${#failures[@]} == 0 ]]
)
touch "${host_root}/tiled/pointcloud_map.pcd/empty.pcd"
(
  BUILD_FOLDER=v1.1.0 AUTOWARE_HOST_MAP_DIR="${host_root}/tiled"
  failures=()
  collect_autoware_map_failures failures
  [[ ${#failures[@]} == 1 && "${failures[0]}" == *empty.pcd* ]]
)
echo 'Autoware tiled map preflight: all checks passed'
