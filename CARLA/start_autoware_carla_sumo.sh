#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BRIDGE_DIR="${SCRIPT_DIR}/UB-API/carla-autoware-sumo-bridge"

has_files() {
  local path="$1"
  [[ -d "${path}" ]] || return 1
  find "${path}" -mindepth 1 -maxdepth 2 -print -quit 2>/dev/null | grep -q .
}

BUILD_FOLDER="${BUILD_FOLDER:-v1.0.0}"
CARLA_MAP="${CARLA_MAP:-UBAutonomousProvingGrounds}"
CARLA_MAP_PATH="${CARLA_MAP_PATH:-/Game/Carla/Maps/${CARLA_MAP}}"
CARLA_ARGS="${CARLA_ARGS:--prefernvidia -quality-level=Epic -nosound}"

DEFAULT_AUTOWARE_HOST_MAP_DIR="${REPO_DIR}/Autoware/host_data/maps/ub_autonomous_proving_grounds"
DEFAULT_AUTOWARE_MAP_PATH="/host_data/maps/ub_autonomous_proving_grounds"
LEGACY_AUTOWARE_HOST_MAP_DIR="${REPO_DIR}/Autoware/host_data/ub_autonomous_proving_grounds"
LEGACY_AUTOWARE_MAP_PATH="/host_data/ub_autonomous_proving_grounds"

if [[ -z "${AUTOWARE_HOST_MAP_DIR:-}" && -z "${AUTOWARE_MAP_PATH:-}" ]] && has_files "${LEGACY_AUTOWARE_HOST_MAP_DIR}" && ! has_files "${DEFAULT_AUTOWARE_HOST_MAP_DIR}"; then
  AUTOWARE_HOST_MAP_DIR="${LEGACY_AUTOWARE_HOST_MAP_DIR}"
  AUTOWARE_MAP_PATH="${LEGACY_AUTOWARE_MAP_PATH}"
fi

AUTOWARE_DOCKER_DIR="${AUTOWARE_DOCKER_DIR:-${REPO_DIR}/Autoware/ub-lincoln-docker/docker}"
AUTOWARE_HOST_MAP_DIR="${AUTOWARE_HOST_MAP_DIR:-${DEFAULT_AUTOWARE_HOST_MAP_DIR}}"
AUTOWARE_MAP_PATH="${AUTOWARE_MAP_PATH:-${DEFAULT_AUTOWARE_MAP_PATH}}"
AUTOWARE_SERVICE="${AUTOWARE_SERVICE:-autoware}"
AUTOWARE_CARLA_HOST="${AUTOWARE_CARLA_HOST:-127.0.0.1}"
AUTOWARE_VEHICLE_MODEL="${AUTOWARE_VEHICLE_MODEL:-sample_vehicle}"
AUTOWARE_SENSOR_MODEL="${AUTOWARE_SENSOR_MODEL:-awsim_sensor_kit}"
AUTOWARE_RVIZ="${AUTOWARE_RVIZ:-}"
AUTOWARE_PLANNING_MODULE_PRESET="${AUTOWARE_PLANNING_MODULE_PRESET:-}"
AUTOWARE_E2E_SIMULATOR_TYPE="${AUTOWARE_E2E_SIMULATOR_TYPE:-awsim}"
AUTOWARE_CARLA_POINTCLOUD_RELAY="${AUTOWARE_CARLA_POINTCLOUD_RELAY:-1}"
UB_AUTOWARE_INSTALL_PY_DEPS="${UB_AUTOWARE_INSTALL_PY_DEPS:-1}"
UB_AUTOWARE_HOST_CONFIG_DDS="${UB_AUTOWARE_HOST_CONFIG_DDS:-1}"
UB_AUTOWARE_RMW_IMPLEMENTATION="${UB_AUTOWARE_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
UB_AUTOWARE_CYCLONEDDS_URI="${UB_AUTOWARE_CYCLONEDDS_URI:-file:///resources/cyclonedds.xml}"
UB_AUTOWARE_CLEAN_STALE_PROCESSES="${UB_AUTOWARE_CLEAN_STALE_PROCESSES:-1}"
UB_KEEP_CARLA="${UB_KEEP_CARLA:-0}"
UB_KEEP_AUTOWARE_ROS="${UB_KEEP_AUTOWARE_ROS:-0}"
UB_KEEP_SUMO="${UB_KEEP_SUMO:-0}"
UB_KEEP_ON_ERROR="${UB_KEEP_ON_ERROR:-1}"
UB_AUTOWARE_CAMERA_FOLLOW="${UB_AUTOWARE_CAMERA_FOLLOW:-1}"
UB_AUTOWARE_CAMERA_FOLLOW_HOST="${UB_AUTOWARE_CAMERA_FOLLOW_HOST:-127.0.0.1}"
UB_AUTOWARE_CAMERA_FOLLOW_PORT="${UB_AUTOWARE_CAMERA_FOLLOW_PORT:-2000}"
UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES="${UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES:-ego_vehicle}"
UB_AUTOWARE_CAMERA_FOLLOW_WAIT_SECONDS="${UB_AUTOWARE_CAMERA_FOLLOW_WAIT_SECONDS:-0}"
UB_AUTOWARE_CAMERA_FOLLOW_DISTANCE_M="${UB_AUTOWARE_CAMERA_FOLLOW_DISTANCE_M:-8.0}"
UB_AUTOWARE_CAMERA_FOLLOW_HEIGHT_M="${UB_AUTOWARE_CAMERA_FOLLOW_HEIGHT_M:-3.0}"
UB_AUTOWARE_CAMERA_FOLLOW_PITCH_DEG="${UB_AUTOWARE_CAMERA_FOLLOW_PITCH_DEG:--12.0}"
UB_AUTOWARE_CAMERA_FOLLOW_UPDATE_HZ="${UB_AUTOWARE_CAMERA_FOLLOW_UPDATE_HZ:-30.0}"

SUMO_BRIDGE_COMPOSE_FILE="${SUMO_BRIDGE_COMPOSE_FILE:-${TMPDIR:-/tmp}/ub-carla-sumo-bridge-compose-$(id -u).yml}"
SUMO_BRIDGE_IMAGE="${SUMO_BRIDGE_IMAGE:-ub-carla-sumo-bridge}"
SUMO_BRIDGE_CONTAINER_NAME="${SUMO_BRIDGE_CONTAINER_NAME:-ub-carla-sumo-bridge}"
UB_SUMO_SCENARIO_DIR="${UB_SUMO_SCENARIO_DIR:-${REPO_DIR}/Scenarios/SUMO/RandomTraffic}"

