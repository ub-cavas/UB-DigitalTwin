Run UB-CARLA
-----------------------------

One-command rendered CARLA + Autoware
-----------------------------

From the repository root, install the packaged CARLA build and Autoware assets:

```bash
bash scripts/install_ub_carla.sh v1.0.0

cd Autoware
./setup_autoware.sh
```

Then launch rendered CARLA on `UBAutonomousProvingGrounds` and run the Autoware
CARLA simulator launch in the foreground:

```bash
cd ../CARLA
./start_autoware_carla.sh
```

The launcher uses `docker compose up --build -d carla redis map-loader`, waits
for the map loader to finish, starts the Autoware Compose service, and runs:

```bash
ros2 launch autoware_launch e2e_simulator.launch.xml \
  map_path:=/host_data/maps/ub_autonomous_proving_grounds \
  vehicle_model:=sample_vehicle \
  sensor_model:=awsim_sensor_kit \
  simulator_type:=carla \
  host:=127.0.0.1 \
  carla_map:=UBAutonomousProvingGrounds
```

Check prerequisites without starting containers:

```bash
./start_autoware_carla.sh --dry-run
```

Common overrides:

```bash
CARLA_ARGS="-prefernvidia -quality-level=Epic" ./start_autoware_carla.sh
AUTOWARE_SERVICE=<compose-service-name> ./start_autoware_carla.sh
AUTOWARE_CARLA_HOST=<host-ip-visible-from-autoware> ./start_autoware_carla.sh
UB_AUTOWARE_INSTALL_PY_DEPS=0 ./start_autoware_carla.sh
UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY=0 ./start_autoware_carla.sh
UB_KEEP_CARLA=1 ./start_autoware_carla.sh
```

By default, the launcher verifies and installs the required Autoware-container
Python packages (`carla==0.9.16`, `transforms3d==0.4.2`) before running the ROS
launch.

It also enables `UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY=1` by default. This patches
the running Autoware container's sensor-kit synchronizer for the current CARLA
bridge, which spawns one top LiDAR while Autoware expects multiple pointcloud
inputs.

Manual Autoware Install + Setup
-----------------------------

Autoware Install + Setup

1.) Follow the autoware (docker) install steps here: https://github.com/ub-cavas/ub-lincoln-docker/tree/main

2.) Download this HD Map of the UB autonomous proving grounds: https://buffalo.box.com/s/nwk8bdgux26ojlk20wbh1ougq9pqfzha

3.) The downloaded files should be located at: "/host_data/maps/ub_autonomous_proving_grounds"

4.) Install updated dependencies to the autoware container 

`pip3 install carla==0.9.16`

`pip3 install --upgrade transforms3d`

CARLA Install + Setup

1.) Download the packaged version:  
2.) Extract the files somewhere on your PC (we recommend ~/Desktop/)

Co-Simulation (Autoware + CARLA)

1.) Start the CARLA server

`./CarlaUE4.sh -prefernvidia`

2.) Launch Autoware

`ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=/host_data/maps/ub_autonomous_proving_grounds vehicle_model:=sample_vehicle sensor_model:=awsim_sensor_kit simulator_type:=carla carla_map:=UBAutonomousProvingGrounds`

3.) Run the camera script

`cd UB-API`

`python3 camera_follow.py`

4.) Wait for RVIZ2 to launch and for the ego-vehicle to localize itself

5.) Set a goal position

6.) Select the "Auto" button in RVIZ

7.) The ego-vehicle should navigate to the designated goal position using autoware

8.) Spawn traffic

`cd UB-API/Traffic`

`python3 spawn_traffic.py`


Edit UB-CARLA in Unreal Engine 
----------------------------
cd /carla
make launch



