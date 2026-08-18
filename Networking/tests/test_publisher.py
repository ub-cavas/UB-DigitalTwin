"""Tests for the CARLA-free synthetic state publisher."""

from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from dtnet import wire
from harness.publisher import (
    SyntheticPublisher,
    constant_velocity_trajectory,
    hard_brake_trajectory,
    lane_change_trajectory,
)


class TrajectoryTests(unittest.TestCase):
    def test_trajectories_produce_encodable_v1_states(self) -> None:
        for trajectory in (
            constant_velocity_trajectory,
            hard_brake_trajectory,
            lane_change_trajectory,
        ):
            with self.subTest(trajectory=trajectory.__name__):
                state = trajectory(1.0)
                self.assertEqual(wire.unpack(wire.pack(state))["actor_id"], state["actor_id"])

    def test_constant_velocity_is_analytic(self) -> None:
        state = constant_velocity_trajectory(2.0)
        self.assertEqual(state["pos_x"], 30.0)
        self.assertEqual(state["vel_x"], 15.0)
        self.assertEqual(state["vel_y"], 0.0)

    def test_hard_brake_stops_without_reversing(self) -> None:
        braking = hard_brake_trajectory(1.0)
        stopped = hard_brake_trajectory(10.0)
        self.assertEqual(braking["vel_x"], 7.0)
        self.assertEqual(braking["light_state"], wire.LIGHT_BRAKE)
        self.assertEqual(stopped["vel_x"], 0.0)
        self.assertEqual(stopped["pos_x"], 14.0625)
        self.assertEqual(stopped["light_state"], 0)

    def test_lane_change_has_continuous_endpoints(self) -> None:
        start = lane_change_trajectory(0.0)
        finish = lane_change_trajectory(3.0)
        self.assertEqual(start["pos_y"], 0.0)
        self.assertEqual(start["vel_y"], 0.0)
        self.assertEqual(finish["pos_y"], 3.5)
        self.assertEqual(finish["vel_y"], 0.0)
        self.assertTrue(math.isclose(finish["rot_y"], 0.0, abs_tol=1e-12))


class SyntheticPublisherTests(unittest.TestCase):
    def test_run_sends_monotonic_sequences_at_configured_cadence(self) -> None:
        class FakeClock:
            now = 0.0

            def monotonic(self):
                return self.now

            def sleep(self, duration):
                self.now += duration

        clock = FakeClock()
        packets = []

        def receive(packet):
            packets.append(wire.unpack(packet))
            if len(packets) == 3:
                raise StopIteration

        publisher = SyntheticPublisher(constant_velocity_trajectory, hz=60)
        with patch("harness.publisher.time.monotonic", clock.monotonic), patch(
            "harness.publisher.time.sleep", clock.sleep
        ):
            with self.assertRaises(StopIteration):
                publisher.run(receive)

        self.assertEqual([packet["master_frame_seq"] for packet in packets], [0, 1, 2])
        self.assertEqual([packet["pos_x"] for packet in packets], [0.0, 0.25, 0.5])

    def test_constructor_rejects_invalid_configuration(self) -> None:
        with self.assertRaises(TypeError):
            SyntheticPublisher(None)
        with self.assertRaises(ValueError):
            SyntheticPublisher(constant_velocity_trajectory, hz=0)
        with self.assertRaises(ValueError):
            SyntheticPublisher(constant_velocity_trajectory, hz=True)


if __name__ == "__main__":
    unittest.main()
