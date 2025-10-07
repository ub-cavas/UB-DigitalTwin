Prerequisites
--------------------------------------
docker engine

nvidia-drivers

nvidia-container-toolkit


Run CARLA Package in Docker
--------------------------------------
ENABLE x11 FORWARDING (forward Docker GUI to host)
<pre>
xhost +local:root 
export DISPLAY=:0
</pre>

Build the Docker Image. TODO
<pre>
docker pull carlasim/carla:0.9.16
</pre>
Run the container with GUI
<pre>
docker run \
    --runtime=nvidia \
    --net=host \
    --user=$(id -u):$(id -g) \
    --env=DISPLAY=$DISPLAY \
    --env=NVIDIA_VISIBLE_DEVICES=all \
    --env=NVIDIA_DRIVER_CAPABILITIES=all \
    --volume="/tmp/.X11-unix:/tmp/.X11-unix:rw" \
    carlasim/carla:0.9.16 bash CarlaUE4.sh -quality-level=Low -nosound
</pre>

Run CARLA Source + Unreal Engine in Docker
--------------------------------------
Update

build_ue4.sh

<pre>
EPIC_USER="your-github-username" 
EPIC_TOKEN="your-github-token"
</pre> 
in build_ue4.sh, The command line args DO NOT WORK

Build the Image (this will take a while)
<pre>
Util/Docker/build.sh --monolith
</pre>

Run the container with GUI
<pre>
docker run -it --rm     --runtime=nvidia     --net=host     --user=$(id -u):$(id -g)     --env=DISPLAY=$DISPLAY     --env=NVIDIA_VISIBLE_DEVICES=all     --env=NVIDIA_DRIVER_CAPABILITIES=all     --volume="/tmp/.X11-unix:/tmp/.X11-unix:rw"     carla-monolith:ue4-dev     bash
</pre>

Start the server
<pre>
make launch
</pre>






AUTOWARE
------------------
ros2 launch autoware_launch e2e_simulator.launch.xml map_path:=/host_data/Town01_traffic_light vehicle_model:=sample_vehicle sensor_model:=awsim_sensor_kit simulator_type:=carla carla_map:=Town01



TODO: add PythonAPI to ub-lincoln-docker
For now use this in the container
<pre>
pip3 install carla==0.9.15
pip3 install --upgrade transforms3d
</pre>






