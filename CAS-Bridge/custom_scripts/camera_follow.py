import carla
import time

# === Connect to CARLA ===
client = carla.Client("localhost", 2000)
# client = carla.Client("localhost", 2000)
client.set_timeout(10.0)
world = client.get_world()

# === Find your ego vehicle ===
# Option 1: by role_name (typical in Autoware or bridge setups)
ego_vehicle = None
for actor in world.get_actors().filter('vehicle.*'):
    if actor.attributes.get('role_name') in ['hero', 'ego_vehicle','actor']:
        ego_vehicle = actor
        break

if ego_vehicle is None:
    raise RuntimeError("Ego vehicle not found. Check role_name or use ID manually.")

print(f"Following ego vehicle: id={ego_vehicle.id}, type={ego_vehicle.type_id}")

# === Attach spectator to follow ===
spectator = world.get_spectator()

while True:
    transform = ego_vehicle.get_transform()
    # Offset the spectator camera 8m behind and 3m above the vehicle
    spectator_transform = carla.Transform(
        transform.location + carla.Location(x=-8, z=3),
        transform.rotation
    )
    spectator.set_transform(spectator_transform)
    time.sleep(0.05)
