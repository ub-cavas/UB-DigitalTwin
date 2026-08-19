"""Contract tests for the authoritative CARLA world master."""

from __future__ import annotations

import copy
import unittest

from dtnet import wire
from server.master import FIXED_DELTA_SECONDS, MAX_FRAME_SEQUENCE, Master


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


class Vector:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z


class Rotation:
    def __init__(self, roll, pitch, yaw):
        self.roll = roll
        self.pitch = pitch
        self.yaw = yaw


class Transform:
    def __init__(self, location, rotation):
        self.location = location
        self.rotation = rotation


class ActorSnapshot:
    def __init__(self, actor_id, *, offset=0.0):
        self.id = actor_id
        self._transform = Transform(
            Vector(1.0 + offset, 2.0 + offset, 3.0 + offset),
            Rotation(4.0 + offset, 5.0 + offset, 6.0 + offset),
        )
        self._velocity = Vector(7.0 + offset, 8.0 + offset, 9.0 + offset)
        self._angular_velocity = Vector(10.0 + offset, 11.0 + offset, 12.0 + offset)
        self.calls = []

    def get_transform(self):
        self.calls.append("transform")
        return self._transform

    def get_velocity(self):
        self.calls.append("velocity")
        return self._velocity

    def get_angular_velocity(self):
        self.calls.append("angular_velocity")
        return self._angular_velocity


class FakeWorld:
    def __init__(self, clock, *, settings=None, tick_duration=0.0, fail_tick=False):
        self.clock = clock
        self.settings = settings or FakeSettings()
        self.tick_duration = tick_duration
        self.fail_tick = fail_tick
        self.applied_settings = []
        self.tick_count = 0
        self.snapshot_reads = 0
        self.actor_snapshots = [ActorSnapshot(17)]

    def get_settings(self):
        return copy.deepcopy(self.settings)

    def apply_settings(self, settings):
        self.settings = copy.deepcopy(settings)
        self.applied_settings.append(copy.deepcopy(settings))

    def tick(self):
        if self.fail_tick:
            raise RuntimeError("CARLA tick failed")
        self.tick_count += 1
        self.clock.now += self.tick_duration
        return self.tick_count

    def get_snapshot(self):
        self.snapshot_reads += 1
        return list(self.actor_snapshots)

    def get_actors(self):
        raise AssertionError("Master must not perform live actor lookups")


class MasterTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.world = FakeWorld(self.clock)
        self.master = Master(
            self.world,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
        )

    def test_start_configures_60_hz_sync_and_close_restores_once(self):
        original = self.world.get_settings()

        self.master.start()

        configured = self.world.settings
        self.assertTrue(configured.synchronous_mode)
        self.assertEqual(configured.fixed_delta_seconds, FIXED_DELTA_SECONDS)
        self.assertTrue(configured.substepping)
        self.assertGreaterEqual(
            configured.max_substep_delta_time * configured.max_substeps,
            FIXED_DELTA_SECONDS,
        )

        self.master.close()
        self.assertEqual(vars(self.world.settings), vars(original))
        self.master.close()
        self.assertEqual(len(self.world.applied_settings), 2)

    def test_start_refuses_an_existing_synchronous_owner(self):
        self.world.settings.synchronous_mode = True

        with self.assertRaisesRegex(RuntimeError, "already has a synchronous"):
            self.master.start()

        self.assertEqual(self.world.applied_settings, [])

    def test_tick_is_paced_and_rebases_after_late_work(self):
        self.world.tick_duration = 0.05
        self.master.start()

        self.assertEqual(self.master.tick(), 0)
        self.assertEqual(self.master.tick(), 1)

        self.assertEqual(self.world.tick_count, 2)
        self.assertEqual(len(self.clock.sleeps), 2)
        for duration in self.clock.sleeps:
            self.assertAlmostEqual(duration, FIXED_DELTA_SECONDS)

    def test_tick_captures_one_snapshot_and_returns_wire_ready_states(self):
        self.world.actor_snapshots = [ActorSnapshot(17), ActorSnapshot(23, offset=10.0)]
        self.master.start()

        self.assertEqual(self.master.tick(), 0)
        states = self.master.snapshot()

        self.assertEqual(self.world.snapshot_reads, 1)
        self.assertEqual([state["actor_id"] for state in states], [17, 23])
        self.assertEqual([state["master_frame_seq"] for state in states], [0, 0])
        self.assertEqual(states[0]["pos_x"], 1.0)
        self.assertEqual(states[0]["rot_y"], 6.0)
        self.assertEqual(states[0]["vel_z"], 9.0)
        self.assertEqual(states[0]["ang_x"], 10.0)
        self.assertEqual(states[0]["steer_angle"], 0.0)
        self.assertEqual(states[0]["light_state"], 0)
        self.assertEqual(wire.unpack(wire.pack(states[0]))["actor_id"], 17)
        self.assertEqual(
            self.world.actor_snapshots[0].calls,
            ["transform", "velocity", "angular_velocity"],
        )

        states[0]["pos_x"] = -1.0
        self.assertEqual(self.master.snapshot()[0]["pos_x"], 1.0)
        self.assertEqual(self.world.snapshot_reads, 1)

    def test_snapshot_requires_a_successful_tick_and_tick_requires_start(self):
        with self.assertRaisesRegex(RuntimeError, "has not been started"):
            self.master.tick()
        with self.assertRaisesRegex(RuntimeError, "successful tick"):
            self.master.snapshot()

        self.master.start()
        with self.assertRaisesRegex(RuntimeError, "successful tick"):
            self.master.snapshot()
        self.master.close()
        with self.assertRaisesRegex(RuntimeError, "has not been started"):
            self.master.tick()

    def test_tick_failure_restores_previous_settings(self):
        original = self.world.get_settings()
        self.world.fail_tick = True
        self.master.start()

        with self.assertRaisesRegex(RuntimeError, "CARLA tick failed"):
            self.master.tick()

        self.assertEqual(vars(self.world.settings), vars(original))
        self.assertEqual(len(self.world.applied_settings), 2)

    def test_refuses_sequence_overflow_before_advancing_carla(self):
        self.master.start()
        self.master._next_sequence = MAX_FRAME_SEQUENCE + 1

        with self.assertRaisesRegex(RuntimeError, "sequence exhausted"):
            self.master.tick()

        self.assertEqual(self.world.tick_count, 0)
        self.assertEqual(self.world.snapshot_reads, 0)

    def test_rejects_invalid_configuration(self):
        with self.assertRaisesRegex(ValueError, "fixed_delta_seconds"):
            Master(self.world, fixed_delta_seconds=0)
        with self.assertRaisesRegex(TypeError, "monotonic"):
            Master(self.world, monotonic=object())
        with self.assertRaisesRegex(TypeError, "sleep"):
            Master(self.world, sleep=object())


if __name__ == "__main__":
    unittest.main()
