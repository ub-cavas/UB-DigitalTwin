"""Headless checks for the DT-10 visualizer packet pipeline."""

from __future__ import annotations

import unittest

from dtnet import wire
from harness.publisher import constant_velocity_trajectory
from harness.visualizer import NO_IMPAIRMENT, VisualizerPipeline


class VisualizerPipelineTests(unittest.TestCase):
    def test_decoded_packet_reaches_clock_and_interpolator(self) -> None:
        pipeline = VisualizerPipeline(constant_velocity_trajectory, NO_IMPAIRMENT)
        try:
            state = constant_velocity_trajectory(0.0)
            state["master_frame_seq"] = 0
            pipeline.receive_packet(wire.pack(state), recv_time=0.0)

            puppet = pipeline.puppet_pose(now=0.1)

            self.assertIsNotNone(puppet)
            self.assertGreater(puppet["pos_x"], 0.0)
            self.assertEqual(puppet["actor_id"], state["actor_id"])
        finally:
            pipeline.close()

    def test_live_profile_changes_are_reflected_by_the_pipeline(self) -> None:
        pipeline = VisualizerPipeline(constant_velocity_trajectory, NO_IMPAIRMENT)
        try:
            pipeline.set_profile((40.0, 10.0, 3.0))
            self.assertEqual(pipeline.profile, (40.0, 10.0, 3.0))
        finally:
            pipeline.close()

    def test_reset_preserves_profile_and_restarts_the_pipeline(self) -> None:
        pipeline = VisualizerPipeline(constant_velocity_trajectory, NO_IMPAIRMENT)
        try:
            pipeline.set_profile((40.0, 10.0, 3.0))
            pipeline.start()
            pipeline.reset()

            self.assertEqual(pipeline.profile, (40.0, 10.0, 3.0))
            self.assertIsNotNone(pipeline._started_at)
        finally:
            pipeline.close()


if __name__ == "__main__":
    unittest.main()
