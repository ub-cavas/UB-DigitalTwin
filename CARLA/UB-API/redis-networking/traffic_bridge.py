#!/usr/bin/env python

import json
import os
import socket
import threading
import time
import redis
import carla
from ub_telemetry.vehicle_mirrors import VehicleMirrors, valid_ego

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
DEFAULT_EGO_BRIDGE = True
DEFAULT_CARLA_EGO_MIRROR = True

# Must match Telemetry.MESSAGE_TYPES in telemetry.py. Duplicated rather than
# imported so this bridge stays a standalone script with no Telemetry dependency.
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


def _get_config_bool(config, env_name, config_name, default):
    raw_value = _get_config_value(config, env_name, config_name, default)

    if isinstance(raw_value, bool):
        return raw_value

    if raw_value is None:
        return default

    normalized = str(raw_value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    print(f"[x] Invalid boolean value '{raw_value}' for {env_name}, using default {default}")
    return default


class CarlaEgoMirror:
    def __init__(self, host, port, timeout, ego_timeout, redis_client, channel):
        self._client = carla.Client(host, port)
        self._client.set_timeout(timeout)
        self._world = self._client.get_world()
        self._ego_timeout = ego_timeout
        self._mirrors = VehicleMirrors(redis_client, channel, self._world, self._client.get_world)
        self._mirrors.start()
        self._actors = {}
        self._last_updates = {}

    def update(self, ego):
        if not valid_ego(ego):
            return
        if not self._mirrors.check_world():
            current = self._mirrors.replacement_world
            if current is None: return
            self._mirrors.close()
            self._world = current
            self._mirrors = VehicleMirrors(self._mirrors.redis, self._mirrors.channel, current, self._client.get_world)
            self._mirrors.start()
            self._actors.clear()
            self._last_updates.clear()
        identity = str(ego["id"])
        actor = self._actors.get(identity)
        if actor is not None and not actor.is_alive:
            actor = None
        reserved = False
        retained = False
        if actor is None:
            if not self._mirrors.begin_spawn("ego", identity): return
            reserved = True
        elif not self._mirrors.claim("ego", identity):
            self._actors.pop(identity, None)
            return
        try:
            if actor is None:
                actor = self._mirrors.adopt("ego", identity)
            transform = self._to_transform(ego)
            if actor is None:
                blueprint = self._world.get_blueprint_library().find(ego.get("blueprint") or DEFAULT_EGO_BLUEPRINT)
                blueprint.set_attribute("role_name", self._mirrors.role("ego", identity))
                if blueprint.has_attribute("color"):
                    blueprint.set_attribute("color", ego.get("color") or DEFAULT_EGO_COLOR)
                actor = self._world.try_spawn_actor(blueprint, transform)
                if actor is None: return
                if not self._mirrors.finish_spawn("ego", identity): return
                actor.set_simulate_physics(False)
                if not self._mirrors.finish_spawn("ego", identity): return
            if self._mirrors.check_world() and self._mirrors.owns("ego", identity):
                actor.set_transform(transform)
                self._actors[identity] = actor
                self._last_updates[identity] = time.monotonic()
                self._mirrors.bind("ego", identity, actor)
                retained = True
        finally:
            if reserved:
                self._mirrors.end_spawn("ego", identity, release_if_unused=not retained, actor=actor)

    def cleanup_if_stale(self):
        for identity in list(self._actors):
            if time.monotonic() - self._last_updates.get(identity, 0) > self._ego_timeout:
                self._mirrors.release("ego", identity, self._actors.pop(identity))
                self._last_updates.pop(identity, None)
            elif not self._mirrors.owns("ego", identity):
                self._actors.pop(identity, None)
                self._last_updates.pop(identity, None)

    def destroy(self):
        for identity, actor in list(self._actors.items()):
            self._mirrors.release("ego", identity, actor)
        self._actors.clear()
        self._last_updates.clear()
        self._mirrors.close()

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
                if not isinstance(parsed, dict): continue
                if "type" in parsed and (type(parsed["type"]) is not int or parsed["type"] != EGO_MESSAGE_TYPE): continue
                if "ego" in parsed and "type" not in parsed: continue
                ego = parsed.get("ego", parsed)
                if not valid_ego(ego):
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
    ego_bridge_enabled = _get_config_bool(
        config,
        "UB_EGO_BRIDGE",
        "ego_bridge",
        DEFAULT_EGO_BRIDGE
    )
    carla_ego_mirror_enabled = _get_config_bool(
        config,
        "UB_CARLA_EGO_MIRROR",
        "carla_ego_mirror",
        DEFAULT_CARLA_EGO_MIRROR
    )

    r = redis.Redis(host=redis_host, port=redis_port, password=redis_password or None,
                    socket_connect_timeout=0.5, socket_timeout=0.5, retry=None, retry_on_timeout=False)
    pubsub = r.pubsub()
    pubsub.subscribe(redis_channel)
    ego_listener = _start_ego_udp_listener(r, redis_channel, config) if ego_bridge_enabled else None
    ego_mirror = (
        CarlaEgoMirror(carla_host, carla_port, carla_timeout, ego_timeout, r, redis_channel)
        if carla_ego_mirror_enabled
        else None
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    unity_addr = (unity_host, unity_port)

    print(f"Subscribed to Redis channel '{redis_channel}'")
    print(f"Forwarding to Unity at {unity_host}:{unity_port}")
    if ego_bridge_enabled:
        print("Publishing UB-MR ego UDP packets to Redis")
    else:
        print("UB-MR ego UDP bridge disabled")
    if carla_ego_mirror_enabled:
        print(f"Mirroring UB-MR ego into CARLA at {carla_host}:{carla_port}")
    else:
        print("CARLA ego mirror disabled")

    try:
        while True:
            raw_message = pubsub.get_message(timeout=0.1)
            if ego_mirror:
                ego_mirror.cleanup_if_stale()
            if not raw_message or raw_message["type"] != "message":
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
                    if valid_ego(parsed.get("ego")):
                        sock.sendto(json.dumps(parsed).encode("utf-8"), unity_addr)
                        if ego_mirror:
                            ego_mirror.update(parsed.get("ego"))

            except Exception as e:
                print(f"Error: {e}")
    finally:
        if ego_mirror:
            ego_mirror.destroy()
        if ego_listener:
            ego_listener.close()

if __name__ == "__main__":
    main()
