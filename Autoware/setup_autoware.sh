#!/bin/bash

# Clone the ub-lincoln-docker repo
git clone https://github.com/ub-cavas/ub-lincoln-docker.git

# Create required "host_data" and "autoware_data" directories
mkdir host_data
mkdir autoware_data

# Download autoware artifacts
cd autoware_data
bash ub-lincoln-docker/scripts/host_dl_artifacts.bash

# Download the UB-HD map
cd ../host_data
mkdir maps
cd maps
wget https://buffalo.box.com/s/nwk8bdgux26ojlk20wbh1ougq9pqfzha

# build the image locally
if [[ " $@ " =~ " --build_local" ]]; then
    echo "Building Autoware..."
    ./build_ros2.sh
    ./build_autoware.sh
# OR
# pull the most recent docker image
else
    echo "Pulling Autoware Image from dockerhub"
    cd ../ub-lincoln-docker/docker
    docker compose pull









