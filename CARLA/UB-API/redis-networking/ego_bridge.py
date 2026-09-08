#!/usr/bin/env python

"""Receives ego vehicle poses from Unity over UDP and publishes them to Redis.

Counterpart of traffic_bridge.py, in the opposite direction:
Unity (EgoPublisher.cs) --UDP--> ego_bridge --Redis--> render_ego.py --> CARLA
"""

import json
import socket
import time
import uuid

import redis

REDIS_HOST = "128.205.222.211"
REDIS_PORT = 6379
REDIS_PASSWORD = "t0mIj7DXXE"
REDIS_CHANNEL = "SIMULATOR_TEST_CHANNEL"

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 12346

EGO_MESSAGE_TYPE = 3

STATUS_PRINT_INTERVAL = 5.0  # seconds between status prints


def main():
    bridge_id = str(uuid.uuid1())
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_HOST, LISTEN_PORT))

    print(f"Listening for ego data on UDP {LISTEN_HOST}:{LISTEN_PORT}")
    print(f"Publishing to Redis channel '{REDIS_CHANNEL}' as type {EGO_MESSAGE_TYPE}")

    forwarded = 0
    last_status = time.time()

    while True:
        try:
            data, addr = sock.recvfrom(65535)
            ego = json.loads(data.decode("utf-8"))

            # Minimal sanity check before forwarding
            if "id" not in ego or "location" not in ego:
                continue

            message = json.dumps({
                "ego": ego,
                "id": bridge_id,
                "type": EGO_MESSAGE_TYPE,
                "timestamp": time.time()
            })
            r.publish(REDIS_CHANNEL, message)
            forwarded += 1

            now = time.time()
            if now - last_status >= STATUS_PRINT_INTERVAL:
                print(f"Forwarded {forwarded} ego messages (last from {addr[0]}, ego id '{ego['id']}')")
                last_status = now

        except redis.exceptions.ConnectionError as e:
            print(f"Redis connection error: {e} — retrying in 1s")
            time.sleep(1.0)
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ndone.")
