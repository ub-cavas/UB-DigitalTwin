#!/usr/bin/env bash
set -euo pipefail

# Keep the legacy entry point aligned with the maintained manual-client launcher.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/../scripts/launch_carla_redis_manual_client.sh" "$@"
