## SUMO Setup

To run a custom map on Carla, you will need .net, .rou, and .sumocfg files.
In this case, UBAutonomousProvingGrounds will be used

1.) In the terminal, locate UBAutonomousProvingGrounds.xodr in CARLA_5cc238b5c-dirty/CarlaUE4/Content/Carla/Maps  

2.) In the command prompt, type netconvert --opendrive-files UBAutonomousProvingGrounds.xodr -o UBAutonomousProvingGrounds.net.xml  

3.) Move UBAutonomousProvingGrounds.net.xml to CARLA_5cc238b5c-dirty/Co-Simulation/Sumo/examples/net folder  

4.) Run Sumo and open UBAutonomousProvingGrounds.net.xml  

5.) Go to Edit on top and press 'Open network in netedit'  

6.) In the netedit, press 'Demand' and go to 'Vehicle Mode' on top to create traffic  

7.) Go to 'File' and press 'Demand Elements' to create .rou file (The .rou file should go into CARLA_5cc238b5c-dirty/Co-Simulation/Sumo/examples/rou folder).  

8.) From the 'File', press 'Sumo Config' to create .sumocfg file (The .sumocfg fiel should go into CARLA_5cc238b5c-dirty/Co-Simulation/Sumo/examples folder).  


## Co-Simulation between Carla and Sumo

1.) Locate the Carla folder and type ./CarlaUE4.sh to run the Carla server  

2.) In another terminal, locate CARLA_5cc238b5c-dirty/Co-Simulation/Sumo  

3.) In the command prompt, type python3 run_synchronization.py examples/UBAutonomousProvingGrounds.sumocfg to synchronize Carla and SUMO





