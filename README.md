Prerequisites
TODO




Run CARLA 0.9.16 in Docker (with Display)
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
    carlasim/carla:0.9.16 bash CarlaUE4.sh -nosound
</pre>
