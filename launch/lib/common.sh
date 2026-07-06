#!/usr/bin/env bash
# Shared helpers for launch/ scripts. Source after computing LAUNCH_DIR/REPO_ROOT.

has_files() {
  local path="$1"
  [[ -d "${path}" ]] || return 1
  find "${path}" -mindepth 1 -maxdepth 2 -print -quit 2>/dev/null | grep -q .
}

shell_quote() {
  printf "%q" "$1"
}

# Parses --dry-run/--help/unknown-arg from "$@". Sets DRY_RUN=1 on --dry-run.
# Requires the caller to define a `usage` function.
parse_common_args() {
  DRY_RUN=0
  local arg
  for arg in "$@"; do
    case "${arg}" in
      --dry-run)
        DRY_RUN=1
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        echo "Unknown argument: ${arg}" >&2
        usage >&2
        exit 2
        ;;
    esac
  done
}

# Stops and removes a single docker-compose service, ignoring errors. Scenario
# scripts set CARLA_DIR before calling this. Used for the transient services
# (camera-follow, sumo-bridge, time-master) that get torn down independently
# of the main `docker compose down`.
stop_compose_service() {
  local service="$1"
  cd "${CARLA_DIR}"
  docker compose stop "${service}" >/dev/null 2>&1 || true
  docker compose rm -f "${service}" >/dev/null 2>&1 || true
}
