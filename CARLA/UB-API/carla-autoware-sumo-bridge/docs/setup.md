# Setup & Installation

This guide covers the complete setup process for the UB Digital Twin environment.

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| CARLA | 0.9.15 or 0.9.16 | Simulator |
| ROS 2 | Humble or Galactic | Middleware |
| SUMO | Latest | Traffic simulation |
| Docker | Latest | UB Custom Container |
| Python | 3.8+ | With pip |

## 1. Environment Setup

### Docker Container

> ⚠️ **IMPORTANT**: This setup is designed to run within **UB's Custom Docker Container**.

Ensure you have:

1. Pulled the UB custom Docker image
2. Launched the container with proper volume mounts
3. Set up display forwarding for GUI applications

### Environment Variables

Add these to your shell profile (`.bashrc` or `.zshrc`):

```bash
# Required paths
export HOST_DATA_PATH=/path/to/host_data
export AUTOWARE_DATA_PATH=/path/to/autoware_data
export CARLA_ROOT=/path/to/carla
export SUMO_HOME=/path/to/sumo

# Python path for CARLA (if doesn't exist)
export PYTHONPATH="$CARLA_ROOT/PythonAPI/carla/dist/carla-0.9.16-py3.7-linux-x86_64.egg:$PYTHONPATH"
```

## 2. Install Python Dependencies

Run the provided setup script inside ub-lincoln container:

```bash
chmod +x ini_setup.sh
./ini_setup.sh
```

This installs:

- `carla==0.9.16` - CARLA Python API
- `transforms3d` - 3D transformation utilities

### Manual Installation (Alternative)

```bash
python3 -m pip install carla==0.9.16
pip3 install --upgrade transforms3d
```

### Verify Installation

```bash
python3 -c "import carla; print(f'CARLA {carla.__version__} OK')"
python3 -c "import transforms3d; print('transforms3d OK')"
```

## 3. SUMO Setup

Ensure SUMO is installed and accessible:

```bash
# Verify SUMO installation
echo $SUMO_HOME
sumo --version
```

If not installed, follow [SUMO Installation Guide](https://sumo.dlr.de/docs/Installing/index.html).

## 4. ROS 2 Workspace Setup

Build the interface package Inside the docker container if it doesnt show up

```bash
# Source ROS 2
source /opt/ros/humble/setup.bash

# Navigate to workspace
cd /autoware

# Build the interface package
colcon build --symlink-install --packages-select autoware_carla_interface

# Source the workspace
source install/setup.bash
```

### Verify ROS 2 Setup

```bash
ros2 pkg list | grep autoware_carla
```

## 5. Verify Complete Setup

Run these checks to ensure everything is ready:

```bash
# 1. Check CARLA connection (start CARLA first)
python3 -c "import carla; c = carla.Client('localhost', 2000); print(f'Connected to CARLA {c.get_server_version()}')"

# 2. Check ROS 2 interface
ros2 launch autoware_carla_interface --show-args autoware_carla_interface.launch.xml

# 3. Check SUMO
python3 -c "import os; print(f'SUMO_HOME: {os.environ.get(\"SUMO_HOME\", \"NOT SET\")}')"
```

---

## Troubleshooting

<details>
<summary> CARLA connection refused</summary>

- Ensure CARLA server is running: `./CarlaUE4.sh`
- Check firewall settings
- Verify host IP if running across containers

</details>

<details>
<summary> Module 'carla' not found</summary>

- Check PYTHONPATH includes CARLA egg file
- Reinstall: `pip install carla==0.9.16`

</details>

<details>
<summary> ROS 2 package not found</summary>

- Rebuild workspace: `colcon build`
- Source setup: `source install/setup.bash`

</details>

---

[← Back to Main README](../README.md)
