#!/usr/bin/env python

"""
Generate CARLA traffic and publish telemetry to Redis.
Subscribers can mirror traffic vehicles on other machines.
"""

import glob
import os
import sys
import time
import argparse
import logging
from numpy import random

try:
    sys.path.append(glob.glob('../carla/dist/carla-*%d.%d-%s.egg' % (
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError:
    pass

import carla
from telemetry import Telemetry

# -------------------------
# Utility
# -------------------------

def get_actor_blueprints(world, filter, generation="All"):
    bps = world.get_blueprint_library().filter(filter)
    if generation.lower() == "all":
        return bps
    try:
        g = int(generation)
        return [x for x in bps if int(x.get_attribute("generation")) == g]
    except:
        print("Warning: invalid generation")
        return []

# -------------------------
# Traffic Publisher Class
# -------------------------

class TrafficTelemetryPublisher(Telemetry):
    TRAFFIC_MESSAGE_TYPE = 2
    PUBLISH_INTERVAL = 0.05  # 20 Hz

    def __init__(self, world):
        super().__init__()
        self.world = world

    def handle_fetch_telemetry_data(self):
        vehicles = self.world.get_actors().filter("vehicle.*")
        msgs = []
        for v in vehicles:
            if v.attributes.get("role_name") == "hero":
                continue
            t = v.get_transform()
            msgs.append({
                "id": str(v.id),
                "blueprint": v.type_id,
                "color": v.attributes.get("color", "255,255,255"),
                "location": {"x": t.location.x, "y": t.location.y, "z": t.location.z},
                "yaw": t.rotation.yaw
            })
        return {"vehicles": msgs}  # Wrap in dict

    def _create_message(self, message):
        # Force message type=2
        return super()._create_message(message, message_type=self.TRAFFIC_MESSAGE_TYPE)

# -------------------------
# Main
# -------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('-p', '--port', type=int, default=2000)
    parser.add_argument('-n', '--number-of-vehicles', type=int, default=20)
    parser.add_argument('--tm-port', type=int, default=8000)
    parser.add_argument('--asynch', action='store_true')
    parser.add_argument('--hero', action='store_true')
    parser.add_argument('--no-rendering', action='store_true')
    parser.add_argument('--seed', type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    random.seed(args.seed if args.seed else int(time.time()))

    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    world = client.get_world()
    traffic_manager = client.get_trafficmanager(args.tm_port)
    traffic_manager.set_global_distance_to_leading_vehicle(2.5)
    if args.seed is not None:
        traffic_manager.set_random_device_seed(args.seed)

    # Synchronous setup
    synchronous_master = not args.asynch
    if synchronous_master:
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        if args.no_rendering:
            settings.no_rendering_mode = True
        world.apply_settings(settings)

    # Spawn Vehicles
    blueprints = get_actor_blueprints(world, "vehicle.*", "All")
    spawn_points = world.get_map().get_spawn_points()
    if args.number_of_vehicles > len(spawn_points):
        args.number_of_vehicles = len(spawn_points)
    random.shuffle(spawn_points)

    vehicles_list = []
    SpawnActor = carla.command.SpawnActor
    SetAutopilot = carla.command.SetAutopilot
    FutureActor = carla.command.FutureActor

    batch = []
    hero_set = args.hero
    for n, transform in enumerate(spawn_points):
        if n >= args.number_of_vehicles:
            break
        bp = random.choice(blueprints)
        if bp.has_attribute('color'):
            color = random.choice(bp.get_attribute('color').recommended_values)
            bp.set_attribute('color', color)
        bp.set_attribute('role_name', 'hero' if hero_set else 'autopilot')
        hero_set = False
        batch.append(SpawnActor(bp, transform).then(SetAutopilot(FutureActor, True, traffic_manager.get_port())))

    for response in client.apply_batch_sync(batch, synchronous_master):
        if not response.error:
            vehicles_list.append(response.actor_id)

    print(f"Spawned {len(vehicles_list)} vehicles")

    # Start telemetry
    telemetry_publisher = TrafficTelemetryPublisher(world)
    telemetry_publisher.start_telemetry_services()

    try:
        while True:
            if synchronous_master:
                world.tick()
            else:
                world.wait_for_tick()
    except KeyboardInterrupt:
        print("[x] Exiting traffic simulation")
    finally:
        telemetry_publisher.stop_telemetry_services()
        client.apply_batch([carla.command.DestroyActor(x) for x in vehicles_list])
        if synchronous_master:
            settings = world.get_settings()
            settings.synchronous_mode = False
            settings.no_rendering_mode = False
            settings.fixed_delta_seconds = None
            world.apply_settings(settings)
        print("Destroyed all vehicles")

if __name__ == "__main__":
    main()
