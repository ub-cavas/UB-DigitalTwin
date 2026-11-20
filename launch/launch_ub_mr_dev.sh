#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Preserve the legacy editor entry point's unseparated trailing Unity arguments.
OPTIONS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h|--dry-run|--iap|--carla|--auto) OPTIONS+=("$1"); shift ;;
    --) shift; break ;;
    *) break ;;
  esac
done
exec "${REPO_ROOT}/launch/launch_ub_mr.sh" --dev "${OPTIONS[@]}" -- "$@"
