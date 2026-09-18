#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_REPO_DIR="$SCRIPT_DIR/ub-lincoln-docker"
DOCKER_DIR="$DOCKER_REPO_DIR/docker"
ENV_FILE="$DOCKER_DIR/.env"
ENV_EXAMPLE_FILE="$DOCKER_DIR/.env-example"
VERSION="${BUILD_FOLDER:-v1.1.0}"
VERSION_SET=0
BUILD_LOCAL=0

usage() {
    cat <<EOF
Usage: $(basename "$0") [VERSION] [--build_local]
       $(basename "$0") --version VERSION [--build_local]

Set up Autoware and its matching versioned maps from public Google Drive.
VERSION defaults to BUILD_FOLDER or v1.1.0; accepts v1.1.0 or 1.1.0.
Use scripts/install_ub_carla.sh VERSION to install both CARLA and maps.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --build_local) BUILD_LOCAL=1; shift ;;
        -h|--help) usage; exit 0 ;;
        -t|--tag|--version)
            if [ "$#" -lt 2 ] || [ "$VERSION_SET" = 1 ]; then
                echo "Specify exactly one version after $1." >&2
                exit 2
            fi
            VERSION="$2"; VERSION_SET=1; shift 2 ;;
        -*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
        *)
            if [ "$VERSION_SET" = 1 ]; then
                echo "Specify the version only once." >&2
                exit 2
            fi
            VERSION="$1"; VERSION_SET=1; shift ;;
    esac
done

has_files() {
    local path="$1"
    [ -d "$path" ] || return 1
    find "$path" -mindepth 1 -maxdepth 2 -print -quit 2>/dev/null | grep -q .
}

set_env_var() {
    local key="$1"
    local value="$2"

    if grep -q "^$key=" "$ENV_FILE"; then
        sed -i "s|^$key=.*|$key=$value|" "$ENV_FILE"
    elif grep -q "^# $key=" "$ENV_FILE"; then
        sed -i "s|^# $key=.*|$key=$value|" "$ENV_FILE"
    else
        printf "%s=%s\n" "$key" "$value" >> "$ENV_FILE"
    fi
}

cd "$SCRIPT_DIR"

# Use the same release selection and validation as the CARLA installer.
# Check maps before downloading artifacts or changing the Docker setup.
bash "$SCRIPT_DIR/../scripts/install_ub_carla.sh" --maps-only --version "$VERSION"

# Clone the ub-lincoln-docker repo
if [ ! -d "$DOCKER_DIR" ]; then
    git clone https://github.com/ub-cavas/ub-lincoln-docker.git "$DOCKER_REPO_DIR"
fi

# Create required "host_data" and "autoware_data" directories
mkdir -p host_data
mkdir -p autoware_data

# Create/update docker .env with paths relative to docker-compose.yml.
if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$ENV_EXAMPLE_FILE" ]; then
        cp "$ENV_EXAMPLE_FILE" "$ENV_FILE"
    else
        touch "$ENV_FILE"
    fi
fi

set_env_var "HOST_DATA_PATH" "../../host_data"
set_env_var "AUTOWARE_DATA_PATH" "../../autoware_data"
set_env_var "UB_AUTOWARE_CARLA_INTERFACE_PATH" "../../../CARLA/UB-API/carla-autoware-sumo-bridge/autoware_carla_interface"

# Download autoware artifacts. Re-running the upstream downloader creates
# duplicate ".1" files, so skip it when artifacts are already present.
if [ "${UB_FORCE_ARTIFACT_DOWNLOAD:-0}" = "1" ] || ! has_files "$SCRIPT_DIR/autoware_data"; then
    cd "$SCRIPT_DIR/autoware_data"
    bash "$DOCKER_REPO_DIR/scripts/host_download_artifacts.sh"
else
    echo "Autoware artifacts already exist; skipping download."
    echo "Set UB_FORCE_ARTIFACT_DOWNLOAD=1 to re-download artifacts."
fi

cd "$DOCKER_DIR"

# build the image locally
if [ "$BUILD_LOCAL" = 1 ]; then
    echo "Building Autoware..."
    ./build_ros2.sh
    ./build_autoware.sh
# OR
# pull the most recent docker image
else
    echo "Pulling Autoware Image from dockerhub"
    docker compose pull autoware
fi
