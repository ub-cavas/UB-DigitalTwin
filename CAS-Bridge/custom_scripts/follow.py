import carla
import time

# === Connect to CARLA ===
client = carla.Client("localhost", 2000)
# client = carla.Client("localhost", 2000)
client.set_timeout(10.0)
world = client.get_world()