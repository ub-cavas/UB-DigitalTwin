#!/usr/bin/env python3
import carla
import random
import time
import math

def set_third_person_camera(world, target_actor, distance=6.0, height=2.5):
    spectator = world.get_spectator()
    transform = target_actor.get_transform()

    yaw = math.radians(transform.rotation.yaw)

    # Offset camera behind and above the vehicle
    cam_location = carla.Location(
        x = transform.location.x - distance * math.cos(yaw),
        y = transform.location.y - distance * math.sin(yaw),
        z = transform.location.z + height
    )

    cam_rotation = carla.Rotation(
        pitch = -10.0,
        yaw = transform.rotation.yaw
    )

    spectator.set_transform(carla.Transform(cam_location, cam_rotation))


def main():
    client = carla.Client("localhost", 2000)
    client.set_timeout(10.0)
    world = client.get_world()
    blueprints = world.get_blueprint_library()

    # Filter only vehicle blueprints
    vehicle_blueprints = blueprints.filter("vehicle.*")

    # Pick a random vehicle model
    vehicle_bp = random.choice(vehicle_blueprints)

    # Spawn location (change as needed)
    spawn_location = carla.Location(x=-155.0, y=2.5, z=1.0)
    #spawn_location = carla.Location(x=90.0, y=200, z=1.0)
    vehicle_transform = carla.Transform(spawn_location, carla.Rotation(yaw=180))

    vehicle = world.try_spawn_actor(vehicle_bp, vehicle_transform)
    if not vehicle:
        print("❌ Could not spawn vehicle at that location")
        return

    print(f"✅ Spawned vehicle: {vehicle.type_id}, id={vehicle.id}")

    # Stop any physics motion
    vehicle.set_simulate_physics(True)
    vehicle.disable_constant_velocity()
    vehicle.set_target_velocity(carla.Vector3D(0, 0, 0))
    vehicle.set_target_angular_velocity(carla.Vector3D(0, 0, 0))
    vehicle.set_autopilot(False)

    # Put spectator behind vehicle
    set_third_person_camera(world, vehicle)

    print("📷 Camera set to 3rd-person view behind vehicle")
    #time.sleep(15)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Script interrupted.")
