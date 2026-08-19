"""Contract tests for the station-owned local CARLA clock."""

from __future__ import annotations

import copy
import unittest

from station.main import FIXED_DELTA_SECONDS, LocalStationClock


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

    def get_settings(self):
        return copy.deepcopy(self.settings)

    def apply_settings(self, settings):
        self.settings = copy.deepcopy(settings)
        self.applied_settings.append(copy.deepcopy(settings))

    def tick(self):
        if self.fail_tick:
            raise RuntimeError("CARLA tick failed")
        self.frames += 1
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

    def test_rejects_invalid_configuration_and_tick_before_start(self):
        with self.assertRaisesRegex(ValueError, "fixed_delta_seconds"):
            LocalStationClock(self.world, fixed_delta_seconds=0)
        with self.assertRaisesRegex(RuntimeError, "has not been started"):
            self.runner.tick()
        with self.assertRaisesRegex(ValueError, "duration_s"):
            self.runner.run(0)


if __name__ == "__main__":
    unittest.main()
