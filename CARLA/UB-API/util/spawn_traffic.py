#!/usr/bin/env python3
"""
Minimal script to spawn traffic in CARLA simulator
"""

import carla
import random
import time
import carla
import argparse
import math
from ub_carla import find_ego

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
    ego_transform = find_ego(world, wait_seconds=10.0).get_transform()
    spawn_points = get_nearby_spawn_points(world, ego_transform.location, 50)
    
    # Limit number of vehicles to available spawn points
    num_vehicles = min(num_vehicles, len(spawn_points))
    
    # Spawn vehicles
    vehicles = []
    for i in range(num_vehicles):
        # Spawn the vehicle
        blueprint = random.choice(vehicle_blueprints)
        vehicle = world.try_spawn_actor(blueprint, spawn_points[i])
        
        if vehicle is not None:
            # Enable autopilot
            vehicle.set_autopilot(True)
            vehicles.append(vehicle)
            print(f"Spawned vehicle {i+1}/{num_vehicles}")
    
    print(f"\nSuccessfully spawned {len(vehicles)} vehicles with autopilot enabled")
    return client, vehicles, world

def get_nearby_spawn_points(world, reference_location, radius=20.0):
    spawn_points = world.get_map().get_spawn_points()
    near = []
    for sp in spawn_points:
        loc = sp.location
        dist = math.sqrt(
            (loc.x - reference_location.x)**2 +
            (loc.y - reference_location.y)**2 +
            (loc.z - reference_location.z)**2
        )
        if dist <= radius:
            near.append((sp, dist))
    
    # Sort by distance
    near.sort(key=lambda x: x[1])
    return [sp for sp, _ in near]



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