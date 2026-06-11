#!/usr/bin/env python

import json
import os
import socket
import threading
import time
import redis
import carla

CONFIG_FILE = "telemetry.conf"

DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6390
DEFAULT_REDIS_PASSWORD = "password"
DEFAULT_REDIS_CHANNEL = "carla:telemetry"

DEFAULT_UNITY_HOST = "127.0.0.1"
DEFAULT_UNITY_PORT = 12345
DEFAULT_EGO_LISTEN_HOST = "0.0.0.0"
DEFAULT_EGO_LISTEN_PORT = 12346
DEFAULT_CARLA_HOST = "127.0.0.1"
DEFAULT_CARLA_PORT = 2000
DEFAULT_EGO_ID = "ub-mr-ego"
DEFAULT_EGO_BLUEPRINT = "vehicle.lincoln.mkz_2020"
DEFAULT_EGO_COLOR = "0,0,255"
DEFAULT_EGO_TIMEOUT = 2.0
DEFAULT_CARLA_TIMEOUT = 10.0

TRAFFIC_MESSAGE_TYPE = 2
EGO_MESSAGE_TYPE = 3
EGO_ROLE_NAME = "external_ego"


def _load_json_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)
    if not os.path.exists(config_path):
        return {}

    try:
        with open(config_path, "r") as file:
            return json.load(file)
    except Exception as e:
        print(f"[x] Ignoring invalid telemetry config file '{config_path}': {e}")
        return {}


def _get_config_value(config, env_name, config_name, default):
    if env_name in os.environ:
        return os.environ[env_name]

    return config.get(config_name, default)


def _get_config_int(config, env_name, config_name, default):
    raw_value = _get_config_value(config, env_name, config_name, default)

    try:
        return int(raw_value)
    except (TypeError, ValueError):
        print(f"[x] Invalid integer value '{raw_value}' for {env_name}, using default {default}")
        return default


def _get_config_float(config, env_name, config_name, default):
    raw_value = _get_config_value(config, env_name, config_name, default)

    try:
        return float(raw_value)
    except (TypeError, ValueError):
        print(f"[x] Invalid float value '{raw_value}' for {env_name}, using default {default}")
        return default


class CarlaEgoMirror:
    def __init__(self, host, port, timeout, ego_timeout):
        self._client = carla.Client(host, port)
        self._client.set_timeout(timeout)
        self._world = self._client.get_world()
        self._ego_timeout = ego_timeout
        self._actor = None
        self._actor_blueprint = None
        self._last_update = 0.0

    def update(self, ego):
        if not ego:
            return

        transform = self._to_transform(ego)
        blueprint_id = ego.get("blueprint") or DEFAULT_EGO_BLUEPRINT
        color = ego.get("color") or DEFAULT_EGO_COLOR

        if self._actor and (
            not self._actor.is_alive
            or self._actor_blueprint != blueprint_id
            or (
                "color" in self._actor.attributes
                and self._actor.attributes.get("color") != color
            )
        ):
            self.destroy()

        if not self._actor:
            self._spawn(transform, blueprint_id, color)

        if self._actor:
            self._actor.set_transform(transform)
            self._last_update = time.time()

    def cleanup_if_stale(self):
        if self._actor and time.time() - self._last_update > self._ego_timeout:
            print(f"[!] Destroying stale CARLA ego actor after {self._ego_timeout:.1f}s without updates")
            self.destroy()

    def destroy(self):
        if self._actor:
            try:
                self._actor.destroy()
            except RuntimeError as e:
                print(f"[x] Failed to destroy CARLA ego actor: {e}")
        self._actor = None
        self._actor_blueprint = None
        self._last_update = 0.0

    def _spawn(self, transform, blueprint_id, color):
        blueprint_library = self._world.get_blueprint_library()

        try:
            blueprint = blueprint_library.find(blueprint_id)
        except RuntimeError:
            print(f"[x] CARLA blueprint '{blueprint_id}' not found, using '{DEFAULT_EGO_BLUEPRINT}'")
            blueprint = blueprint_library.find(DEFAULT_EGO_BLUEPRINT)
            blueprint_id = DEFAULT_EGO_BLUEPRINT

        if blueprint.has_attribute("role_name"):
            blueprint.set_attribute("role_name", EGO_ROLE_NAME)
        if blueprint.has_attribute("color"):
            blueprint.set_attribute("color", color)

        try:
            actor = self._world.try_spawn_actor(blueprint, transform)
            if actor is None:
                transform.location.z += 0.5
                actor = self._world.spawn_actor(blueprint, transform)
            actor.set_autopilot(False)
            actor.set_simulate_physics(False)
            self._actor = actor
            self._actor_blueprint = blueprint_id
            print(f"[!] Spawned CARLA ego mirror actor ID={actor.id} blueprint={blueprint_id}")
        except RuntimeError as e:
            print(f"[x] Failed to spawn CARLA ego mirror: {e}")

    def _to_transform(self, ego):
        location = ego.get("location") or {}
        return carla.Transform(
            carla.Location(
                x=float(location.get("x", 0.0)),
                y=float(location.get("y", 0.0)),
                z=float(location.get("z", 0.0))
            ),
            carla.Rotation(yaw=float(ego.get("yaw", 0.0)))
        )


