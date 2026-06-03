#!/usr/bin/env python3
"""
Traffic spawner: spawn random vehicles at designated spawn points only,
maintain a max count, enable waypoint following via Traffic Manager,
and respawn if a vehicle goes offline.

Usage examples:
  - Use first 10 map spawn points, keep 30 vehicles total managed by this script:
	  python3 test_traffic1.py --max-vehicles 30 --points-from-map 10 --sync --sync-owns-tick --set-world-sync

  - Use custom spawn points from JSON file (list of {x,y,z,yaw}):
	  python3 test_traffic1.py --spawn-file spawns.json --max-vehicles 50 --filter "vehicle.*" --sync

  - Limit total vehicles in environment (not just ours) to 100:
	  python3 test_traffic1.py --spawn-file spawns.json --max-env-vehicles 100 --limit-total --sync

Spawn file format (JSON):
[
  {"x": 10.0, "y": 20.0, "z": 0.5, "yaw": 90.0},
  {"x": 15.0, "y": 25.0, "z": 0.5, "yaw": 180.0}
]

Notes:
- If a spawn transform is invalid or blocked, the script will retry others.
- Vehicles are put on Traffic Manager autopilot for road/waypoint following.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import signal
import sys
import time
from dataclasses import dataclass
import re
from typing import Dict, List, Optional, Sequence, Tuple

import carla


# ------------- Config & CLI -------------


def positive_int(value: str) -> int:
	ivalue = int(value)
	if ivalue <= 0:
		raise argparse.ArgumentTypeError("Value must be positive")
	return ivalue


def non_negative_int(value: str) -> int:
	ivalue = int(value)
	if ivalue < 0:
		raise argparse.ArgumentTypeError("Value must be non-negative")
	return ivalue


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="CARLA traffic spawner at fixed points")
	parser.add_argument("--host", default="localhost", help="CARLA server host")
	parser.add_argument("--port", type=int, default=2000, help="CARLA server port")
	parser.add_argument("--timeout", type=float, default=10.0, help="Client timeout seconds")
	# Important: we do NOT load/change the world map; we use the existing world to avoid interfering.
	parser.add_argument("--sync", action="store_true", help="Operate in a sync-friendly loop (no guarantee we own the tick)")
	parser.add_argument("--set-world-sync", action="store_true", help="Explicitly set world synchronous mode (use only if you control the sim)")
	parser.add_argument("--sync-owns-tick", action="store_true", help="If in sync mode, call world.tick() ourselves; otherwise we wait_for_tick() so external masters (e.g., Autoware/ROS bridge) drive ticks")
	parser.add_argument("--fixed-dt", type=float, default=0.05, help="Fixed delta seconds in sync mode")
	parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")

	# Spawn points sources
	group = parser.add_mutually_exclusive_group()
	group.add_argument(
		"--spawn-file",
		type=str,
		default=None,
		help="Path to JSON list of spawn points ({x,y,z,yaw})",
	)
	group.add_argument(
		"--spawn-json",
		type=str,
		default=None,
		help="Inline JSON list of spawn points ({x,y,z,yaw})",
	)
	parser.add_argument(
		"--points-from-map",
		type=non_negative_int,
		default=0,
		help="Use first N map spawn points if >0 (used when no custom points provided)",
	)

	# Vehicle limits
	parser.add_argument("--max-vehicles", type=non_negative_int, default=30, help="Max vehicles managed by this script")
	parser.add_argument(
		"--limit-total",
		action="store_true",
		help="If set, cap environment total vehicles to --max-env-vehicles before spawning ours",
	)
	parser.add_argument(
		"--max-env-vehicles",
		type=non_negative_int,
		default=120,
		help="Max vehicles allowed in environment when --limit-total is set",
	)

	# Blueprints & TM
	parser.add_argument("--filter", type=str, default="vehicle.*", help="Vehicle blueprint filter")
	parser.add_argument(
		"--generation",
		type=str,
		default="2",
		help='Vehicle generation to filter by: "1","2","all" (if supported by map bps)',
	)
	parser.add_argument("--tm-port", type=int, default=8000, help="Traffic Manager port")
	parser.add_argument("--tm-global-distance", type=float, default=3.0, help="TM global distance to leading vehicle (m)")
	parser.add_argument("--tm-seed", type=int, default=None, help="Traffic Manager random seed")
	parser.add_argument("--tm-perc-speed", type=float, default=100.0, help="TM percentage speed (100 = speed limit)")
	parser.add_argument("--tm-set-sync", action="store_true", help="Set Traffic Manager to synchronous mode to match world (advanced)")
	parser.add_argument("--ignore-lights", action="store_true", help="Let TM ignore traffic lights (testing)")

	# Loop cadence
	parser.add_argument("--spawn-tries-per-tick", type=positive_int, default=8, help="Max spawn attempts per loop")
	parser.add_argument("--loop-delay", type=float, default=0.05, help="Sleep seconds in async mode loop")

	return parser.parse_args()


# ------------- Helpers -------------


@dataclass
class ManagedVehicle:
	actor_id: int
	spawn_idx: int


def set_sync_mode(world: carla.World, enable: bool, fixed_dt: Optional[float]) -> Tuple[bool, Optional[float]]:
	settings = world.get_settings()
	prev = (settings.synchronous_mode, settings.fixed_delta_seconds)
	settings.synchronous_mode = enable
	settings.fixed_delta_seconds = fixed_dt if enable else None
	world.apply_settings(settings)
	return prev


def _sanitize_json(text: str) -> str:
	"""Allow a relaxed JSON: strip // and /* */ comments and trailing commas.

	This keeps user convenience in spawn files while still producing valid JSON.
	"""
	# Remove block comments
	text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
	# Remove full-line // comments
	lines = []
	for line in text.splitlines():
		stripped = line.lstrip()
		if stripped.startswith("//"):
			continue
		lines.append(line)
	text = "\n".join(lines)
	# Remove trailing commas before } or ]
	text = re.sub(r",\s*([}\]])", r"\1", text)
	return text


def load_spawn_points_from_json(text: str) -> List[carla.Transform]:
	try:
		cleaned = _sanitize_json(text)
		data = json.loads(cleaned)
	except Exception as e:  # noqa: BLE001
		raise RuntimeError(f"Failed to parse spawn points JSON: {e}") from e
	points: List[carla.Transform] = []
	for item in data:
		x = float(item.get("x", 0.0))
		y = float(item.get("y", 0.0))
		z = float(item.get("z", 0.0))
		yaw = float(item.get("yaw", 0.0))
		transform = carla.Transform(
			carla.Location(x=x, y=y, z=z),
			carla.Rotation(pitch=0.0, yaw=yaw, roll=0.0),
		)
		points.append(transform)
	return points


def get_spawn_points(world: carla.World, args: argparse.Namespace) -> List[carla.Transform]:
	# Priority: spawn-json > spawn-file > points-from-map > all map spawns fallback
	if args.spawn_json:
		logging.info("Loading spawn points from inline JSON")
		return load_spawn_points_from_json(args.spawn_json)
	if args.spawn_file:
		path = os.path.expanduser(args.spawn_file)
		logging.info("Loading spawn points from file: %s", path)
		with open(path, "r", encoding="utf-8") as f:
			return load_spawn_points_from_json(f.read())

	m = world.get_map()
	map_spawns = list(m.get_spawn_points())
	if args.points_from_map and args.points_from_map > 0:
		if args.points_from_map > len(map_spawns):
			logging.warning(
				"Requested %d points-from-map but map has only %d; using all.",
				args.points_from_map,
				len(map_spawns),
			)
			return map_spawns
		return map_spawns[: args.points_from_map]
	if not map_spawns:
		raise RuntimeError("Map has no spawn points and no custom points provided")
	logging.info("Using all %d map spawn points as designated points", len(map_spawns))
	return map_spawns


def get_vehicle_blueprints(world: carla.World, filter_str: str, generation: str) -> List[carla.ActorBlueprint]:
	bps = world.get_blueprint_library().filter(filter_str)
	if generation == "all":
		return list(bps)
	if generation in {"1", "2"}:
		filtered = [bp for bp in bps if int(bp.get_attribute("generation").as_int()) == int(generation)] if bps and bps[0].has_attribute("generation") else list(bps)
		return filtered
	return list(bps)


def choose_vehicle_bp(bps: Sequence[carla.ActorBlueprint]) -> carla.ActorBlueprint:
	bp = random.choice(list(bps))
	# Randomize color if available
	if bp.has_attribute("color"):
		color = random.choice(bp.get_attribute("color").recommended_values)
		bp.set_attribute("color", color)
	if bp.has_attribute("driver_id"):
		driver_id = random.choice(bp.get_attribute("driver_id").recommended_values)
		bp.set_attribute("driver_id", driver_id)
	if bp.has_attribute("is_invincible"):
		bp.set_attribute("is_invincible", "false")
	return bp


def enable_autopilot(vehicle: carla.Vehicle, tm: carla.TrafficManager, args: argparse.Namespace) -> None:
	vehicle.set_autopilot(True, tm.get_port())
	# Per-vehicle configuration to avoid global side-effects
	try:
		tm.distance_to_leading_vehicle(vehicle, args.tm_global_distance)
	except Exception:
		pass
	try:
		# positive value slows down w.r.t. speed limit; 100 - perc_speed matches global behavior
		tm.vehicle_percentage_speed_difference(vehicle, 100.0 - float(args.tm_perc_speed))
	except Exception:
		pass
	if args.ignore_lights:
		try:
			tm.ignore_lights_percentage(vehicle, 100)
		except Exception:
			pass


def try_spawn_vehicle(world: carla.World, tm: carla.TrafficManager, bps: List[carla.ActorBlueprint], transform: carla.Transform, args: argparse.Namespace) -> Optional[carla.Vehicle]:
	bp = choose_vehicle_bp(bps)
	actor = world.try_spawn_actor(bp, transform)
	if actor is None:
		return None
	assert isinstance(actor, carla.Vehicle)
	# Enable lights for visibility
	try:
		from carla import VehicleLightState as VLS  # type: ignore[attr-defined]

		lights = VLS.Position | VLS.LowBeam
		actor.set_light_state(carla.VehicleLightState(lights))
	except Exception:
		pass
	enable_autopilot(actor, tm, args)
	return actor


def world_tick_or_wait(world: carla.World, sync: bool, own_tick: bool) -> None:
	# In sync mode, if we don't own the tick (e.g., Autoware/ROS bridge drives it), wait_for_tick
	if sync and own_tick:
		world.tick()
	else:
		world.wait_for_tick()


# ------------- Main loop -------------


def main() -> int:
	args = parse_args()
	logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)

	if args.seed is not None:
		random.seed(args.seed)

	client = carla.Client(args.host, args.port)
	client.set_timeout(args.timeout)

	world = client.get_world()
	original_settings = world.get_settings()
	# We intentionally do NOT load/replace the current world to avoid interfering with other systems.

	# Traffic Manager
	tm = client.get_trafficmanager(args.tm_port)
	if args.tm_seed is not None:
		tm.set_random_device_seed(args.tm_seed)
	# Avoid global TM settings to not impact other controllers; set per-vehicle in enable_autopilot instead.
	if args.tm_set_sync:
		try:
			tm.set_synchronous_mode(True)
		except Exception:
			pass

	# Sync mode
	prev_sync = None
	if args.sync and args.set_world_sync:
		prev_sync = set_sync_mode(world, True, args.fixed_dt)
		# Only tick if we own the tick
		if args.sync_owns_tick:
			world.tick()

	# Prepare spawn points
	designated_points = get_spawn_points(world, args)
	logging.info("Designated spawn points: %d", len(designated_points))
	if not designated_points:
		logging.error("No designated spawn points available")
		return 2

	# Blueprints
	vehicle_bps = get_vehicle_blueprints(world, args.filter, args.generation)
	if not vehicle_bps:
		logging.error("No vehicle blueprints for filter=%s generation=%s", args.filter, args.generation)
		return 3

	managed: Dict[int, ManagedVehicle] = {}
	occupancy: Dict[int, Optional[int]] = {i: None for i in range(len(designated_points))}
	stop_flag = False

	def handle_sigint(signum, frame):  # noqa: ANN001
		nonlocal stop_flag
		stop_flag = True

	signal.signal(signal.SIGINT, handle_sigint)
	signal.signal(signal.SIGTERM, handle_sigint)

	try:
		logging.info("Spawning up to %d vehicles at designated points", args.max_vehicles)
		while not stop_flag:
			# Cleanup destroyed/offline
			to_remove: List[int] = []
			for aid, mv in managed.items():
				actor = world.get_actor(aid)
				if actor is None or not actor.is_alive:
					to_remove.append(aid)
			for aid in to_remove:
				mv = managed.pop(aid)
				if occupancy.get(mv.spawn_idx) == aid:
					occupancy[mv.spawn_idx] = None

			# Optional environment limit
			if args.limit_total:
				total_env = len(world.get_actors().filter("vehicle.*"))
				if total_env >= args.max_env_vehicles:
					world_tick_or_wait(world, args.sync, args.sync_owns_tick)
					if not args.sync and args.loop_delay > 0:
						time.sleep(args.loop_delay)
					continue

			# Spawn if needed
			tries = args.spawn_tries_per_tick
			while len(managed) < args.max_vehicles and tries > 0:
				tries -= 1
				# Find a free designated point
				free_indices = [idx for idx, occ in occupancy.items() if occ is None]
				if not free_indices:
					break
				idx = random.choice(free_indices)
				transform = designated_points[idx]

				# Optional: project to road to avoid off-road spawns
				try:
					waypoint = world.get_map().get_waypoint(
						transform.location,
						project_to_road=True,
						lane_type=carla.LaneType.Driving,
					)
					if waypoint is not None:
						# Snap location to road surface but keep provided rotation to respect user yaw
						loc = waypoint.transform.location
						transform = carla.Transform(
							carla.Location(x=loc.x, y=loc.y, z=loc.z),
							transform.rotation,
						)
				except Exception:
					pass

				actor = try_spawn_vehicle(world, tm, vehicle_bps, transform, args)
				if actor is None:
					continue

				occupancy[idx] = actor.id
				managed[actor.id] = ManagedVehicle(actor_id=actor.id, spawn_idx=idx)
				logging.info("Spawned %s id=%d at point %d", actor.type_id, actor.id, idx)

			world_tick_or_wait(world, args.sync, args.sync_owns_tick)
			if not args.sync and args.loop_delay > 0:
				time.sleep(args.loop_delay)

	except Exception:
		logging.exception("Error in traffic spawner loop")
		return 1
	finally:
		# Destroy only our managed vehicles
		try:
			if managed:
				client.apply_batch([carla.command.DestroyActor(aid) for aid in list(managed.keys())])
				logging.info("Destroyed %d managed vehicles", len(managed))
		except Exception:
			logging.exception("Failed destroying managed vehicles")
		# Restore settings
		try:
			if args.tm_set_sync:
				tm.set_synchronous_mode(False)
		except Exception:
			pass
		try:
			if prev_sync is not None:
				sync, fdt = prev_sync
				set_sync_mode(world, sync, fdt)
		except Exception:
			pass

	return 0


if __name__ == "__main__":
	sys.exit(main())
