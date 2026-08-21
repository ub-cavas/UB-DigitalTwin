"""Contract tests for the authoritative CARLA world master."""

from __future__ import annotations

import copy
import unittest
from unittest import mock

from dtnet import wire
from server import master as master_module
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
    def __init__(
        self,
        clock,
        *,
        settings=None,
        tick_duration=0.0,
        fail_tick=False,
        interrupt_tick=False,
    ):
        self.clock = clock
        self.settings = settings or FakeSettings()
        self.tick_duration = tick_duration
        self.fail_tick = fail_tick
        self.interrupt_tick = interrupt_tick
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
        if self.interrupt_tick:
            raise KeyboardInterrupt
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


class FakeLifecycle:
    def __init__(self, *, fail_start=False, fail_close=False):
        self.fail_start = fail_start
        self.fail_close = fail_close
        self.calls = []

    def start(self):
        self.calls.append("start")
        if self.fail_start:
            raise RuntimeError("traffic startup failed")

    def close(self):
        self.calls.append("close")
        if self.fail_close:
            raise RuntimeError("traffic cleanup failed")


class FakeRelay:
    def __init__(self, *, fail_send=False):
        self.fail_send = fail_send
        self.snapshots = []
        self.close_calls = 0

    def send_snapshot(self, frame_seq, actor_states):
        self.snapshots.append((frame_seq, actor_states))
        if self.fail_send:
            raise OSError("station link unavailable")

    def close(self):
        self.close_calls += 1


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

    def test_tick_relays_the_single_cached_snapshot_and_closes_the_relay(self):
        relay = FakeRelay()
        master = Master(
            self.world,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
            snapshot_relay=relay,
        )
        master.start()

        self.assertEqual(master.tick(), 0)

        self.assertEqual(self.world.snapshot_reads, 1)
        self.assertEqual(len(relay.snapshots), 1)
        frame_seq, states = relay.snapshots[0]
        self.assertEqual(frame_seq, 0)
        self.assertIs(states, master._latest_states)
        self.assertEqual(states[0]["actor_id"], 17)
        master.snapshot()
        self.assertEqual(self.world.snapshot_reads, 1)

        master.close()

        self.assertEqual(relay.close_calls, 1)

    def test_relay_udp_error_is_logged_and_later_ticks_continue(self):
        relay = FakeRelay(fail_send=True)
        master = Master(
            self.world,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
            snapshot_relay=relay,
        )
        master.start()

        with self.assertLogs("server.master", "WARNING"):
            self.assertEqual(master.tick(), 0)
        relay.fail_send = False
        self.assertEqual(master.tick(), 1)

        self.assertEqual(self.world.tick_count, 2)
        self.assertEqual([frame_seq for frame_seq, _ in relay.snapshots], [0, 1])
        master.close()

    def test_failed_tick_does_not_relay_a_snapshot(self):
        relay = FakeRelay()
        master = Master(
            self.world,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
            snapshot_relay=relay,
        )
        self.world.fail_tick = True
        master.start()

        with self.assertRaisesRegex(RuntimeError, "CARLA tick failed"):
            master.tick()

        self.assertEqual(relay.snapshots, [])
        self.assertEqual(relay.close_calls, 1)

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

    def test_background_traffic_lifecycle_runs_inside_world_ownership(self):
        lifecycle = FakeLifecycle()
        master = Master(
            self.world,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
            background_traffic=lifecycle,
        )

        master.start()
        self.assertTrue(self.world.settings.synchronous_mode)
        self.assertEqual(lifecycle.calls, ["start"])
        master.close()

        self.assertEqual(lifecycle.calls, ["start", "close"])
        self.assertFalse(self.world.settings.synchronous_mode)

    def test_background_traffic_start_failure_restores_world(self):
        original = self.world.get_settings()
        lifecycle = FakeLifecycle(fail_start=True)
        master = Master(
            self.world,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
            background_traffic=lifecycle,
        )

        with self.assertRaisesRegex(RuntimeError, "traffic startup failed"):
            master.start()

        self.assertEqual(lifecycle.calls, ["start", "close"])
        self.assertEqual(vars(self.world.settings), vars(original))

    def test_background_traffic_cleanup_failure_still_restores_world(self):
        original = self.world.get_settings()
        lifecycle = FakeLifecycle(fail_close=True)
        master = Master(
            self.world,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
            background_traffic=lifecycle,
        )
        master.start()

        with self.assertRaisesRegex(RuntimeError, "traffic cleanup failed"):
            master.close()

        self.assertEqual(vars(self.world.settings), vars(original))

    def test_run_counts_bounded_ticks_and_restores_previous_settings(self):
        original = self.world.get_settings()

        frames = self.master.run(FIXED_DELTA_SECONDS * 2)

        self.assertEqual(frames, 2)
        self.assertEqual(self.world.tick_count, 2)
        self.assertEqual(vars(self.world.settings), vars(original))
        self.assertEqual(len(self.world.applied_settings), 2)

    def test_run_restores_previous_settings_after_interrupt(self):
        original = self.world.get_settings()
        self.world.interrupt_tick = True

        with self.assertRaises(KeyboardInterrupt):
            self.master.run()

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


