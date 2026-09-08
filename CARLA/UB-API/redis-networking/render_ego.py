#!/usr/bin/env python

"""Subscribes to ego vehicle poses on Redis (published by ego_bridge.py from
Unity) and renders them in CARLA as physics-less replica vehicles.

The replicas are spawned with role_name='hero' so that:
  - generate_traffic_modified.py does not destroy them at startup, and
  - they are excluded from the traffic telemetry, so they never echo back
    to Unity as traffic vehicles.

Supports multiple simultaneous egos (one per Unity client), keyed by the
'id' field inside the ego payload. A replica is destroyed when its client
stops sending for --stale-timeout seconds.
"""

import argparse
import logging
import threading
import time

import carla

from telemetry import Telemetry


class EgoTelemetryReceiver(Telemetry):
    EGO_MESSAGE_TYPE = 3

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._latest = {}  # ego_id -> {"data": ego dict, "received_at": float}

    def start(self):
        # Subscriber only — this script never publishes telemetry, so the
        # base class publisher thread is intentionally not started.
        self.logger.start_logging()
        self._start_telemetry_subscriber()

    def stop(self):
        self._stop_telemetry_subscriber()
        self.logger.stop_logging()

    def on_receive_telemetry(self, parsed_message):
        if parsed_message.get("type") != self.EGO_MESSAGE_TYPE:
            return
        ego = parsed_message.get("ego")
        if not ego or "id" not in ego or "location" not in ego:
            return
        with self._lock:
            self._latest[ego["id"]] = {"data": ego, "received_at": time.time()}

    def on_receive_conn_destroy(self, id):
        pass

    def snapshot(self):
        with self._lock:
            return dict(self._latest)

    def forget(self, ego_id):
        with self._lock:
            self._latest.pop(ego_id, None)


def pick_blueprint(world, requested, fallback):
    library = world.get_blueprint_library()
    for name in (requested, fallback):
        if not name:
            continue
        matches = library.filter(name)
        if matches:
            return matches[0]
    return library.filter("vehicle.*")[0]


def make_transform(ego, z_offset):
    loc = ego["location"]
    return carla.Transform(
        carla.Location(
            x=float(loc.get("x", 0.0)),
            y=float(loc.get("y", 0.0)),
            z=float(loc.get("z", 0.0)) + z_offset),
        carla.Rotation(yaw=float(ego.get("yaw", 0.0))))


def spawn_ego(world, ego, fallback_blueprint, transform):
    blueprint = pick_blueprint(world, ego.get("blueprint"), fallback_blueprint)
    blueprint.set_attribute("role_name", "hero")
    color = ego.get("color")
    if color and blueprint.has_attribute("color"):
        try:
            blueprint.set_attribute("color", color)
        except RuntimeError:
            pass

    # Lift the initial spawn slightly to avoid ground collision rejection;
    # the exact pose is applied right after physics is disabled.
    lifted = carla.Transform(
        carla.Location(transform.location.x, transform.location.y, transform.location.z + 0.5),
        transform.rotation)
    actor = world.try_spawn_actor(blueprint, lifted)
    if actor is None:
        return None
    actor.set_simulate_physics(False)
    actor.set_transform(transform)
    return actor


def main():
    argparser = argparse.ArgumentParser(description=__doc__)
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
        '--blueprint',
        metavar='BP',
        default='vehicle.lincoln.mkz_2017',
        help='Fallback CARLA blueprint when the ego message does not name a valid one '
             '(default: vehicle.lincoln.mkz_2017)')
    argparser.add_argument(
        '--stale-timeout',
        metavar='S',
        default=2.0,
        type=float,
        help='Seconds without messages before an ego replica is destroyed (default: 2.0)')
    argparser.add_argument(
        '--z-offset',
        metavar='Z',
        default=0.0,
        type=float,
        help='Vertical offset (meters) added to received ego z, to reconcile Unity/CARLA '
             'pivot differences (default: 0.0)')
    args = argparser.parse_args()

    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    world = client.get_world()

    receiver = EgoTelemetryReceiver()
    receiver.start()

    spawned = {}  # ego_id -> carla.Actor
    print('Waiting for ego messages, press Ctrl+C to exit.')

    try:
        while True:
            now = time.time()
            for ego_id, entry in receiver.snapshot().items():
                try:
                    if now - entry["received_at"] > args.stale_timeout:
                        actor = spawned.pop(ego_id, None)
                        if actor is not None:
                            actor.destroy()
                            logging.info("Ego '%s' stale for %.1fs, destroyed replica",
                                         ego_id, now - entry["received_at"])
                        receiver.forget(ego_id)
                        continue

                    transform = make_transform(entry["data"], args.z_offset)
                    actor = spawned.get(ego_id)
                    if actor is None:
                        actor = spawn_ego(world, entry["data"], args.blueprint, transform)
                        if actor is None:
                            # Spawn spot blocked, retry on the next message
                            continue
                        spawned[ego_id] = actor
                        logging.info("Spawned replica %s (actor %d) for ego '%s'",
                                     actor.type_id, actor.id, ego_id)
                    else:
                        actor.set_transform(transform)
                except RuntimeError as e:
                    # Actor may have been destroyed externally (e.g. world reload);
                    # drop it so it respawns on the next iteration.
                    logging.warning("Ego '%s' actor error (%s), will respawn", ego_id, e)
                    spawned.pop(ego_id, None)

            time.sleep(0.02)
    finally:
        receiver.stop()
        for actor in spawned.values():
            try:
                actor.destroy()
            except RuntimeError:
                pass
        print('\ndestroyed %d ego replicas' % len(spawned))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        print('\ndone.')
