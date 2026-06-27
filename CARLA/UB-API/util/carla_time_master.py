#!/usr/bin/env python3
import os
import time

import carla


def env_float(name, default):
    value = os.environ.get(name, "")
    if not value:
        return default
    return float(value)


def env_int(name, default):
    value = os.environ.get(name, "")
    if not value:
        return default
    return int(value)


def main():
    host = os.environ.get("UB_CARLA_HOST", "127.0.0.1")
    port = env_int("UB_CARLA_PORT", 2000)
    step = env_float("UB_CARLA_STEP_LENGTH", 0.05)
    timeout = env_float("UB_CARLA_TIMEOUT", 10.0)
    reset_on_exit = os.environ.get("UB_CARLA_RESET_SYNC_ON_EXIT", "0") == "1"

    client = carla.Client(host, port)
    client.set_timeout(timeout)
    world = client.get_world()

    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = step
    world.apply_settings(settings)

    print(
        "CARLA time master running "
        f"host={host} port={port} fixed_delta_seconds={step}",
        flush=True,
    )
    try:
        while True:
            start = time.time()
            frame = world.tick()
            elapsed = time.time() - start
            print(f"Ticked CARLA frame={frame}", flush=True)
            if elapsed < step:
                time.sleep(step - elapsed)
    finally:
        if reset_on_exit:
            settings = world.get_settings()
            settings.synchronous_mode = False
            settings.fixed_delta_seconds = None
            world.apply_settings(settings)


if __name__ == "__main__":
    main()
