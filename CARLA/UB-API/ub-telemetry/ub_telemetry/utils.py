import carla

INVALID_HEIGHT = -10000
HEIGHT_OFFSET = 0.08
RAY_START_HEIGHT = 20
RAY_STOP_HEIGHT = -10

def get_spawn_point_location(world, location):
    if not location["z"] == INVALID_HEIGHT:
        return carla.Location(**location)
    
    start_location = carla.Location(location["x"], location["y"], RAY_START_HEIGHT)
    end_location = carla.Location(location["x"], location["y"], RAY_STOP_HEIGHT)

    raycast_result = world.cast_ray(start_location, end_location)

    if raycast_result:
        carla_location = min(raycast_result, key=lambda result: result.location.z).location
        carla_location.z += HEIGHT_OFFSET

        return carla_location
    else:
        print("Ray did not hit the ground.")
        return None