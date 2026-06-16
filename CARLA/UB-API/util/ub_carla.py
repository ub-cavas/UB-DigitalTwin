import time


DEFAULT_WAIT_INTERVAL_SECONDS = 0.05


def _normalized_role_names(role_names):
    if isinstance(role_names, str):
        return (role_names,)
    return tuple(role_names or ())


def find_ego(
    world,
    role_names=("ego_vehicle",),
    wait_seconds=10.0,
    fallback_to_any=True,
    wait_interval_seconds=DEFAULT_WAIT_INTERVAL_SECONDS,
):
    deadline = None if wait_seconds is None else time.time() + wait_seconds
    wanted = set(_normalized_role_names(role_names))
    while deadline is None or time.time() < deadline:
        vehicles = list(world.get_actors().filter('vehicle.*')) #TODO: change this to find the vehicle.lincoln.mkz_2017
        if vehicles:
            for v in vehicles:
                rn = (v.attributes.get('role_name') or '').strip()
                if rn in wanted:
                    return v
            if fallback_to_any:
                return vehicles[0]  # fallback
        time.sleep(wait_interval_seconds)
    return None
