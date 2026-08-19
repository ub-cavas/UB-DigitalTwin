"""Contract tests for the master-frame puppet interpolator."""

from __future__ import annotations

import math
import unittest

from dtnet import wire
from dtnet.interp import EXTRAPOLATION_HORIZON_FRAMES, PuppetInterpolator


def pose(*, position: float, velocity: float = 0.0, rotation: float = 0.0,
         angular_velocity: float = 0.0, light_state: int = 0,
         sequence: int = 0) -> dict:
    """Build a canonical decoded v1 pose with X-axis motion for concise tests."""

    return wire.unpack(wire.pack({
        "actor_id": 17,
        "master_frame_seq": sequence,
        "pos_x": position,
        "pos_y": 0.0,
        "pos_z": 0.0,
        "rot_r": 0.0,
        "rot_p": 0.0,
        "rot_y": rotation,
        "vel_x": velocity,
        "vel_y": 0.0,
        "vel_z": 0.0,
        "ang_x": 0.0,
        "ang_y": 0.0,
        "ang_z": angular_velocity,
        "steer_angle": 1.0,
        "light_state": light_state,
    }))


class PuppetInterpolatorTests(unittest.TestCase):
    def test_delay_is_converted_from_seconds_to_master_frames(self) -> None:
        interpolator = PuppetInterpolator(0.04)  # 2.4 frames at 60 Hz
        interpolator.on_packet(0.0, 0.0, pose(position=0.0, sequence=0))
        interpolator.on_packet(1.0, 10.0, pose(position=10.0, sequence=10))

        rendered = interpolator.pose_at(7.4)

        self.assertAlmostEqual(rendered["pos_x"], 5.0)

    def test_interpolates_continuous_fields_and_keeps_left_discrete_state(self) -> None:
        interpolator = PuppetInterpolator(0.0)
        left = pose(
            position=0.0,
            velocity=2.0,
            rotation=10.0,
            angular_velocity=4.0,
            light_state=wire.LIGHT_BRAKE,
            sequence=1,
        )
        right = pose(
            position=10.0,
            velocity=6.0,
            rotation=30.0,
            angular_velocity=8.0,
            light_state=wire.LIGHT_LEFT_BLINKER,
            sequence=2,
        )
        interpolator.on_packet(0.0, 0.0, left)
        interpolator.on_packet(1.0, 10.0, right)

        rendered = interpolator.pose_at(5.0)

        self.assertAlmostEqual(rendered["pos_x"], 5.0)
        self.assertAlmostEqual(rendered["vel_x"], 4.0)
        self.assertAlmostEqual(rendered["rot_y"], 20.0)
        self.assertAlmostEqual(rendered["ang_z"], 6.0)
        self.assertAlmostEqual(rendered["steer_angle"], 1.0)
        self.assertEqual(rendered["light_state"], wire.LIGHT_BRAKE)
        self.assertEqual(rendered["master_frame_seq"], 1)
        self.assertEqual(rendered["version"], wire.VERSION)

    def test_orders_delayed_packets_and_replaces_duplicate_master_time(self) -> None:
        interpolator = PuppetInterpolator(0.0)
        interpolator.on_packet(2.0, 10.0, pose(position=10.0, sequence=10))
        interpolator.on_packet(3.0, 0.0, pose(position=0.0, sequence=0))
        interpolator.on_packet(4.0, 10.0, pose(position=20.0, sequence=11))
        interpolator.on_packet(5.0, 20.0, pose(position=30.0, sequence=20))

        rendered = interpolator.pose_at(15.0)

        self.assertAlmostEqual(rendered["pos_x"], 25.0)

    def test_returns_earliest_pose_before_buffered_data(self) -> None:
        interpolator = PuppetInterpolator(0.0)
        earliest = pose(position=4.0, sequence=3)
        interpolator.on_packet(1.0, 3.0, earliest)
        interpolator.on_packet(2.0, 6.0, pose(position=8.0, sequence=6))

        self.assertEqual(interpolator.pose_at(1.0), earliest)

    def test_extrapolates_for_200_ms_then_holds_the_projected_pose(self) -> None:
        interpolator = PuppetInterpolator(0.0)
        interpolator.on_packet(0.0, 0.0, pose(position=0.0, velocity=6.0,
                                               rotation=0.0, angular_velocity=30.0))

        within_horizon = interpolator.pose_at(EXTRAPOLATION_HORIZON_FRAMES / 2.0)
        at_horizon = interpolator.pose_at(EXTRAPOLATION_HORIZON_FRAMES)
        after_horizon = interpolator.pose_at(EXTRAPOLATION_HORIZON_FRAMES + 100.0)

        self.assertAlmostEqual(within_horizon["pos_x"], 0.6)
        self.assertAlmostEqual(within_horizon["rot_y"], 3.0)
        self.assertAlmostEqual(at_horizon["pos_x"], 1.2)
        self.assertAlmostEqual(at_horizon["rot_y"], 6.0)
        self.assertEqual(after_horizon, at_horizon)

    def test_hard_brake_samples_never_reverse_velocity_or_position(self) -> None:
        interpolator = PuppetInterpolator(0.0)
        # Analytic hard-brake states: all velocities are non-negative and the
        # final state is stationary. Rendering each frame must retain that.
        samples = (
            (0.0, 0.0, 15.0),
            (60.0, 11.0, 7.0),
            (112.5, 14.0625, 0.0),
            (140.0, 14.0625, 0.0),
        )
        for sequence, (master_time, position, velocity) in enumerate(samples):
            interpolator.on_packet(
                float(sequence), master_time,
                pose(position=position, velocity=velocity, sequence=sequence),
            )

        rendered_positions = []
        rendered_velocities = []
        for frame in range(0, 161):
            rendered = interpolator.pose_at(float(frame))
            rendered_positions.append(rendered["pos_x"])
            rendered_velocities.append(rendered["vel_x"])

        self.assertTrue(all(value >= 0.0 for value in rendered_velocities))
        self.assertTrue(
            all(next_value >= value for value, next_value in zip(
                rendered_positions, rendered_positions[1:]
            ))
        )

    def test_rejects_invalid_inputs_and_empty_buffer_queries(self) -> None:
        with self.assertRaisesRegex(ValueError, "render_delay_s"):
            PuppetInterpolator(math.nan)
        with self.assertRaisesRegex(ValueError, "render_delay_s must be non-negative"):
            PuppetInterpolator(-0.01)

        interpolator = PuppetInterpolator(0.0)
        with self.assertRaisesRegex(RuntimeError, "has not received a packet"):
            interpolator.pose_at(0.0)
        with self.assertRaisesRegex(ValueError, "recv_time"):
            interpolator.on_packet(math.inf, 0.0, pose(position=0.0))
        with self.assertRaisesRegex(ValueError, "master_time"):
            interpolator.on_packet(0.0, math.nan, pose(position=0.0))
        with self.assertRaisesRegex(ValueError, "missing required field"):
            interpolator.on_packet(0.0, 0.0, {})
        with self.assertRaisesRegex(ValueError, "render_time"):
            interpolator.pose_at(True)


if __name__ == "__main__":
    unittest.main()