UB_SUMO_CONFIG="${UB_SUMO_CONFIG:-UBAutonomousProvingGrounds.sumocfg}"
UB_SUMO_STEP_LENGTH="${UB_SUMO_STEP_LENGTH:-0.05}"
UB_SUMO_GUI="${UB_SUMO_GUI:-1}"
UB_SUMO_AUTO_START="${UB_SUMO_AUTO_START:-1}"
UB_SUMO_TLS_MANAGER="${UB_SUMO_TLS_MANAGER:-sumo}"
UB_SUMO_SYNC_VEHICLE_COLOR="${UB_SUMO_SYNC_VEHICLE_COLOR:-0}"
UB_SUMO_SYNC_VEHICLE_LIGHTS="${UB_SUMO_SYNC_VEHICLE_LIGHTS:-0}"
UB_SUMO_EXTRA_ARGS="${UB_SUMO_EXTRA_ARGS:-}"
UB_SUMO_RANDOM_TRAFFIC="${UB_SUMO_RANDOM_TRAFFIC:-0}"
UB_SUMO_RANDOM_VEHICLES="${UB_SUMO_RANDOM_VEHICLES:-25}"
UB_SUMO_RANDOM_WALKERS="${UB_SUMO_RANDOM_WALKERS:-0}"
UB_SUMO_RANDOM_SAFE="${UB_SUMO_RANDOM_SAFE:-1}"
UB_SUMO_RANDOM_FILTERV="${UB_SUMO_RANDOM_FILTERV:-vehicle.*}"
UB_SUMO_RANDOM_FILTERW="${UB_SUMO_RANDOM_FILTERW:-walker.pedestrian.*}"
UB_SUMO_RANDOM_EXTRA_ARGS="${UB_SUMO_RANDOM_EXTRA_ARGS:-}"

DRY_RUN=0
CARLA_STARTED=0
SUMO_STARTED=0
CAMERA_FOLLOW_STARTED=0
AUTOWARE_LAUNCH_STARTED=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run] [--help]

Start single-machine UB-CARLA + SUMO + Autoware using the custom
carla-autoware-sumo-bridge. SUMO is the time master; Autoware's CARLA
interface is launched with external_tick:=True.

Defaults:
  BUILD_FOLDER=${BUILD_FOLDER}
  CARLA_MAP=${CARLA_MAP}
  CARLA_ARGS=${CARLA_ARGS}
  UB_SUMO_CONFIG=${UB_SUMO_CONFIG}
  UB_SUMO_SCENARIO_DIR=${UB_SUMO_SCENARIO_DIR}
  UB_SUMO_STEP_LENGTH=${UB_SUMO_STEP_LENGTH}
  UB_SUMO_GUI=${UB_SUMO_GUI}
  UB_SUMO_AUTO_START=${UB_SUMO_AUTO_START}
  UB_SUMO_TLS_MANAGER=${UB_SUMO_TLS_MANAGER}
  UB_SUMO_RANDOM_TRAFFIC=${UB_SUMO_RANDOM_TRAFFIC}
  UB_SUMO_RANDOM_VEHICLES=${UB_SUMO_RANDOM_VEHICLES}
  UB_SUMO_RANDOM_SAFE=${UB_SUMO_RANDOM_SAFE}
  UB_KEEP_ON_ERROR=${UB_KEEP_ON_ERROR}
  UB_AUTOWARE_CAMERA_FOLLOW=${UB_AUTOWARE_CAMERA_FOLLOW}
  UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES=${UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES}
  UB_AUTOWARE_CAMERA_FOLLOW_UPDATE_HZ=${UB_AUTOWARE_CAMERA_FOLLOW_UPDATE_HZ}
  AUTOWARE_MAP_PATH=${AUTOWARE_MAP_PATH}
  AUTOWARE_SERVICE=${AUTOWARE_SERVICE}
  AUTOWARE_VEHICLE_MODEL=${AUTOWARE_VEHICLE_MODEL}
  AUTOWARE_SENSOR_MODEL=${AUTOWARE_SENSOR_MODEL}
  AUTOWARE_E2E_SIMULATOR_TYPE=${AUTOWARE_E2E_SIMULATOR_TYPE}
  AUTOWARE_CARLA_POINTCLOUD_RELAY=${AUTOWARE_CARLA_POINTCLOUD_RELAY}

Useful overrides:
  UB_SUMO_RANDOM_VEHICLES=40 $(basename "$0")
  UB_SUMO_GUI=0 $(basename "$0")
  UB_SUMO_SCENARIO_DIR=/path/to/scenario $(basename "$0")
  UB_SUMO_RANDOM_TRAFFIC=1 $(basename "$0")
  UB_SUMO_SCENARIO_DIR= UB_SUMO_CONFIG=Town01.sumocfg $(basename "$0")
  UB_SUMO_EXTRA_ARGS="--debug" $(basename "$0")
  AUTOWARE_RVIZ=false $(basename "$0")
  UB_KEEP_ON_ERROR=0 $(basename "$0")
  UB_AUTOWARE_CAMERA_FOLLOW=0 $(basename "$0")
  UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES=ego_vehicle $(basename "$0")
  UB_KEEP_CARLA=1 UB_KEEP_SUMO=1 $(basename "$0")

Options:
  --dry-run  Validate prerequisites and print commands without starting containers.
  --help     Show this help text.
EOF
}

setup_hint() {
  cat <<EOF

Setup hints:
  CARLA build:
    bash scripts/install_ub_carla.sh ${BUILD_FOLDER}

  Autoware submodule, image, and UB HD map:
    cd Autoware
    ./setup_autoware.sh

  Autoware DDS host settings:
    cd ${AUTOWARE_DOCKER_DIR}
    ../scripts/host_config_dds.bash
EOF
}

