# UB Digital Twin

Welcome to the documentation for UB-DigitalTwin, the open-source autonomous vehicle simulation ecosystem.


## Main Components
- `CARLA/`: CARLA runtime, API containers, Redis networking, and SUMO bridge
  integration.
- `Autoware/`: UB's custom Autoware configuration
- `UB-MR/`: Mixed Reality runtime.
- `Map-Reconstruction/`: Map reconstruction resources.
- `scripts/`: Setup, launch, and evaluation helpers.

## Quick Start

1.) Clone this repo and submodules
```bash
# SSH
git clone --recurse-submodules git@github.com:ub-cavas/UB-DigitalTwin.git
# --OR--
# HTTPS
git clone --recurse-submodules https://github.com/ub-cavas/UB-DigitalTwin.git
```

2.) Set up CARLA (Packaged Version)
```bash
bash scripts/install_ub_carla.sh v1.0.0
# Build the Runtime Containers (CARLA Server, Redis Server, Python-API)
docker build -f CARLA/Dockerfile -t ub-carla CARLA
docker build -f CARLA/UB-API/redis-networking/Dockerfile -t ub-carla-redis-networking CARLA/UB-API/redis-networking
```

3.) Set up Autoware
```bash
bash Autoware/setup_autoware.sh
```

4.) Set up Mixed Reality
```bash
# Full setup (recommended)
bash scripts/setup_ub_mr.sh

# Partial setup = Unity player only, without pulling the Docker runtime image. Use this only if you plan to edit the UB-MR runtime docker image and build + test frequently
./scripts/download_ub_mr_release.sh
```
