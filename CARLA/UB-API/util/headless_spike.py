#!/usr/bin/env python3
"""Measure the CARLA headless path used by the DT-27 spike.

Run this only against a dedicated CARLA instance.  It changes world settings,
spawns vehicles, and removes only the actors that it created when it exits.
The process writes a JSON report even when the probe fails, making it suitable
for attaching exact evidence to the sprint ticket.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import carla


DEFAULT_DURATION_SECONDS = 30 * 60
DEFAULT_ACTOR_COUNT = 50
DEFAULT_STEP_SECONDS = 1.0 / 60.0
RAY_HEIGHT_METRES = 5.0
RAY_DEPTH_METRES = 15.0
MINIMUM_HZ_FRACTION = 0.99


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run the DT-27 CARLA headless Traffic Manager and raycast probe."
    )
    result.add_argument("--host", default="127.0.0.1")
    result.add_argument("--port", type=int, default=2000)
    result.add_argument("--tm-port", type=int, default=8000)
    result.add_argument("--duration-seconds", type=float, default=DEFAULT_DURATION_SECONDS)
    result.add_argument("--actors", type=int, default=DEFAULT_ACTOR_COUNT)
    result.add_argument("--fixed-delta", type=float, default=DEFAULT_STEP_SECONDS)
    result.add_argument("--seed", type=int, default=27)
    result.add_argument("--output", type=Path, required=True)
    return result


def configure_world(world: carla.World, fixed_delta: float) -> carla.WorldSettings:
    """Enable the synchronous 60 Hz configuration used by the world master."""
    previous = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = fixed_delta
    settings.substepping = True
    # CARLA requires max_substep_delta_time * max_substeps >= fixed delta.
    settings.max_substep_delta_time = min(0.01, fixed_delta)
    settings.max_substeps = max(1, int(fixed_delta / settings.max_substep_delta_time + 0.999))
    world.apply_settings(settings)
    return previous


def spawn_autopilot_vehicles(
    client: carla.Client,
    world: carla.World,
    actor_count: int,
    tm_port: int,
    seed: int,
) -> list[int]:
    """Spawn exactly ``actor_count`` deterministic autopilot vehicles or fail."""
    blueprints = world.get_blueprint_library().filter("vehicle.*")
    blueprints = [blueprint for blueprint in blueprints if blueprint.has_attribute("number_of_wheels")]
    if not blueprints:
        raise RuntimeError("the map exposes no vehicle blueprints")

    spawn_points = list(world.get_map().get_spawn_points())
    random.Random(seed).shuffle(spawn_points)
    if len(spawn_points) < actor_count:
        raise RuntimeError(
            f"map has only {len(spawn_points)} spawn points; need {actor_count} vehicles"
        )

    commands = []
    for index, transform in enumerate(spawn_points[:actor_count]):
        blueprint = blueprints[index % len(blueprints)]
        if blueprint.has_attribute("role_name"):
            blueprint.set_attribute("role_name", "dt27-headless-spike")
        commands.append(
            carla.command.SpawnActor(blueprint, transform).then(
                carla.command.SetAutopilot(carla.command.FutureActor, True, tm_port)
            )
        )

    responses = client.apply_batch_sync(commands, True)
    errors = [response.error for response in responses if response.error]
    actor_ids = [response.actor_id for response in responses if not response.error]
    if errors or len(actor_ids) != actor_count:
        client.apply_batch([carla.command.DestroyActor(actor_id) for actor_id in actor_ids])
        detail = "; ".join(errors[:3]) or "CARLA returned too few spawned actors"
        raise RuntimeError(f"failed to spawn {actor_count} autopilot vehicles: {detail}")
    return actor_ids


def raycast_probe(world: carla.World, transform: carla.Transform) -> int:
    """Cast through the road below a spawn point and return the hit count."""
    location = transform.location
    start = carla.Location(location.x, location.y, location.z + RAY_HEIGHT_METRES)
    end = carla.Location(location.x, location.y, location.z - RAY_DEPTH_METRES)
    return len(world.cast_ray(start, end))


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parser().parse_args()
    if args.duration_seconds <= 0 or args.actors <= 0 or args.fixed_delta <= 0:
        raise SystemExit("duration, actors, and fixed delta must be positive")

    report: dict[str, Any] = {
        "status": "failed",
        "host": args.host,
        "port": args.port,
        "tm_port": args.tm_port,
        "requested_duration_seconds": args.duration_seconds,
        "requested_actor_count": args.actors,
        "requested_fixed_delta_seconds": args.fixed_delta,
        "seed": args.seed,
        "started_at_unix_seconds": time.time(),
    }
    client = carla.Client(args.host, args.port)
    client.set_timeout(20.0)
    world: carla.World | None = None
    previous_settings: carla.WorldSettings | None = None
    actor_ids: list[int] = []
    traffic_manager: Any = None

    try:
        world = client.get_world()
        report["map"] = world.get_map().name
        previous_settings = configure_world(world, args.fixed_delta)
        traffic_manager = client.get_trafficmanager(args.tm_port)
        traffic_manager.set_synchronous_mode(True)
        traffic_manager.set_random_device_seed(args.seed)

        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            raise RuntimeError("map has no spawn points for the cast-ray probe")
        report["cast_ray_hit_count"] = raycast_probe(world, spawn_points[0])
        actor_ids = spawn_autopilot_vehicles(
            client, world, args.actors, args.tm_port, args.seed
        )
        report["spawned_actor_count"] = len(actor_ids)

        start = time.monotonic()
        deadline = start
        tick_durations: list[float] = []
        late_ticks = 0
        frames = 0
        initial_locations = {
            actor.id: actor.get_location() for actor in world.get_actors(actor_ids)
        }
        while time.monotonic() - start < args.duration_seconds:
            deadline += args.fixed_delta
            sleep_seconds = deadline - time.monotonic()
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            else:
                late_ticks += 1

            tick_start = time.monotonic()
            world.tick()
            tick_durations.append(time.monotonic() - tick_start)
            frames += 1

        elapsed = time.monotonic() - start
        actors = world.get_actors(actor_ids)
        alive_actor_ids = {actor.id for actor in actors if actor.is_alive}
        moved_actor_count = sum(
            actor.id in initial_locations
            and actor.get_location().distance(initial_locations[actor.id]) > 1.0
            for actor in actors
            if actor.is_alive
        )
        report.update(
            {
                "status": "passed",
                "elapsed_wall_seconds": elapsed,
                "frames": frames,
                "actual_hz": frames / elapsed,
                "late_tick_count": late_ticks,
                "max_tick_seconds": max(tick_durations, default=0.0),
                "mean_tick_seconds": sum(tick_durations) / len(tick_durations),
                "alive_actor_count": len(alive_actor_ids),
                "moved_actor_count": moved_actor_count,
                "tm_synchronous_mode": True,
            }
        )
        if report["cast_ray_hit_count"] < 1:
            raise RuntimeError("world.cast_ray returned no road hit below a map spawn point")
        if len(alive_actor_ids) != args.actors:
            raise RuntimeError("one or more Traffic Manager actors died during the run")
        if moved_actor_count == 0:
            raise RuntimeError("Traffic Manager actors never moved")
        minimum_hz = args.fixed_delta ** -1 * MINIMUM_HZ_FRACTION
        if report["actual_hz"] < minimum_hz:
            raise RuntimeError(
                f"tick rate {report['actual_hz']:.3f} Hz is below the "
                f"{minimum_hz:.3f} Hz acceptance threshold"
            )
    except Exception as exc:  # Keep the failure evidence in the JSON report.
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(report["error"], file=sys.stderr)
    finally:
        if actor_ids:
            client.apply_batch([carla.command.DestroyActor(actor_id) for actor_id in actor_ids])
        if traffic_manager is not None:
            traffic_manager.set_synchronous_mode(False)
        if world is not None and previous_settings is not None:
            world.apply_settings(previous_settings)
        report["finished_at_unix_seconds"] = time.time()
        write_report(args.output, report)

    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
