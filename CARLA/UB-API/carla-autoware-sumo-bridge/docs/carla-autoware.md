# Running CARLA + Autoware

**Goal**: Run Autoware with CARLA as the simulator for autonomous vehicle testing.

## Overview

```
┌─────────────────┐     ┌──────────────────────────┐         ┌─────────────┐
│  CARLA Server   │◄───►│ autoware_carla_interface │◄───►    │  Autoware   │
│  (Simulator)    │     │    (ROS 2 Bridge)        │         │ (AV Stack)  │
└─────────────────┘     └──────────────────────────┘         └─────────────┘
                              ⏱️ Time Master
```

**Time Control**: The interface acts as the "Ticker" - it triggers each simulation step in CARLA and publishes `/clock` to ROS 2.

## Prerequisites

- [ ] CARLA installed and accessible
- [ ] Python dependencies installed in the docker container(`./ini_setup.sh`)
- [ ] The interface shows no errors and is able to publish ros topics

## Quick Start

```bash
# Terminal 1: Start CARLA
./CarlaUE4.sh -quality-level=Epic

# Terminal 2: Launch Autoware with CARLA
ros2 launch autoware_launch e2e_simulator.launch.xml \
    map_path:=/host_data/new_build_map \
    vehicle_model:=sample_vehicle \
    sensor_model:=awsim_sensor_kit \
    simulator_type:=carla \
    carla_map:=UBAutonomousProvingGrounds
```

## Detailed Steps

### Step 1: Launch CARLA

Start the simulator in server mode from your CARLA installation directory:

```bash
cd $CARLA_ROOT
./CarlaUE4.sh -quality-level=Epic
```

**Options**:

- `-quality-level=Low` - For lower-end hardware
- `-windowed` - Run in windowed mode
- `-ResX=1280 -ResY=720` - Set resolution

### Step 2: Verify Interface (Optional)

Test the bridge connection before launching full Autoware:

```bash
ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml \
    carla_map:=Town01 \
    external_tick:=False
```

**Verify**:

```bash
# Check topics are being published
ros2 topic list | grep -E "clock|sensing|tf"

# Check message rate
ros2 topic hz /clock
```

> ⚠️ **Terminate this process (Ctrl+C)** after verification to avoid conflicts.

### Step 3: Launch Autoware

Start the full Autoware stack:

```bash
ros2 launch autoware_launch e2e_simulator.launch.xml \
    map_path:=/host_data/new_build_map \
    vehicle_model:=sample_vehicle \
    sensor_model:=awsim_sensor_kit \
    simulator_type:=carla \
    carla_map:=UBAutonomousProvingGrounds
```

### Step 4: Operation Inside Autoware

If there are no errors up to this point, you should see the Autoware RViz window open and the ego vehicle localizing.

1.  **Verify Localization**: Ensure the vehicle position in RViz matches the spawn point in CARLA.
2.  **Set Goal**: Use the **2D Goal Pose** tool in RViz to set a destination on the map.
3.  **Engage Autonomy**:
    *   Wait for the path to be planned (visualized as a trajectory line).
    *   Click the **AUTO** button in the Autoware panel (or press the engage button if configured).
4.  **Observe Motion**: The vehicle should start moving in both the Autoware RViz visualization and the CARLA simulator window. 

## Key Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `carla_map` | CARLA map to load | `Town01`, `UBAutonomousProvingGrounds` |
| `external_tick` | Who controls time | `False` (interface ticks) |
| `map_path` | Autoware map directory | `/host_data/new_build_map` |
| `vehicle_model` | Vehicle configuration | `sample_vehicle` |
| `sensor_model` | Sensor configuration | `awsim_sensor_kit` |

## Data Flow

| Direction | Data | ROS 2 Topic |
|-----------|------|-------------|
| CARLA → Autoware | LiDAR | `/sensing/lidar/pointcloud` |
| CARLA → Autoware | Camera | `/sensing/camera/image_raw` |
| CARLA → Autoware | GNSS | `/sensing/gnss/nav_sat_fix` |
| CARLA → Autoware | Clock | `/clock` |
| Autoware → CARLA | Control | `/control/command/control_cmd` |

## Troubleshooting

<details>
<summary> "Failed to connect to CARLA server"</summary>

- Verify CARLA is running
- Check host/port settings (default: `localhost:2000`)
- If in Docker, use host IP: `host:=172.17.0.1`

</details>

<details>
<summary> No sensor data in RViz</summary>

- Check if interface is publishing: `ros2 topic echo /sensing/lidar/pointcloud`
- Verify map names match
- Check `/tf` transforms

</details>

---

[← Back to Main README](../README.md) | [Next: CARLA + SUMO →](carla-sumo.md)
