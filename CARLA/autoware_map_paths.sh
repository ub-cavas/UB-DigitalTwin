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
  local filename
  for filename in lanelet2_map.osm pointcloud_map.pcd map_projector_info.yaml; do
    if [[ ! -s "${AUTOWARE_HOST_MAP_DIR}/${filename}" ]]; then
      map_failures+=("Missing or empty Autoware map file for CARLA ${BUILD_FOLDER}: ${AUTOWARE_HOST_MAP_DIR}/${filename}")
    fi
  done
}
