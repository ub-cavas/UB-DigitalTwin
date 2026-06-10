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

3. Build the Runtime Container
```bash
docker build -f CARLA/Dockerfile -t ub-carla CARLA
```

4. Start the CARLA executable
```bash
# w/ Rendering
bash CARLA/run_ub_carla.sh v1.0.0 -prefernvidia -quality-level=Low -nosound
# w/o Rendering
bash CARLA/run_ub_carla.sh v1.0.0 -RenderOffScreen -nosound
```