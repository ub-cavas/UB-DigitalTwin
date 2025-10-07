AWSIM Docker
-----------------
cd ~/Unity/Hub/Editor/6000.0.36f1/Editor/
mv Unity Unity.bin

tee Unity >/dev/null <<'SH'
#!/usr/bin/env bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///home/oakley/cyclonedds.xml
exec "$(dirname "$0")/Unity.bin" "$@"
SH
chmod +x Unity




docker run -it --rm   --gpus all   --env="DISPLAY=$DISPLAY"   --env="QT_X11_NO_MITSHM=1"   --volume="/tmp/.X11-unix:/tmp/.X11-unix:rw"   --volume="$HOME/Desktop/AWSIM_Build:/awsim"   --name awsim-demo   awsim-runtime

docker run -it --rm \
	--runtime=nvidia \
	--net=host \
	--env=DISPLAY=$DISPLAY \
	--env=NVIDIA_VISIBLE_DEVICES=all \
    	--env=NVIDIA_DRIVER_CAPABILITIES=all \
	--volume="/tmp/.X11-unix:/tmp/.X11-unix:rw" \
	--volume="$HOME/Desktop/AWSIM_Build:/awsim" \
	--name awsim-demo \
	--entrypoint bash awsim-runtime
	
	
docker run --gpus all --runtime=nvidia -it --rm -e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix  -v ~/Desktop/AWSIM_Build:/AWSIM awsim-runtime /bin/bash