collect_preflight_failures() {
  local failures_ref="$1"
  local -n preflight_failures="${failures_ref}"

  if ! command -v docker >/dev/null 2>&1; then
    preflight_failures+=("Docker is not installed or not on PATH.")
  elif ! docker compose version >/dev/null 2>&1; then
    preflight_failures+=("Docker Compose v2 is unavailable. Install the Docker Compose plugin so 'docker compose' works.")
  elif ! docker info >/dev/null 2>&1; then
    preflight_failures+=("Docker daemon is unreachable or this user cannot access /var/run/docker.sock.")
  fi

  if [[ ! -x "${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/CarlaUE4.sh" ]]; then
    preflight_failures+=("Missing executable CARLA build: ${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/CarlaUE4.sh")
  fi

  if ! find "${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/PythonAPI/carla/dist" -maxdepth 1 -type f -name 'carla-*-cp310-*.whl' -print -quit 2>/dev/null | grep -q .; then
    preflight_failures+=("Missing CARLA Python cp310 wheel under ${SCRIPT_DIR}/Builds/${BUILD_FOLDER}/PythonAPI/carla/dist.")
  fi

  if bool_enabled "${UB_SUMO_RANDOM_TRAFFIC}"; then
    if [[ ! -f "${BRIDGE_DIR}/Sumo/spawn_npc_sumo.py" ]]; then
      preflight_failures+=("Missing random SUMO traffic launcher: ${BRIDGE_DIR}/Sumo/spawn_npc_sumo.py")
    fi
    if [[ ! -f "${BRIDGE_DIR}/Sumo/data/vtypes.json" ]]; then
      preflight_failures+=("Missing SUMO vehicle type data: ${BRIDGE_DIR}/Sumo/data/vtypes.json")
    fi
  elif [[ -n "${UB_SUMO_SCENARIO_DIR}" ]]; then
    if [[ ! -f "${UB_SUMO_SCENARIO_DIR}/${UB_SUMO_CONFIG}" ]]; then
      preflight_failures+=("Missing SUMO scenario config: ${UB_SUMO_SCENARIO_DIR}/${UB_SUMO_CONFIG}")
    fi
    if [[ ! -f "${UB_SUMO_SCENARIO_DIR}/UBAutonomousProvingGrounds.net.xml" ]]; then
      preflight_failures+=("Missing SUMO scenario net: ${UB_SUMO_SCENARIO_DIR}/UBAutonomousProvingGrounds.net.xml")
    fi
    if [[ ! -f "${UB_SUMO_SCENARIO_DIR}/UBAutonomousProvingGrounds.rou.xml" ]]; then
      preflight_failures+=("Missing SUMO scenario routes: ${UB_SUMO_SCENARIO_DIR}/UBAutonomousProvingGrounds.rou.xml")
    fi
  elif [[ ! -f "${BRIDGE_DIR}/Sumo/examples/${UB_SUMO_CONFIG}" ]]; then
    preflight_failures+=("Missing SUMO config: ${BRIDGE_DIR}/Sumo/examples/${UB_SUMO_CONFIG}")
  fi

  if [[ ! -d "${BRIDGE_DIR}/autoware_carla_interface" ]]; then
    preflight_failures+=("Missing custom autoware_carla_interface package: ${BRIDGE_DIR}/autoware_carla_interface")
  fi

  if [[ "${UB_AUTOWARE_CAMERA_FOLLOW}" == "1" && ! -f "${SCRIPT_DIR}/UB-API/util/camera_follow_sync.py" ]]; then
    preflight_failures+=("Missing CARLA spectator camera follow helper: ${SCRIPT_DIR}/UB-API/util/camera_follow_sync.py")
  fi

  if [[ ! -d "${AUTOWARE_DOCKER_DIR}" ]]; then
    preflight_failures+=("Missing Autoware Docker directory: ${AUTOWARE_DOCKER_DIR}")
  elif [[ ! -f "${AUTOWARE_DOCKER_DIR}/compose.yml" && ! -f "${AUTOWARE_DOCKER_DIR}/docker-compose.yml" && ! -f "${AUTOWARE_DOCKER_DIR}/docker-compose.yaml" ]]; then
    preflight_failures+=("Autoware Docker directory does not contain a Compose file: ${AUTOWARE_DOCKER_DIR}")
  fi

  if ! has_files "${AUTOWARE_HOST_MAP_DIR}"; then
    preflight_failures+=("Missing or empty Autoware UB HD map directory: ${AUTOWARE_HOST_MAP_DIR}")
  fi

  if [[ -z "${DISPLAY:-}" ]]; then
    preflight_failures+=("DISPLAY is not set. Run from a graphical Linux session or configure X11 forwarding.")
  fi

  if [[ ! -d /tmp/.X11-unix ]]; then
    preflight_failures+=("Missing /tmp/.X11-unix. CARLA and SUMO GUI need the host X11 socket mounted into Docker.")
  fi

  if ! carla_compose config --services >/dev/null 2>&1; then
    preflight_failures+=("Generated CARLA/SUMO Compose stack is invalid. Check ${SUMO_BRIDGE_COMPOSE_FILE}.")
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

print_dry_run() {
  cat <<EOF
Dry run passed. The launcher would run:

  cd ${SCRIPT_DIR}
  docker compose -f ${SCRIPT_DIR}/docker-compose.yml -f ${SUMO_BRIDGE_COMPOSE_FILE} config --services >/dev/null
  BUILD_FOLDER=${BUILD_FOLDER} \\
  CARLA_MAP_PATH=${CARLA_MAP_PATH} \\
  CARLA_ARGS=${CARLA_ARGS} \\
  docker compose -f docker-compose.yml -f ${SUMO_BRIDGE_COMPOSE_FILE} up --build -d carla map-loader

  cd ${SCRIPT_DIR}
  UB_SUMO_RANDOM_TRAFFIC=${UB_SUMO_RANDOM_TRAFFIC} \\
  UB_SUMO_RANDOM_VEHICLES=${UB_SUMO_RANDOM_VEHICLES} \\
  UB_SUMO_RANDOM_SAFE=${UB_SUMO_RANDOM_SAFE} \\
  UB_SUMO_SCENARIO_DIR=${UB_SUMO_SCENARIO_DIR:-<disabled>} \\
  UB_SUMO_CONFIG=${UB_SUMO_CONFIG} \\
  UB_SUMO_STEP_LENGTH=${UB_SUMO_STEP_LENGTH} \\
  UB_SUMO_GUI=${UB_SUMO_GUI} \\
  UB_SUMO_AUTO_START=${UB_SUMO_AUTO_START} \\
  UB_SUMO_TLS_MANAGER=${UB_SUMO_TLS_MANAGER} \\
  docker compose -f docker-compose.yml -f ${SUMO_BRIDGE_COMPOSE_FILE} up --build -d sumo-bridge

  cd ${SCRIPT_DIR}
  UB_AUTOWARE_CAMERA_FOLLOW=${UB_AUTOWARE_CAMERA_FOLLOW} \\
  UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES=${UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES} \\
  docker compose -f docker-compose.yml -f ${SUMO_BRIDGE_COMPOSE_FILE} up --build -d camera-follow

  cd ${AUTOWARE_DOCKER_DIR}
  docker compose up -d ${AUTOWARE_SERVICE}
  docker compose cp ${BRIDGE_DIR}/autoware_carla_interface \\
    ${AUTOWARE_SERVICE}:/autoware/src/universe/autoware_universe/simulator/autoware_carla_interface
  docker compose exec ${AUTOWARE_SERVICE} bash -lc 'colcon build --symlink-install --packages-select autoware_carla_interface'
  docker compose exec ${AUTOWARE_SERVICE} bash -lc 'ros2 launch autoware_carla_interface ... external_tick:=True & ros2 run topic_tools relay ... & ros2 launch autoware_launch e2e_simulator.launch.xml simulator_type:=awsim ...'
EOF
}

shell_quote() {
  printf "%q" "$1"
}

bool_enabled() {
  case "${1:-0}" in
    1|true|True|TRUE|yes|Yes|YES|on|On|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

write_sumo_bridge_compose_override() {
  cat > "${SUMO_BRIDGE_COMPOSE_FILE}" <<EOF
services:
  sumo-bridge:
    image: ${SUMO_BRIDGE_IMAGE}
    build:
      context: ${SCRIPT_DIR}
      dockerfile_inline: |
        FROM ubuntu:22.04

        ENV DEBIAN_FRONTEND=noninteractive

        RUN apt-get update && apt-get install -y --no-install-recommends \\
            ca-certificates \\
            gnupg \\
            software-properties-common \\
         && add-apt-repository -y ppa:sumo/stable \\
         && apt-get update && apt-get install -y --no-install-recommends \\
            ca-certificates \\
            libgl1 \\
            libglu1-mesa \\
            libx11-6 \\
            libxcursor1 \\
            libxext6 \\
            libxi6 \\
            libxinerama1 \\
            libxrandr2 \\
            libxrender1 \\
            python3 \\
            python3-pip \\
            sumo \\
            sumo-tools \\
         && rm -rf /var/lib/apt/lists/*

        COPY UB-API/carla-autoware-sumo-bridge/Sumo/requirements.txt /tmp/sumo-requirements.txt
        RUN python3 -m pip install --no-cache-dir -r /tmp/sumo-requirements.txt

        COPY UB-API/carla-autoware-sumo-bridge/Sumo /opt/carla-autoware-sumo-bridge/Sumo

        ENV SUMO_HOME=/usr/share/sumo \\
            CARLA_PYTHON_TARGET=/tmp/ub-carla-python \\
            PYTHONUNBUFFERED=1

        WORKDIR /opt/carla-autoware-sumo-bridge/Sumo
    container_name: ${SUMO_BRIDGE_CONTAINER_NAME}
    network_mode: host
    depends_on:
      map-loader:
        condition: service_completed_successfully
    environment:
      UB_CARLA_HOST: \${UB_CARLA_HOST:-127.0.0.1}
      UB_CARLA_PORT: \${UB_CARLA_PORT:-2000}
      RMW_IMPLEMENTATION: \${UB_AUTOWARE_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}
      CYCLONEDDS_URI: \${UB_AUTOWARE_CYCLONEDDS_URI:-file:///resources/cyclonedds.xml}
      PYTHONUNBUFFERED: "1"
      DISPLAY: \${DISPLAY:-}
      XAUTHORITY: /tmp/.docker.xauth
      SUMO_HOME: \${SUMO_HOME:-/usr/share/sumo}
      CARLA_PYTHON_TARGET: /tmp/ub-carla-python-${BUILD_FOLDER}
      UB_SUMO_CONFIG: \${UB_SUMO_CONFIG:-UBAutonomousProvingGrounds.sumocfg}
      UB_SUMO_SCENARIO_DIR: /opt/ub-sumo-scenarios/RandomTraffic
      UB_SUMO_RANDOM_TRAFFIC: \${UB_SUMO_RANDOM_TRAFFIC:-0}
      UB_SUMO_RANDOM_VEHICLES: \${UB_SUMO_RANDOM_VEHICLES:-25}
      UB_SUMO_RANDOM_WALKERS: \${UB_SUMO_RANDOM_WALKERS:-0}
      UB_SUMO_RANDOM_SAFE: \${UB_SUMO_RANDOM_SAFE:-1}
      UB_SUMO_RANDOM_FILTERV: \${UB_SUMO_RANDOM_FILTERV:-vehicle.*}
      UB_SUMO_RANDOM_FILTERW: \${UB_SUMO_RANDOM_FILTERW:-walker.pedestrian.*}
      UB_SUMO_RANDOM_EXTRA_ARGS: \${UB_SUMO_RANDOM_EXTRA_ARGS:-}
      UB_SUMO_STEP_LENGTH: \${UB_SUMO_STEP_LENGTH:-0.05}
      UB_SUMO_GUI: \${UB_SUMO_GUI:-1}
      UB_SUMO_AUTO_START: \${UB_SUMO_AUTO_START:-1}
      UB_SUMO_TLS_MANAGER: \${UB_SUMO_TLS_MANAGER:-sumo}
      UB_SUMO_SYNC_VEHICLE_COLOR: \${UB_SUMO_SYNC_VEHICLE_COLOR:-0}
      UB_SUMO_SYNC_VEHICLE_LIGHTS: \${UB_SUMO_SYNC_VEHICLE_LIGHTS:-0}
      UB_SUMO_EXTRA_ARGS: \${UB_SUMO_EXTRA_ARGS:-}
    volumes:
      - ./Builds/${BUILD_FOLDER}:/carla:ro
      - "${UB_SUMO_SCENARIO_DIR}:/opt/ub-sumo-scenarios/RandomTraffic:ro"
      - /tmp/.X11-unix:/tmp/.X11-unix:rw
      - \${XAUTHORITY:-/tmp/.Xauthority}:/tmp/.docker.xauth:ro
    entrypoint:
      - /bin/bash
      - -lc
    command:
      - |
        set -euo pipefail

        SUMO_ROOT="\$\${UB_SUMO_ROOT:-/opt/carla-autoware-sumo-bridge/Sumo}"
        CARLA_PYTHON_TARGET="\$\${CARLA_PYTHON_TARGET:-/tmp/ub-carla-python}"

        is_true() {
          case "\$\${1:-0}" in
            1|true|True|TRUE|yes|Yes|YES|on|On|ON)
              return 0
              ;;
            *)
              return 1
              ;;
          esac
        }

        if [[ -z "\$\${SUMO_HOME:-}" || ! -d "\$\${SUMO_HOME}/tools" ]]; then
          echo "Error: SUMO_HOME is not set to a valid SUMO install." >&2
          exit 1
        fi

        CARLA_WHEEL="\$\$(find /carla/PythonAPI/carla/dist -maxdepth 1 -type f -name 'carla-*-cp310-*.whl' 2>/dev/null | head -n 1 || true)"
        if [[ -z "\$\${CARLA_WHEEL}" ]]; then
          echo "Error: CARLA Python cp310 wheel not found under /carla/PythonAPI/carla/dist." >&2
          exit 1
        fi

        if [[ ! -d "\$\${CARLA_PYTHON_TARGET}/carla" ]]; then
          python3 -m pip install --no-index --target "\$\${CARLA_PYTHON_TARGET}" "\$\${CARLA_WHEEL}" >/dev/null
        fi

        export PYTHONPATH="\$\${CARLA_PYTHON_TARGET}:\$\${SUMO_ROOT}:\$\${SUMO_HOME}/tools\$\${PYTHONPATH:+:\$\${PYTHONPATH}}"
        cd "\$\${SUMO_ROOT}"

        if is_true "\$\${UB_SUMO_RANDOM_TRAFFIC:-0}"; then
          ARGS=(
            --host "\$\${UB_CARLA_HOST:-127.0.0.1}"
            --port "\$\${UB_CARLA_PORT:-2000}"
            --step-length "\$\${UB_SUMO_STEP_LENGTH:-0.05}"
            --tls-manager "\$\${UB_SUMO_TLS_MANAGER:-sumo}"
            --number-of-vehicles "\$\${UB_SUMO_RANDOM_VEHICLES:-25}"
            --number-of-walkers "\$\${UB_SUMO_RANDOM_WALKERS:-0}"
            --filterv "\$\${UB_SUMO_RANDOM_FILTERV:-vehicle.*}"
            --filterw "\$\${UB_SUMO_RANDOM_FILTERW:-walker.pedestrian.*}"
          )

          if is_true "\$\${UB_SUMO_GUI:-0}"; then
            ARGS+=(--sumo-gui)
          fi
          if is_true "\$\${UB_SUMO_RANDOM_SAFE:-1}"; then
            ARGS+=(--safe)
          fi
          if is_true "\$\${UB_SUMO_SYNC_VEHICLE_COLOR:-0}"; then
            ARGS+=(--sync-vehicle-color)
          fi
          if is_true "\$\${UB_SUMO_SYNC_VEHICLE_LIGHTS:-0}"; then
            ARGS+=(--sync-vehicle-lights)
          fi
          if [[ -n "\$\${UB_SUMO_RANDOM_EXTRA_ARGS:-}" ]]; then
            read -r -a EXTRA_ARGS <<< "\$\${UB_SUMO_RANDOM_EXTRA_ARGS}"
            ARGS+=("\$\${EXTRA_ARGS[@]}")
          fi

          echo "Starting random SUMO traffic on the loaded CARLA map:"
          printf '  %q' python3 "\$\${SUMO_ROOT}/spawn_npc_sumo.py" "\$\${ARGS[@]}"
          echo
          exec python3 -u "\$\${SUMO_ROOT}/spawn_npc_sumo.py" "\$\${ARGS[@]}"
        fi

        SCENARIO_ROOT="\$\${UB_SUMO_SCENARIO_DIR:-}"
        if [[ -n "\$\${SCENARIO_ROOT}" && -f "\$\${SCENARIO_ROOT}/\$\${UB_SUMO_CONFIG:-UBAutonomousProvingGrounds.sumocfg}" ]]; then
          PREPARED_SCENARIO_DIR="/tmp/ub-sumo-scenario"
          rm -rf "\$\${PREPARED_SCENARIO_DIR}"
          mkdir -p "\$\${PREPARED_SCENARIO_DIR}/net" "\$\${PREPARED_SCENARIO_DIR}/rou"
          cp "\$\${SCENARIO_ROOT}/\$\${UB_SUMO_CONFIG:-UBAutonomousProvingGrounds.sumocfg}" "\$\${PREPARED_SCENARIO_DIR}/"
          cp "\$\${SCENARIO_ROOT}/UBAutonomousProvingGrounds.net.xml" "\$\${PREPARED_SCENARIO_DIR}/net/"
          cp "\$\${SCENARIO_ROOT}/UBAutonomousProvingGrounds.rou.xml" "\$\${PREPARED_SCENARIO_DIR}/rou/"
          SUMO_CFG_PATH="\$\${PREPARED_SCENARIO_DIR}/\$\${UB_SUMO_CONFIG:-UBAutonomousProvingGrounds.sumocfg}"
          echo "Using SUMO scenario: \$\${SCENARIO_ROOT}"
        else
          SUMO_CFG_PATH="\$\${SUMO_ROOT}/examples/\$\${UB_SUMO_CONFIG:-UBAutonomousProvingGrounds.sumocfg}"
        fi

        if [[ ! -f "\$\${SUMO_CFG_PATH}" ]]; then
          echo "Error: SUMO config not found: \$\${SUMO_CFG_PATH}" >&2
          exit 1
        fi

        ARGS=(
          "\$\${SUMO_CFG_PATH}"
          --carla-host "\$\${UB_CARLA_HOST:-127.0.0.1}"
          --carla-port "\$\${UB_CARLA_PORT:-2000}"
          --step-length "\$\${UB_SUMO_STEP_LENGTH:-0.05}"
          --tls-manager "\$\${UB_SUMO_TLS_MANAGER:-sumo}"
        )

        if is_true "\$\${UB_SUMO_GUI:-0}"; then
          ARGS+=(--sumo-gui)
        fi
        if is_true "\$\${UB_SUMO_SYNC_VEHICLE_COLOR:-0}"; then
          ARGS+=(--sync-vehicle-color)
        fi
        if is_true "\$\${UB_SUMO_SYNC_VEHICLE_LIGHTS:-0}"; then
          ARGS+=(--sync-vehicle-lights)
        fi
        if [[ -n "\$\${UB_SUMO_EXTRA_ARGS:-}" ]]; then
          read -r -a EXTRA_ARGS <<< "\$\${UB_SUMO_EXTRA_ARGS}"
          ARGS+=("\$\${EXTRA_ARGS[@]}")
        fi

        echo "Starting fixed-config CARLA-SUMO synchronization:"
        printf '  %q' python3 "\$\${SUMO_ROOT}/run_synchronization.py" "\$\${ARGS[@]}"
        echo
        exec python3 -u "\$\${SUMO_ROOT}/run_synchronization.py" "\$\${ARGS[@]}"
EOF
}

carla_compose() {
  docker compose -f "${SCRIPT_DIR}/docker-compose.yml" -f "${SUMO_BRIDGE_COMPOSE_FILE}" "$@"
}

configure_autoware_host_dds() {
  if [[ "${UB_AUTOWARE_HOST_CONFIG_DDS}" != "1" || "${UB_AUTOWARE_RMW_IMPLEMENTATION}" != "rmw_cyclonedds_cpp" ]]; then
    return 0
  fi

  if [[ ! -x "${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash" ]]; then
    echo "Warning: missing executable Autoware host DDS setup script: ${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash" >&2
    return 0
  fi

  echo "Applying Autoware host DDS settings. sudo may prompt for your password."
  "${AUTOWARE_DOCKER_DIR}/../scripts/host_config_dds.bash"
}

wait_for_map_loader() {
  local map_loader_id=""
  local status=""

  cd "${SCRIPT_DIR}"
  for _ in {1..30}; do
    map_loader_id="$(carla_compose ps -a -q map-loader 2>/dev/null || true)"
    if [[ -n "${map_loader_id}" ]]; then
      break
    fi
    sleep 1
  done

  if [[ -z "${map_loader_id}" ]]; then
    echo "Error: map-loader container was not created." >&2
    carla_compose ps >&2 || true
    return 1
  fi

  echo "Waiting for CARLA map loader to finish..."
  status="$(docker wait "${map_loader_id}")"

  if [[ "${status}" != "0" ]]; then
    echo "Error: map-loader exited with status ${status}." >&2
    carla_compose logs map-loader >&2 || true
    return 1
  fi

  echo "CARLA map loaded: ${CARLA_MAP}"
}

assert_carla_running() {
  local carla_id=""
  local running=""
  local status=""
  local exit_code=""

  cd "${SCRIPT_DIR}"
  carla_id="$(carla_compose ps -q carla 2>/dev/null || true)"
  if [[ -z "${carla_id}" ]]; then
    echo "Error: CARLA container was not created." >&2
    carla_compose ps >&2 || true
    return 1
  fi

  running="$(docker inspect -f '{{.State.Running}}' "${carla_id}")"
  if [[ "${running}" == "true" ]]; then
    return 0
  fi

  status="$(docker inspect -f '{{.State.Status}}' "${carla_id}")"
  exit_code="$(docker inspect -f '{{.State.ExitCode}}' "${carla_id}")"
  echo "Error: CARLA container is not running: status=${status}, exit_code=${exit_code}" >&2
  carla_compose logs --tail=120 carla >&2 || true
  return 1
}

start_carla() {
  cd "${SCRIPT_DIR}"

  export BUILD_FOLDER
  export CARLA_ARGS
  export CARLA_MAP_PATH
  export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
  if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
    export XAUTHORITY="${HOME}/.Xauthority"
  fi

  if command -v xhost >/dev/null 2>&1; then
    xhost +local:root >/dev/null || echo "Warning: xhost did not grant local root X11 access. CARLA or SUMO GUI may fail to render." >&2
  fi

  echo "Starting rendered CARLA Compose stack..."
  CARLA_STARTED=1
  carla_compose up --build -d carla map-loader
  wait_for_map_loader
  echo "Checking CARLA stays alive after map load..."
  for _ in {1..8}; do
    sleep 1
    assert_carla_running
  done
}

start_sumo_bridge() {
  cd "${SCRIPT_DIR}"

  export BUILD_FOLDER
  export DISPLAY
  export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
  if [[ ! -f "${XAUTHORITY}" && -f "${HOME}/.Xauthority" ]]; then
    export XAUTHORITY="${HOME}/.Xauthority"
  fi
  export UB_SUMO_CONFIG
  export UB_SUMO_SCENARIO_DIR
  export UB_SUMO_STEP_LENGTH
  export UB_SUMO_GUI
  export UB_SUMO_AUTO_START
  export UB_SUMO_TLS_MANAGER
  export UB_SUMO_SYNC_VEHICLE_COLOR
  export UB_SUMO_SYNC_VEHICLE_LIGHTS
  export UB_SUMO_EXTRA_ARGS
  export UB_SUMO_RANDOM_TRAFFIC
  export UB_SUMO_RANDOM_VEHICLES
  export UB_SUMO_RANDOM_WALKERS
  export UB_SUMO_RANDOM_SAFE
  export UB_SUMO_RANDOM_FILTERV
  export UB_SUMO_RANDOM_FILTERW
  export UB_SUMO_RANDOM_EXTRA_ARGS

  if bool_enabled "${UB_SUMO_RANDOM_TRAFFIC}"; then
    echo "Starting CARLA-SUMO bridge with ${UB_SUMO_RANDOM_VEHICLES} random SUMO vehicles on ${CARLA_MAP}..."
  elif [[ -n "${UB_SUMO_SCENARIO_DIR}" ]]; then
    echo "Starting CARLA-SUMO bridge with SUMO scenario ${UB_SUMO_SCENARIO_DIR}/${UB_SUMO_CONFIG}..."
  else
    echo "Starting CARLA-SUMO bridge with SUMO config ${UB_SUMO_CONFIG}..."
  fi
  carla_compose up --build -d sumo-bridge
  SUMO_STARTED=1

  sleep 2
  if [[ "$(carla_compose ps --status running -q sumo-bridge 2>/dev/null || true)" == "" ]]; then
    echo "Error: sumo-bridge exited during startup." >&2
    carla_compose logs --tail=120 sumo-bridge >&2 || true
    return 1
  fi
}

start_camera_follow() {
  if [[ "${UB_AUTOWARE_CAMERA_FOLLOW}" != "1" ]]; then
    return 0
  fi

  cd "${SCRIPT_DIR}"
  export BUILD_FOLDER
  export UB_AUTOWARE_CAMERA_FOLLOW_HOST
  export UB_AUTOWARE_CAMERA_FOLLOW_PORT
  export UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES
  export UB_AUTOWARE_CAMERA_FOLLOW_WAIT_SECONDS
  export UB_AUTOWARE_CAMERA_FOLLOW_DISTANCE_M
  export UB_AUTOWARE_CAMERA_FOLLOW_HEIGHT_M
  export UB_AUTOWARE_CAMERA_FOLLOW_PITCH_DEG
  export UB_AUTOWARE_CAMERA_FOLLOW_UPDATE_HZ

  echo "Starting CARLA spectator camera follow for role_name(s): ${UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES}"
  carla_compose up --build -d camera-follow
  CAMERA_FOLLOW_STARTED=1

  sleep 1
  if [[ -z "$(carla_compose ps -q camera-follow 2>/dev/null || true)" ]]; then
    echo "Warning: CARLA spectator camera follow container was not created." >&2
    carla_compose logs --tail=80 camera-follow >&2 || true
    CAMERA_FOLLOW_STARTED=0
  elif [[ "$(carla_compose ps --status running -q camera-follow 2>/dev/null || true)" == "" ]]; then
    echo "Warning: CARLA spectator camera follow container exited during startup." >&2
    carla_compose logs --tail=80 camera-follow >&2 || true
    CAMERA_FOLLOW_STARTED=0
  fi
}

cleanup_autoware_launch_processes() {
  cd "${AUTOWARE_DOCKER_DIR}"
  if [[ -z "$(docker compose ps -q "${AUTOWARE_SERVICE}" 2>/dev/null || true)" ]]; then
    return 0
  fi

  echo "${1:-Stopping Autoware ROS launch processes.}"
  docker compose exec -T "${AUTOWARE_SERVICE}" bash -lc '
pkill -INT -f "ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml" || true
pkill -INT -f "ros2 launch autoware_launch e2e_simulator.launch.xml" || true
pkill -INT -f "ros2 run topic_tools relay /sensing/lidar/top/pointcloud_before_sync /sensing/lidar/concatenated/pointcloud" || true
sleep 2
pkill -TERM -f "ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml" || true
pkill -TERM -f "ros2 launch autoware_launch e2e_simulator.launch.xml" || true
pkill -TERM -f "ros2 run topic_tools relay /sensing/lidar/top/pointcloud_before_sync /sensing/lidar/concatenated/pointcloud" || true
pkill -TERM -f "/autoware/install/autoware_carla_interface/lib/autoware_carla_interface/autoware_carla_interface" || true
' >/dev/null 2>&1 || true
}

start_autoware_container() {
  cd "${AUTOWARE_DOCKER_DIR}"

  echo "Starting Autoware Compose service: ${AUTOWARE_SERVICE}"
  export RMW_IMPLEMENTATION="${UB_AUTOWARE_RMW_IMPLEMENTATION}"
  export CYCLONEDDS_URI="${UB_AUTOWARE_CYCLONEDDS_URI}"
  docker compose up -d "${AUTOWARE_SERVICE}"

  if [[ "${UB_AUTOWARE_CLEAN_STALE_PROCESSES}" == "1" ]]; then
    cleanup_autoware_launch_processes "Cleaning stale Autoware ROS launch processes before starting."
  fi
}

install_custom_autoware_bridge() {
  cd "${AUTOWARE_DOCKER_DIR}"

  echo "Installing custom autoware_carla_interface into the Autoware container..."
  docker compose exec -T "${AUTOWARE_SERVICE}" bash -lc '
set -euo pipefail
mkdir -p /autoware/src/universe/autoware_universe/simulator
rm -rf /autoware/src/universe/autoware_universe/simulator/autoware_carla_interface
'
  docker compose cp "${BRIDGE_DIR}/autoware_carla_interface" "${AUTOWARE_SERVICE}:/autoware/src/universe/autoware_universe/simulator/autoware_carla_interface"

  local install_deps_cmd=""
  if [[ "${UB_AUTOWARE_INSTALL_PY_DEPS}" == "1" ]]; then
    install_deps_cmd='
python3 - <<'"'"'PY'"'"' || python3 -m pip install --upgrade carla==0.9.16 transforms3d==0.4.2
import carla
import transforms3d

def version_tuple(version):
    parts = []
    for part in version.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts)

if version_tuple(transforms3d.__version__) < (0, 4, 2):
    raise SystemExit(f"transforms3d {transforms3d.__version__} is older than 0.4.2")
PY
'
  fi

  docker compose exec -T "${AUTOWARE_SERVICE}" bash -lc "
set -eo pipefail
export RMW_IMPLEMENTATION=$(shell_quote "${UB_AUTOWARE_RMW_IMPLEMENTATION}")
export CYCLONEDDS_URI=$(shell_quote "${UB_AUTOWARE_CYCLONEDDS_URI}")
source /opt/ros/humble/setup.bash
${install_deps_cmd}
cd /autoware
colcon build --symlink-install --packages-select autoware_carla_interface
source /autoware/install/setup.bash
ros2 pkg prefix autoware_carla_interface
"
}

launch_autoware() {
  local exec_args=(exec)
  local optional_launch_args=""
  local launch_cmd

  cd "${AUTOWARE_DOCKER_DIR}"

  if [[ ! -t 0 ]]; then
    exec_args+=(-T)
  fi

  if [[ -n "${AUTOWARE_RVIZ}" ]]; then
    optional_launch_args+=" \\
  rviz:=$(shell_quote "${AUTOWARE_RVIZ}")"
  fi
  if [[ -n "${AUTOWARE_PLANNING_MODULE_PRESET}" ]]; then
    optional_launch_args+=" \\
  planning_module_preset:=$(shell_quote "${AUTOWARE_PLANNING_MODULE_PRESET}")"
  fi

launch_cmd="
set -eo pipefail
export RMW_IMPLEMENTATION=$(shell_quote "${UB_AUTOWARE_RMW_IMPLEMENTATION}")
export CYCLONEDDS_URI=$(shell_quote "${UB_AUTOWARE_CYCLONEDDS_URI}")
source /opt/ros/humble/setup.bash
source /autoware/install/setup.bash

ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml \\
  host:=$(shell_quote "${AUTOWARE_CARLA_HOST}") \\
  carla_map:=$(shell_quote "${CARLA_MAP}") \\
  fixed_delta_seconds:=$(shell_quote "${UB_SUMO_STEP_LENGTH}") \\
  external_tick:=True &
BRIDGE_PID=\$!
RELAY_PID=

cleanup_bridge_processes() {
  kill \${BRIDGE_PID} 2>/dev/null || true
  if [[ -n \"\${RELAY_PID}\" ]]; then
    kill \${RELAY_PID} 2>/dev/null || true
  fi
}
trap cleanup_bridge_processes EXIT

sleep 5
if ! kill -0 \${BRIDGE_PID} 2>/dev/null; then
  echo \"Error: autoware_carla_interface exited before Autoware launch started.\" >&2
  wait \${BRIDGE_PID} || true
  exit 1
fi

if [[ $(shell_quote "${AUTOWARE_CARLA_POINTCLOUD_RELAY}") == \"1\" ]]; then
  ros2 run topic_tools relay \\
    /sensing/lidar/top/pointcloud_before_sync \\
    /sensing/lidar/concatenated/pointcloud &
  RELAY_PID=\$!
fi

ros2 launch autoware_launch e2e_simulator.launch.xml \\
  map_path:=$(shell_quote "${AUTOWARE_MAP_PATH}") \\
  vehicle_model:=$(shell_quote "${AUTOWARE_VEHICLE_MODEL}") \\
  sensor_model:=$(shell_quote "${AUTOWARE_SENSOR_MODEL}") \\
  simulator_type:=$(shell_quote "${AUTOWARE_E2E_SIMULATOR_TYPE}")${optional_launch_args}
"

  echo "Launching passive CARLA interface and Autoware. Press Ctrl+C to stop the ROS launch."
  AUTOWARE_LAUNCH_STARTED=1
  set +e
  docker compose "${exec_args[@]}" "${AUTOWARE_SERVICE}" bash -lc "${launch_cmd}"
  local launch_status=$?
  set -e

  if [[ "${UB_KEEP_AUTOWARE_ROS}" != "1" ]]; then
    cleanup_autoware_launch_processes "Stopping Autoware ROS launch processes. Set UB_KEEP_AUTOWARE_ROS=1 to leave them running."
    AUTOWARE_LAUNCH_STARTED=0
  fi

  return "${launch_status}"
}

cleanup() {
  local exit_code="$?"

  if [[ "${exit_code}" -ne 0 && "${exit_code}" -ne 130 && "${exit_code}" -ne 143 && "${UB_KEEP_ON_ERROR}" == "1" ]]; then
    echo "Launcher exited with status ${exit_code}; leaving started containers for inspection because UB_KEEP_ON_ERROR=1."
    if [[ "${SUMO_STARTED}" -eq 1 ]]; then
      echo "Inspect SUMO with:"
      echo "  cd ${SCRIPT_DIR} && docker compose -f docker-compose.yml -f ${SUMO_BRIDGE_COMPOSE_FILE} logs --tail=200 sumo-bridge"
    fi
    if [[ "${CARLA_STARTED}" -eq 1 ]]; then
      echo "Stop CARLA/SUMO later with:"
      echo "  cd ${SCRIPT_DIR} && docker compose -f docker-compose.yml -f ${SUMO_BRIDGE_COMPOSE_FILE} down"
    fi
    exit "${exit_code}"
  fi

  if [[ "${AUTOWARE_LAUNCH_STARTED}" -eq 1 && "${UB_KEEP_AUTOWARE_ROS}" != "1" ]]; then
    cleanup_autoware_launch_processes "Stopping Autoware ROS launch processes. Set UB_KEEP_AUTOWARE_ROS=1 to leave them running." || true
    AUTOWARE_LAUNCH_STARTED=0
  fi

  if [[ "${CAMERA_FOLLOW_STARTED}" -eq 1 ]]; then
    echo "Stopping CARLA spectator camera follow."
    cd "${SCRIPT_DIR}"
    carla_compose stop camera-follow >/dev/null 2>&1 || true
    carla_compose rm -f camera-follow >/dev/null 2>&1 || true
    CAMERA_FOLLOW_STARTED=0
  fi

  if [[ "${SUMO_STARTED}" -eq 1 && "${UB_KEEP_SUMO}" != "1" ]]; then
    echo "Stopping SUMO bridge. Set UB_KEEP_SUMO=1 to leave it running."
    cd "${SCRIPT_DIR}"
    carla_compose stop sumo-bridge >/dev/null 2>&1 || true
    carla_compose rm -f sumo-bridge >/dev/null 2>&1 || true
    SUMO_STARTED=0
  fi

  if [[ "${CARLA_STARTED}" -eq 1 && "${UB_KEEP_CARLA}" != "1" ]]; then
    echo "Stopping CARLA Compose stack. Set UB_KEEP_CARLA=1 to leave it running."
    cd "${SCRIPT_DIR}"
    carla_compose down >/dev/null 2>&1 || true
    CARLA_STARTED=0
  fi

  exit "${exit_code}"
}

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

write_sumo_bridge_compose_override
run_preflight

if [[ "${DRY_RUN}" -eq 1 ]]; then
  print_dry_run
  exit 0
fi

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

configure_autoware_host_dds
start_carla
start_sumo_bridge
start_camera_follow
start_autoware_container
install_custom_autoware_bridge
launch_autoware
