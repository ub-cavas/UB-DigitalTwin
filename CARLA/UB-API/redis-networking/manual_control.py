#!/usr/bin/env python3

"""Keyboard-controlled CARLA vehicle client."""

import argparse
import json
import math
import os
import sys
import time

import carla
import redis

try:
    import pygame
except Exception as exc:
    pygame = None
    PYGAME_IMPORT_ERROR = exc
else:
    PYGAME_IMPORT_ERROR = None


DEFAULT_ROLE_NAME = "manual_vehicle"
DEFAULT_BLUEPRINT = "vehicle.lincoln.mkz_2020"
DEFAULT_COLOR = "0,0,255"
DEFAULT_ACTOR_REDIS_KEY = "carla:manual_control:actor"


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in ("0", "false", "no", "off")


def _env_float(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        print(f"[x] Invalid {name}={value!r}; using {default}")
        return default


def _env_int(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        print(f"[x] Invalid {name}={value!r}; using {default}")
        return default


def _env_first(names, default):
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            return value
    return default


def _env_first_int(names, default):
    for name in names:
        value = os.environ.get(name)
        if value is None:
            continue
        try:
            return int(value)
        except ValueError:
            print(f"[x] Invalid {name}={value!r}; using {default}")
            return default
    return default


def redis_client_from_env():
    password = os.environ.get("UB_REDIS_PASSWORD", "password")
    return redis.Redis(
        host=os.environ.get("UB_REDIS_HOST", "127.0.0.1"),
        port=_env_int("UB_REDIS_PORT", 6390),
        password=password or None,
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=_env_first(("UB_MANUAL_CARLA_HOST", "UB_CARLA_HOST"), "127.0.0.1"))
    parser.add_argument("--port", type=int, default=_env_first_int(("UB_MANUAL_CARLA_PORT", "UB_CARLA_PORT"), 2000))
    parser.add_argument("--role-name", default=os.environ.get("UB_MANUAL_ROLE_NAME", DEFAULT_ROLE_NAME))
    parser.add_argument("--blueprint", default=os.environ.get("UB_MANUAL_BLUEPRINT", DEFAULT_BLUEPRINT))
    parser.add_argument("--color", default=os.environ.get("UB_MANUAL_COLOR", DEFAULT_COLOR))
    parser.add_argument("--max-kmh", type=float, default=_env_float("UB_MANUAL_MAX_KMH", 60.0))
    parser.add_argument(
        "--spawn-index",
        type=int,
        default=_env_int("UB_MANUAL_SPAWN_INDEX", 0),
        help="Preferred CARLA map spawn point index.",
    )
    parser.add_argument(
        "--follow-spectator",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("UB_MANUAL_FOLLOW_SPECTATOR", False),
    )
    parser.add_argument(
        "--actor-redis-key",
        default=os.environ.get("UB_MANUAL_ACTOR_REDIS_KEY", DEFAULT_ACTOR_REDIS_KEY),
        help="Redis key used to publish the controlled CARLA actor id for visual clients.",
    )
    return parser.parse_args()


def find_vehicle_by_role(world, role_name):
    for actor in world.get_actors().filter("vehicle.*"):
        if actor.attributes.get("role_name") == role_name:
            return actor
    return None


def get_vehicle_blueprint(world, blueprint_id, role_name, color):
    blueprints = world.get_blueprint_library()
    try:
        blueprint = blueprints.find(blueprint_id)
    except RuntimeError:
        print(f"[x] CARLA blueprint {blueprint_id!r} not found; using {DEFAULT_BLUEPRINT!r}")
        blueprint = blueprints.find(DEFAULT_BLUEPRINT)

    if blueprint.has_attribute("role_name"):
        blueprint.set_attribute("role_name", role_name)
    if color and blueprint.has_attribute("color"):
        blueprint.set_attribute("color", color)
    return blueprint


def spawn_vehicle(world, blueprint, spawn_index):
    spawn_points = list(world.get_map().get_spawn_points())
    if not spawn_points:
        raise RuntimeError("Current CARLA map has no vehicle spawn points.")

    start = spawn_index % len(spawn_points)
    ordered_spawn_points = spawn_points[start:] + spawn_points[:start]
    for transform in ordered_spawn_points:
        actor = world.try_spawn_actor(blueprint, transform)
        if actor is not None:
            return actor

    raise RuntimeError("Unable to spawn the manual vehicle at any map spawn point.")


def speed_kmh(vehicle):
    velocity = vehicle.get_velocity()
    return 3.6 * math.sqrt(
        velocity.x * velocity.x + velocity.y * velocity.y + velocity.z * velocity.z
    )


class KeyboardController:
    def __init__(self, vehicle, max_kmh, follow_spectator):
        if pygame is None:
            raise RuntimeError(f"pygame is not available: {PYGAME_IMPORT_ERROR}")

        self.vehicle = vehicle
        self.max_kmh = max_kmh
        self.follow_spectator = follow_spectator
        self.reverse = False
        self.quit = False
        self._throttle = 0.0
        self._steer = 0.0
        self._last_time = time.time()

        pygame.init()
        pygame.display.set_caption("CARLA Manual Control")
        self.surface = pygame.display.set_mode((560, 120))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 16)

    def tick(self):
        now = time.time()
        dt = max(1e-3, now - self._last_time)
        self._last_time = now

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit = True
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.quit = True
                elif event.key == pygame.K_q:
                    self.reverse = not self.reverse
                elif event.key == pygame.K_f:
                    self.follow_spectator = not self.follow_spectator

        keys = pygame.key.get_pressed()
        current_speed = speed_kmh(self.vehicle)

        if keys[pygame.K_w] or keys[pygame.K_UP]:
            self._throttle = min(1.0, self._throttle + 1.25 * dt)
        else:
            self._throttle = max(0.0, self._throttle - 2.0 * dt)

        if current_speed > self.max_kmh:
            throttle = 0.0
        elif current_speed > 0.95 * self.max_kmh:
            throttle = self._throttle * 0.35
        else:
            throttle = self._throttle

        steer_target = 0.0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            steer_target = -1.0
        elif keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            steer_target = 1.0

        steer_target *= 1.0 / (1.0 + current_speed / 45.0)
        steer_delta = steer_target - self._steer
        max_steer_step = 1.8 * dt
        if steer_delta > max_steer_step:
            steer_delta = max_steer_step
        elif steer_delta < -max_steer_step:
            steer_delta = -max_steer_step
        self._steer += steer_delta
        if abs(steer_target) < 1e-3:
            self._steer *= max(0.0, 1.0 - 5.0 * dt)

        brake = 0.0
        if keys[pygame.K_SPACE]:
            brake = 1.0
            throttle = 0.0
        elif keys[pygame.K_s] or keys[pygame.K_DOWN]:
            brake = 0.65
            throttle = 0.0

        control = carla.VehicleControl(
            throttle=float(max(0.0, min(1.0, throttle))),
            steer=float(max(-1.0, min(1.0, self._steer))),
            brake=float(max(0.0, min(1.0, brake))),
            reverse=self.reverse,
        )
        self.vehicle.apply_control(control)
        self._draw(current_speed, control)
        self.clock.tick_busy_loop(60)
        return not self.quit

    def close(self):
        pygame.quit()

    def _draw(self, current_speed, control):
        self.surface.fill((25, 25, 25))
        text = (
            f"Speed {current_speed:5.1f} km/h  "
            f"Throttle {control.throttle:.2f}  "
            f"Steer {control.steer:.2f}  "
            f"Brake {control.brake:.2f}  "
            f"Reverse {control.reverse}"
        )
        hint = "Focus this window | W/Up throttle | S/Down brake | A/D steer | Space full brake"
        hint2 = f"Q reverse | F chase camera {'on' if self.follow_spectator else 'off'} | Esc quit"
        self.surface.blit(self.font.render(text, True, (235, 235, 235)), (10, 12))
        self.surface.blit(self.font.render(hint, True, (170, 170, 170)), (10, 42))
        self.surface.blit(self.font.render(hint2, True, (170, 170, 170)), (10, 72))
        self.surface.blit(self.font.render(f"Max speed {self.max_kmh:.0f} km/h", True, (170, 170, 170)), (10, 96))
        pygame.display.flip()


def update_spectator(world, vehicle):
    transform = vehicle.get_transform()
    forward = transform.rotation.get_forward_vector()
    location = transform.location + carla.Location(
        x=-8.0 * forward.x,
        y=-8.0 * forward.y,
        z=4.0,
    )
    rotation = carla.Rotation(pitch=-15.0, yaw=transform.rotation.yaw, roll=0.0)
    world.get_spectator().set_transform(carla.Transform(location, rotation))


def publish_actor_metadata(args, vehicle):
    payload = {
        "actor_id": str(vehicle.id),
        "role_name": args.role_name,
        "timestamp": time.time(),
    }
    try:
        redis_client_from_env().set(args.actor_redis_key, json.dumps(payload))
        print(f"[!] Published manual actor metadata to Redis key {args.actor_redis_key}: {payload}")
    except Exception as exc:
        print(f"[x] Could not publish manual actor metadata to Redis: {exc}")


def clear_actor_metadata(args, actor_id):
    try:
        client = redis_client_from_env()
        current = client.get(args.actor_redis_key)
        if not current:
            return
        current_payload = json.loads(current)
        if str(current_payload.get("actor_id")) == str(actor_id):
            client.delete(args.actor_redis_key)
            print(f"[!] Cleared manual actor metadata from Redis key {args.actor_redis_key}")
    except Exception as exc:
        print(f"[x] Could not clear manual actor metadata from Redis: {exc}")


def main():
    args = parse_args()
    print(f"[!] Manual control connecting to CARLA at {args.host}:{args.port}")
    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    world = client.get_world()
    print(f"[!] Manual control connected to CARLA map={world.get_map().name}")

    vehicle = find_vehicle_by_role(world, args.role_name)
    spawned_by_client = False
    if vehicle is None:
        blueprint = get_vehicle_blueprint(world, args.blueprint, args.role_name, args.color)
        vehicle = spawn_vehicle(world, blueprint, args.spawn_index)
        spawned_by_client = True
        print(f"[!] Spawned manual vehicle id={vehicle.id} role_name={args.role_name}")
    else:
        print(f"[!] Reusing manual vehicle id={vehicle.id} role_name={args.role_name}")

    vehicle.set_simulate_physics(True)
    publish_actor_metadata(args, vehicle)
    controller = None

    try:
        controller = KeyboardController(vehicle, args.max_kmh, args.follow_spectator)
        print("[!] Manual control ready.")
        while controller.tick():
            if controller.follow_spectator:
                update_spectator(world, vehicle)
    except KeyboardInterrupt:
        print("\n[!] Manual control interrupted.")
    finally:
        if controller is not None:
            controller.close()
        if spawned_by_client and vehicle.is_alive:
            actor_id = vehicle.id
            vehicle.destroy()
            print(f"[!] Destroyed manual vehicle id={actor_id}")
            clear_actor_metadata(args, actor_id)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[x] Manual control failed: {exc}", file=sys.stderr)
        raise
