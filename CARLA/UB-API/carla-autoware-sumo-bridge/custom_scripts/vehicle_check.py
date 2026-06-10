import carla

def main():
    # Connect to the CARLA server (change host/port if needed)
    client = carla.Client('localhost', 2000)
    client.set_timeout(5.0)

    world = client.get_world()

    # Get all actors
    actors = world.get_actors()

    # Filter only vehicles
    vehicles = actors.filter('vehicle.*')

    print(f"Total vehicles found: {len(vehicles)}\n")

    for vehicle in vehicles:
        transform = vehicle.get_transform()
        location = transform.location
        rotation = transform.rotation
        print(f"ID: {vehicle.id}")
        print(f"Type: {vehicle.type_id}")
        print(f"Location: (x={location.x:.2f}, y={location.y:.2f}, z={location.z:.2f})")
        print(f"Rotation: (pitch={rotation.pitch:.2f}, yaw={rotation.yaw:.2f}, roll={rotation.roll:.2f})")
        print("-" * 40)

if __name__ == '__main__':
    main()
