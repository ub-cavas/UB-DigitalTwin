#!/usr/bin/env bash
# Preflight-check scaffold. Scenario scripts define collect_preflight_failures()
# (calling collect_docker_preflight_failures for the shared docker/compose
# checks below, then appending scenario-specific checks) and setup_hint().

collect_docker_preflight_failures() {
  local -n _docker_preflight_failures="$1"

  if ! command -v docker >/dev/null 2>&1; then
    _docker_preflight_failures+=("Docker is not installed or not on PATH.")
  elif ! docker compose version >/dev/null 2>&1; then
    _docker_preflight_failures+=("Docker Compose v2 is unavailable. Install the Docker Compose plugin so 'docker compose' works.")
  elif ! docker info >/dev/null 2>&1; then
    _docker_preflight_failures+=("Docker daemon is unreachable or this user cannot access /var/run/docker.sock.")
  fi
}

run_preflight() {
  local failures=()
  collect_preflight_failures failures

  if [[ ${#failures[@]} -gt 0 ]]; then
    echo "Preflight failed:"
    local failure
    for failure in "${failures[@]}"; do
      echo "  - ${failure}"
    done
    setup_hint
    return 1
  fi
}
