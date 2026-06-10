import carla
import time
import random

def main():
    # A list to store all spawned actors for cleanup
    actor_list = []
    client = None

    try:
        # 1. Connect to the CARLA server (must be running with --ros2)
        client = carla.Client('localhost', 2000)
        client.set_timeout(10.0)
        world = client.get_world()
        blueprint_library = world.get_blueprint_library()

        # 2. Spawn a vehicle
        vehicle_bp = blueprint_library.find('vehicle.tesla.model3')
        # spawn_point = random.choice(world.get_map().get_spawn_points())
        spawn_location = carla.Location(x=-100, y=0, z=1.0)
        spawn_rotation = carla.Rotation(pitch=0, yaw=180, roll=0)
        
        # Create the complete transform
        spawn_point = carla.Transform(spawn_location, spawn_rotation)
        vehicle = world.spawn_actor(vehicle_bp, spawn_point)
        actor_list.append(vehicle)
        print(f"Spawned vehicle {vehicle.id}")

        # --- 3. Spawn All Sensors with ROS2 Support ---

        # Camera
        camera_bp = blueprint_library.find('sensor.camera.rgb')
        camera_bp.set_attribute('ros_name', 'front_camera')
        camera_bp.set_attribute('ros_publish_tf', 'true')
        camera_transform = carla.Transform(carla.Location(x=1.5, z=2.4))
        camera = world.spawn_actor(camera_bp, camera_transform, attach_to=vehicle)
        actor_list.append(camera)
        print(f"Spawned camera {camera.id} with ROS name: front_camera")

        # LIDAR
        lidar_bp = blueprint_library.find('sensor.lidar.ray_cast')
        lidar_bp.set_attribute('range', '100')
        lidar_bp.set_attribute('ros_name', 'lidar')
        lidar_bp.set_attribute('ros_publish_tf', 'true')
        lidar_transform = carla.Transform(carla.Location(x=0, z=2.4))
        lidar = world.spawn_actor(lidar_bp, lidar_transform, attach_to=vehicle)
        actor_list.append(lidar)
        print(f"Spawned lidar {lidar.id} with ROS name: lidar")

        # IMU
        imu_bp = blueprint_library.find('sensor.other.imu')
        imu_bp.set_attribute('ros_name', 'imu')
        imu_bp.set_attribute('ros_publish_tf', 'true')
        imu_transform = carla.Transform(carla.Location(x=0, z=0))
        imu = world.spawn_actor(imu_bp, imu_transform, attach_to=vehicle)
        actor_list.append(imu)
        print(f"Spawned IMU {imu.id} with ROS name: imu")

        # GNSS
        gnss_bp = blueprint_library.find('sensor.other.gnss')
        gnss_bp.set_attribute('ros_name', 'gnss')
        gnss_bp.set_attribute('ros_publish_tf', 'true')
        gnss_transform = carla.Transform(carla.Location(x=0, z=0))
        gnss = world.spawn_actor(gnss_bp, gnss_transform, attach_to=vehicle)
        actor_list.append(gnss)
        print(f"Spawned GNSS {gnss.id} with ROS name: gnss")
        
        print("All sensors with ROS2 support spawned.")

        # --- 4. Enable Autopilot ---
        traffic_manager = client.get_trafficmanager()
        vehicle.set_autopilot(True, traffic_manager.get_port())
        print("Autopilot enabled.")

        # --- 5. Attach Spectator "Chase Camera" (Video Game Style) ---
        spectator = world.get_spectator()
        print("Attaching chase camera. Press Ctrl+C to stop.")

        while True:
            # Get the vehicle's current transform
            vehicle_transform = vehicle.get_transform()
            
            # Calculate position behind the vehicle (chase camera style)
            # Get the forward vector and rotate it 180 degrees to get backward direction
            yaw = vehicle_transform.rotation.yaw
            import math
            backward_offset = 8.0  # Distance behind vehicle
            height_offset = 3.5    # Height above vehicle
            
            # Calculate camera position behind the vehicle
            camera_x = vehicle_transform.location.x - backward_offset * math.cos(math.radians(yaw))
            camera_y = vehicle_transform.location.y - backward_offset * math.sin(math.radians(yaw))
            camera_z = vehicle_transform.location.z + height_offset
            
            spectator_location = carla.Location(x=camera_x, y=camera_y, z=camera_z)
            
            # Make camera look at the vehicle
            spectator_rotation = carla.Rotation(
                pitch=-15.0,  # Slight downward angle
                yaw=vehicle_transform.rotation.yaw,
                roll=0.0
            )
            
            # Set the spectator's transform
            spectator.set_transform(carla.Transform(spectator_location, spectator_rotation))
            
            # Wait for the world to tick
            world.wait_for_tick()

    except KeyboardInterrupt:
        print("\nScript interrupted by user. Cleaning up...")
    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        # --- 6. Clean up all actors ---
        print("Cleaning up all spawned actors...")
        if client and actor_list:
            client.apply_batch([carla.command.DestroyActor(x) for x in actor_list])
        print("Done.")

if __name__ == '__main__':
    main()