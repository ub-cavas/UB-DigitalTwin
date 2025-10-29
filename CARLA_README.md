Run UB-CARLA
-----------------------------
Autoware Install + Setup

1.) Follow the autoware (docker) install steps here: https://github.com/ub-cavas/ub-lincoln-docker/tree/main

2.) Download this HD Map of the UB autonomous proving grounds: https://buffalo.box.com/s/nwk8bdgux26ojlk20wbh1ougq9pqfzha

3.) The downloaded files should be located at: "/host_data/maps/ub_autonomous_proving_grounds"

4.) Install updated dependencies to the autoware container 

`pip install carla==0.9.16`

`pip3 install --upgrade transforms3d`

CARLA Install + Setup

1.) Download the packaged version:  
2.) Extract the files somewhere on your PC (we recommend ~/Desktop/)

Co-Simulation (Autoware + CARLA)

1.) Start the CARLA server

`./CarlaUE4.sh -prefernvidia`

2.) Launch the UB Autonomous Proving Ground Map

`python3 config.py -m=UBAutonomousProvingGrounds`

3.) Launch Autoware

`ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=/host_data/maps/ub_autonomous_proving_grounds vehicle_model:=sample_vehicle sensor_model:=awsim_sensor_kit simulator_type:=carla carla_map:=UBAutonomousProvingGrounds`

4.) Wait for RVIZ2 to launch and for the ego-vehicle to localize itself

5.) Set a goal position

6.) Select the "Auto" button in RVIZ

7.) The ego-vehicle should navigate to the designated goal position using autoware


Edit UB-CARLA in Unreal Engine 
----------------------------
cd /carla
make launch






