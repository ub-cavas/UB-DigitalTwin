#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MR_DIR="${REPO_ROOT}/UB-MR"
DOWNLOAD_SCRIPT="${MR_DIR}/download_unity_player.sh"
BUILDS_DIR="${MR_DIR}/Builds"

RELEASE="${UB_MR_RELEASE:-latest}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options] [release-tag]

Download the UB-MR Unity player release and verify the executable is ready for
the existing UB-MR launch scripts. This does not pull or tag Docker images.

Options:
  -r, --release TAG  GitHub release tag to download. Defaults to latest.
  -h, --help         Show this help text.

Environment overrides:
  UB_MR_RELEASE=${RELEASE}

Examples:
  ./scripts/download_ub_mr_release.sh
  ./scripts/download_ub_mr_release.sh 0.0.7
  ./scripts/download_ub_mr_release.sh --release 0.0.7
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

require_command() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 || die "Missing required command: ${command_name}"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -r|--release|--version)
        [[ $# -ge 2 ]] || die "$1 requires a value."
        RELEASE="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      -*)
        die "Unknown option: $1"
        ;;
      *)
        RELEASE="$1"
        shift
        ;;
    esac
  done
}

find_latest_player_dir() {
  find "$BUILDS_DIR" -mindepth 2 -maxdepth 2 -type f -name 'UB-MR.x86_64' -printf '%C@ %h\n' 2>/dev/null \
    | sort -nr \
    | head -n 1 \
    | cut -d ' ' -f 2-
}

download_release() {
  [[ -d "$MR_DIR" ]] || die "Missing UB-MR directory: ${MR_DIR}"
  [[ -x "$DOWNLOAD_SCRIPT" ]] || die "Missing executable downloader: ${DOWNLOAD_SCRIPT}"
  require_command curl

  echo "Downloading UB-MR Unity player release: ${RELEASE}"
  (
    cd "$MR_DIR"
    ./download_unity_player.sh "$RELEASE"
  )
}

verify_release() {
  local player_dir
  player_dir="$(find_latest_player_dir || true)"

  [[ -n "$player_dir" ]] || die "No UB-MR player found under ${BUILDS_DIR}. Expected Builds/<release>/UB-MR.x86_64."

  chmod +x "${player_dir}/UB-MR.x86_64"

  echo
  echo "UB-MR Unity player setup complete."
  echo "  player_dir=${player_dir}"
  echo "  player_build_folder=$(basename "$player_dir")"
  echo
  echo "Run with:"
  echo "  UB_MR_BUILD_FOLDER=$(basename "$player_dir") ./scripts/launch_ub_mr.sh"
  echo
  echo "Or start UB-MR only:"
  echo "  cd UB-MR"
  echo "  ./run_ub_mr.sh $(basename "$player_dir")"
}

parse_args "$@"
download_release
verify_release
