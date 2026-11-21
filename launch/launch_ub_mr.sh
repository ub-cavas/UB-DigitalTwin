#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${REPO_ROOT}/launch/lib/iap_tunnel.sh"
MR_DIR="${REPO_ROOT}/UB-MR"
PROJECT_PATH="${MR_DIR}"
ROS_ENV_SCRIPT="${PROJECT_PATH}/Scripts/host_ros2_env.bash"
VERSION_FILE="${PROJECT_PATH}/ProjectSettings/ProjectVersion.txt"
MR_CONTAINER_NAME=ub-mr-container
DEV=0 CARLA=0 AUTO=0 DRY_RUN=0 USE_IAP=0
VERSION="" VERSION_SET=0
INJECTION="" QUALITY=""
AUTOWARE_COMMAND=("${REPO_ROOT}/launch/launch_autoware_carla.sh")
UNITY_ARGS=()
PRIMARY_PID="" AUTO_PID="" COMPOSE_PID="" LOCALIZATION_PID="" MR_ATTEMPTED=0 MR_STARTED=0 MR_LOCALIZATION_STARTED=0
CARLA_OWNED=() CARLA_SERVICES=(carla map-loader)
export BUILD_FOLDER="${BUILD_FOLDER:-v1.1.0}"
export CARLA_ARGS="${CARLA_ARGS:--prefernvidia -quality-level=Epic -nosound}"
export UB_CARLA_EXTRA_SERVICES="${UB_CARLA_EXTRA_SERVICES:-}"
export UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY="${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY:-1}"
export UB_AUTOWARE_EGO_ONLY_PERCEPTION="${UB_AUTOWARE_EGO_ONLY_PERCEPTION:-1}"
export UB_AUTOWARE_CARLA_PLANNING_PRESET="${UB_AUTOWARE_CARLA_PLANNING_PRESET:-1}"
export UB_AUTOWARE_CONTROL_MODE_SHIM="${UB_AUTOWARE_CONTROL_MODE_SHIM:-0}"
export AUTOWARE_PLANNING_MODULE_PRESET="${AUTOWARE_PLANNING_MODULE_PRESET:-ub_carla}"
UB_MR_LOCALIZATION="${UB_MR_LOCALIZATION:-1}"
UB_KEEP_MR="${UB_KEEP_MR:-0}"

