import time


def find_ego(world, role_names=("ego_vehicle"), wait_seconds=10.0):
    deadline = time.time() + wait_seconds
    wanted = set(role_names or [])
    while time.time() < deadline:
        vehicles = list(world.get_actors().filter('vehicle.*')) #TODO: change this to find the vehicle.lincoln.mkz_2017
        if vehicles:
            for v in vehicles:
                rn = (v.attributes.get('role_name') or '').strip()
                if rn in wanted:
                    return v
            return vehicles[0]  # fallback
        try:
            world.wait_for_tick()
        except RuntimeError:
            time.sleep(0.01)
    return None