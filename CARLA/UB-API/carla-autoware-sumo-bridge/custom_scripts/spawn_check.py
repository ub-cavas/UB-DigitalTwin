# This script is for the CARLA Simulator (https://carla.org/)
#
# Before running this script, you need to have the CARLA simulator running.
# You can download it from the official website. Once it's running, you can
# execute this Python script.

import carla
import random
import time

def main():
    """
    Main function to connect to CARLA, spawn a vehicle, and attach the spectator
    camera to follow it.
    """
    actor_list = []
    client = None

    try:
        # 1. Connect to the CARLA server
        # Make sure you have the CARLA server running before executing this script.
        client = carla.Client('localhost', 2000)
        client.set_timeout(10.0) # seconds

        # Get the current world
        # world = client.get_world()
        world = client.load_world('UBAutonomousProvingGrounds')
        print("Successfully connected to the CARLA world.")

        # 2. Get the blueprint library and choose a vehicle
        blueprint_library = world.get_blueprint_library()
        # Filter for a specific vehicle, e.g., the Tesla Model 3
        vehicle_bp = blueprint_library.find('vehicle.tesla.model3')
        print(f"Selected blueprint: {vehicle_bp.id}")

        # 3. Find a suitable spawn point
        # Get a random spawn point from the map's recommended spawn points
        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            print("Could not find any spawn points on this map. Exiting.")
            return
        # spawn_point = random.choice(spawn_points)
        spawn_location = carla.Location(x=-100, y=0, z=1.0)
        spawn_rotation = carla.Rotation(pitch=0, yaw=180, roll=0)
        
        # Create the complete transform
        spawn_point = carla.Transform(spawn_location, spawn_rotation)
        print(f"Found a random spawn point.")

        # 4. Spawn the vehicle
        vehicle = world.try_spawn_actor(vehicle_bp, spawn_point)
        if vehicle is None:
            print("Failed to spawn vehicle. Trying a different location...")
            # If the first spawn fails, try another random one
            spawn_point = random.choice(spawn_points)
            vehicle = world.try_spawn_actor(vehicle_bp, spawn_point)
            if vehicle is None:
                print("Could not spawn vehicle. Exiting.")
                return
        
        actor_list.append(vehicle)
        print(f"Spawned vehicle with ID: {vehicle.id}")

        # Set the vehicle to autopilot to make it move
        vehicle.set_autopilot(True)
        print("Vehicle is now on autopilot.")

        # 5. Attach the spectator camera
        spectator = world.get_spectator()
        print("Got spectator camera actor.")

        print("\nCamera is now following the vehicle. Press Ctrl+C to exit.")

        # Main loop to keep the camera attached to the vehicle.
        # This is a simple, direct follow without any smoothing.
        while True:
            # Get the vehicle's current transform
            vehicle_transform = vehicle.get_transform()
            
            # Calculate the camera's target transform.
            # We position it 10 meters behind and 5 meters above the vehicle.
            # Using the vehicle's forward vector ensures the camera is always behind it.
            camera_transform = carla.Transform(
                vehicle_transform.location - vehicle_transform.get_forward_vector() * 10 + carla.Location(z=5),
                vehicle_transform.rotation
            )
            
            # Set the spectator's transform directly
            spectator.set_transform(camera_transform)
            
            # Wait for the next simulator frame
            world.wait_for_tick()

    except KeyboardInterrupt:
        print("\nScript interrupted by user. Cleaning up...")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # 6. Clean up: destroy the spawned vehicle
        if client and actor_list:
            print("Destroying spawned actors...")
            client.apply_batch([carla.command.DestroyActor(x) for x in actor_list])
            print("Cleanup complete.")

if __name__ == '__main__':
    main()


