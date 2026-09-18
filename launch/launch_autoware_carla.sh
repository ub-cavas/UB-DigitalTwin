#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The default profile preserves the UB wrapper's settings. The profile helper
# only selects environment values; the existing launcher owns startup/cleanup.
exec python3 "${SCRIPT_DIR}/autoware_map_config.py" "$@"
