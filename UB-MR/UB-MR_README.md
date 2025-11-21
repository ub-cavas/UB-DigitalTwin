UB-MR

This is a Mixed Reality simulation tool to edit vehicle sensor data in real time

Requirements
-------------------------------
ROS2 Humble: https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html 

------------------------------
Download the packaged simulator: TODO

Make a ROS2 workspace - https://docs.ros.org/en/humble/Tutorials/Beginner-Client-Libraries/Creating-A-Workspace/Creating-A-Workspace.html 
Download the ros2 interface: https://github.com/ub-cavas/mr_pkg

-----------------------------
Developing UB-MR

1.) Install UnityHub: https://docs.unity3d.com/hub/manual/InstallHub.html 

2.) Install Unity Editor 6000.0.36f1: https://unity.com/releases/editor/whats-new/6000.0.36f1#notes

3.) Clone the Unity Project: https://github.com/ub-cavas/UB-MR 

4.) Initialize git lfs for the project: `git lfs install`

5.) Add the Unity project to the Unity HUB



Launching the Unity Project

6.) We suggest adding this line to your .bashrc `source /opt/ros/humble/setup.bash`. You can also source from the terminal instead

7.) **NOTE**: ROS2 MUST be sourced before launching the unity hub

8.) In the terminal `unityhub` - this will launch the HUB

9.) Open the project in Unity


(*Optional) Import the preconfigured Lincoln MKZ

    Copy agents/agent-Lincoln MKZ.json into /.config/unity3d/DefaultCompany/UB-MR


Running with a rosbag

In one terminal:

1.) `cd /ros2_workspace`

2.) `colcon build` - build workspace

3.) `source install/setup.bash` - source ros2 workspace

4.) `ros2 launch mr_pkg localization.launch.py` - start the localization package

In Unity:

5.) Navigate to MainMenu scene in Unity

6.) Press play in the editor

7.) Load the Lincoln MKZ vehicle from the Agent menu

8.) Load a map

9.) Press Start button

In another terminl

10.) `cd oakley_test_bag`

11.)`ros2 bag play oakley_test_bag_0.db3 --clock --start-offset 190`


In a third terminal 

12.) `rviz2`

13.) Load the rviz file from /rviz

14.) Verify sensor data is streaming




-----------------------------

Copy agent into ~/.config/unity3d/DefaultCompany/UB-MR 