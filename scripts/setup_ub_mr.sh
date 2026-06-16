#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MR_DIR="${REPO_ROOT}/UB-MR"
RELEASE_SCRIPT="${SCRIPT_DIR}/download_ub_mr_release.sh"
BUILDS_DIR="${MR_DIR}/Builds"

RELEASE="${UB_MR_RELEASE:-latest}"
REMOTE_IMAGE="${UB_MR_DOCKER_IMAGE:-oakleyth/ub-mr:latest}"
LOCAL_IMAGE="${UB_MR_LOCAL_IMAGE:-ub-mr}"
SKIP_PLAYER_DOWNLOAD=0
SKIP_IMAGE_PULL=0
SKIP_LOCAL_TAG=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [options] [release-tag]

Download the UB-MR Unity player release, pull the UB-MR Docker runtime image,
and verify the files are in the locations expected by the launch scripts.

Options:
  -r, --release TAG       GitHub release tag to download. Defaults to latest.
  -i, --image IMAGE       Docker Hub runtime image. Defaults to ${REMOTE_IMAGE}.
      --local-image IMAGE Local tag used by UB-MR/run_ub_mr.sh. Defaults to ${LOCAL_IMAGE}.
      --skip-player       Do not download the Unity player release.
      --skip-image-pull   Do not pull the Docker runtime image.
      --skip-local-tag    Do not tag the pulled image as the local runtime image.
  -h, --help              Show this help text.

Environment overrides:
  UB_MR_RELEASE=${RELEASE}
  UB_MR_DOCKER_IMAGE=${REMOTE_IMAGE}
  UB_MR_LOCAL_IMAGE=${LOCAL_IMAGE}

Examples:
  ./scripts/setup_ub_mr.sh
  ./scripts/setup_ub_mr.sh 0.0.7
  ./scripts/setup_ub_mr.sh --release 0.0.7 --image oakleyth/ub-mr:latest
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
      -i|--image)
        [[ $# -ge 2 ]] || die "$1 requires a value."
        REMOTE_IMAGE="$2"
        shift 2
        ;;
      --local-image)
        [[ $# -ge 2 ]] || die "$1 requires a value."
        LOCAL_IMAGE="$2"
        shift 2
        ;;
      --skip-player)
        SKIP_PLAYER_DOWNLOAD=1
        shift
        ;;
      --skip-image-pull)
        SKIP_IMAGE_PULL=1
        shift
        ;;
      --skip-local-tag)
        SKIP_LOCAL_TAG=1
        shift
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

download_player() {
  if [[ "${SKIP_PLAYER_DOWNLOAD}" -eq 1 ]]; then
    echo "Skipping UB-MR Unity player download."
    return
  fi

  [[ -x "$RELEASE_SCRIPT" ]] || die "Missing executable release downloader: ${RELEASE_SCRIPT}"

  "$RELEASE_SCRIPT" "$RELEASE"
}

pull_runtime_image() {
  if [[ "${SKIP_IMAGE_PULL}" -eq 1 ]]; then
    echo "Skipping UB-MR Docker runtime image pull."
    return
  fi

  require_command docker

  echo "Pulling UB-MR Docker runtime image: ${REMOTE_IMAGE}"
  docker pull "$REMOTE_IMAGE"

  if [[ "${SKIP_LOCAL_TAG}" -ne 1 && "$REMOTE_IMAGE" != "$LOCAL_IMAGE" ]]; then
    echo "Tagging runtime image for local launchers: ${LOCAL_IMAGE}"
    docker tag "$REMOTE_IMAGE" "$LOCAL_IMAGE"
  fi
}

verify_setup() {
  local player_dir
  player_dir="$(find_latest_player_dir || true)"

  [[ -n "$player_dir" ]] || die "No UB-MR player found under ${BUILDS_DIR}. Expected Builds/<release>/UB-MR.x86_64."

  chmod +x "${player_dir}/UB-MR.x86_64"

  echo
  echo "UB-MR setup complete."
  echo "  player_dir=${player_dir}"
  echo "  player_build_folder=$(basename "$player_dir")"
  echo "  docker_runtime_image=${LOCAL_IMAGE}"
  echo
  echo "Run with:"
  echo "  UB_MR_BUILD_FOLDER=$(basename "$player_dir") ./scripts/launch_ub_mr.sh"
  echo
  echo "Or start UB-MR only:"
  echo "  cd UB-MR"
  echo "  ./run_ub_mr.sh $(basename "$player_dir")"
}

parse_args "$@"

[[ -d "$MR_DIR" ]] || die "Missing UB-MR directory: ${MR_DIR}"

download_player
pull_runtime_image
verify_setup
