# UB Digital Twin

## Setup Instructions

1. Clone this repo and submodules
```bash
# SSH
git clone --recurse-submodules git@github.com:ub-cavas/UB-DigitalTwin.git
# HTTPS
git clone --recurse-submodules https://github.com/ub-cavas/UB-DigitalTwin.git
```

2. Run the CARLA Installer Script (Packaged Version)
```bash
bash scripts/install_ub_carla.sh v1.0.0
```

3. Build the Runtime Containers (CARLA Server, Redis Server, Python-API)
```bash
docker build -f CARLA/Dockerfile -t ub-carla CARLA
docker build -f CARLA/UB-API/redis-networking/Dockerfile -t ub-carla-redis-networking CARLA/UB-API/redis-networking
```

## CARLA Docker Compose Stack

The Compose stack includes CARLA, Redis, map loading, and Redis networking sidecars.

```bash
cd CARLA
xhost +local:root

# CARLA + Redis + map loader only
docker compose up --build

# Headless/offscreen CARLA + Redis + map loader
CARLA_ARGS="-RenderOffScreen -nosound" 
docker compose up --build

# CARLA + Redis + traffic publisher + UDP bridge for UB-MR client
CARLA_ARGS="-quality=Low -nosound" 
docker compose --profile ub-mr up --build
```

Useful overrides:
```bash
# Use a different packaged CARLA build folder under CARLA/Builds
BUILD_FOLDER=v1.0.0 docker compose --profile ub-mr up --build

# Send UDP bridge traffic to UB-MR on another machine
UB_UNITY_HOST=<ub-mr-machine-ip> docker compose --profile ub-mr up --build

# Disable the default async traffic publisher mode
UB_CARLA_ASYNC=0 docker compose --profile ub-mr up --build

# Disable automatic map loading
CARLA_MAP_PATH= docker compose --profile ub-mr up --build
```

Optional sidecar profiles:
```bash
docker compose --profile traffic-publisher up --build
docker compose --profile udp-bridge up --build
docker compose --profile traffic-renderer up --build
docker compose --profile multi-agent-renderer up --build
```
