import argparse
import carla
import os
import time
from ub_carla import find_ego


DEFAULT_ROLE_NAMES = ("ego_vehicle", "hero", "actor", "autopilot")
DEFAULT_UPDATE_HZ = 30.0


def _role_names(value):
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_args():
    parser = argparse.ArgumentParser(
        description="Passively keep the CARLA spectator camera behind the ego vehicle."
    )
    parser.add_argument("--host", default=os.environ.get("UB_CAMERA_FOLLOW_HOST", "localhost"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("UB_CAMERA_FOLLOW_PORT", "2000")),
    )
    parser.add_argument(
        "--role-names",
        default=os.environ.get("UB_CAMERA_FOLLOW_ROLE_NAMES", ",".join(DEFAULT_ROLE_NAMES)),
        help="Comma-separated vehicle role_name values to follow, in priority order.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=float(os.environ.get("UB_CAMERA_FOLLOW_WAIT_SECONDS", "0")),
        help="Seconds to wait for the ego vehicle. Use 0 to wait forever.",
    )
    parser.add_argument(
        "--fallback-to-any",
        action="store_true",
        help="Follow the first available vehicle if no requested role_name exists.",
    )
    parser.add_argument(
        "--distance",
        type=float,
        default=float(os.environ.get("UB_CAMERA_FOLLOW_DISTANCE_M", "8.0")),
    )
    parser.add_argument(
        "--height",
        type=float,
        default=float(os.environ.get("UB_CAMERA_FOLLOW_HEIGHT_M", "3.0")),
    )
    parser.add_argument(
        "--pitch",
        type=float,
        default=float(os.environ.get("UB_CAMERA_FOLLOW_PITCH_DEG", "-12.0")),
    )
    parser.add_argument(
        "--update-hz",
        type=float,
        default=float(os.environ.get("UB_CAMERA_FOLLOW_UPDATE_HZ", str(DEFAULT_UPDATE_HZ))),
        help="Polling rate for passive spectator updates.",
    )
    return parser.parse_args()


def camera_transform_for_vehicle(vehicle_transform, distance, height, pitch):
    fwd = vehicle_transform.rotation.get_forward_vector()
    offset = carla.Location(
        x=-distance * fwd.x,
        y=-distance * fwd.y,
        z=height
    )
    camera_rotation = carla.Rotation(
        pitch=pitch,
        yaw=vehicle_transform.rotation.yaw,
        roll=vehicle_transform.rotation.roll,
    )
    return carla.Transform(vehicle_transform.location + offset, camera_rotation)


def update_spectator(spectator, ego, args):
    transform = ego.get_transform()
    spectator.set_transform(
        camera_transform_for_vehicle(
            transform,
            distance=args.distance,
            height=args.height,
            pitch=args.pitch,
        )
    )
    return transform


def main():
    args = parse_args()
    wait_seconds = None if args.wait_seconds <= 0 else args.wait_seconds
    role_names = _role_names(args.role_names)
    update_interval = 1.0 / max(args.update_hz, 1.0)

    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    world = client.get_world()

    ego = find_ego(
        world,
        role_names=role_names,
        wait_seconds=wait_seconds,
        fallback_to_any=args.fallback_to_any,
    )
    if ego is None:
        raise RuntimeError("No vehicles found in the simulation within timeout.")

    print(f"Following ego vehicle: id={ego.id}, type={ego.type_id}, role_name={ego.attributes.get('role_name')}")

    spectator = world.get_spectator()
    update_spectator(spectator, ego, args)

    try:
        while True:
            try:
                update_spectator(spectator, ego, args)
            except RuntimeError:
                ego = find_ego(
                    world,
                    role_names=role_names,
                    wait_seconds=1.0,
                    fallback_to_any=args.fallback_to_any,
                )
                if ego is None:
                    time.sleep(update_interval)
                    continue
                print(
                    "Following ego vehicle: "
                    f"id={ego.id}, type={ego.type_id}, role_name={ego.attributes.get('role_name')}"
                )
                update_spectator(spectator, ego, args)
            time.sleep(update_interval)

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
