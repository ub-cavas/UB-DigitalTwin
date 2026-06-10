#!/usr/bin/env python

# Copyright (c) 2025 Computer Vision Center (CVC) at the Universitat Autonoma de
# Barcelona (UAB).
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

"""Example script to generate traffic in the simulation"""

import carla

from carla import VehicleLightState as vls
from carla.command import SpawnActor, SetAutopilot, FutureActor, DestroyActor

import argparse
import logging
from numpy import random
import time

# Custom spawn points (x, y). Z will be projected to road and yaw taken from nearest waypoint
CUSTOM_SPAWN_POINTS = [
    (-431.17, 29.75),
    (-436.59, 165.68),
    (-318.63, 184.36),
    (-301.08, 170.19),
    (-222.0, 149.05),
    (-198.0, 19.13),
]


def get_actor_blueprints(world, filter, generation):
    bps = world.get_blueprint_library().filter(filter)

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
    except:
        print("   Warning! Actor Generation is not valid. No actor will be spawned.")
        return []

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
        '--hybrid-radius',
        metavar='R',
        type=float,
        default=70.0,
        help='Hybrid physics radius when --hybrid is enabled (default: 70.0)')
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
    # Simulation timing & physics
    argparser.add_argument(
        '--fixed-delta-seconds',
        metavar='DT',
        type=float,
        default=0.03,
        help='Fixed time step in synchronous mode (default: 0.03)')
    argparser.add_argument(
        '--substepping',
        action='store_true',
        help='Enable physics substepping for smoother simulation')
    argparser.add_argument(
        '--max-substep-dt',
        metavar='DT',
        type=float,
        default=0.01,
        help='Max substep delta time when substepping (default: 0.01)')
    argparser.add_argument(
        '--max-substeps',
        metavar='N',
        type=int,
        default=10,
        help='Max substeps when substepping (default: 10)')
    # TM tuning for smoother flow
    argparser.add_argument(
        '--tm-distance',
        metavar='M',
        type=float,
        default=4.0,
        help='Traffic Manager global distance to leading vehicle (meters, default: 4.0)')
    argparser.add_argument(
        '--tm-speed-diff',
        metavar='PCT',
        type=float,
        default=0.0,
        help='Traffic Manager global percentage speed difference (default: 0.0)')
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
    # Custom spawn points options
    argparser.add_argument(
        '--use-custom-spawn-points',
        action='store_true',
        help='Spawn vehicles based on predefined custom points instead of map spawn points')
    argparser.add_argument(
        '--custom-step-distance',
        metavar='D',
        type=float,
        default=10.0,
        help='Distance in meters between successive spawns along a lane when using custom points (default: 10.0)')
    argparser.add_argument(
        '--custom-steps',
        metavar='K',
        type=int,
        default=15,
        help='Number of successive spawns to attempt along each custom point lane (default: 15)')
    argparser.add_argument(
        '--min-spawn-distance',
        metavar='M',
        type=float,
        default=10.0,
        help='Minimum distance to existing vehicles for a spawn transform to be considered (default: 10.0)')
    # Maintain vehicle count options
    argparser.add_argument(
        '--no-maintain-vehicles',
        action='store_true',
        help='Disable maintaining vehicle count at the target threshold')
    argparser.add_argument(
        '--maintain-interval',
        metavar='SECONDS',
        type=float,
        default=2.0,
        help='Seconds between vehicle count maintenance checks (default: 2.0)')

    args = argparser.parse_args()

    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

    vehicles_list = []
    walkers_list = []
    all_id = []
    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    synchronous_master = False
    random.seed(args.seed if args.seed is not None else int(time.time()))

    world = None
    all_actors = None
    try:
        world = client.get_world()

        traffic_manager = client.get_trafficmanager(args.tm_port)
        traffic_manager.set_global_distance_to_leading_vehicle(float(args.tm_distance))
        if args.respawn:
            traffic_manager.set_respawn_dormant_vehicles(True)
        if args.hybrid:
            traffic_manager.set_hybrid_physics_mode(True)
            traffic_manager.set_hybrid_physics_radius(float(args.hybrid_radius))
        if args.seed is not None:
            traffic_manager.set_random_device_seed(args.seed)
        # Smooth flow: apply global TM speed difference
        traffic_manager.global_percentage_speed_difference(float(args.tm_speed_diff))

        settings = world.get_settings()
        if not args.asynch:
            traffic_manager.set_synchronous_mode(True)
            if not settings.synchronous_mode:
                synchronous_master = True
                settings.synchronous_mode = True
            else:
                synchronous_master = False
            # Apply timing and substepping regardless of who enabled sync
            settings.fixed_delta_seconds = float(args.fixed_delta_seconds)
            if args.substepping:
                settings.substepping = True
                settings.max_substep_delta_time = float(args.max_substep_dt)
                settings.max_substeps = int(args.max_substeps)
            world.apply_settings(settings)
        else:
            print("You are currently in asynchronous mode. If this is a traffic simulation, \
            you could experience some issues. If it's not working correctly, switch to synchronous \
            mode by using traffic_manager.set_synchronous_mode(True)")
        if args.no_rendering:
            settings.no_rendering_mode = True
            world.apply_settings(settings)

        blueprints = get_actor_blueprints(world, args.filterv, args.generationv)
        if not blueprints:
            raise ValueError("Couldn't find any vehicles with the specified filters")
        blueprintsWalkers = get_actor_blueprints(world, args.filterw, args.generationw)
        if not blueprintsWalkers:
            raise ValueError("Couldn't find any walkers with the specified filters")

        if args.safe:
            blueprints = [x for x in blueprints if x.get_attribute('base_type') == 'car']

        blueprints = sorted(blueprints, key=lambda bp: bp.id)

        # --------------
        # Spawn vehicles (custom or map spawn points)
        # --------------
        def build_custom_transforms(map_obj, needed, step_distance, steps_per_seed):
            transforms = []
            for (x, y) in CUSTOM_SPAWN_POINTS:
                wp = map_obj.get_waypoint(
                    carla.Location(x=float(x), y=float(y), z=0.0),
                    project_to_road=True,
                    lane_type=carla.LaneType.Driving,
                )
                if wp is None:
                    logging.warning('No drivable waypoint found near custom point (%.2f, %.2f)', x, y)
                    continue
                cur = wp
                for _ in range(max(1, steps_per_seed)):
                    transforms.append(cur.transform)
                    nxt = cur.next(step_distance)
                    if not nxt:
                        break
                    cur = nxt[0]
                    if len(transforms) >= needed:
                        break
                if len(transforms) >= needed:
                    break
            # Randomize order to distribute spawns
            random.shuffle(transforms)
            return transforms

        def get_vehicle_locations():
            try:
                actors = world.get_actors().filter('vehicle.*')
                return [a.get_transform().location for a in actors]
            except Exception:
                return []

        def filter_clear_transforms(transforms, min_distance):
            vehicle_locs = get_vehicle_locations()
            accepted = []
            for tr in transforms:
                loc = tr.location
                clear = True
                for vloc in vehicle_locs:
                    if loc.distance(vloc) < min_distance:
                        clear = False
                        break
                if clear:
                    # also keep distance from already accepted to avoid overlaps in same batch
                    for atr in accepted:
                        if loc.distance(atr.location) < min_distance:
                            clear = False
                            break
                if clear:
                    accepted.append(tr)
            return accepted

        hero_assigned = False

        def spawn_from_transforms(transforms, count_needed):
            nonlocal hero_assigned
            spawned_count = 0
            new_ids = []
            idx = 0
            while spawned_count < count_needed and idx < len(transforms):
                transform = transforms[idx]
                idx += 1
                blueprint = random.choice(blueprints)
                if blueprint.has_attribute('color'):
                    color = random.choice(blueprint.get_attribute('color').recommended_values)
                    blueprint.set_attribute('color', color)
                if blueprint.has_attribute('driver_id'):
                    driver_id = random.choice(blueprint.get_attribute('driver_id').recommended_values)
                    blueprint.set_attribute('driver_id', driver_id)
                # Assign hero to first successful spawn only if requested and not yet assigned
                if not hero_assigned and args.hero:
                    blueprint.set_attribute('role_name', 'hero')
                else:
                    blueprint.set_attribute('role_name', 'autopilot')

                batch = [
                    SpawnActor(blueprint, transform).then(
                        SetAutopilot(FutureActor, True, traffic_manager.get_port())
                    )
                ]
                response = client.apply_batch_sync(batch, synchronous_master)[0]
                if response.error:
                    logging.debug('Spawn failed at transform %s: %s', transform, response.error)
                    continue
                if not hero_assigned and args.hero:
                    hero_assigned = True
                vehicles_list.append(response.actor_id)
                new_ids.append(response.actor_id)
                spawned_count += 1
            # Update lights for newly spawned
            if new_ids and args.car_lights_on:
                for actor in world.get_actors(new_ids):
                    traffic_manager.update_vehicle_lights(actor, True)
            return spawned_count

        def spawn_up_to_threshold(remaining_to_spawn):
            if remaining_to_spawn <= 0:
                return 0
            # Build transforms from custom points or default map spawn points
            transforms = []
            if args.use_custom_spawn_points:
                transforms = build_custom_transforms(
                    world.get_map(),
                    needed=remaining_to_spawn * 2,
                    step_distance=float(args.custom_step_distance),
                    steps_per_seed=int(args.custom_steps),
                )
                if not transforms:
                    logging.warning('No custom transforms could be generated; falling back to map spawn points.')
            if not transforms:
                spawn_points = world.get_map().get_spawn_points()
                random.shuffle(spawn_points)
                transforms = spawn_points
            # Filter out transforms too close to existing vehicles
            transforms = filter_clear_transforms(transforms, float(args.min_spawn_distance))
            return spawn_from_transforms(transforms, remaining_to_spawn)

        target_total = int(args.number_of_vehicles)
        # Initial spawn up to threshold
        try:
            existing_vehicle_ids = [a.id for a in world.get_actors().filter('vehicle.*')]
        except Exception as e:
            logging.warning('Failed to count existing vehicles: %s', e)
            existing_vehicle_ids = []
        existing_count = len(existing_vehicle_ids)
        remaining_to_spawn = max(0, target_total - existing_count)
        if remaining_to_spawn == 0:
            logging.info('Target of %d vehicles already reached (existing: %d). No new spawns.', target_total, existing_count)
        else:
            spawned_now = spawn_up_to_threshold(remaining_to_spawn)
            if spawned_now < remaining_to_spawn:
                logging.info('Spawned %d/%d initial vehicles (some transforms failed).', spawned_now, remaining_to_spawn)

        maintain_enabled = not args.no_maintain_vehicles
        last_maintain = time.time()

        # Set automatic vehicle lights update if specified
        if args.car_lights_on:
            all_vehicle_actors = world.get_actors(vehicles_list)
            for actor in all_vehicle_actors:
                traffic_manager.update_vehicle_lights(actor, True)

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
            if (loc != None):
                spawn_point.location = loc
                spawn_points.append(spawn_point)
        # 2. we spawn the walker object
        batch = []
        walker_speed = []
        for spawn_point in spawn_points:
            walker_bp = random.choice(blueprintsWalkers)
            # set as not invincible
            probability = random.randint(0,100 + 1);
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
        for i in range(len(walkers_list)):
            all_id.append(walkers_list[i]["con"])
            all_id.append(walkers_list[i]["id"])
        all_actors = world.get_actors(all_id)

        # wait for a tick to ensure client receives the last transform of the walkers we have just created
        if not args.asynch:
            world.tick()
        else:
            world.wait_for_tick()

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

        print('spawned %d vehicles and %d walkers, press Ctrl+C to exit.' % (len(vehicles_list), len(walkers_list)))

        while True:
            if not args.asynch:
                world.tick()
            else:
                world.wait_for_tick()

            if maintain_enabled and (time.time() - last_maintain) >= float(args.maintain_interval):
                last_maintain = time.time()
                try:
                    current_vehicle_count = len(world.get_actors().filter('vehicle.*'))
                except Exception as e:
                    logging.debug('Maintenance: failed to count vehicles: %s', e)
                    current_vehicle_count = 0
                deficit = max(0, target_total - current_vehicle_count)
                if deficit > 0:
                    spawned = spawn_up_to_threshold(deficit)
                    if spawned > 0:
                        logging.debug('Maintenance: spawned %d to reach target %d (now approx %d).', spawned, target_total, current_vehicle_count + spawned)

    finally:

        if world is not None and (not args.asynch and synchronous_master):
            settings = world.get_settings()
            settings.synchronous_mode = False
            settings.no_rendering_mode = False
            settings.fixed_delta_seconds = None
            world.apply_settings(settings)

        if vehicles_list:
            print('\ndestroying %d vehicles' % len(vehicles_list))
            client.apply_batch([DestroyActor(x) for x in vehicles_list])

        # stop walker controllers (list is [controller, actor, controller, actor ...])
        if all_actors is not None:
            for i in range(0, len(all_id), 2):
                all_actors[i].stop()

        if all_id:
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
