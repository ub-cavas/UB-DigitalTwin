"""Contract tests for the station-owned local CARLA clock."""

from __future__ import annotations

import copy
import unittest
from unittest import mock

import station.main as station_main
from station.main import FIXED_DELTA_SECONDS, LocalStationClock, _vehicle_control, spawn_station_ego


class FakeSettings:
    def __init__(
        self,
        *,
        synchronous_mode=False,
        fixed_delta_seconds=None,
        substepping=False,
        max_substep_delta_time=0.0,
        max_substeps=1,
    ):
        self.synchronous_mode = synchronous_mode
        self.fixed_delta_seconds = fixed_delta_seconds
        self.substepping = substepping
        self.max_substep_delta_time = max_substep_delta_time
        self.max_substeps = max_substeps


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.sleeps.append(duration)
        self.now += duration


class FakeWorld:
    def __init__(self, clock, *, settings=None, tick_duration=0.0, fail_tick=False):
        self.clock = clock
        self.settings = settings or FakeSettings()
        self.tick_duration = tick_duration
        self.fail_tick = fail_tick
        self.applied_settings = []
        self.frames = 0
        self.tick_events = []

    def get_settings(self):
        return copy.deepcopy(self.settings)

    def apply_settings(self, settings):
        self.settings = copy.deepcopy(settings)
        self.applied_settings.append(copy.deepcopy(settings))

    def tick(self):
        if self.fail_tick:
            raise RuntimeError("CARLA tick failed")
        self.frames += 1
        self.tick_events.append("tick")
        self.clock.now += self.tick_duration
        return self.frames


class LocalStationClockTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.world = FakeWorld(self.clock)
        self.runner = LocalStationClock(
            self.world, monotonic=self.clock.monotonic, sleep=self.clock.sleep
        )

    def test_start_configures_60_hz_sync_with_valid_substepping_and_close_restores(self):
        original = self.world.get_settings()

        self.runner.start()

        configured = self.world.settings
        self.assertTrue(configured.synchronous_mode)
        self.assertEqual(configured.fixed_delta_seconds, FIXED_DELTA_SECONDS)
        self.assertTrue(configured.substepping)
        self.assertGreaterEqual(
            configured.max_substep_delta_time * configured.max_substeps,
            FIXED_DELTA_SECONDS,
        )

        self.runner.close()
        self.assertEqual(vars(self.world.settings), vars(original))
        self.runner.close()
        self.assertEqual(len(self.world.applied_settings), 2)

    def test_start_refuses_an_existing_synchronous_time_master(self):
        self.world.settings.synchronous_mode = True

        with self.assertRaisesRegex(RuntimeError, "already has a synchronous"):
            self.runner.start()

        self.assertEqual(self.world.applied_settings, [])

    def test_tick_is_paced_by_monotonic_deadlines_without_waiting_for_network(self):
        self.runner.start()

        self.assertEqual(self.runner.tick(), 1)
        self.assertEqual(self.runner.tick(), 2)

        self.assertEqual(self.world.frames, 2)
        self.assertEqual(self.clock.sleeps, [FIXED_DELTA_SECONDS, FIXED_DELTA_SECONDS])

    def test_normal_tick_work_does_not_accumulate_into_the_next_deadline(self):
        self.world.tick_duration = 0.001
        self.runner.start()

        self.runner.tick()
        self.runner.tick()

        self.assertEqual(self.world.frames, 2)
        self.assertAlmostEqual(self.clock.sleeps[0], FIXED_DELTA_SECONDS)
        self.assertAlmostEqual(self.clock.sleeps[1], FIXED_DELTA_SECONDS - 0.001)

    def test_late_tick_rebases_deadline_instead_of_bursting_catch_up_frames(self):
        self.world.tick_duration = 0.05
        self.runner.start()

        self.runner.tick()
        self.runner.tick()

        self.assertEqual(self.world.frames, 2)
        self.assertEqual(len(self.clock.sleeps), 2)
        for duration in self.clock.sleeps:
            self.assertAlmostEqual(duration, FIXED_DELTA_SECONDS)

    def test_run_restores_settings_when_a_tick_raises(self):
        original = self.world.get_settings()
        self.world.fail_tick = True

        with self.assertRaisesRegex(RuntimeError, "CARLA tick failed"):
            self.runner.run(1.0)

        self.assertEqual(vars(self.world.settings), vars(original))

    def test_before_tick_runs_immediately_before_each_world_tick(self):
        callback_times = []
        frames = self.runner.run(
            0.01,
            before_tick=lambda: (
                callback_times.append(self.clock.now),
                self.world.tick_events.append("control"),
            ),
            after_tick=lambda: self.world.tick_events.append("render"),
        )

        self.assertEqual(frames, 1)
        self.assertEqual(callback_times, [FIXED_DELTA_SECONDS])
        self.assertEqual(self.world.tick_events[:3], ["control", "tick", "render"])

    def test_rejects_invalid_configuration_and_tick_before_start(self):
        with self.assertRaisesRegex(ValueError, "fixed_delta_seconds"):
            LocalStationClock(self.world, fixed_delta_seconds=0)
        with self.assertRaisesRegex(RuntimeError, "has not been started"):
            self.runner.tick()
        with self.assertRaisesRegex(ValueError, "duration_s"):
            self.runner.run(0)
        with self.assertRaisesRegex(TypeError, "after_tick"):
            self.runner.run(1, after_tick=object())


