#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_REPO_DIR="$SCRIPT_DIR/ub-lincoln-docker"
DOCKER_DIR="$DOCKER_REPO_DIR/docker"
ENV_FILE="$DOCKER_DIR/.env"
ENV_EXAMPLE_FILE="$DOCKER_DIR/.env-example"
MAP_GOOGLE_DRIVE_FILE_ID="1XKcmCLL2_jhauSTsU1KjlXMF8JvlfInp"
MAP_ARCHIVE="$SCRIPT_DIR/host_data/ub_hd_map_download"
MAP_EXTRACTED_DIR="$SCRIPT_DIR/host_data/ub_autonomous_proving_grounds"
MAP_DEST_DIR="$SCRIPT_DIR/host_data/maps/ub_autonomous_proving_grounds"

has_files() {
    local path="$1"
    [ -d "$path" ] || return 1
    find "$path" -mindepth 1 -maxdepth 2 -print -quit 2>/dev/null | grep -q .
}

map_is_present() {
    [ -f "$MAP_DEST_DIR/lanelet2_map.osm" ] \
        && [ -f "$MAP_DEST_DIR/map_projector_info.yaml" ] \
        && [ -f "$MAP_DEST_DIR/pointcloud_map.pcd" ]
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

is_html_file() {
    head -c 512 "$1" | grep -qiE '<!doctype html|<html'
}

download_google_drive_file() {
    local file_id="$1"
    local output_path="$2"
    local cookie_file
    local response_file
    local download_url
    local confirm_token

    cookie_file="$(mktemp)"
    response_file="$(mktemp)"

    curl -fL -c "$cookie_file" -o "$response_file" \
        "https://drive.google.com/uc?export=download&id=$file_id"

    if is_html_file "$response_file"; then
        download_url="$(grep -o 'href="[^"]*uc?export=download[^"]*"' "$response_file" \
            | head -n 1 \
            | cut -d '"' -f 2 \
            | sed 's/&amp;/\&/g')"

        if [ -n "$download_url" ]; then
            case "$download_url" in
                http*) ;;
                /*) download_url="https://drive.google.com$download_url" ;;
                *) download_url="https://drive.google.com/$download_url" ;;
            esac

            curl -fL -b "$cookie_file" -o "$output_path" "$download_url"
        else
            confirm_token="$(grep -o 'confirm=[^&"]*' "$response_file" \
                | head -n 1 \
                | cut -d '=' -f 2)"

            if [ -n "$confirm_token" ]; then
                curl -fL -b "$cookie_file" -o "$output_path" \
                    "https://drive.google.com/uc?export=download&confirm=$confirm_token&id=$file_id"
            else
                curl -fL -b "$cookie_file" -o "$output_path" \
                    "https://drive.usercontent.google.com/download?id=$file_id&export=download&confirm=t"
            fi
        fi
    else
        mv "$response_file" "$output_path"
    fi

    rm -f "$cookie_file" "$response_file"

    if is_html_file "$output_path"; then
        echo "Downloaded map file is an HTML page instead of an archive."
        exit 1
    fi
}

extract_map_archive() {
    local archive_path="$1"
    local destination_dir="$2"

    if unzip -tq "$archive_path" >/dev/null 2>&1; then
        unzip -o "$archive_path" -d "$destination_dir"
    elif tar -tf "$archive_path" >/dev/null 2>&1; then
        tar --no-same-owner -xf "$archive_path" -C "$destination_dir"
    else
        echo "Downloaded map file is not a supported archive format."
        exit 1
    fi
}

normalize_map_location() {
    if [ -d "$MAP_DEST_DIR" ]; then
        return
    fi

    if [ -d "$MAP_EXTRACTED_DIR" ]; then
        mkdir -p "$(dirname "$MAP_DEST_DIR")"
        mv "$MAP_EXTRACTED_DIR" "$MAP_DEST_DIR"
    fi
}

cd "$SCRIPT_DIR"

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

# Download autoware artifacts. Re-running the upstream downloader creates
# duplicate ".1" files, so skip it when artifacts are already present.
if [ "${UB_FORCE_ARTIFACT_DOWNLOAD:-0}" = "1" ] || ! has_files "$SCRIPT_DIR/autoware_data"; then
    cd "$SCRIPT_DIR/autoware_data"
    bash "$DOCKER_REPO_DIR/scripts/host_download_artifacts.sh"
else
    echo "Autoware artifacts already exist; skipping download."
    echo "Set UB_FORCE_ARTIFACT_DOWNLOAD=1 to re-download artifacts."
fi

# Download and extract the UB-HD map into host_data.
if map_is_present; then
    echo "UB HD map already exists at $MAP_DEST_DIR; skipping download."
elif [ -d "$MAP_EXTRACTED_DIR" ]; then
    normalize_map_location
else
    download_google_drive_file "$MAP_GOOGLE_DRIVE_FILE_ID" "$MAP_ARCHIVE"
    extract_map_archive "$MAP_ARCHIVE" "$SCRIPT_DIR/host_data"
    normalize_map_location
    rm -f "$MAP_ARCHIVE"
fi

cd "$DOCKER_DIR"

# build the image locally
if [[ " $@ " =~ " --build_local" ]]; then
    echo "Building Autoware..."
    ./build_ros2.sh
    ./build_autoware.sh
# OR
# pull the most recent docker image
else
    echo "Pulling Autoware Image from dockerhub"
    docker compose pull autoware
fi
