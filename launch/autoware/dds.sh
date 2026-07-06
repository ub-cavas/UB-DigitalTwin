#!/usr/bin/env bash
# Autoware host DDS/CycloneDDS setup, shared by every Autoware scenario.
# Scenario scripts set AUTOWARE_DOCKER_DIR, UB_AUTOWARE_HOST_CONFIG_DDS,
# UB_AUTOWARE_RMW_IMPLEMENTATION, and define setup_hint() before calling
# configure_autoware_host_dds.

DDS_REQUIRED_RMEM_MAX=10485760
DDS_REQUIRED_IPFRAG_HIGH_THRESH=134217728
DDS_REQUIRED_IPFRAG_TIME=3

collect_dds_host_config_failures() {
  local failures_ref="$1"
  local -n dds_failures_ref="${failures_ref}"
  local value

  if [[ "${UB_AUTOWARE_HOST_CONFIG_DDS}" != "1" || "${UB_AUTOWARE_RMW_IMPLEMENTATION}" != "rmw_cyclonedds_cpp" ]]; then
    return 0
  fi

  value="$(sysctl -n net.core.rmem_max 2>/dev/null || true)"
  if [[ ! "${value}" =~ ^[0-9]+$ || "${value}" -lt "${DDS_REQUIRED_RMEM_MAX}" ]]; then
    dds_failures_ref+=("net.core.rmem_max is ${value:-unreadable}; CycloneDDS needs at least ${DDS_REQUIRED_RMEM_MAX}.")
  fi

  value="$(sysctl -n net.ipv4.ipfrag_time 2>/dev/null || true)"
  if [[ ! "${value}" =~ ^[0-9]+$ || "${value}" -gt "${DDS_REQUIRED_IPFRAG_TIME}" ]]; then
    dds_failures_ref+=("net.ipv4.ipfrag_time is ${value:-unreadable}; Autoware DDS setup expects ${DDS_REQUIRED_IPFRAG_TIME}.")
  fi

  value="$(sysctl -n net.ipv4.ipfrag_high_thresh 2>/dev/null || true)"
  if [[ ! "${value}" =~ ^[0-9]+$ || "${value}" -lt "${DDS_REQUIRED_IPFRAG_HIGH_THRESH}" ]]; then
    dds_failures_ref+=("net.ipv4.ipfrag_high_thresh is ${value:-unreadable}; Autoware DDS setup expects at least ${DDS_REQUIRED_IPFRAG_HIGH_THRESH}.")
  fi

  if ! ip link show lo 2>/dev/null | grep -qw MULTICAST; then
    dds_failures_ref+=("loopback interface lo does not have multicast enabled.")
  fi
}

print_dds_host_config_failures() {
  local failures_ref="$1"
  local -n dds_failures_ref="${failures_ref}"
  local failure

  echo "Autoware host DDS settings are not applied:"
  for failure in "${dds_failures_ref[@]}"; do
    echo "  - ${failure}"
  done
}

configure_autoware_host_dds() {
  local dds_failures=()

  if [[ "${UB_AUTOWARE_HOST_CONFIG_DDS}" != "1" || "${UB_AUTOWARE_RMW_IMPLEMENTATION}" != "rmw_cyclonedds_cpp" ]]; then
    return 0
  fi

  if [[ ! -x "${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash" ]]; then
    echo "Warning: missing executable Autoware host DDS setup script: ${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash" >&2
    return 0
  fi

  collect_dds_host_config_failures dds_failures
  if [[ ${#dds_failures[@]} -eq 0 ]]; then
    return 0
  fi

  print_dds_host_config_failures dds_failures >&2

  if ! command -v sudo >/dev/null 2>&1; then
    echo "Error: sudo is required to apply Autoware host DDS settings." >&2
    setup_hint >&2
    return 1
  fi

  if [[ -t 0 ]]; then
    echo "Applying Autoware host DDS settings. sudo may prompt for your password."
    "${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash"
  elif sudo -n true 2>/dev/null; then
    echo "Applying Autoware host DDS settings..."
    "${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash"
  else
    echo "Error: sudo needs a password, but this launcher is not attached to an interactive terminal." >&2
    echo "Run this once in a terminal before launching:" >&2
    echo "  cd ${AUTOWARE_DOCKER_DIR} && ../scripts/host_config_dds.bash" >&2
    return 1
  fi

  dds_failures=()
  collect_dds_host_config_failures dds_failures
  if [[ ${#dds_failures[@]} -gt 0 ]]; then
    echo "Error: Autoware host DDS settings are still invalid after setup." >&2
    print_dds_host_config_failures dds_failures >&2
    return 1
  fi
}
