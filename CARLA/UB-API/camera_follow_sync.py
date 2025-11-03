import carla
import math
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


def main():
    client = carla.Client("localhost", 2000)
    client.set_timeout(10.0)
    world = client.get_world()
    ego = find_ego(world, wait_seconds=10.0)
    if ego is None:
        raise RuntimeError("No vehicles found in the simulation within timeout.")

    print(f"Following ego vehicle: id={ego.id}, type={ego.type_id}, role_name={ego.attributes.get('role_name')}")

    spectator = world.get_spectator()
    distance = 8.0
    height = 3.0

    try:
        while True:
            try:
                world.wait_for_tick()
            except RuntimeError:
                time.sleep(0.01)
                continue

            try:
                transform = ego.get_transform()
            except RuntimeError:
                ego = find_ego(world, wait_seconds=1.0)
                if ego is None:
                    continue
                transform = ego.get_transform()

            # Use forward vector to place camera behind the car
            fwd = transform.rotation.get_forward_vector()
            offset = carla.Location(
                x=-distance * fwd.x,
                y=-distance * fwd.y,
                z=height
            )

            spectator.set_transform(carla.Transform(transform.location + offset, transform.rotation))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()