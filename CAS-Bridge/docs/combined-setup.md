# Running CARLA + Autoware + SUMO (Combined)

**Goal**: Run the full Digital Twin with all three systems working together.

## Overview

```
                         ┌──────────────────────┐
                         │run_synchronization.py│
                         │    ⏱️ TIME MASTER    │
                         └──────────┬───────────┘
                                    │ world.tick()
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            ┌───────────┐   ┌─────────────┐   ┌─────────┐
            │   CARLA   │   │    SUMO     │   │         │
            │ Simulator │◄─►│   Traffic   │   │         │
            └─────┬─────┘   └─────────────┘   │         │
                  │                           │Autoware │
                  │ Sensors                   │         │
                  ▼                           │         │
        ┌──────────────────┐                  │         │
        │ autoware_carla_  │◄────────────────►│         │
        │    interface     │  ROS 2 Topics    │         │
        │external_tick=True│                  └─────────┘
        └──────────────────┘
              PASSIVE
```

**Key Concept**: Only ONE system can be the "Ticker":

- **Ticker**: `run_synchronization.py` controls time
- **Passive**: `autoware_carla_interface` with `external_tick:=True`

## Prerequisites

- [ ] All prerequisites from [CARLA + Autoware](carla-autoware.md)
- [ ] All prerequisites from [CARLA + SUMO](carla-sumo.md)
- [ ] Same map configured in all three systems

## Quick Start

```bash
# Terminal 1: CARLA
./CarlaUE4.sh /Game/Carla/Maps/UBAutonomousProvingGrounds

# Terminal 2: SUMO Sync (Time Master)
python3 Sumo/run_synchronization.py Sumo/examples/UBAutonomousProvingGrounds.sumocfg

# Terminal 3: Interface (Passive Mode)
ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml \
    carla_map:=UBAutonomousProvingGrounds external_tick:=True

# Terminal 4: Autoware
ros2 launch autoware_launch e2e_simulator.launch.xml \
    map_path:=/host_data/new_build_map \
    vehicle_model:=sample_vehicle \
    sensor_model:=awsim_sensor_kit \
    simulator_type:=carla \
    carla_map:=UBAutonomousProvingGrounds
```

## Initial Setup (One-Time)

### 1. Setup Custom SUMO Files

Copy the custom SUMO folder to your CARLA installation:

```bash
cp -r Sumo $CARLA_ROOT/Co-Simulation/Sumo
```

### 2. Setup Autoware Interface (In Docker)

Replace the default interface package:

```bash
# Remove existing
rm -rf /autoware/src/universe/autoware_universe/simulator/autoware_carla_interface

# Copy modified package (from host_data or clone)
cp -r $HOST_DATA_PATH/autoware_carla_interface \
      /autoware/src/universe/autoware_universe/simulator/
```

### 3. Configure Default to Passive Mode

Edit the launch file to default to passive mode:

**File**: `autoware_carla_interface/launch/autoware_carla_interface.launch.xml`

```xml
<!-- Change this line -->
<arg name="external_tick" default="True"/>
```

### 4. Rebuild the Package
Rebuild the package and source if the package is not detected
```bash
cd /autoware
colcon build --packages-select autoware_carla_interface
source install/setup.bash
```

## Detailed Execution

### Step 1: Launch CARLA with Graphic Card

```bash
./CarlaUE4.sh -prefer-nvidia -quality-level=Epic
```

Or launch and then load:

```bash
./CarlaUE4.sh
# Then in another terminal:
python3 $CARLA_ROOT/PythonAPI/util/config.py --map UBAutonomousProvingGrounds

```

### Step 2: Start SUMO Synchronization (Time Master)

This script controls simulation time for both CARLA and SUMO:

```bash
python3 run_synchronization.py examples/UBAutonomousProvingGrounds.sumocfg --step-length 0.05 --sumo-gui
```

**Verify**:

- SUMO GUI opens if gui option is selected
- if gui start the simulation (click on play), if it is running in headless mode the SUMO starts automatically
- Traffic appears in CARLA
- Console shows tick messages

### Step 3: Launch Autoware
> ⚠️ **CRITICAL**: Must use `external_tick:=True`

```bash
ros2 launch autoware_launch e2e_simulator.launch.xml \
    map_path:=/host_data/new_build_map \
    vehicle_model:=sample_vehicle \
    sensor_model:=awsim_sensor_kit \
    simulator_type:=carla \
    carla_map:=UBAutonomousProvingGrounds
```

## Time Control Explained

| Component | Role | `external_tick` |
|-----------|------|-----------------|
| `run_synchronization.py` | **Time Master** | N/A |
| `autoware_carla_interface` | Passive Bridge | `True` |
| CARLA | Waits for tick | N/A |
| SUMO | Synced by script | N/A |
| Autoware | Uses `/clock` | N/A |

### What Happens with Wrong Settings

| Scenario | Result |
|----------|--------|
| Both try to tick | Double-speed simulation, desync |
| Neither ticks | Simulation frozen |
| Correct setup | Smooth synchronized simulation |

## Map Consistency Checklist

| System | Must Match |
|--------|------------|
| CARLA | `UBAutonomousProvingGrounds` |
| SUMO | `UBAutonomousProvingGrounds.sumocfg` |
| Autoware | `carla_map:=UBAutonomousProvingGrounds` |
| Map Path | Contains matching lanelet2 map |

## Troubleshooting

<details>
<summary> "Double tick" or simulation running too fast</summary>

- Ensure `external_tick:=True` in interface launch
- Check only sync script is running, not multiple instances

</details>

<details>
<summary> Simulation frozen / not advancing</summary>

- Verify sync script is running
- Check for errors in sync script output
- Ensure CARLA is in synchronous mode

</details>

<details>
<summary> Autoware not receiving sensor data</summary>

- Check interface is running
- Verify `/clock` is being published: `ros2 topic hz /clock`
- Check ROS_DOMAIN_ID matches

</details>

<details>
<summary> Traffic not appearing</summary>

- Verify SUMO config matches CARLA map
- Check sync script shows "spawning" messages
- Try restarting sync script

</details>

---

[← Back to Main README](../README.md) | [← Previous: CARLA + SUMO](carla-sumo.md)
