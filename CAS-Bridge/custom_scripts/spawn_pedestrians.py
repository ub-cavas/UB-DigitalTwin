#!/usr/bin/env python3
import argparse
import logging
import random
import sys
import time
from typing import List, Tuple

import carla


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spawn pedestrians in CARLA 0.9.16")
    parser.add_argument("--host", default="localhost", help="CARLA server IP")
    parser.add_argument("--port", default=2000, type=int, help="CARLA server port")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--count", type=int, default=30, help="Number of pedestrians to spawn")
    parser.add_argument("--sync", action="store_true", help="Enable synchronous mode during setup")
    parser.add_argument("--life-time", type=float, default=0.0, help="Lifetime for walkers; 0 means keep alive")
    parser.add_argument("--timeout", type=float, default=10.0, help="Client connection timeout in seconds")
    return parser.parse_args()


def set_synchronous_mode(world: carla.World, enabled: bool, delta_seconds: float = 0.05) -> None:
    settings = world.get_settings()
    if enabled and not settings.synchronous_mode:
        logging.info("Enabling synchronous mode")
    settings.synchronous_mode = enabled
    settings.fixed_delta_seconds = delta_seconds if enabled else None
    world.apply_settings(settings)


def make_walker_blueprints(blueprints: carla.BlueprintLibrary) -> List[carla.ActorBlueprint]:
    walkers = blueprints.filter("walker.pedestrian.*")
    return list(walkers)


def spawn_walkers(client: carla.Client, world: carla.World, count: int) -> Tuple[List[int], List[int], List[float]]:
    walker_bps = make_walker_blueprints(world.get_blueprint_library())
    controller_bp = world.get_blueprint_library().find("controller.ai.walker")
    if not walker_bps:
        raise RuntimeError("No walker blueprints found")

    spawn_commands = []
    spawn_metadata = []
    attempts = 0
    max_attempts = max(count * 15, 50)
    while len(spawn_commands) < count and attempts < max_attempts:
        attempts += 1
        blueprint = random.choice(walker_bps)
        if blueprint.has_attribute("is_invincible"):
            blueprint.set_attribute("is_invincible", "false")
        spawn_point = carla.Transform()
        location = world.get_random_location_from_navigation()
        if location is None:
            continue
        spawn_point.location = location
        speed = 1.4
        if blueprint.has_attribute("speed"):
            speed_attr = blueprint.get_attribute("speed")
            if speed_attr.is_float():
                speed = float(speed_attr.as_float())
            elif speed_attr.recommended_values:
                speed = float(random.choice(speed_attr.recommended_values))
        spawn_commands.append(carla.command.SpawnActor(blueprint, spawn_point))
        spawn_metadata.append(speed)

    if not spawn_commands:
        raise RuntimeError(
            "Could not find valid navigation locations for pedestrians. "
            "Ensure the loaded map has pedestrian navigation data and that the navigation layer is streamed."
        )

    results = client.apply_batch_sync(spawn_commands, True)

    walkers = []
    for meta, result in zip(spawn_metadata, results):
        if result.error:
            logging.warning("Walker spawn failed: %s", result.error)
            continue
        walkers.append({"id": result.actor_id, "speed": meta})

    if not walkers:
        raise RuntimeError("No pedestrians were spawned")

    controller_commands = [
        carla.command.SpawnActor(controller_bp, carla.Transform(), walker["id"])
        for walker in walkers
    ]
    controller_results = client.apply_batch_sync(controller_commands, True)

    walker_ids: List[int] = []
    controller_ids: List[int] = []
    speeds: List[float] = []
    for walker, result in zip(walkers, controller_results):
        if result.error:
            logging.warning("Controller spawn failed for %s: %s", walker["id"], result.error)
            continue
        walker_ids.append(walker["id"])
        controller_ids.append(result.actor_id)
        speeds.append(walker["speed"])

    if not controller_ids:
        raise RuntimeError("No controllers were created for pedestrians")

    return walker_ids, controller_ids, speeds


def start_walkers(world: carla.World, controller_ids: List[int], speeds: List[float], life_time: float, use_sync: bool) -> None:
    controllers = []
    for controller_id in controller_ids:
        controller = world.get_actor(controller_id)
        if controller is None:
            continue
        controllers.append(controller)

    for controller, speed in zip(controllers, speeds):
        controller.start()
        destination = world.get_random_location_from_navigation()
        if destination is None:
            continue
        controller.go_to_location(destination)
        controller.set_max_speed(speed)

    def step_world() -> None:
        if use_sync:
            world.tick()
        else:
            world.wait_for_tick()

    if life_time > 0.0:
        expiry = time.time() + life_time
        logging.info("Keeping walkers alive for %.1f seconds", life_time)
        while time.time() < expiry:
            step_world()
    else:
        logging.info("Walkers will keep moving until script terminates")
        try:
            while True:
                step_world()
        except KeyboardInterrupt:
            logging.info("Stopping walkers after keyboard interrupt")


def destroy_actors(client: carla.Client, actors: List[int]) -> None:
    if not actors:
        return
    client.apply_batch([carla.command.DestroyActor(actor_id) for actor_id in actors])


def main() -> int:
    args = parse_args()
    logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)

    if args.seed is not None:
        random.seed(args.seed)

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)

    world = client.get_world()
    original_settings = world.get_settings()

    walker_ids: List[int] = []
    controller_ids: List[int] = []
    speeds: List[float] = []
    try:
        if args.sync:
            set_synchronous_mode(world, True)
            world.tick()

        walker_ids, controller_ids, speeds = spawn_walkers(client, world, args.count)
        logging.info("Spawned %d pedestrians", len(walker_ids))

        start_walkers(world, controller_ids, speeds, args.life_time, args.sync)
    except Exception:  # noqa: BLE001
        logging.exception("Error while spawning pedestrians")
        return 1
    finally:
        for controller_id in controller_ids:
            controller = world.get_actor(controller_id)
            if controller is not None:
                controller.stop()
        destroy_actors(client, controller_ids + walker_ids)
        if args.sync:
            world.apply_settings(original_settings)

    return 0


if __name__ == "__main__":
    sys.exit(main())
