#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PATH="${REPO_ROOT}/UB-MR"
ROS_ENV_SCRIPT="${PROJECT_PATH}/Scripts/host_ros2_env.bash"
VERSION_FILE="${PROJECT_PATH}/ProjectSettings/ProjectVersion.txt"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: launch_ub_mr_dev.sh [--dry-run] [--help] [--] [Unity arguments...]

Open UB-MR in the Unity editor with ROS 2 Humble and the project's CycloneDDS
environment. The repository location is resolved from this script.

The editor version comes from UB-MR/ProjectSettings/ProjectVersion.txt.
Searches common Linux Unity Hub installation directories, then Unity on PATH.
For a custom installation, set UNITY_EDITOR to the editor executable:

  UNITY_EDITOR=/path/to/Editor/Unity ./launch/launch_ub_mr_dev.sh

ROS_DOMAIN_ID defaults to 0 and can be overridden in the environment.
Additional arguments are passed to Unity after -projectPath.

  --dry-run  Show the editor, project and environment without starting anything.
  --help     Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --) shift; break ;;
    *) break ;;
  esac
done

if [[ ! -r "${VERSION_FILE}" || ! -r "${ROS_ENV_SCRIPT}" ]]; then
  echo "Error: UB-MR project files are missing at ${PROJECT_PATH}. Initialize the UB-MR submodule first." >&2
  exit 1
fi
if [[ ! -r /opt/ros/humble/setup.bash ]]; then
  echo "Error: ROS 2 Humble setup was not found at /opt/ros/humble/setup.bash." >&2
  exit 1
fi

UNITY_VERSION="$(awk '$1 == "m_EditorVersion:" { print $2; exit }' "${VERSION_FILE}" | tr -d '\r')"
if [[ -z "${UNITY_VERSION}" ]]; then
  echo "Error: could not read the Unity editor version from ${VERSION_FILE}." >&2
  exit 1
fi

EDITOR_PATH=""
if [[ -n "${UNITY_EDITOR:-}" ]]; then
  EDITOR_PATH="$(command -v "${UNITY_EDITOR}" || true)"
else
  for editor_root in \
    "${HOME}/Unity/Hub/Editor" \
    "${HOME}/Unity/Editors" \
    "${HOME}/.local/share/UnityHub/Editors" \
    /opt/unity/Hub/Editor \
    /opt/unity/Editors; do
    candidate="${editor_root}/${UNITY_VERSION}/Editor/Unity"
    if [[ -x "${candidate}" ]]; then
      EDITOR_PATH="${candidate}"
      break
    fi
  done
  if [[ -z "${EDITOR_PATH}" ]]; then
    EDITOR_PATH="$(command -v Unity || true)"
  fi
fi

if [[ -z "${EDITOR_PATH}" || ! -f "${EDITOR_PATH}" || ! -x "${EDITOR_PATH}" ]]; then
  echo "Error: Unity ${UNITY_VERSION} was not found. Set UNITY_EDITOR to its Editor/Unity executable." >&2
  exit 1
fi
# Resolve relative executable overrides before changing the working directory.
EDITOR_PATH="$(cd "$(dirname "${EDITOR_PATH}")" && pwd)/$(basename "${EDITOR_PATH}")"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

echo "Unity editor: ${EDITOR_PATH} (project version: ${UNITY_VERSION})"
echo "Project: ${PROJECT_PATH}"
echo "ROS_DOMAIN_ID: ${ROS_DOMAIN_ID}"
if [[ "${DRY_RUN}" == 1 ]]; then
  printf 'Source environment: %s\n' "${ROS_ENV_SCRIPT}"
  printf 'Command:'
  printf ' %q' "${EDITOR_PATH}" -projectPath "${PROJECT_PATH}" "$@"
  printf '\n'
  exit 0
fi

cd "${REPO_ROOT}"
# The helper sources /opt/ros/humble/setup.bash, selects CycloneDDS and restarts
# ROS discovery. ROS setup scripts expect unset variables to be allowed.
set +u
source "${ROS_ENV_SCRIPT}"
set -u

exec "${EDITOR_PATH}" -projectPath "${PROJECT_PATH}" "$@"
