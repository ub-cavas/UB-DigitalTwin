# autoware_carla_interface

## ROS 2 / Autoware Universe bridge for CARLA simulator

Thanks to <https://github.com/gezp> for ROS 2 Humble support for CARLA Communication.
This ros package enables communication between Autoware and CARLA for autonomous driving simulation.
In this UB Digital Twin fork, the default mode is passive: the bridge does not tick CARLA when
`external_tick:=True`. A separate Python time master, such as the SUMO synchronization script, owns
CARLA `world.tick()`.

## Supported Environment

| ubuntu |  ros   | carla  | autoware |
| :----: | :----: | :----: | :------: |
| 22.04  | humble | 0.9.15 |   Main   |

## Setup

### UB Autoware Container Integration

This package is mounted into the Autoware container as a ROS 2 `ament_python` source package:

```text
/autoware/src/universe/autoware_universe/simulator/autoware_carla_interface
```

The Autoware Compose service mounts it from:

```text
CARLA/UB-API/carla-autoware-sumo-bridge/autoware_carla_interface
```

`Autoware/setup_autoware.sh` writes `UB_AUTOWARE_CARLA_INTERFACE_PATH` into
`Autoware/ub-lincoln-docker/docker/.env`. Override that variable if you want the container to use
another checkout of this package.

After the Autoware container starts, build and source it in the normal Autoware workspace:

```bash
cd /autoware
colcon build --symlink-install --packages-select autoware_carla_interface
source /autoware/install/setup.bash
ros2 pkg prefix autoware_carla_interface
```

The `CARLA/start_autoware_carla_sumo.sh` launcher performs this build automatically before it
launches the passive bridge.

### Install

