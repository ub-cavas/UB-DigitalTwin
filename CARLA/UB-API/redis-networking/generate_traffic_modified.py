#!/usr/bin/env python

# Copyright (c) 2021 Computer Vision Center (CVC) at the Universitat Autonoma de
# Barcelona (UAB).
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

"""Example script to generate traffic in the simulation"""

import carla

from carla.command import SpawnActor, SetAutopilot, FutureActor, DestroyActor

import argparse
import logging
import threading
from numpy import random
import time

from telemetry import Telemetry


def get_actor_blueprints(world, bp_filter, generation):
    bps = world.get_blueprint_library().filter(bp_filter)

    if generation.lower() == "all":
        return bps

    # If the filter returns only one bp, we assume that this one needed
    # and therefore, we ignore the generation
    if len(bps) == 1:
        return bps

    try:
        int_generation = int(generation)
        # Check if generation is in available generations
        if int_generation in [1, 2, 3]:
            bps = [x for x in bps if int(x.get_attribute('generation')) == int_generation]
            return bps
        else:
            print("   Warning! Actor Generation is not valid. No actor will be spawned.")
            return []
    except (ValueError, TypeError):
        print("   Warning! Actor Generation is not valid. No actor will be spawned.")
        return []
    
class TrafficTelemetryPublisher(Telemetry):
    TRAFFIC_MESSAGE_TYPE = 2
    PUBLISH_INTERVAL = 0.05 # 20 Hz

    def __init__(self, world):
        super().__init__()
        self._world = world
        self._world_lock = threading.Lock()

    def handle_fetch_telemetry_data(self):
        with self._world_lock:
            vehicles = self._world.get_actors().filter("vehicle.*")

        messages = []
        for vehicle in vehicles:
            if vehicle.attributes.get("role_name") == "hero":
                continue
            transform = vehicle.get_transform()
            messages.append({
                "id": str(vehicle.id),
                "blueprint": vehicle.type_id,
                "color": vehicle.attributes.get("color", "255,255,255"),
                "location": {
                    "x": transform.location.x, 
                    "y": transform.location.y, 
                    "z": transform.location.z
                    },
                "yaw": transform.rotation.yaw
            })
        return {"vehicles": messages}
    
    def _create_message(self, message, message_type=None):
        if message_type is None:
            message_type = self.TRAFFIC_MESSAGE_TYPE
        return super()._create_message(message, message_type=message_type)