def _start_ego_udp_listener(redis_client, redis_channel, config):
    ego_host = _get_config_value(config, "UB_EGO_LISTEN_HOST", "ego_listen_host", DEFAULT_EGO_LISTEN_HOST)
    ego_port = _get_config_int(config, "UB_EGO_LISTEN_PORT", "ego_listen_port", DEFAULT_EGO_LISTEN_PORT)
    ego_id = _get_config_value(config, "UB_EGO_ID", "ego_id", DEFAULT_EGO_ID)
    ego_blueprint = _get_config_value(
        config,
        "UB_EGO_BLUEPRINT",
        "ego_blueprint",
        DEFAULT_EGO_BLUEPRINT
    )
    ego_color = _get_config_value(config, "UB_EGO_COLOR", "ego_color", DEFAULT_EGO_COLOR)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ego_host, ego_port))

    def receive_loop():
        print(f"Listening for UB-MR ego UDP at {ego_host}:{ego_port}")
        while True:
            try:
                data, addr = sock.recvfrom(65535)
                parsed = json.loads(data.decode("utf-8"))
                ego = parsed.get("ego", parsed)
                if not isinstance(ego, dict) or "location" not in ego:
                    print(f"[x] Ignoring invalid ego packet from {addr[0]}:{addr[1]}")
                    continue

                ego.setdefault("id", ego_id)
                ego.setdefault("blueprint", ego_blueprint)
                ego.setdefault("color", ego_color)

                message = {
                    "id": "udp-bridge",
                    "type": EGO_MESSAGE_TYPE,
                    "timestamp": time.time(),
                    "ego": ego
                }
                redis_client.publish(redis_channel, json.dumps(message))
            except Exception as e:
                print(f"[x] Ego UDP receive error: {e}")
                if isinstance(e, OSError):
                    break

    thread = threading.Thread(target=receive_loop, daemon=True)
    thread.start()
    return sock


def main():
    config = _load_json_config()
    redis_host = _get_config_value(config, "UB_REDIS_HOST", "host", DEFAULT_REDIS_HOST)
    redis_port = _get_config_int(config, "UB_REDIS_PORT", "port", DEFAULT_REDIS_PORT)
    redis_password = _get_config_value(
        config,
        "UB_REDIS_PASSWORD",
        "password",
        DEFAULT_REDIS_PASSWORD
    )
    redis_channel = _get_config_value(
        config,
        "UB_REDIS_CHANNEL",
        "channel",
        DEFAULT_REDIS_CHANNEL
    )
    unity_host = _get_config_value(config, "UB_UNITY_HOST", "unity_host", DEFAULT_UNITY_HOST)
    unity_port = _get_config_int(config, "UB_UNITY_PORT", "unity_port", DEFAULT_UNITY_PORT)
    carla_host = _get_config_value(config, "UB_CARLA_HOST", "carla_host", DEFAULT_CARLA_HOST)
    carla_port = _get_config_int(config, "UB_CARLA_PORT", "carla_port", DEFAULT_CARLA_PORT)
    carla_timeout = _get_config_float(
        config,
        "UB_CARLA_TIMEOUT",
        "carla_timeout",
        DEFAULT_CARLA_TIMEOUT
    )
    ego_timeout = _get_config_float(config, "UB_EGO_TIMEOUT", "ego_timeout", DEFAULT_EGO_TIMEOUT)

    r = redis.Redis(host=redis_host, port=redis_port, password=redis_password or None)
    pubsub = r.pubsub()
    pubsub.subscribe(redis_channel)
    ego_listener = _start_ego_udp_listener(r, redis_channel, config)
    ego_mirror = CarlaEgoMirror(carla_host, carla_port, carla_timeout, ego_timeout)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    unity_addr = (unity_host, unity_port)

    print(f"Subscribed to Redis channel '{redis_channel}'")
    print(f"Forwarding to Unity at {unity_host}:{unity_port}")
    print(f"Mirroring UB-MR ego into CARLA at {carla_host}:{carla_port}")

    try:
        for raw_message in pubsub.listen():
            ego_mirror.cleanup_if_stale()
            if raw_message["type"] != "message":
                continue
            try:
                parsed = json.loads(raw_message["data"])
                message_type = parsed.get("type")

                if message_type == TRAFFIC_MESSAGE_TYPE:
                    if "vehicles" not in parsed:
                        continue

                    payload = {
                        "vehicles": parsed["vehicles"],
                        "timestamp": parsed["timestamp"]
                    }

                    data = json.dumps(payload).encode("utf-8")

                    print(f"Sending {len(payload['vehicles'])} vehicles over the bridge")

                    if len(data) > 60000:
                        print(f"Warning: payload size {len(data)} bytes is close to UDP limit")

                    sock.sendto(data, unity_addr)
                    continue

                if message_type == EGO_MESSAGE_TYPE:
                    ego_mirror.update(parsed.get("ego"))

            except Exception as e:
                print(f"Error: {e}")
    finally:
        ego_mirror.destroy()
        ego_listener.close()

if __name__ == "__main__":
    main()
