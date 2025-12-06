# Command Cheat Sheet

Quick reference for all commands. Copy-paste ready.

---

## Quick Start Commands

### CARLA + Autoware Only
```bash
# Terminal 1
./CarlaUE4.sh -quality-level=Epic

# Terminal 2
ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=/host_data/new_build_map vehicle_model:=sample_vehicle sensor_model:=awsim_sensor_kit simulator_type:=carla carla_map:=UBAutonomousProvingGrounds
```

### CARLA + SUMO Only
```bash
# Terminal 1
./CarlaUE4.sh

# Terminal 2
python3 $CARLA_ROOT/PythonAPI/util/config.py --map UBAutonomousProvingGrounds

# Terminal 3
python3 Sumo/run_synchronization.py Sumo/examples/UBAutonomousProvingGrounds.sumocfg
```

### Full System (CARLA + Autoware + SUMO)
```bash
# Terminal 1: CARLA
./CarlaUE4.sh /Game/Carla/Maps/UBAutonomousProvingGrounds

# Terminal 2: SUMO (Time Master)
python3 Sumo/run_synchronization.py Sumo/examples/UBAutonomousProvingGrounds.sumocfg

# Terminal 3: Interface (Passive)
ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml carla_map:=UBAutonomousProvingGrounds external_tick:=True

# Terminal 4: Autoware
ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=/host_data/new_build_map vehicle_model:=sample_vehicle sensor_model:=awsim_sensor_kit simulator_type:=carla carla_map:=UBAutonomousProvingGrounds
```

---

## Setup Commands

### Install Dependencies
```bash
chmod +x ini_setup.sh
./ini_setup.sh
```

### Environment Variables
```bash
export HOST_DATA_PATH=/home/poison/host_data
export AUTOWARE_DATA_PATH=/home/poison/autoware_data
export CARLA_ROOT=/path/to/carla
export SUMO_HOME=/usr/share/sumo
```

### Build ROS 2 Package
```bash
source /opt/ros/humble/setup.bash
cd /autoware
colcon build --symlink-install --packages-select autoware_carla_interface
source install/setup.bash
```

---

## CARLA Commands

### Start CARLA
```bash
./CarlaUE4.sh                              # Default
./CarlaUE4.sh -quality-level=Epic          # High quality
./CarlaUE4.sh -quality-level=Low           # Low quality
./CarlaUE4.sh -windowed -ResX=1280 -ResY=720  # Windowed
```

### Load Map
```bash
python3 $CARLA_ROOT/PythonAPI/util/config.py --map Town01
python3 $CARLA_ROOT/PythonAPI/util/config.py --map UBAutonomousProvingGrounds
```

### Start with Specific Map
```bash
./CarlaUE4.sh /Game/Carla/Maps/Town01
./CarlaUE4.sh /Game/Carla/Maps/UBAutonomousProvingGrounds
```

---

## Autoware Commands

### Launch Full Stack
```bash
ros2 launch autoware_launch e2e_simulator.launch.xml \
    map_path:=/host_data/new_build_map \
    vehicle_model:=sample_vehicle \
    sensor_model:=awsim_sensor_kit \
    simulator_type:=carla \
    carla_map:=UBAutonomousProvingGrounds
```

### Launch Interface Only
```bash
# Active mode (interface ticks)
ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml \
    carla_map:=Town01 external_tick:=False

# Passive mode (external ticker)
ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml \
    carla_map:=UBAutonomousProvingGrounds external_tick:=True
```

---

## SUMO Commands

### Run Synchronization
```bash
python3 Sumo/run_synchronization.py Sumo/examples/Town01.sumocfg
python3 Sumo/run_synchronization.py Sumo/examples/UBAutonomousProvingGrounds.sumocfg
```

---

## Debugging Commands

### Check ROS 2 Topics
```bash
ros2 topic list
ros2 topic list | grep sensing
ros2 topic hz /clock
ros2 topic echo /sensing/lidar/pointcloud --once
```

### Check Transforms
```bash
ros2 run tf2_tools view_frames
ros2 run tf2_ros tf2_echo base_link map
```

### Check CARLA Connection
```bash
python3 -c "import carla; c = carla.Client('localhost', 2000); print(c.get_server_version())"
```

### Check Installed Packages
```bash
python3 -m pip show carla transforms3d
ros2 pkg list | grep autoware
```

---

## File Locations

| What | Path |
|------|------|
| SUMO configs | `Sumo/examples/*.sumocfg` |
| SUMO networks | `Sumo/examples/net/*.net.xml` |
| Interface launch | `autoware_carla_interface/launch/` |
| Calibration maps | `autoware_carla_interface/calibration_maps/` |
| Custom scripts | `custom/` |

---

## Available Maps

| CARLA Map | SUMO Config |
|-----------|-------------|
| `Town01` | `Town01.sumocfg` |
| `Town04` | `Town04.sumocfg` |
| `Town05` | `Town05.sumocfg` |
| `UBAutonomousProvingGrounds` | `UBAutonomousProvingGrounds.sumocfg` |

---

[← Back to Main README](../README.md)
