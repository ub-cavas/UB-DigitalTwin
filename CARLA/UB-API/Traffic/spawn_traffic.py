#!/usr/bin/env python3
"""
Minimal script to spawn traffic in CARLA simulator
"""

import carla
import random
import time
import argparse

def spawn_traffic(num_vehicles=150, map_name=None):
    """Spawn traffic vehicles in CARLA"""
    
    # Connect to CARLA server
    client = carla.Client('localhost', 2000)
    client.set_timeout(10.0)
    
    # Load the specified map if provided
    if map_name:
        print(f"Loading map: {map_name}")
        client.load_world(map_name)
        time.sleep(2)  # Give the map time to load
    
    # Get the world
    world = client.get_world()
    print(f"Current map: {world.get_map().name}")
    
    # Get blueprint library and filter for vehicles
    blueprint_library = world.get_blueprint_library()
    vehicle_blueprints = blueprint_library.filter('vehicle.*')
    
    # Get spawn points
    spawn_points = world.get_map().get_spawn_points()
    
    # Limit number of vehicles to available spawn points
    num_vehicles = min(num_vehicles, len(spawn_points))
    
    # Shuffle spawn points for randomness
    random.shuffle(spawn_points)
    
    # Spawn vehicles
    vehicles = []
    for i in range(num_vehicles):
        # Pick a random vehicle blueprint
        blueprint = random.choice(vehicle_blueprints)
        
        # Spawn the vehicle
        vehicle = world.try_spawn_actor(blueprint, spawn_points[i])
        
        if vehicle is not None:
            # Enable autopilot
            vehicle.set_autopilot(True)
            vehicles.append(vehicle)
            print(f"Spawned vehicle {i+1}/{num_vehicles}")
    
    print(f"\nSuccessfully spawned {len(vehicles)} vehicles with autopilot enabled")
    return client, vehicles, world

if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Spawn traffic in CARLA simulator')
    parser.add_argument('-m', '--map', type=str, default=None,
                        help='CARLA map to load (e.g., Town01, Town02, Town03)')
    parser.add_argument('-v', '--num-vehicles', type=int, default=150,
                        help='Number of vehicles to spawn (default: 150)')
    
    args = parser.parse_args()
    
    client = None
    vehicles = []
    try:
        client, vehicles, world = spawn_traffic(num_vehicles=args.num_vehicles, map_name=args.map)
        print("\nTraffic is running. Press Ctrl+C to stop and cleanup...")
        
        # Keep the script running
        while True:
            world.wait_for_tick()
            
    except KeyboardInterrupt:
        print("\nInterrupted by user...")
        
    except Exception as e:
        print(f"Error: {e}")
        
    finally:
        # Clean up all spawned vehicles using batch destroy
        if client is not None and vehicles:
            print("Cleaning up vehicles...")
            client.apply_batch([carla.command.DestroyActor(x) for x in vehicles])
            print(f"Destroyed {len(vehicles)} vehicles")