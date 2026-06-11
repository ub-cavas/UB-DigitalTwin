#!/usr/bin/env python

import json
import os
import socket
import redis

CONFIG_FILE = "telemetry.conf"

DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6390
DEFAULT_REDIS_PASSWORD = "password"
DEFAULT_REDIS_CHANNEL = "carla:telemetry"

DEFAULT_UNITY_HOST = "127.0.0.1"
DEFAULT_UNITY_PORT = 12345

TRAFFIC_MESSAGE_TYPE = 2


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

    r = redis.Redis(host=redis_host, port=redis_port, password=redis_password or None)
    pubsub = r.pubsub()
    pubsub.subscribe(redis_channel)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    unity_addr = (unity_host, unity_port)

    print(f"Subscribed to Redis channel '{redis_channel}'")
    print(f"Forwarding to Unity at {unity_host}:{unity_port}")

    for raw_message in pubsub.listen():
        if raw_message["type"] != "message":
            continue
        try:
            parsed = json.loads(raw_message["data"])

            if parsed.get("type") != TRAFFIC_MESSAGE_TYPE:
                continue
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

        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