class MasterEntrypointTests(unittest.TestCase):
    def test_main_connects_with_cli_values_and_reports_completed_frames(self):
        world = object()
        client = mock.Mock()
        client.get_world.return_value = world
        carla = mock.Mock(Client=mock.Mock(return_value=client))
        master = mock.Mock()
        master.run.return_value = 180
        relay = mock.Mock()

        with (
            mock.patch.object(master_module.importlib, "import_module", return_value=carla) as load_carla,
            mock.patch.object(master_module, "Master", return_value=master) as master_class,
            mock.patch.object(master_module, "Relay", return_value=relay) as relay_class,
        ):
            self.assertEqual(
                master_module.main(
                    ["--host", "carla.example", "--port", "2100", "--timeout", "3", "--duration", "3"]
                ),
                0,
            )

        self.assertIn(mock.call("carla"), load_carla.call_args_list)
        client.set_timeout.assert_called_once_with(3.0)
        master_class.assert_called_once()
        self.assertIs(master_class.call_args.args[0], world)
        background_traffic = master_class.call_args.kwargs["background_traffic"]
        self.assertIs(background_traffic._client, client)
        self.assertIs(background_traffic._world, world)
        self.assertEqual(background_traffic._config.vehicle_count, 50)
        self.assertEqual(background_traffic._config.seed, 27)
        self.assertEqual(background_traffic._config.port, 8000)
        relay_class.assert_called_once_with()
        relay.register.assert_called_once_with("station-1", ("127.0.0.1", 5005))
        self.assertIs(master_class.call_args.kwargs["snapshot_relay"], relay)
        master.run.assert_called_once_with(3.0)

    def test_main_configures_the_static_relay_participant_from_cli(self):
        world = object()
        client = mock.Mock()
        client.get_world.return_value = world
        carla = mock.Mock(Client=mock.Mock(return_value=client))
        master = mock.Mock()
        relay = mock.Mock()

        with (
            mock.patch.object(master_module.importlib, "import_module", return_value=carla),
            mock.patch.object(master_module, "Master", return_value=master),
            mock.patch.object(master_module, "Relay", return_value=relay),
        ):
            self.assertEqual(
                master_module.main(
                    [
                        "--participant-id", "wheel-bay",
                        "--participant-host", "10.0.0.24",
                        "--participant-port", "6001",
                    ]
                ),
                0,
            )

        relay.register.assert_called_once_with("wheel-bay", ("10.0.0.24", 6001))

    def test_main_treats_keyboard_interrupt_as_clean_shutdown(self):
        client = mock.Mock()
        carla = mock.Mock(Client=mock.Mock(return_value=client))
        master = mock.Mock()
        master.run.side_effect = KeyboardInterrupt
        relay = mock.Mock()

        with (
            mock.patch.object(master_module.importlib, "import_module", return_value=carla),
            mock.patch.object(master_module, "Master", return_value=master),
            mock.patch.object(master_module, "Relay", return_value=relay),
        ):
            self.assertEqual(master_module.main([]), 0)


if __name__ == "__main__":
    unittest.main()
