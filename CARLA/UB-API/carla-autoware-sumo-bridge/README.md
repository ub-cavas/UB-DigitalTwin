# Custom Digital Twin Project for UB

A high-fidelity **Digital Twin** environment for the University at Buffalo (UB) Autonomous Proving Grounds, integrating **CARLA**, **SUMO**, and **Autoware**.

> ⚠️ **Prerequisite**: Run within [UB's Custom Docker Container](docs/setup.md#docker-container)

---

## Quick Start

```bash
# 1. Install dependencies in Autoware docker container
./ini_setup.sh

# 2. Start CARLA on host
./CarlaUE4.sh -quality-level=Low/Medium/High/Epic -prefernvidia

# 3. Launch Autoware
ros2 launch autoware_launch e2e_simulator.launch.xml \
    map_path:=/host_data/<PATH_TO_UB_AUTOWARE_MAP> \
    vehicle_model:=sample_vehicle \
    sensor_model:=awsim_sensor_kit \
    simulator_type:=carla \
    carla_map:=UBAutonomousProvingGrounds
```

📋 [Full Command Cheat Sheet](docs/COMMANDS.md)

---

## System Architecture

```mermaid
graph TB
    subgraph DOCKER["UB Custom Docker Container"]
        subgraph AW["Autoware Stack"]
            A_PERC["Perception"]
            A_PLAN["Planning"]
            A_CTRL["Control"]
        end
        
        subgraph INTERFACE["autoware_carla_interface"]
            BRIDGE["ROS 2 Bridge<br/>external_tick: True/False"]
        end
    end

    subgraph CARLA_SIM["CARLA Simulator"]
        ENV["UB Proving Grounds"]
        SENSORS["Sensors"]
        EGO["Ego Vehicle"]
        NPC["NPC Vehicles"]
    end

    subgraph SUMO_SIM["SUMO Traffic"]
        TRAFFIC["Traffic Logic"]
        LIGHTS["Traffic Lights"]
    end

    subgraph SYNC["run_synchronization.py"]
        TICKER["Time Master"]
    end

    A_PERC --> A_PLAN --> A_CTRL
    SENSORS --> BRIDGE
    BRIDGE --> EGO
    BRIDGE <--> A_PERC
    A_CTRL --> BRIDGE
    TICKER --> ENV
    TICKER <--> NPC
    TICKER <--> TRAFFIC
    LIGHTS <--> TICKER

    style DOCKER fill:#1a1a2e,stroke:#16213e,stroke-width:2px,color:#fff
    style CARLA_SIM fill:#e91e63,stroke:#880e4f,stroke-width:3px,color:#fff
    style SUMO_SIM fill:#4caf50,stroke:#1b5e20,stroke-width:3px,color:#fff
    style AW fill:#2196f3,stroke:#0d47a1,stroke-width:2px,color:#fff
    style INTERFACE fill:#ff9800,stroke:#e65100,stroke-width:2px,color:#fff
    style SYNC fill:#9c27b0,stroke:#4a148c,stroke-width:2px,color:#fff
    style TICKER fill:#ffeb3b,stroke:#f57f17,stroke-width:2px,color:#333
```

---

## 📁 Project Structure

```
├── autoware_carla_interface/   # ROS 2 bridge package
├── Sumo/                       # SUMO integration & configs
├── custom/                     # Custom maps and scripts
├── docs/                       # Documentation
│   ├── setup.md               # Installation guide
│   ├── carla-autoware.md      # CARLA + Autoware guide
│   ├── carla-sumo.md          # CARLA + SUMO guide
│   ├── combined-setup.md      # Full system guide
│   └── COMMANDS.md            # Command cheat sheet
└── ini_setup.sh               # Dependency installer
```

---

## Requirements

| Component | Version |
|-----------|---------|
| CARLA | 0.9.15 / 0.9.16 |
| ROS 2 | Humble / Galactic |
| SUMO | Latest |
| Python | 3.8+ |

[📖 Full Setup Guide](docs/setup.md)

---

## Documentation

| Document | Description |
|----------|-------------|
| [Setup Guide](docs/setup.md) | Installation & configuration |
| [CARLA + Autoware](docs/carla-autoware.md) | AV testing mode |
| [CARLA + SUMO](docs/carla-sumo.md) | Traffic simulation mode |
| [Combined Setup (SUMO + Autoware + Carla)](docs/combined-setup.md) | Full digital twin |
| [Commands](docs/COMMANDS.md) | Quick reference cheat sheet |

---

## Why Use This?

- **Realistic Simulation** - CARLA's physics + SUMO's traffic
- **Safe Testing** - Validate algorithms before real-world deployment  
- **Scalability** - Simulate edge cases impossible in reality
- **UB Custom Map** - Tailored for the Autonomous Proving Grounds

---