usage() {
  cat <<'EOF'
Usage: launch_ub_mr.sh [--dev | --version TAG] [--carla | --auto] [--iap] [--injection lidar|boxes|both]
                      [--quality Low|Epic] [--dry-run]
                      [-- Unity arguments...] (Unity arguments require --dev)

Default: run the latest UB-MR player in the existing ub-mr Docker image.
  --dev          Open the Unity editor (version from ProjectVersion.txt), or reuse one already
                 open for this project. The editor runs detached and is never closed by the launcher.
  --version TAG  Select a player release; cannot be combined with --dev.
  --carla        Also start CARLA and map-loader, without Autoware.
  --auto         Also start CARLA and Autoware; implies --carla.
  --injection MODE  Select Autoware routing/profile; requires --auto. Select the matching Unity agent separately.
  --quality LEVEL  Set CARLA's -quality-level (Low or Epic, case-insensitive; default Epic);
                 requires --carla or --auto. Replaces any -quality-level in CARLA_ARGS.
  --iap          Open a managed Redis-only IAP tunnel before starting clients.
  --dry-run      Print the selected commands without changing files or starting clients.
  --help, -h     Show help.

Player selection: --version > UB_MR_BUILD_FOLDER > UB_MR_RELEASE > latest.
Concrete releases use Builds/TAG (then numeric leading-v alias); missing players
use UB-MR/download_unity_player.sh. Latest resolves GitHub's current release.
BUILD_FOLDER selects CARLA only (default v1.1.0); IMAGE_NAME defaults to ub-mr
for the player. Optional component prerequisites are checked only when selected.
UB_KEEP_MR=1 keeps an owned player/localization; UB_KEEP_CARLA=1 keeps CARLA.
With --dev and no companions or --iap, the launcher exits after starting or reusing the editor.
A launched editor's console output goes to Client-Logs/ub-mr/unity-editor-console.log.

mr_pkg localization starts automatically: carla_localization with --carla/--auto,
otherwise autoware_localization (physical vehicle). The player runs it inside the
UB-MR container; the editor runs launch_mr_pkg_dev.sh. UB_MR_LOCALIZATION=0 skips it.

IAP uses authenticated gcloud/ssh, forwarding only Redis. In Main Menu -> Server
connection use 127.0.0.1:16390 and the remote Redis password. Override
UB_IAP_INSTANCE/PROJECT/ZONE, UB_IAP_REDIS_HOST/PORT or UB_IAP_LOCAL_REDIS_PORT.
The tunnel closes on exit, including UB_KEEP_MR=1. Preview with --iap --dry-run.
EOF
}
fail() { echo "Error: $*" >&2; exit 1; }
cli_error() { echo "Error: $*" >&2; exit 2; }
valid_selector() { [[ "$1" =~ ^[[:alnum:]][[:alnum:]_.+-]*$ && "$1" != *..* ]]; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --dev) DEV=1; shift ;;
    --carla) CARLA=1; shift ;;
    --auto) AUTO=1; CARLA=1; shift ;;
    --iap) USE_IAP=1; shift ;;
    --injection)
      [[ $# -ge 2 && "$2" =~ ^(lidar|boxes|both)$ ]] || cli_error '--injection requires lidar, boxes, or both.'
      INJECTION="$2"; shift 2 ;;
    --quality|--Quality)
      [[ $# -ge 2 ]] || cli_error '--quality requires Low or Epic.'
      case "${2,,}" in
        low) QUALITY=Low ;;
        epic) QUALITY=Epic ;;
        *) cli_error '--quality requires Low or Epic.' ;;
      esac
      shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --version)
      [[ $# -ge 2 && -n "$2" && "$2" != -* ]] || cli_error '--version requires a release tag.'
      VERSION="$2"; VERSION_SET=1; shift 2 ;;
    --) shift; UNITY_ARGS=("$@"); break ;;
    *) cli_error "Unknown argument: $1" ;;
  esac
done
if [[ -n "${INJECTION}" ]]; then
  [[ "${AUTO}" == 1 ]] || cli_error '--injection requires --auto.'
  AUTOWARE_COMMAND=("${REPO_ROOT}/launch/launch_autoware_carla_ub_mr_lidar.sh" --injection "${INJECTION}")
fi
if [[ -n "${QUALITY}" ]]; then
  [[ "${CARLA}" == 1 ]] || cli_error '--quality requires --carla or --auto.'
  read -r -a carla_arg_words <<< "${CARLA_ARGS}"
  quality_args=()
  for word in ${carla_arg_words[@]+"${carla_arg_words[@]}"}; do
    [[ "${word}" == -quality-level=* ]] || quality_args+=("${word}")
  done
  quality_args+=("-quality-level=${QUALITY}")
  CARLA_ARGS="${quality_args[*]}"
