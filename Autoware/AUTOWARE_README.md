Installing Autoware via Docker
----------------------
1.) Follow **ALL** steps in the "Prerequisite" section to set up an NVIDIA supported docker environment: https://github.com/ub-cavas/ub-lincoln-docker

2.)  Run `./setup_autoware.sh v1.1.0` (or the version matching your CARLA build).


The setup helper downloads the corresponding map files from the public release
folder into `host_data/maps/ub_autonomous_proving_grounds/<version>/` and reuses
complete existing map sets. To install both CARLA and maps from the repository
root, run `bash scripts/install_ub_carla.sh v1.1.0`.

AWSIM
--------------------
ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=/host_data/Shinjuku-Map vehicle_model:=sample_vehicle sensor_model:=awsim_sensor_kit simulator_type:=awsim

CARLA
-------------------
ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=/host_data/maps/ub_autonomous_proving_grounds/v1.1.0 vehicle_model:=sample_vehicle sensor_model:=awsim_sensor_kit simulator_type:=carla carla_map:=UBAutonomousProvingGrounds
