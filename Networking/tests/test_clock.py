"""Contract tests for the RTT-aware master-frame clock estimator."""

from __future__ import annotations

import math
import unittest

from dtnet.clock import ClockEstimator, EWMA_ALPHA, FRAME_RATE_HZ


class ClockEstimatorTests(unittest.TestCase):
    def test_cold_start_applies_half_rtt_frame_correction(self) -> None:
        estimator = ClockEstimator()

        estimator.on_packet(local_recv_time=10.0, master_frame_seq=600, rtt=0.1)

        self.assertAlmostEqual(estimator.estimated_master_time(10.0), 603.0)
        self.assertAlmostEqual(estimator.estimated_master_time(10.5), 633.0)

    def test_ewma_smooths_observations_and_projects_from_local_time(self) -> None:
        estimator = ClockEstimator()
        estimator.on_packet(local_recv_time=1.0, master_frame_seq=60, rtt=0.0)
        estimator.on_packet(local_recv_time=2.0, master_frame_seq=180, rtt=0.0)

        expected_offset = EWMA_ALPHA * 60.0
        self.assertAlmostEqual(estimator.estimated_master_time(2.0), 120.0 + expected_offset)
        self.assertAlmostEqual(estimator.estimated_master_time(2.25), 135.0 + expected_offset)

    def test_metro_jitter_converges_and_stays_within_two_frames(self) -> None:
        estimator = ClockEstimator()
        jitter_s = (-0.010, 0.006, -0.004, 0.010, -0.008, 0.002)
        errors = []

        for frame_seq in range(0, 60 * 10):
            jitter = jitter_s[frame_seq % len(jitter_s)]
            local_recv_time = frame_seq / FRAME_RATE_HZ + 0.040 + jitter
            estimator.on_packet(local_recv_time, frame_seq, rtt=0.080)
            if frame_seq >= 60 * 5:
                expected_filtered_frame = frame_seq + 0.040 * FRAME_RATE_HZ
                errors.append(
                    abs(estimator.estimated_master_time(local_recv_time) - expected_filtered_frame)
                )

        self.assertLess(max(errors), 2.0)

    def test_duplicate_and_older_sequences_do_not_change_the_estimate(self) -> None:
        estimator = ClockEstimator()
        estimator.on_packet(local_recv_time=1.0, master_frame_seq=60, rtt=0.0)
        baseline = estimator.estimated_master_time(1.5)

        estimator.on_packet(local_recv_time=1.2, master_frame_seq=60, rtt=5.0)
        estimator.on_packet(local_recv_time=1.3, master_frame_seq=59, rtt=5.0)

        self.assertEqual(estimator.estimated_master_time(1.5), baseline)

    def test_uint32_sequence_wrap_is_newer(self) -> None:
        estimator = ClockEstimator()
        estimator.on_packet(local_recv_time=1.0, master_frame_seq=0xFFFFFFFF, rtt=0.0)
        before = estimator.estimated_master_time(1.0)
        later = 1.0 + 1.0 / FRAME_RATE_HZ
        estimator.on_packet(local_recv_time=later, master_frame_seq=0, rtt=0.0)
        self.assertAlmostEqual(estimator.estimated_master_time(later) - before, 1.0)

    def test_large_sequence_jump_uses_normal_ewma_update_not_skip_ahead(self) -> None:
        estimator = ClockEstimator()
        estimator.on_packet(local_recv_time=1.0, master_frame_seq=60, rtt=0.0)
        estimator.on_packet(local_recv_time=2.0, master_frame_seq=600, rtt=0.0)

        # The observed offset is 480 frames, but DT-9 must not perform the
        # old LAN heuristic and jump directly to frame 600.
        self.assertAlmostEqual(estimator.estimated_master_time(2.0), 168.0)
        self.assertLess(estimator.estimated_master_time(2.0), 600.0)

    def test_rejects_invalid_inputs_and_uninitialized_queries(self) -> None:
        estimator = ClockEstimator()
        with self.assertRaisesRegex(RuntimeError, "has not received a packet"):
            estimator.estimated_master_time(0.0)

        invalid_packets = [
            (math.nan, 0, 0.0, "local_recv_time"),
            (0.0, -1, 0.0, "master_frame_seq"),
            (0.0, 2**32, 0.0, "master_frame_seq"),
            (0.0, 1.5, 0.0, "master_frame_seq"),
            (0.0, True, 0.0, "master_frame_seq"),
            (0.0, 0, -0.1, "rtt"),
            (0.0, 0, math.inf, "rtt"),
            (0.0, 0, True, "rtt"),
        ]
        for local_recv_time, frame_seq, rtt, message in invalid_packets:
            with self.subTest(packet=(local_recv_time, frame_seq, rtt)):
                with self.assertRaisesRegex(ValueError, message):
                    estimator.on_packet(local_recv_time, frame_seq, rtt)

        estimator.on_packet(local_recv_time=0.0, master_frame_seq=0, rtt=0.0)
        for local_time in (math.nan, math.inf, True):
            with self.subTest(local_time=local_time):
                with self.assertRaisesRegex(ValueError, "local_time"):
                    estimator.estimated_master_time(local_time)


if __name__ == "__main__":
    unittest.main()