class FakeBlueprint:
    def __init__(self):
        self.attributes = {}

    def has_attribute(self, name):
        return name == "role_name"

    def set_attribute(self, name, value):
        self.attributes[name] = value


class FakeActor:
    def __init__(self):
        self.id = 1
        self.physics_enabled = None
        self.destroyed = False
        self.controls = []
        self.transform = type(
            "Transform",
            (),
            {
                "location": type("Location", (), {"x": 100.0, "y": 200.0, "z": 1.0})(),
                "rotation": type("Rotation", (), {"yaw": 0.0})(),
            },
        )()

    def set_simulate_physics(self, enabled):
        self.physics_enabled = enabled

    def destroy(self):
        self.destroyed = True

    def apply_control(self, control):
        self.controls.append(control)

    def get_transform(self):
        return self.transform


class EgoWorld:
    def __init__(self):
        self.blueprint = FakeBlueprint()
        self.spawn_points = ["occupied", "available"]
        self.spawn_attempts = []
        self.spawned_actors = []

    def get_blueprint_library(self):
        return type("Library", (), {"find": lambda library_self, name: self.blueprint})()

    def get_map(self):
        return type("Map", (), {"get_spawn_points": lambda map_self: self.spawn_points})()

    def try_spawn_actor(self, blueprint, transform):
        self.spawn_attempts.append(transform)
        if transform == "occupied":
            return None
        actor = FakeActor()
        self.spawned_actors.append(actor)
        return actor

    def get_snapshot(self):
        return type("Snapshot", (), {"frame": 1, "__iter__": lambda snapshot: iter(self.spawned_actors)})()


class VehicleControl:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeCarla:
    VehicleControl = VehicleControl


class FakeInput:
    def __init__(self):
        self.closed = False

    @property
    def quit_requested(self):
        return False

    def start(self):
        pass

    def latest_control(self):
        return {
            "throttle": 0.4,
            "brake": 0.0,
            "steer": 0.0,
            "gear": 1,
            "hand_brake": False,
        }

    def handle_pygame_input(self, events, keys, pygame):
        self.handled_input = (events, keys, pygame)

    def close(self):
        self.closed = True


class StubClock:
    instance = None

    def __init__(self, world):
        self.world = world
        self.run_args = None
        type(self).instance = self

    def run(self, duration_s, *, before_tick, after_tick, should_stop):
        self.run_args = (duration_s, should_stop())
        before_tick()
        after_tick()
        return 1


class FakeCamera:
    instance = None

    def __init__(self, world, ego, *, carla_module, telemetry_provider, impairment_provider):
        self.world = world
        self.ego = ego
        self.carla_module = carla_module
        self.telemetry_provider = telemetry_provider
        self.impairment_provider = impairment_provider
        self.closed = False
        self.rendered = False
        self.pygame = object()
        type(self).instance = self

    @property
    def quit_requested(self):
        return False

    def start(self):
        pass

    def pump_events(self):
        return [], object()

    def render(self):
        self.rendered = True

    def close(self):
        self.closed = True