def main():
    argparser = argparse.ArgumentParser(
        description=__doc__)
    argparser.add_argument(
        '--host',
        metavar='H',
        default='127.0.0.1',
        help='IP of the host server (default: 127.0.0.1)')
    argparser.add_argument(
        '-p', '--port',
        metavar='P',
        default=2000,
        type=int,
        help='TCP port to listen to (default: 2000)')
    argparser.add_argument(
        '-n', '--number-of-vehicles',
        metavar='N',
        default=30,
        type=int,
        help='Number of vehicles (default: 30)')
    argparser.add_argument(
        '-w', '--number-of-walkers',
        metavar='W',
        default=10,
        type=int,
        help='Number of walkers (default: 10)')
    argparser.add_argument(
        '--safe',
        action='store_true',
        help='Avoid spawning vehicles prone to accidents')
    argparser.add_argument(
        '--filterv',
        metavar='PATTERN',
        default='vehicle.*',
        help='Filter vehicle model (default: "vehicle.*")')
    argparser.add_argument(
        '--generationv',
        metavar='G',
        default='All',
        help='restrict to certain vehicle generation (values: "1","2","All" - default: "All")')
    argparser.add_argument(
        '--filterw',
        metavar='PATTERN',
        default='walker.pedestrian.*',
        help='Filter pedestrian type (default: "walker.pedestrian.*")')
    argparser.add_argument(
        '--generationw',
        metavar='G',
        default='2',
        help='restrict to certain pedestrian generation (values: "1","2","All" - default: "2")')
    argparser.add_argument(
        '--tm-port',
        metavar='P',
        default=8000,
        type=int,
        help='Port to communicate with TM (default: 8000)')
    argparser.add_argument(
        '--asynch',
        action='store_true',
        help='Activate asynchronous mode execution')
    argparser.add_argument(
        '--hybrid',
        action='store_true',
        help='Activate hybrid mode for Traffic Manager')
    argparser.add_argument(
        '-s', '--seed',
        metavar='S',
        type=int,
        help='Set random device seed and deterministic mode for Traffic Manager')
    argparser.add_argument(
        '--seedw',
        metavar='S',
        default=0,
        type=int,
        help='Set the seed for pedestrians module')
    argparser.add_argument(
        '--car-lights-on',
        action='store_true',
        default=False,
        help='Enable automatic car light management')
    argparser.add_argument(
        '--hero',
        action='store_true',
        default=False,
        help='Set one of the vehicles as hero')
    argparser.add_argument(
        '--respawn',
        action='store_true',
        default=False,
        help='Automatically respawn dormant vehicles (only in large maps)')
    argparser.add_argument(
        '--no-rendering',
        action='store_true',
        default=False,
        help='Activate no rendering mode')
    argparser.add_argument(
        '--bounding-box',
        metavar='BBOX',
        default='-440,-195,31.5,15',
        help='Bounding box for vehicle spawning as "x_min,y_min,x_max,y_max" (default: "-440,-195,31.5,15")')

    args = argparser.parse_args()

    bbox_values = [float(v) for v in args.bounding_box.split(',')]
    if len(bbox_values) != 4:
        raise ValueError("Bounding box must have exactly 4 values: x_min,y_min,x_max,y_max")
    bbox_x_min, bbox_y_min, bbox_x_max, bbox_y_max = bbox_values

    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

    vehicles_list = []
    walkers_list = []
    all_id = []
    all_actors = []
    world = None
    telemetry_publisher = None
    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    synchronous_master = False
    random.seed(args.seed if args.seed is not None else int(time.time()))

    try:
        world = client.get_world()

        traffic_manager = client.get_trafficmanager(args.tm_port)
        traffic_manager.set_global_distance_to_leading_vehicle(2.5)
        if args.respawn:
            traffic_manager.set_respawn_dormant_vehicles(True)
        if args.hybrid:
            traffic_manager.set_hybrid_physics_mode(True)
            traffic_manager.set_hybrid_physics_radius(70.0)
        if args.seed is not None:
            traffic_manager.set_random_device_seed(args.seed)

        settings = world.get_settings()
        if not args.asynch:
            traffic_manager.set_synchronous_mode(True)
            if not settings.synchronous_mode:
                synchronous_master = True
                settings.synchronous_mode = True
                settings.fixed_delta_seconds = 0.05
            else:
                synchronous_master = False
        else:
            print("You are currently in asynchronous mode. If this is a traffic simulation, \
            you could experience some issues. If it's not working correctly, switch to synchronous \
            mode by using traffic_manager.set_synchronous_mode(True)")

        if args.no_rendering:
            settings.no_rendering_mode = True
        world.apply_settings(settings)

        # Destroy leftover vehicles/walkers from previous runs to free spawn points
        existing_vehicles = world.get_actors().filter("vehicle.*")
        existing_walkers = world.get_actors().filter("walker.*")
        existing_controllers = world.get_actors().filter("controller.ai.walker")
        stale_count = 0
        if len(existing_controllers) > 0:
            client.apply_batch([DestroyActor(x) for x in existing_controllers])
            stale_count += len(existing_controllers)
        if len(existing_walkers) > 0:
            client.apply_batch([DestroyActor(x) for x in existing_walkers])
            stale_count += len(existing_walkers)
        if len(existing_vehicles) > 0:
            non_hero = [v for v in existing_vehicles if v.attributes.get("role_name") != "hero"]
            if non_hero:
                client.apply_batch([DestroyActor(x) for x in non_hero])
                stale_count += len(non_hero)
        if stale_count > 0:
            logging.info('Cleaned up %d stale actors from previous runs', stale_count)
            time.sleep(0.5)

        blueprints = get_actor_blueprints(world, args.filterv, args.generationv)
        if not blueprints:
            raise ValueError("Couldn't find any vehicles with the specified filters")
        blueprintsWalkers = get_actor_blueprints(world, args.filterw, args.generationw)
        if not blueprintsWalkers:
            raise ValueError("Couldn't find any walkers with the specified filters")

        if args.safe:
            blueprints = [x for x in blueprints if x.get_attribute('base_type') == 'car']

        blueprints = sorted(blueprints, key=lambda bp: bp.id)

        all_spawn_points = world.get_map().get_spawn_points()
        spawn_points = [
            sp for sp in all_spawn_points
            if bbox_x_min <= sp.location.x <= bbox_x_max
            and bbox_y_min <= sp.location.y <= bbox_y_max
        ]
        if not spawn_points:
            raise ValueError("No spawn points found within the specified bounding box: %s" % args.bounding_box)

        number_of_spawn_points = len(spawn_points)
        logging.info('Found %d spawn points within bounding box', number_of_spawn_points)

        if args.number_of_vehicles < number_of_spawn_points:
            random.shuffle(spawn_points)
        elif args.number_of_vehicles > number_of_spawn_points:
            msg = 'requested %d vehicles, but could only find %d spawn points in bounding box'
            logging.warning(msg, args.number_of_vehicles, number_of_spawn_points)
            args.number_of_vehicles = number_of_spawn_points

        # --------------
        # Spawn vehicles
        # --------------
        batch = []
        hero = args.hero
        for n, transform in enumerate(spawn_points):
            if n >= args.number_of_vehicles:
                break
            blueprint = random.choice(blueprints)
            if blueprint.has_attribute('color'):
                color = random.choice(blueprint.get_attribute('color').recommended_values)
                blueprint.set_attribute('color', color)
            if blueprint.has_attribute('driver_id'):
                driver_id = random.choice(blueprint.get_attribute('driver_id').recommended_values)
                blueprint.set_attribute('driver_id', driver_id)
            if hero:
                blueprint.set_attribute('role_name', 'hero')
                hero = False
            else:
                blueprint.set_attribute('role_name', 'autopilot')

            # spawn the cars and set their autopilot and light state all together
            batch.append(SpawnActor(blueprint, transform)
                .then(SetAutopilot(FutureActor, True, traffic_manager.get_port())))

        for response in client.apply_batch_sync(batch, synchronous_master):
            if response.error:
                logging.error(response.error)
            else:
                vehicles_list.append(response.actor_id)

        # Set automatic vehicle lights update if specified
        if args.car_lights_on:
            all_vehicle_actors = world.get_actors(vehicles_list)
            for actor in all_vehicle_actors:
                traffic_manager.update_vehicle_lights(actor, True)

        # Save vehicle spawn points for respawning (before walker code overwrites spawn_points)
        vehicle_spawn_points = list(spawn_points)

        # -------------
        # Spawn Walkers
        # -------------
        # some settings
        percentagePedestriansRunning = 0.0      # how many pedestrians will run
        percentagePedestriansCrossing = 0.0     # how many pedestrians will walk through the road
        if args.seedw:
            world.set_pedestrians_seed(args.seedw)
            random.seed(args.seedw)
        # 1. take all the random locations to spawn
        spawn_points = []
        for i in range(args.number_of_walkers):
            spawn_point = carla.Transform()
            loc = world.get_random_location_from_navigation()
            if loc is not None:
                spawn_point.location = loc
                spawn_points.append(spawn_point)
        # 2. we spawn the walker object
        batch = []
        walker_speed = []
        for spawn_point in spawn_points:
            walker_bp = random.choice(blueprintsWalkers)
            # set as not invincible
            probability = random.randint(0, 100 + 1)
            if walker_bp.has_attribute('is_invincible'):
                walker_bp.set_attribute('is_invincible', 'false')
            if walker_bp.has_attribute('can_use_wheelchair') and probability < 11:
                walker_bp.set_attribute('use_wheelchair', 'true')
            # set the max speed
            if walker_bp.has_attribute('speed'):
                if (random.random() > percentagePedestriansRunning):
                    # walking
                    walker_speed.append(walker_bp.get_attribute('speed').recommended_values[1])
                else:
                    # running
                    walker_speed.append(walker_bp.get_attribute('speed').recommended_values[2])
            else:
                print("Walker has no speed")
                walker_speed.append(0.0)
            batch.append(SpawnActor(walker_bp, spawn_point))
        results = client.apply_batch_sync(batch, True)
        walker_speed2 = []
        for i in range(len(results)):
            if results[i].error:
                logging.error(results[i].error)
            else:
                walkers_list.append({"id": results[i].actor_id})
                walker_speed2.append(walker_speed[i])
        walker_speed = walker_speed2
        # 3. we spawn the walker controller
        batch = []
        walker_controller_bp = world.get_blueprint_library().find('controller.ai.walker')
        for i in range(len(walkers_list)):
            batch.append(SpawnActor(walker_controller_bp, carla.Transform(), walkers_list[i]["id"]))
        results = client.apply_batch_sync(batch, True)
        for i in range(len(results)):
            if results[i].error:
                logging.error(results[i].error)
            else:
                walkers_list[i]["con"] = results[i].actor_id
        # 4. we put together the walkers and controllers id to get the objects from their id
        # Filter out walkers whose controller failed to spawn
        walkers_list = [w for w in walkers_list if "con" in w]
        for i in range(len(walkers_list)):
            all_id.append(walkers_list[i]["con"])
            all_id.append(walkers_list[i]["id"])
        all_actors = world.get_actors(all_id)

        # wait for a tick to ensure client receives the last transform of the walkers we have just created
        if args.asynch or not synchronous_master:
            world.wait_for_tick()
        else:
            world.tick()

        # 5. initialize each controller and set target to walk to (list is [controler, actor, controller, actor ...])
        # set how many pedestrians can cross the road
        world.set_pedestrians_cross_factor(percentagePedestriansCrossing)
        for i in range(0, len(all_id), 2):
            # start walker
            all_actors[i].start()
            # set walk to random point
            all_actors[i].go_to_location(world.get_random_location_from_navigation())
            # max speed
            all_actors[i].set_max_speed(float(walker_speed[int(i/2)]))

        target_vehicle_count = len(vehicles_list)
        print('spawned %d vehicles and %d walkers, press Ctrl+C to exit.' % (target_vehicle_count, len(walkers_list)))

        telemetry_publisher = TrafficTelemetryPublisher(world)
        telemetry_publisher.start_telemetry_services()

        # Example of how to use Traffic Manager parameters
        traffic_manager.global_percentage_speed_difference(30.0)

        RESPAWN_CHECK_INTERVAL = 5.0
        FALL_OFF_Z_THRESHOLD = -10.0
        STUCK_DISTANCE_THRESHOLD = 1.0  # Minimum distance (meters) a vehicle must move between checks
        STUCK_CHECKS_BEFORE_DESTROY = 3  # Number of consecutive stuck checks before destroying
        last_respawn_check = time.time()
        vehicle_last_positions = {}  # {vehicle_id: (x, y, z)}
        vehicle_stuck_counts = {}   # {vehicle_id: consecutive_stuck_count}

        while True:
            if not args.asynch and synchronous_master:
                with telemetry_publisher._world_lock:
                    world.tick()
            else:
                world.wait_for_tick()

            # Periodically check for missing/fallen vehicles and respawn
            now = time.time()
            if now - last_respawn_check < RESPAWN_CHECK_INTERVAL:
                continue
            last_respawn_check = now

            # Find alive vehicles that are still within bounds and not stuck
            with telemetry_publisher._world_lock:
                alive_actors = world.get_actors(vehicles_list)
            healthy_ids = set()
            remove_ids = []
            for actor in alive_actors:
                loc = actor.get_location()
                aid = actor.id
                if loc.z < FALL_OFF_Z_THRESHOLD:
                    remove_ids.append(aid)
                elif not (bbox_x_min <= loc.x <= bbox_x_max and bbox_y_min <= loc.y <= bbox_y_max):
                    remove_ids.append(aid)
                else:
                    # Check if vehicle is stuck
                    if aid in vehicle_last_positions:
                        last_x, last_y, last_z = vehicle_last_positions[aid]
                        dist = ((loc.x - last_x)**2 + (loc.y - last_y)**2 + (loc.z - last_z)**2)**0.5
                        if dist < STUCK_DISTANCE_THRESHOLD:
                            vehicle_stuck_counts[aid] = vehicle_stuck_counts.get(aid, 0) + 1
                        else:
                            vehicle_stuck_counts[aid] = 0
                    vehicle_last_positions[aid] = (loc.x, loc.y, loc.z)

                    if vehicle_stuck_counts.get(aid, 0) >= STUCK_CHECKS_BEFORE_DESTROY:
                        remove_ids.append(aid)
                        logging.info('Vehicle %d stuck for %d checks, destroying', aid, vehicle_stuck_counts[aid])
                    else:
                        healthy_ids.add(aid)

            # Destroy unhealthy vehicles (out-of-bounds, fallen, stuck)
            alive_actor_ids = {actor.id for actor in alive_actors}
            missing_ids = [vid for vid in vehicles_list if vid not in alive_actor_ids]
            if remove_ids:
                client.apply_batch([DestroyActor(x) for x in remove_ids])
                logging.info('Destroyed %d unhealthy vehicles', len(remove_ids))
            if missing_ids:
                logging.info('Detected %d already-destroyed vehicles', len(missing_ids))

            # Clean up tracking dicts for removed vehicles
            for vid in remove_ids + missing_ids:
                vehicle_last_positions.pop(vid, None)
                vehicle_stuck_counts.pop(vid, None)

            vehicles_list = [vid for vid in vehicles_list if vid in healthy_ids]
            vehicles_to_spawn = target_vehicle_count - len(vehicles_list)

            if vehicles_to_spawn > 0:
                respawn_batch = []
                respawn_points = list(vehicle_spawn_points)
                random.shuffle(respawn_points)
                for i in range(min(vehicles_to_spawn, len(respawn_points))):
                    bp = random.choice(blueprints)
                    if bp.has_attribute('color'):
                        bp.set_attribute('color', random.choice(bp.get_attribute('color').recommended_values))
                    if bp.has_attribute('driver_id'):
                        bp.set_attribute('driver_id', random.choice(bp.get_attribute('driver_id').recommended_values))
                    bp.set_attribute('role_name', 'autopilot')
                    respawn_batch.append(SpawnActor(bp, respawn_points[i])
                        .then(SetAutopilot(FutureActor, True, traffic_manager.get_port())))

                for response in client.apply_batch_sync(respawn_batch, synchronous_master):
                    if response.error:
                        logging.error(response.error)
                    else:
                        vehicles_list.append(response.actor_id)

                respawned = len(vehicles_list) - (target_vehicle_count - vehicles_to_spawn)
                if respawned > 0:
                    logging.info('Respawned %d vehicles (total: %d/%d)', respawned, len(vehicles_list), target_vehicle_count)

    finally:
        if telemetry_publisher:
            telemetry_publisher.stop_telemetry_services()

        if world and not args.asynch and synchronous_master:
            settings = world.get_settings()
            settings.synchronous_mode = False
            settings.no_rendering_mode = False
            settings.fixed_delta_seconds = None
            world.apply_settings(settings)

        print('\ndestroying %d vehicles' % len(vehicles_list))
        client.apply_batch([DestroyActor(x) for x in vehicles_list])

        # stop walker controllers (list is [controller, actor, controller, actor ...])
        if all_actors:
            for i in range(0, len(all_id), 2):
                all_actors[i].stop()

        print('\ndestroying %d walkers' % len(walkers_list))
        client.apply_batch([DestroyActor(x) for x in all_id])

        time.sleep(0.5)

if __name__ == '__main__':

    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        print('\ndone.')