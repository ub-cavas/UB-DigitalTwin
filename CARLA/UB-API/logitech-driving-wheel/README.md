Use a steering-wheel-controlled client

```bash
# Install drivers (just once)
sudo apt install joystick jstest-gtk evtest
sudo usermod -aG input $USER   # log out/in

# Run manual_control
python manual_control_steeringwheel.py --host <SERVER-IP-ADDRESS> --rolename steering_wheel
```
