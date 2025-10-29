AWSIM
--------------------
ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=/host_data/Shinjuku-Map vehicle_model:=sample_vehicle sensor_model:=awsim_sensor_kit simulator_type:=awsim

CARLA
-------------------
ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=/host_data/UBAutonomousProvingGrounds vehicle_model:=sample_vehicle sensor_model:=awsim_sensor_kit simulator_type:=carla carla_map:=UBAutonomousProvingGrounds