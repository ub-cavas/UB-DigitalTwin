# Local Simulation

## Empty World (UB-CARLA only)
```bash
# No Graphics
bash scripts/launch_carla.sh
# Graphics
CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound" bash scripts/launch_carla.sh
```

## Autonomous Vehicle (Autoware)
```bash
./scripts/launch_autoware_carla.sh
```

This wrapper defaults to these CARLA settings:
`CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound"`,


It also runs the same Autoware DDS host setup as `dc_up.sh` before starting
containers. In an interactive terminal, `sudo` may prompt for your password.
For non-interactive runs, run this once first:

```bash
cd Autoware/ub-lincoln-docker/docker
../scripts/host_config_dds.bash
```

The Autoware container and launcher both pin ROS 2 to CycloneDDS:
`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` and
`CYCLONEDDS_URI=file:///resources/cyclonedds.xml`. This keeps the automated
path consistent with the interactive `dc_bash.sh` workflow.

The rendered CARLA spectator follows the Autoware-controlled CARLA vehicle
behind `role_name=ego_vehicle` by default. For a custom ego role, set
`UB_AUTOWARE_CAMERA_FOLLOW_ROLE_NAMES=<role-name>`.

## Autonomous Vehicle with SUMO
```bash
# Starts rendered UB-CARLA, visible SUMO GUI, SUMO/CARLA synchronization,
# the Autoware container, the custom autoware_carla_interface, and Autoware.
./scripts/launch_autoware_carla_sumo.sh
```

This wrapper uses the existing
`CARLA/UB-API/carla-autoware-sumo-bridge` workflow. SUMO is the time master and
the Autoware CARLA interface is launched with `external_tick:=True`. The
launcher starts that interface explicitly, then runs Autoware e2e with
`AUTOWARE_E2E_SIMULATOR_TYPE=awsim` by default so Autoware does not include a
second CARLA interface. The launcher relays the CARLA bridge's
`/sensing/lidar/top/pointcloud_before_sync` output into
`/sensing/lidar/concatenated/pointcloud` for Autoware localization.


