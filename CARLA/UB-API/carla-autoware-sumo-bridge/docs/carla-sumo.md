# Running CARLA + SUMO

**Goal**: Run CARLA with realistic SUMO traffic for environment simulation.

## Overview

```
┌─────────────────┐     ┌──────────────────────┐       ┌─────────────┐
│  CARLA Server   │◄───►│ run_synchronization.py │◄───►│    SUMO     │
│  (3D Rendering) │     │   (Co-Simulation)    │       │  (Traffic)  │
└─────────────────┘     └──────────────────────┘       └─────────────┘
                              ⏱️ Time Master
```

**Time Control**: The synchronization script (`run_synchronization.py`) acts as the "Ticker" - it advances both CARLA and SUMO step-by-step.

## Prerequisites

- [ ] CARLA installed
- [ ] SUMO installed with `SUMO_HOME` set
- [ ] Python dependencies installed in docker container(`./ini_setup.sh`)
- [ ] Matching maps in CARLA and SUMO

## Quick Start

```bash
# Terminal 1: Start CARLA
./CarlaUE4.sh

# Terminal 2: Load map
python3 $CARLA_ROOT/PythonAPI/util/config.py --map UBAutonomousProvingGrounds

# Terminal 3: Run synchronization
python3 Sumo/run_synchronization.py Sumo/examples/UBAutonomousProvingGrounds.sumocfg
```

## Detailed Steps

### Step 1: Launch CARLA

```bash
cd $CARLA_ROOT
./CarlaUE4.sh
```

### Step 2: Load the Map

In a new terminal, load the desired map:

```bash
cd $CARLA_ROOT/PythonAPI/util
python3 config.py --map UBAutonomousProvingGrounds
```

**Available Maps**:

- `Town01`, `Town04`, `Town05` (built-in)
- `UBAutonomousProvingGrounds` (custom)

## ⚠️ Critical: Map Matching

> **The CARLA map and SUMO configuration MUST match!**

| CARLA Map | SUMO Config File |
|-----------|------------------|
| `Town01` | `Town01.sumocfg` |
| `Town04` | `Town04.sumocfg` |
| `Town05` | `Town05.sumocfg` |
| `UBAutonomousProvingGrounds` | `UBAutonomousProvingGrounds.sumocfg` |

Mismatched maps will cause:

- Vehicles spawning in wrong locations
- Crashes or simulation errors
- Traffic light desync

### Step 3: Run Synchronization

Start the co-simulation bridge:

```bash
python3 run_synchronization.py examples/UBAutonomousProvingGrounds.sumocfg --step-length 0.05 --sumo-gui
```

You should see:

- SUMO GUI window open
- Vehicles appearing in both CARLA and SUMO
- Traffic lights synchronized

## Available SUMO Configurations

| File | Map | Description |
|------|-----|-------------|
| `Town01.sumocfg` | Town01 | Basic town |
| `Town04.sumocfg` | Town04 | Highway |
| `Town05.sumocfg` | Town05 | Urban |
| `UBAutonomousProvingGrounds.sumocfg` | UB Custom | Proving grounds |

## Synchronization Details

### What Gets Synced

| Element | Direction | Notes |
|---------|-----------|-------|
| Vehicle positions | SUMO ↔ CARLA | Bidirectional |
| Traffic lights | SUMO → CARLA | State and timing |
| Spawned vehicles | SUMO → CARLA | NPC traffic |

### Sync Script Options

```bash
python3 run_synchronization.py [config.sumocfg] [options]

Options:
  --tls-manager sumo    # SUMO controls traffic lights (default)
  --tls-manager carla   # CARLA controls traffic lights
  --sync-vehicle-all    # Sync all vehicles, not just SUMO-spawned
```

## Troubleshooting

<details>
<summary> "SUMO_HOME not set"</summary>

```bash
export SUMO_HOME=/usr/share/sumo  # Linux
export SUMO_HOME=/opt/homebrew/opt/sumo/share/sumo  # macOS
```

</details>

<details>
<summary> Vehicles not appearing in CARLA</summary>

- Check map names match exactly
- Verify SUMO GUI shows vehicles
- Check synchronization script output for errors

</details>

<details>
<summary> Traffic lights not syncing</summary>

- Try `--tls-manager sumo` flag
- Ensure traffic light IDs match between CARLA and SUMO net file

</details>

---

[← Back to Main README](../README.md) | [← Previous: CARLA + Autoware](carla-autoware.md) | [Next: Combined Setup →](combined-setup.md)