fi
# --carla selects the simulator bridge; without it, the physical-vehicle bridge.
if [[ "${CARLA}" == 1 ]]; then LOCALIZATION_NODE=carla_localization; else LOCALIZATION_NODE=autoware_localization; fi
LOCALIZATION_COMMAND=("${REPO_ROOT}/launch/launch_mr_pkg_dev.sh")
[[ "${CARLA}" == 1 ]] || LOCALIZATION_COMMAND+=(--physical)
[[ "${DEV}" != 1 || "${VERSION_SET}" != 1 ]] || cli_error '--dev and --version cannot be combined.'
[[ "${DEV}" == 1 || ${#UNITY_ARGS[@]} == 0 ]] || cli_error 'Unity arguments require --dev.'
if [[ "${VERSION_SET}" == 1 ]]; then
  RELEASE_SOURCE=--version
elif [[ -n "${UB_MR_BUILD_FOLDER:-}" ]]; then
  VERSION="${UB_MR_BUILD_FOLDER}"; RELEASE_SOURCE=UB_MR_BUILD_FOLDER
elif [[ -n "${UB_MR_RELEASE:-}" ]]; then
  VERSION="${UB_MR_RELEASE}"; RELEASE_SOURCE=UB_MR_RELEASE
else
  VERSION=latest; RELEASE_SOURCE=default
fi
if [[ "${DEV}" == 0 ]]; then
  valid_selector "${VERSION}" || cli_error "Unsafe release selector: ${VERSION}"
fi

require_command() { command -v "$1" >/dev/null 2>&1 || fail "Required command is unavailable: $1"; }
print_command() { printf '  '; printf '%q ' "$@"; printf '\n'; }
compose() { (cd "${REPO_ROOT}/CARLA"; docker compose "$@"); }
has_named_container() { docker ps -a --format '{{.Names}}' | grep -qx "${MR_CONTAINER_NAME}"; }
has_running_container() { docker ps --format '{{.Names}}' | grep -qx "${MR_CONTAINER_NAME}"; }
find_build() {
  local tag="$1" candidate alias=""
  UB_MR_BUILD_FOLDER=""
  if [[ "${tag}" =~ ^v[0-9]+(\.[0-9]+)*$ ]]; then alias="${tag#v}";
  elif [[ "${tag}" =~ ^[0-9]+(\.[0-9]+)*$ ]]; then alias="v${tag}"; fi
  for candidate in "${tag}" "${alias}"; do
    [[ -n "${candidate}" ]] || continue
    if [[ -f "${MR_DIR}/Builds/${candidate}/UB-MR.x86_64" ]]; then
      UB_MR_BUILD_FOLDER="${candidate}"; return 0
    fi
  done
  return 1
}
prepare_player() {
  require_command docker
  [[ -x "${MR_DIR}/run_ub_mr.sh" ]] || fail "Missing executable UB-MR Docker launcher: ${MR_DIR}/run_ub_mr.sh"
  if [[ "${VERSION}" == latest && "${DRY_RUN}" == 0 ]]; then
    require_command curl; require_command python3
    local metadata
    metadata="$(curl -fsSL https://api.github.com/repos/ub-cavas/UB-MR/releases/latest)" || fail 'Could not fetch latest UB-MR release metadata.'
    VERSION="$(printf '%s' "${metadata}" | python3 -c 'import json,sys; value=json.load(sys.stdin)["tag_name"]; assert isinstance(value,str) and value; print(value)')" || fail 'Invalid latest UB-MR release metadata.'
    valid_selector "${VERSION}" && [[ "${VERSION}" != latest ]] || fail "Invalid release tag in metadata: ${VERSION}"
  fi
  if [[ "${VERSION}" == latest ]]; then
    UB_MR_BUILD_FOLDER=latest
    echo 'Latest release is unresolved (dry run; no metadata requested).'
  elif ! find_build "${VERSION}"; then
    UB_MR_BUILD_FOLDER="${VERSION}"
    if [[ "${DRY_RUN}" == 1 ]]; then
      echo "Player is not cached; would download release ${VERSION}."
      print_command "${MR_DIR}/download_unity_player.sh" "${VERSION}"
    else
      [[ -x "${MR_DIR}/download_unity_player.sh" ]] || fail 'Missing executable UB-MR/download_unity_player.sh.'
      require_command curl; require_command tar; require_command unzip
      (cd "${MR_DIR}"; ./download_unity_player.sh "${VERSION}")
      find_build "${VERSION}" || fail "Downloaded release did not provide Builds/${VERSION}/UB-MR.x86_64 (or numeric v alias)."
    fi
  fi
  if [[ "${DRY_RUN}" == 0 ]]; then
    chmod +x "${MR_DIR}/Builds/${UB_MR_BUILD_FOLDER}/UB-MR.x86_64"
  fi
}
prepare_editor() {
  if [[ ! -r "${VERSION_FILE}" || ! -r "${ROS_ENV_SCRIPT}" ]]; then
    echo "Error: UB-MR project files are missing at ${PROJECT_PATH}. Initialize the UB-MR submodule first." >&2
    exit 1
  fi
  if [[ ! -r "/opt/ros/humble/setup.bash" ]]; then
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
  export UB_CLIENT_LOG_ROOT="${UB_CLIENT_LOG_ROOT:-${REPO_ROOT}/Client-Logs}"
  export UB_CLIENT_LOG_DIR="${UB_CLIENT_LOG_DIR:-${UB_CLIENT_LOG_ROOT}/ub-mr}"
  export UB_EXPERIMENT_DIR="${UB_EXPERIMENT_DIR:-${UB_EXPERIMENT_HOST_DIR:-${UB_MR_METRICS_DIR:-${UB_CLIENT_LOG_DIR}/experiments}}}"
  EDITOR_LOG_ARGS=(-logFile "${UB_CLIENT_LOG_DIR}/unity-editor.log")
  for argument in "${UNITY_ARGS[@]}"; do
    if [[ "${argument}" == -logFile || "${argument}" == -logFile=* ]]; then
      EDITOR_LOG_ARGS=()
      break
    fi
  done
  if [[ ${#EDITOR_LOG_ARGS[@]} -gt 0 ]]; then EDITOR_LOG_DESC="${EDITOR_LOG_ARGS[1]}"; else EDITOR_LOG_DESC='explicit -logFile argument'; fi
  EDITOR_CONSOLE_LOG="${UB_CLIENT_LOG_DIR}/unity-editor-console.log"
}
# Finds a Unity process already open for PROJECT_PATH with a read-only /proc scan
# (no processes started). UB-MR/Temp/UnityLockfile is deliberately not consulted:
# it survives crashes, probing its flock could race with a starting editor, and it
# names no PID. If it is stale, Unity resolves that on its own launch.
# The main editor is reported in preference to its AssetImportWorker children,
# which carry the same -projectPath: a match whose parent also matches is skipped.
find_running_editor() {
  local proc pid target index argument value cwd resolved parent status_line
  local -a argv matches=()
  EXISTING_EDITOR_PID=""
  target="$(cd "${PROJECT_PATH}" && pwd -P)" || return 1
  for proc in /proc/[0-9]*; do
    pid="${proc#/proc/}"
    [[ "${pid}" != "$$" && "${pid}" != "${BASHPID}" ]] || continue
    mapfile -d '' -t argv 2>/dev/null <"${proc}/cmdline" || continue
    [[ ${#argv[@]} -ge 2 ]] || continue
    # argv[0] is a real editor (Hub launches, import workers); argv[1] is an
    # editor started through an interpreter or wrapper.
    [[ "${argv[0]##*/}" == Unity || "${argv[1]##*/}" == Unity ]] || continue
    value=""
    for ((index=1; index<${#argv[@]}; index++)); do
      argument="${argv[index]}"
      if [[ "${argument,,}" == -projectpath ]]; then
        [[ $((index + 1)) -lt ${#argv[@]} ]] && value="${argv[index + 1]}"
        break
      elif [[ "${argument,,}" == -projectpath=* ]]; then
        value="${argument#*=}"
        break
      fi
    done
    [[ -n "${value}" ]] || continue
    if [[ "${value}" != /* ]]; then
      cwd="$(readlink "${proc}/cwd" 2>/dev/null)" || continue
      [[ -n "${cwd}" ]] || continue
      # Unity changes into the project root after startup, so a relative
      # -projectPath also matches when the process cwd is the project itself.
      resolved="$(cd "${cwd}" 2>/dev/null && pwd -P)" || resolved=""
      if [[ "${resolved}" == "${target}" ]]; then matches+=("${pid}"); continue; fi
      value="${cwd}/${value}"
    fi
    resolved="$(cd "${value}" 2>/dev/null && pwd -P)" || continue
    [[ "${resolved}" != "${target}" ]] || matches+=("${pid}")
  done
  [[ ${#matches[@]} -gt 0 ]] || return 1
  for pid in "${matches[@]}"; do
    parent=""
    while IFS= read -r status_line; do
      if [[ "${status_line}" == PPid:* ]]; then parent="${status_line#PPid:}"; parent="${parent//[[:space:]]/}"; break; fi
    done 2>/dev/null <"/proc/${pid}/status" || true
    if [[ -z "${parent}" || " ${matches[*]} " != *" ${parent} "* ]]; then
      EXISTING_EDITOR_PID="${pid}"
      return 0
    fi
  done
  # Every match has a matching parent (not expected); report the first one.
  EXISTING_EDITOR_PID="${matches[0]}"
  return 0
}
report_existing_editor() {
  local prefix="${1:-}" quoted
  if [[ -n "${prefix}" ]]; then
    echo "${prefix}Unity editor is already open for ${PROJECT_PATH}; would reuse running editor PID ${EXISTING_EDITOR_PID}."
  else
    echo "Unity editor is already open for ${PROJECT_PATH} (PID ${EXISTING_EDITOR_PID}); not launching another."
  fi
  if [[ ${#UNITY_ARGS[@]} -gt 0 ]]; then
    printf -v quoted '%q ' "${UNITY_ARGS[@]}"
    echo "Warning: the existing editor keeps its own settings; Unity arguments after -- (${quoted% }) and -logFile (${EDITOR_LOG_DESC}) are not applied." >&2
  else
    echo "Warning: the existing editor keeps its own settings; -logFile (${EDITOR_LOG_DESC}) is not applied." >&2
  fi
}

# All selected prerequisites are checked before any tunnel or application starts.
if [[ "${DEV}" == 1 ]]; then prepare_editor; else prepare_player; fi
if [[ "${CARLA}" == 1 && "${AUTO}" == 0 ]]; then
  require_command docker
  [[ -f "${REPO_ROOT}/CARLA/docker-compose.yml" ]] || fail 'Missing CARLA/docker-compose.yml.'
  [[ -f "${REPO_ROOT}/CARLA/Builds/${BUILD_FOLDER}/CarlaUE4.sh" ]] || fail "Missing CARLA player for BUILD_FOLDER=${BUILD_FOLDER}."
  docker compose version >/dev/null || fail 'Docker Compose v2 is required for --carla.'
  export CARLA_MAP_PATH="${CARLA_MAP_PATH:-/Game/Carla/Maps/${CARLA_MAP:-UBAutonomousProvingGrounds}}"
  export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
  if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then export XAUTHORITY="${HOME}/.Xauthority"; fi
  if [[ -n "${UB_CARLA_EXTRA_SERVICES}" ]]; then
    read -r -a extra_services <<< "${UB_CARLA_EXTRA_SERVICES}"
    for service in "${extra_services[@]}"; do
      [[ "${service}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || fail "Invalid CARLA service: ${service}"
      if [[ " ${CARLA_SERVICES[*]} " != *" ${service} "* ]]; then CARLA_SERVICES+=("${service}"); fi
    done
  fi
fi
if [[ "${AUTO}" == 1 ]]; then
  [[ -x "${AUTOWARE_COMMAND[0]}" ]] || fail 'Missing executable Autoware/CARLA launcher.'
  "${AUTOWARE_COMMAND[@]}" --dry-run
fi
if [[ "${DEV}" == 1 && "${UB_MR_LOCALIZATION}" == 1 ]]; then
  [[ -x "${LOCALIZATION_COMMAND[0]}" ]] || fail 'Missing executable launch/launch_mr_pkg_dev.sh.'
  # Read-only preflight: checks the mr_pkg sources and ROS environment helper.
  if [[ "${DRY_RUN}" == 1 ]]; then
    "${LOCALIZATION_COMMAND[@]}" --dry-run
  else
    "${LOCALIZATION_COMMAND[@]}" --dry-run >/dev/null
  fi
fi

echo "UB-MR mode: $([[ "${DEV}" == 1 ]] && echo editor || echo player); CARLA=${CARLA}; Autoware=${AUTO}"
echo "mr_pkg localization: $([[ "${UB_MR_LOCALIZATION}" == 1 ]] && echo "${LOCALIZATION_NODE}" || echo 'disabled (UB_MR_LOCALIZATION=0)')"
if [[ "${DEV}" == 0 ]]; then echo "Player release: ${VERSION} (source: ${RELEASE_SOURCE}); build: ${UB_MR_BUILD_FOLDER}"; fi
if [[ "${DRY_RUN}" == 1 ]]; then
  [[ "${USE_IAP}" != 1 ]] || ub_iap_preview redis
  if [[ "${DEV}" == 1 ]]; then
    echo "Source environment: ${ROS_ENV_SCRIPT}"
    if find_running_editor; then
      report_existing_editor 'Dry run: '
    else
      echo 'Unity editor: not running; would launch detached:'
      print_command "${EDITOR_PATH}" -projectPath "${PROJECT_PATH}" "${EDITOR_LOG_ARGS[@]}" "${UNITY_ARGS[@]}"
      echo "  console output -> ${EDITOR_CONSOLE_LOG}"
    fi
    if [[ "${UB_MR_LOCALIZATION}" == 1 ]]; then print_command "${LOCALIZATION_COMMAND[@]}"; fi
  else
    echo "Runtime image: ${IMAGE_NAME:-ub-mr}"
    print_command "${MR_DIR}/run_ub_mr.sh" "${UB_MR_BUILD_FOLDER}" /app/ub-mr.sh
    if [[ "${UB_MR_LOCALIZATION}" == 1 ]]; then
      print_command docker exec -d "${MR_CONTAINER_NAME}" bash -lc "ros2 launch mr_pkg ${LOCALIZATION_NODE}.launch.py"
    fi
  fi
  if [[ "${AUTO}" == 1 ]]; then
    print_command "${AUTOWARE_COMMAND[@]}"
  elif [[ "${CARLA}" == 1 ]]; then
    echo "CARLA cwd: ${REPO_ROOT}/CARLA; BUILD_FOLDER=${BUILD_FOLDER}; CARLA_ARGS=${CARLA_ARGS}; CARLA_MAP_PATH=${CARLA_MAP_PATH}"
    print_command docker compose up --build --no-deps -d "${CARLA_SERVICES[@]}"
  fi
  exit 0
fi
require_command setsid

# Every managed application is a session leader, so cleanup also reaches its
# descendants. The Unity editor is the exception: it is launched fully detached
# (or reused) and is never tracked or stopped by the launcher.
# Polling keeps Bash's signal traps responsive; waits only reap exited children.
stop_child() {
  local pid="$1" signal="${2:-TERM}" attempts="${3:-50}" attempt
  [[ -n "${pid}" ]] || return 0
  # A child signalled just after launch may not have called setsid yet, so its
  # process group does not exist; signal the process itself in that case.
  kill -"${signal}" -- "-${pid}" 2>/dev/null || kill -"${signal}" "${pid}" 2>/dev/null || true
  for ((attempt=0; attempt<attempts; attempt++)); do
    kill -0 -- "-${pid}" 2>/dev/null || break
    sleep 0.1
  done
  kill -KILL -- "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
  wait "${pid}" 2>/dev/null || true
}
cleanup() {
  local status="$?"
  trap - EXIT INT TERM
  # Only launcher-owned processes are stopped here. In --dev, PRIMARY_PID stays
  # empty: the editor is intentionally never tracked, so it outlives the launcher.
  # The Autoware delegate owns its stack teardown. Give it time to run its trap.
  stop_child "${AUTO_PID}" INT 600
  stop_child "${COMPOSE_PID}"
  stop_child "${LOCALIZATION_PID}"
  # A startup signal can arrive after Docker creates the container but before
  # readiness is observed. Only claim it after observing creation; preexisting
  # named containers are rejected before launching the runtime.
  if [[ "${MR_ATTEMPTED}" == 1 && "${MR_STARTED}" == 0 ]] && has_named_container; then MR_STARTED=1; fi
  if [[ "${UB_KEEP_MR}" != 1 ]]; then
    if [[ "${MR_LOCALIZATION_STARTED}" == 1 ]]; then
      docker exec "${MR_CONTAINER_NAME}" bash -lc 'pkill -TERM -f "ros2 launch mr_pkg $1.launch.py" || true; pkill -TERM -f "mr_pkg.*$1" || true' bash "${LOCALIZATION_NODE}" >/dev/null 2>&1 || true
    fi
    if [[ "${MR_STARTED}" == 1 ]]; then docker rm -f "${MR_CONTAINER_NAME}" >/dev/null 2>&1 || true; fi
  fi
  if [[ "${DEV}" == 0 && "${UB_KEEP_MR}" == 1 ]]; then
    # docker run proxies catchable signals to the container. SIGKILL only
    # detaches the host CLI; it cannot be forwarded to the retained player.
    stop_child "${PRIMARY_PID}" KILL 0
  else
    stop_child "${PRIMARY_PID}"
  fi
  if [[ ${#CARLA_OWNED[@]} -gt 0 && "${UB_KEEP_CARLA:-0}" != 1 ]]; then
    compose stop -t 5 "${CARLA_OWNED[@]}" >/dev/null 2>&1 || true
    compose rm -f "${CARLA_OWNED[@]}" >/dev/null 2>&1 || true
  fi
  ub_iap_cleanup
  exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

child_status() {
  local code=0
  wait "$1" || code="$?"
  return "${code}"
}
check_primary() {
  if [[ -n "${PRIMARY_PID}" ]] && ! kill -0 "${PRIMARY_PID}" 2>/dev/null; then
    child_status "${PRIMARY_PID}"
    exit 0
  fi
}
check_companion() {
  local status=0
  if [[ -n "${AUTO_PID}" ]] && ! kill -0 "${AUTO_PID}" 2>/dev/null; then
    child_status "${AUTO_PID}" || status="$?"
    echo "Error: Autoware/CARLA exited unexpectedly (status ${status})." >&2
    [[ "${status}" != 0 ]] || status=1
    exit "${status}"
  fi
  if [[ -n "${LOCALIZATION_PID}" ]] && ! kill -0 "${LOCALIZATION_PID}" 2>/dev/null; then
    child_status "${LOCALIZATION_PID}" || status="$?"
    LOCALIZATION_PID=""
    echo "Error: mr_pkg ${LOCALIZATION_NODE} exited unexpectedly (status ${status})." >&2
    [[ "${status}" != 0 ]] || status=1
    exit "${status}"
  fi
}
carla_running() {
  local id
  id="$(compose ps -q carla)"
  [[ -n "${id}" && "$(docker inspect -f '{{.State.Running}}' "${id}")" == true ]]
}
check_carla_extra_services() {
  local service id
  for service in "${CARLA_SERVICES[@]}"; do
    # map-loader exits successfully by design; all other selected services
    # must remain alive for the duration of the session.
    [[ "${service}" != carla && "${service}" != map-loader ]] || continue
    id="$(compose ps -q "${service}")"
    if [[ -z "${id}" || "$(docker inspect -f '{{.State.Running}}' "${id}")" != true ]]; then
      fail "CARLA companion service '${service}' exited or disappeared unexpectedly."
    fi
  done
}
start_carla() {
  local service id state
  for service in "${CARLA_SERVICES[@]}"; do
    # Preserve running selected services. --no-deps prevents implicit ownership.
    id="$(compose ps --status running -q "${service}")"
    if [[ -z "${id}" ]]; then CARLA_OWNED+=("${service}"); fi
  done
  if [[ ${#CARLA_OWNED[@]} -gt 0 ]]; then
    if command -v xhost >/dev/null 2>&1; then xhost +local:root >/dev/null || true; fi
    (cd "${REPO_ROOT}/CARLA"; exec setsid env --default-signal=INT --default-signal=TERM docker compose up --build --no-deps -d "${CARLA_OWNED[@]}") &
    COMPOSE_PID="$!"
    while kill -0 "${COMPOSE_PID}" 2>/dev/null; do
      check_primary
      sleep 0.1
    done
    child_status "${COMPOSE_PID}"
    COMPOSE_PID=""
  fi
  for _ in {1..600}; do
    check_primary
    id="$(compose ps -a -q map-loader)"
    if [[ -n "${id}" ]]; then
      state="$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' "${id}")"
      case "${state}" in
        'exited 0') carla_running || fail 'CARLA exited during map loading.'; return 0 ;;
        exited*|dead*) fail "CARLA map-loader failed: ${state}" ;;
      esac
    fi
    sleep 0.1
  done
  fail 'Timed out waiting for CARLA map-loader.'
}

if [[ "${DEV}" == 0 ]] && has_named_container && ! has_running_container; then
  fail "A stopped container named ${MR_CONTAINER_NAME} already exists; remove or rename it before launching UB-MR."
fi
if [[ "${DEV}" == 1 ]]; then
  cd "${REPO_ROOT}"
  mkdir -p "${UB_CLIENT_LOG_DIR}"
  set +u
  source "${ROS_ENV_SCRIPT}"
  set -u
fi
if [[ "${USE_IAP}" == 1 ]]; then
  ub_iap_start redis
  echo "UB-MR Server connection: 127.0.0.1:${UB_IAP_LOCAL_REDIS_PORT:-16390}; enter the remote Redis password in the menu."
fi
if [[ "${DEV}" == 1 ]]; then
  # Detect as late as possible to narrow the race with another launcher.
  if find_running_editor; then
    report_existing_editor
  else
    # --fork returns at once; the editor runs in its own session with no
    # controlling terminal and no inherited stdio, so signals, terminal closure
    # and companion failures never reach it.
    setsid --fork env --default-signal=INT --default-signal=TERM \
      "${EDITOR_PATH}" -projectPath "${PROJECT_PATH}" "${EDITOR_LOG_ARGS[@]}" "${UNITY_ARGS[@]}" \
      </dev/null >>"${EDITOR_CONSOLE_LOG}" 2>&1
    echo "Started Unity editor (detached; console output: ${EDITOR_CONSOLE_LOG})."
    echo "If the editor window does not appear, check ${EDITOR_CONSOLE_LOG} and the -logFile output."
  fi
else
  if has_running_container; then
    mounted="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/UB-MR-Player"}}{{.Source}}{{end}}{{end}}' "${MR_CONTAINER_NAME}")"
    expected="$(cd "${MR_DIR}/Builds/${UB_MR_BUILD_FOLDER}" && pwd -P)"
    [[ "${mounted}" == "${expected}" ]] || fail "Running UB-MR container mounts '${mounted}', expected '${expected}'; stop it before selecting this release."
    echo 'Reusing the running UB-MR container.'
    setsid bash -c 'status=$(docker wait "$1") || exit "$?"; [[ "$status" =~ ^[0-9]+$ ]] || exit 1; exit "$status"' bash "${MR_CONTAINER_NAME}" &
    PRIMARY_PID="$!"
  else
    if has_named_container; then fail "A stopped container named ${MR_CONTAINER_NAME} already exists; remove or rename it before launching UB-MR."; fi
    MR_ATTEMPTED=1
    (cd "${MR_DIR}"; exec setsid env --default-signal=INT --default-signal=TERM ./run_ub_mr.sh "${UB_MR_BUILD_FOLDER}" /app/ub-mr.sh) &
    PRIMARY_PID="$!"
    ready=0
    for _ in {1..600}; do
      # An early successful CLI exit is still a startup failure.
      if ! kill -0 "${PRIMARY_PID}" 2>/dev/null; then
        status=0; child_status "${PRIMARY_PID}" || status="$?"
        [[ "${status}" != 0 ]] || status=1
        echo 'Error: UB-MR runtime exited before container readiness.' >&2
        exit "${status}"
      fi
      if has_running_container; then MR_STARTED=1; ready=1; break; fi
      sleep 0.1
    done
    [[ "${ready}" == 1 ]] || fail 'Timed out waiting for UB-MR container.'
  fi
fi
if [[ "${AUTO}" == 1 ]]; then
  setsid env --default-signal=INT --default-signal=TERM "${AUTOWARE_COMMAND[@]}" &
  AUTO_PID="$!"
elif [[ "${CARLA}" == 1 ]]; then
  start_carla
fi
if [[ "${UB_MR_LOCALIZATION}" == 1 && "${DEV}" == 1 ]]; then
  echo "Starting mr_pkg ${LOCALIZATION_NODE} for the editor."
  setsid env --default-signal=INT --default-signal=TERM "${LOCALIZATION_COMMAND[@]}" &
  LOCALIZATION_PID="$!"
elif [[ "${UB_MR_LOCALIZATION}" == 1 ]]; then
  echo "Starting mr_pkg ${LOCALIZATION_NODE} in ${MR_CONTAINER_NAME}."
  MR_LOCALIZATION_STARTED=1
  docker exec -d "${MR_CONTAINER_NAME}" bash -lc '
set -eo pipefail
source /app/ub-mr-env.sh
ROS_ENV_SCRIPT="${UB_MR_ROS_ENV_SCRIPT:-/app/Scripts/host_ros2_env.bash}"
if [[ -f "${ROS_ENV_SCRIPT}" ]]; then source "${ROS_ENV_SCRIPT}"; fi
exec ros2 launch mr_pkg "$1.launch.py"' bash "${LOCALIZATION_NODE}"
fi
if [[ "${DEV}" == 1 && "${CARLA}" == 0 && -z "${LOCALIZATION_PID}" && "${USE_IAP}" == 0 ]]; then
  echo 'No companions selected; leaving the Unity editor running and exiting.'
  exit 0
fi
while :; do
  check_companion
  check_primary
  if [[ "${CARLA}" == 1 && "${AUTO}" == 0 ]]; then
    carla_running || fail 'CARLA exited unexpectedly.'
    check_carla_extra_services
  fi
  sleep 0.2
done
