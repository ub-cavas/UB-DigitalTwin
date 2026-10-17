#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: stop_carla_redis_server.sh

Stops the CARLA, Redis, map loader, traffic publisher, and ego renderer
services started by launch_carla_redis_server.sh. Containers are kept for reuse.
If the launcher used COMPOSE_PROJECT_NAME, use the same value here.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}/CARLA"

exec docker compose stop carla redis map-loader traffic-publisher ego-renderer
