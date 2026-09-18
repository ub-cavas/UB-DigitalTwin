#!/usr/bin/env bash
# Shared by the CARLA/Autoware launchers. REPO_DIR and BUILD_FOLDER are set by
# the caller; /host_data is the Autoware/host_data Docker bind mount.
configure_autoware_map_paths() {
  local host_root="${REPO_DIR}/Autoware/host_data"
  local map_root="maps/ub_autonomous_proving_grounds"
  local relative_path="${map_root}/${BUILD_FOLDER}"

  if [[ -z "${AUTOWARE_HOST_MAP_DIR:-}" && -z "${AUTOWARE_MAP_PATH:-}" ]]; then
    # The original unversioned download belongs to v1.0.0 only. Never fall
    # back to it for newer builds, or bypass an incomplete versioned map.
    if [[ "${BUILD_FOLDER}" == v1.0.0 && ! -e "${host_root}/${relative_path}" ]]; then
      if [[ -f "${host_root}/${map_root}/lanelet2_map.osm" ]]; then
        relative_path="${map_root}"
      elif [[ -f "${host_root}/ub_autonomous_proving_grounds/lanelet2_map.osm" ]]; then
        relative_path="ub_autonomous_proving_grounds"
      fi
    fi
    AUTOWARE_HOST_MAP_DIR="${host_root}/${relative_path}"
    AUTOWARE_MAP_PATH="/host_data/${relative_path}"
  elif [[ -z "${AUTOWARE_HOST_MAP_DIR:-}" ]]; then
    case "${AUTOWARE_MAP_PATH}" in
      /host_data/*) AUTOWARE_HOST_MAP_DIR="${host_root}/${AUTOWARE_MAP_PATH#/host_data/}" ;;
      *) echo "Set AUTOWARE_HOST_MAP_DIR as well for a map outside /host_data." >&2; return 1 ;;
    esac
  elif [[ -z "${AUTOWARE_MAP_PATH:-}" ]]; then
    case "${AUTOWARE_HOST_MAP_DIR}" in
      "${host_root}/"*) AUTOWARE_MAP_PATH="/host_data/${AUTOWARE_HOST_MAP_DIR#"${host_root}/"}" ;;
      *) echo "Set AUTOWARE_MAP_PATH as well and mount the custom host map directory in Autoware." >&2; return 1 ;;
    esac
  fi
}

collect_autoware_map_failures() {
  local -n map_failures="$1"
  local filename tile found_tile=0
  local pcd_path="${AUTOWARE_HOST_MAP_DIR}/pointcloud_map.pcd"
  for filename in lanelet2_map.osm map_projector_info.yaml; do
    if [[ ! -f "${AUTOWARE_HOST_MAP_DIR}/${filename}" || ! -s "${AUTOWARE_HOST_MAP_DIR}/${filename}" ]]; then
      map_failures+=("Missing or empty Autoware map file for CARLA ${BUILD_FOLDER}: ${AUTOWARE_HOST_MAP_DIR}/${filename}")
    fi
  done

  if [[ -d "${pcd_path}" ]]; then
    for tile in "${pcd_path}"/*.pcd; do
      [[ -e "${tile}" || -L "${tile}" ]] || continue
      found_tile=1
      if [[ ! -f "${tile}" || ! -s "${tile}" ]]; then
        map_failures+=("Missing or empty PCD tile: ${tile}")
      fi
    done
    if [[ "${found_tile}" == 0 ]]; then
      map_failures+=("No PCD tiles found in: ${pcd_path}")
    fi
    if [[ ! -f "${AUTOWARE_HOST_MAP_DIR}/pointcloud_map_metadata.yaml" || ! -s "${AUTOWARE_HOST_MAP_DIR}/pointcloud_map_metadata.yaml" ]]; then
      map_failures+=("Tiled PCD requires nonempty metadata: ${AUTOWARE_HOST_MAP_DIR}/pointcloud_map_metadata.yaml")
    fi
  elif [[ ! -f "${pcd_path}" || ! -s "${pcd_path}" ]]; then
    map_failures+=("Missing or empty Autoware point cloud for CARLA ${BUILD_FOLDER}: ${pcd_path}")
  fi
}