- [CARLA Installation](https://carla.readthedocs.io/en/latest/start_quickstart/)
- [Carla Lanelet2 Maps](https://bitbucket.org/carla-simulator/autoware-contents/src/master/maps/)
- [Python Package for CARLA 0.9.15 ROS 2 Humble communication](https://github.com/gezp/carla_ros/releases/tag/carla-0.9.15-ubuntu-22.04)

  - Install the wheel using pip.
  - OR add the egg file to the `PYTHONPATH`.

1. Download maps (y-axis inverted version) to arbitrary location
2. Change names and create the map folder (example: Town01) inside `autoware_map`. (`point_cloud/Town01.pcd` -> `autoware_map/Town01/pointcloud_map.pcd`, `vector_maps/lanelet2/Town01.osm`-> `autoware_map/Town01/lanelet2_map.osm`)
3. Create `map_projector_info.yaml` on the folder and add `projector_type: Local` on the first line.

### Build

```bash
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release
```

### Run

1. Run carla, change map, spawn object if you need
   <!--- cspell:ignore prefernvidia -->

   ```bash
   cd CARLA
   ./CarlaUE4.sh -prefernvidia -quality-level=Low -RenderOffScreen
   ```

2. Run ros nodes

   ```bash
   ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=$HOME/autoware_map/Town01 vehicle_model:=ub_lincoln_vehicle sensor_model:=ub_lincoln_sensor_kit simulator_type:=awsim
   ```

3. Set initial pose (Init by GNSS)
4. Set goal position
5. Wait for planning
6. Engage

## Inner-workings / Algorithms

The `InitializeInterface` class is key to setting up both the CARLA world and the ego vehicle. It fetches configuration parameters through the `autoware_carla_interface.launch.xml`.

The main simulation loop runs within the `carla_ros2_interface` class. In passive mode, it waits for
CARLA frames produced by an external time master, then publishes the matching sensor data and
vehicle status to ROS 2 once per frame. In active mode (`external_tick:=False`), the bridge can still
tick CARLA itself for standalone testing.

Ego vehicle commands from Autoware are processed through the `autoware_raw_vehicle_cmd_converter`, which calibrates these commands for CARLA. The calibrated commands are then fed directly into CARLA control via `CarlaDataProvider`.

### Configurable Parameters for World Loading

All the key parameters can be configured in `autoware_carla_interface.launch.xml`.

| Name                      | Type   | Default Value                                                                     | Description                                                                                                                                                                                                         |
| ------------------------- | ------ | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `host`                    | string | "localhost"                                                                       | Hostname for the CARLA server                                                                                                                                                                                       |
| `port`                    | int    | "2000"                                                                            | Port number for the CARLA server                                                                                                                                                                                    |
| `timeout`                 | int    | 20                                                                                | Timeout for the CARLA client                                                                                                                                                                                        |
| `ego_vehicle_role_name`   | string | "ego_vehicle"                                                                     | Role name for the ego vehicle                                                                                                                                                                                       |
| `vehicle_type`            | string | "vehicle.lincoln.mkz_2020"                                                        | Blueprint ID of the vehicle to spawn. The Blueprint ID of vehicles can be found in [CARLA Blueprint ID](https://carla.readthedocs.io/en/latest/catalogue_vehicles/)                                                 |
| `spawn_point`             | string | None                                                                              | Coordinates for spawning the ego vehicle (None is random). Format = [x, y, z, roll, pitch, yaw]                                                                                                                     |
| `project_spawn_point_to_road` | bool | False                                                                         | When true, project `spawn_point` x/y to the nearest CARLA driving waypoint and use that waypoint transform. This matches the old UB custom traffic spawn behavior.                                                   |
| `carla_map`               | string | "Town01"                                                                          | Name of the map to load in CARLA                                                                                                                                                                                    |
| `sync_mode`               | bool   | True                                                                              | Boolean flag to set synchronous mode in CARLA                                                                                                                                                                       |
| `fixed_delta_seconds`     | double | 0.05                                                                              | Time step for the simulation (related to client FPS)                                                                                                                                                                |
| `objects_definition_file` | string | "$(find-pkg-share autoware_carla_interface)/objects.json"                         | Sensor parameters file that are used for spawning sensor in CARLA. The passive UB-Lincoln launcher overrides this to `objects_ub_lincoln.json`.                                                                      |
| `use_traffic_manager`     | bool   | True                                                                              | Boolean flag to set traffic manager in CARLA                                                                                                                                                                        |
| `max_real_delta_seconds`  | double | 0.05                                                                              | Parameter to limit the simulation speed below `fixed_delta_seconds`                                                                                                                                                 |
| `external_tick`           | bool   | True                                                                              | When true, the bridge never calls `world.tick()` and waits for an external time master                                                                                                                              |
| `external_tick_timeout`   | double | 20.0                                                                              | Seconds to wait for the next externally produced CARLA frame before failing clearly                                                                                                                                  |
| `align_base_link_to_rear_axle` | bool | True                                                                        | When true, publish `base_link` at the CARLA ego rear axle and convert `base_link` sensor offsets into CARLA actor-relative transforms.                                                                               |
| `config_file`             | string | "$(find-pkg-share autoware_carla_interface)/raw_vehicle_cmd_converter.ub_lincoln.param.yaml" | Control mapping file to be used in `autoware_raw_vehicle_cmd_converter`. Use `custom_scripts/calibrate_ub_lincoln_control_maps.py` to regenerate the UB-Lincoln maps from a live CARLA sweep.                    |

### Passive Time-Master Contract

When `external_tick:=True`:

- The bridge does not call `client.load_world()`, `world.apply_settings()`, or `world.tick()`.
- The external time master must load the CARLA map, enable synchronous mode, set
  `fixed_delta_seconds`, and call `world.tick()`.
- The bridge waits on CARLA frame snapshots using `wait_for_tick()` and processes each new frame
  once.
- Launch Autoware with `simulator_type:=awsim` when this bridge is started separately, so Autoware
  does not launch a second CARLA interface.

### Configurable Parameters for Sensors

Below parameters can be configured in `carla_ros.py`.

| Name                      | Type | Default Value                                                                          | Description                                                                                                                                                                                                                       |
| ------------------------- | ---- | -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `self.sensor_frequencies` | dict | {"top": 11, "left": 11, "right": 11, "camera": 11, "imu": 50, "status": 50, "pose": 2} | (line 67) Calculates the time interval since the last publication and checks if this interval meets the minimum required to not exceed the desired frequency. It will only affect ROS publishing frequency not CARLA sensor tick. |

- CARLA sensor parameters can be configured in `config/objects.json`.
  - For more details regarding the parameters that can be modified in CARLA are explained in [Carla Ref Sensor](https://carla.readthedocs.io/en/latest/ref_sensors/).

### World Loading

The `carla_ros.py` sets up the CARLA world:

1. **Client Connection**:

   ```python
   client = carla.Client(self.local_host, self.port)
   client.set_timeout(self.timeout)
   ```

2. **Load the Map**:

   Map loaded in CARLA world with map according to `carla_map` parameter.

   ```python
   client.load_world(self.map_name)
   self.world = client.get_world()
   ```

3. **Spawn Ego Vehicle**:

   Vehicle are spawn according to `vehicle_type`, `spawn_point`, and `agent_role_name` parameter.

   ```python
   spawn_point = carla.Transform()
   point_items = self.spawn_point.split(",")
   if len(point_items) == 6:
      spawn_point.location.x = float(point_items[0])
      spawn_point.location.y = float(point_items[1])
      spawn_point.location.z = float(point_items[2])
      spawn_point.rotation.roll = float(point_items[3])
      spawn_point.rotation.pitch = float(point_items[4])
      spawn_point.rotation.yaw = float(point_items[5])
   CarlaDataProvider.request_new_actor(self.vehicle_type, spawn_point, self.agent_role_name)
   ```

## Traffic Light Recognition

The maps provided by the Carla Simulator ([Carla Lanelet2 Maps](https://bitbucket.org/carla-simulator/autoware-contents/src/master/maps/)) currently lack proper traffic light components for Autoware and have different latitude and longitude coordinates compared to the pointcloud map. To enable traffic light recognition, follow the steps below to modify the maps.

- Options to Modify the Map

  - A. Create a New Map from Scratch
  - Use the [TIER IV Vector Map Builder](https://tools.tier4.jp/feature/vector_map_builder_ll2/) to create a new map.

  - B. Modify the Existing Carla Lanelet2 Maps
  - Adjust the longitude and latitude of the [Carla Lanelet2 Maps](https://bitbucket.org/carla-simulator/autoware-contents/src/master/maps/) to align with the PCD (origin).
    - Use this [tool](https://github.com/mraditya01/offset_lanelet2/tree/main) to modify the coordinates.
    - Snap Lanelet with PCD and add the traffic lights using the [TIER IV Vector Map Builder](https://tools.tier4.jp/feature/vector_map_builder_ll2/).

- When using the TIER IV Vector Map Builder, you must convert the PCD format from `binary_compressed` to `ascii`. You can use `pcl_tools` for this conversion.
- For reference, an example of Town01 with added traffic lights at one intersection can be downloaded [here](https://drive.google.com/drive/folders/1QFU0p3C8NW71sT5wwdnCKXoZFQJzXfTG?usp=sharing).

## Tips

- Misalignment might occurs during initialization, pressing `init by gnss` button should fix it.
- Changing the `fixed_delta_seconds` can increase the simulation tick (default 0.05 s), some sensors params in `objects.json` need to be adjusted when it is changed (example: LIDAR rotation frequency have to match the FPS).

## Known Issues and Future Works

- Testing on procedural map (Adv Digital Twin).
  - Currently unable to test it due to failing in the creation of the Adv digital twin map.
- Automatic sensor configuration of the CARLA sensors from the Autoware sensor kit.
  - Sensor currently not automatically configured to have the same location as the Autoware Sensor kit. The current work around is to create a new frame of each sensors with (0, 0, 0, 0, 0, 0) coordinate relative to base_link and attach each sensor on the new frame (`autoware_carla_interface.launch.xml` Line 28). This work around is very limited and restrictive, as when the sensor_kit is changed the sensor location will be wrongly attached.
- Traffic light recognition.
  - Currently the HDmap of CARLA did not have information regarding the traffic light which is necessary for Autoware to conduct traffic light recognition.