class FakeFeed:
    instance = None

    def __init__(self, config, metrics):
        self.config = config
        self.metrics = metrics
        self.started = False
        self.closed = False
        type(self).instance = self

    def start(self):
        self.started = True

    def render_time(self):
        return 123.0

    def close(self):
        self.closed = True


class FakePuppets:
    instance = None

    def __init__(self, world, feed, *, carla_module):
        self.world = world
        self.feed = feed
        self.carla_module = carla_module
        self.updated_at = []
        self.closed = False
        type(self).instance = self

    @property
    def buffer_depth(self):
        return 2

    def update(self, render_time):
        self.updated_at.append(render_time)

    def close(self):
        self.closed = True


class StationEgoTests(unittest.TestCase):
    def test_spawn_falls_back_and_enables_physics(self):
        world = EgoWorld()

        ego = spawn_station_ego(
            world,
            blueprint_id="vehicle.lincoln.mkz_2020",
            role_name="dt_station_ego",
            spawn_index=0,
        )

        self.assertEqual(world.spawn_attempts, ["occupied", "available"])
        self.assertEqual(world.blueprint.attributes["role_name"], "dt_station_ego")
        self.assertTrue(ego.physics_enabled)

    def test_vehicle_control_clamps_fields_and_sets_reverse_from_gear(self):
        control = _vehicle_control(
            FakeCarla,
            {"throttle": 2.0, "brake": -1.0, "steer": -2.0, "gear": -1, "hand_brake": True},
        )

        self.assertEqual(control.throttle, 1.0)
        self.assertEqual(control.brake, 0.0)
        self.assertEqual(control.steer, -1.0)
        self.assertEqual(control.gear, -1)
        self.assertTrue(control.reverse)
        self.assertTrue(control.hand_brake)

    def test_main_applies_control_then_destroys_only_the_station_ego(self):
        world = EgoWorld()
        input_source = FakeInput()
        client = type(
            "Client",
            (),
            {
                "set_timeout": lambda client_self, timeout: None,
                "get_world": lambda client_self: world,
            },
        )()
        carla = type(
            "Carla",
            (),
            {"Client": lambda host, port: client, "VehicleControl": VehicleControl},
        )

        with (
            mock.patch.object(station_main.importlib, "import_module", return_value=carla),
            mock.patch.object(station_main, "WheelInput", return_value=input_source),
            mock.patch.object(station_main, "EgoCamera", FakeCamera),
            mock.patch.object(station_main, "RelayPuppetFeed", FakeFeed),
            mock.patch.object(station_main, "PuppetManager", FakePuppets),
            mock.patch.object(station_main, "LocalStationClock", StubClock),
            mock.patch.object(station_main, "StationUplink"),
        ):
            self.assertEqual(station_main.main(["--duration", "0.1"]), 0)

        ego = world.spawned_actors[0]
        self.assertTrue(input_source.closed)
        self.assertTrue(FakeCamera.instance.closed)
        self.assertTrue(FakeCamera.instance.rendered)
        self.assertEqual(
            FakeCamera.instance.telemetry_provider(),
            {
                "rtt_ms": None,
                "jitter_ms": None,
                "loss_pct": None,
                "loss_total_pct": None,
                "buffer_depth": 2,
            },
        )
        self.assertEqual(input_source.handled_input[0], [])
        self.assertTrue(FakeFeed.instance.started)
        self.assertTrue(FakeFeed.instance.closed)
        self.assertEqual(FakePuppets.instance.updated_at, [123.0])
        self.assertTrue(FakePuppets.instance.closed)
        self.assertIsNone(FakeCamera.instance.impairment_provider)
        self.assertEqual(StubClock.instance.run_args, (0.1, False))
        self.assertTrue(ego.physics_enabled)
        self.assertTrue(ego.destroyed)
        self.assertEqual(ego.controls[0].throttle, 0.4)


if __name__ == "__main__":
    unittest.main()
