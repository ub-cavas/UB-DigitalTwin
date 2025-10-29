Run UB-CARLA
-----------------------------
Autoware Setup
1.) Follow the autoware (docker) install steps here:
2.) Download this HD Map of the UB autonomous proving grounds:
3.) Place the HD map files in "/host_data/maps/UB-Autonomous-Proving-Grounds"

CARLA Setup

1.) Download the packaged version:  
2.) Extract the files somewhere on your PC (we recommend ~/Desktop/)

Co-Simulation (Autoware + CARLA)

1.) Start the CARLA server
`./CarlaUE4.sh -prefernvidia`
2.) Launch the UB Autonomous Proving Ground Map
`python3 config.py -m=UBAutonomousProvingGrounds`
3.) Launch Autoware
`TODO`

4.) Wait for Autoware to localize the ego-vehicle

5.) Set a goal position

6.) Select the "Auto" button in RVIZ


Edit UB-CARLA in Unreal Engine 
----------------------------
cd /carla
make launch






