#!/usr/bin/env python3
"""Generate Autoware raw vehicle converter maps for CARLA's UB Lincoln ego."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import statistics
import time

import carla


DEFAULT_SPEEDS = [0.0, 1.39, 2.78, 4.17, 5.56, 6.94, 8.33, 9.72, 11.11, 12.5, 13.89]
DEFAULT_THROTTLES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
DEFAULT_BRAKES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
DEFAULT_STEERS = [-1.0, -0.8, -0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[1]
    / "autoware_carla_interface"
    / "calibration_maps"
)


def vehicle_speed(vehicle: carla.Vehicle) -> float:
    velocity = vehicle.get_velocity()
    return (velocity.x**2 + velocity.y**2 + velocity.z**2) ** 0.5


def reset_vehicle(world: carla.World, vehicle: carla.Vehicle, transform: carla.Transform) -> None:
    vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, hand_brake=True))
    vehicle.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))
    vehicle.set_target_angular_velocity(carla.Vector3D(0.0, 0.0, 0.0))
    vehicle.set_transform(transform)
    for _ in range(10):
        world.tick()


def bucket_index(value: float, buckets: list[float]) -> int:
    return min(range(len(buckets)), key=lambda index: abs(buckets[index] - value))


def mean_or_zero(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def collect_accel_map(
    world: carla.World,
    vehicle: carla.Vehicle,
    transform: carla.Transform,
    speeds: list[float],
    throttles: list[float],
    settle_ticks: int,
    sample_ticks: int,
    dt: float,
) -> list[list[float]]:
    rows: list[list[float]] = []
    for throttle in throttles:
        samples = [[] for _ in speeds]
        reset_vehicle(world, vehicle, transform)
        for _ in range(settle_ticks):
            vehicle.apply_control(carla.VehicleControl(throttle=throttle, brake=0.0))
            world.tick()
        previous_speed = vehicle_speed(vehicle)
        for _ in range(sample_ticks):
            vehicle.apply_control(carla.VehicleControl(throttle=throttle, brake=0.0))
            world.tick()
            current_speed = vehicle_speed(vehicle)
            acceleration = (current_speed - previous_speed) / dt
            samples[bucket_index(current_speed, speeds)].append(acceleration)
            previous_speed = current_speed
        rows.append([throttle] + [mean_or_zero(bucket) for bucket in samples])
    return rows


def collect_brake_map(
    world: carla.World,
    vehicle: carla.Vehicle,
    transform: carla.Transform,
    speeds: list[float],
    brakes: list[float],
    settle_ticks: int,
    sample_ticks: int,
    dt: float,
) -> list[list[float]]:
    rows: list[list[float]] = []
    target_speed = max(speeds)
    for brake in brakes:
        samples = [[] for _ in speeds]
        reset_vehicle(world, vehicle, transform)
        while vehicle_speed(vehicle) < target_speed:
            vehicle.apply_control(carla.VehicleControl(throttle=0.5, brake=0.0))
            world.tick()
        for _ in range(settle_ticks):
            vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=brake))
            world.tick()
        previous_speed = vehicle_speed(vehicle)
        for _ in range(sample_ticks):
            vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=brake))
            world.tick()
            current_speed = vehicle_speed(vehicle)
            acceleration = (current_speed - previous_speed) / dt
            samples[bucket_index(current_speed, speeds)].append(acceleration)
            previous_speed = current_speed
            if current_speed < 0.1:
                break
        rows.append([brake] + [mean_or_zero(bucket) for bucket in samples])
    return rows


def collect_steer_map(
    world: carla.World,
    vehicle: carla.Vehicle,
    transform: carla.Transform,
    steers: list[float],
    settle_ticks: int,
) -> list[list[float]]:
    rows: list[list[float]] = []
    for requested in steers:
        row = [requested]
        for command in steers:
            reset_vehicle(world, vehicle, transform)
            for _ in range(settle_ticks):
                vehicle.apply_control(carla.VehicleControl(steer=command, brake=1.0))
                world.tick()
            measured = -vehicle.get_wheel_steer_angle(carla.VehicleWheelLocation.FL_Wheel)
            row.append(measured)
        rows.append(row)
    return rows


def write_map(path: Path, header_values: list[float], rows: list[list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["default"] + [format(value, ".6g") for value in header_values])
        for row in rows:
            writer.writerow([format(value, ".6g") for value in row])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--vehicle-type", default="vehicle.lincoln.mkz_2020")
    parser.add_argument("--role-name", default="ego_calibration")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixed-delta-seconds", type=float, default=0.05)
    parser.add_argument("--settle-ticks", type=int, default=20)
    parser.add_argument("--sample-ticks", type=int, default=240)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()
    original_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = args.fixed_delta_seconds
    world.apply_settings(settings)

    vehicle = None
    try:
        blueprint = world.get_blueprint_library().find(args.vehicle_type)
        blueprint.set_attribute("role_name", args.role_name)
        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            raise RuntimeError("CARLA map has no spawn points")
        transform = spawn_points[0]
        vehicle = world.try_spawn_actor(blueprint, transform)
        if vehicle is None:
            raise RuntimeError(f"Failed to spawn {args.vehicle_type} at {transform}")

        accel_rows = collect_accel_map(
            world,
            vehicle,
            transform,
            DEFAULT_SPEEDS,
            DEFAULT_THROTTLES,
            args.settle_ticks,
            args.sample_ticks,
            args.fixed_delta_seconds,
        )
        brake_rows = collect_brake_map(
            world,
            vehicle,
            transform,
            DEFAULT_SPEEDS,
            DEFAULT_BRAKES,
            args.settle_ticks,
            args.sample_ticks,
            args.fixed_delta_seconds,
        )
        steer_rows = collect_steer_map(
            world,
            vehicle,
            transform,
            DEFAULT_STEERS,
            args.settle_ticks,
        )

        write_map(args.output_dir / "ub_lincoln_accel_map.csv", DEFAULT_SPEEDS, accel_rows)
        write_map(args.output_dir / "ub_lincoln_brake_map.csv", DEFAULT_SPEEDS, brake_rows)
        write_map(args.output_dir / "ub_lincoln_steer_map.csv", DEFAULT_STEERS, steer_rows)
    finally:
        if vehicle is not None:
            vehicle.destroy()
        world.apply_settings(original_settings)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
