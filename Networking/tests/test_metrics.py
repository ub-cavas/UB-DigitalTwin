"""Deterministic contract tests for the station telemetry accumulator."""

from __future__ import annotations

import unittest

from dtnet.metrics import LinkMetrics


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class LinkMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.metrics = LinkMetrics(monotonic=self.clock.monotonic)

    def test_cold_snapshot_uses_unknown_values(self) -> None:
        self.assertEqual(
            self.metrics.snapshot(),
            {
                "rtt_ms": None,
                "jitter_ms": None,
                "loss_pct": None,
                "loss_total_pct": None,
                "buffer_depth": None,
            },
        )

    def test_records_rtt_rfc_jitter_and_sequence_gap_loss(self) -> None:
        self.clock.now = 0.1
        self.metrics.on_packet(0.0, 0.1, 10)
        self.clock.now = 1.14
        self.metrics.on_packet(1.0, 1.14, 12)

        snapshot = self.metrics.snapshot()
        self.assertAlmostEqual(snapshot["rtt_ms"], 140.0)
        self.assertAlmostEqual(snapshot["jitter_ms"], 2.5)
        self.assertAlmostEqual(snapshot["loss_pct"], 100.0 / 3.0)
        self.assertAlmostEqual(snapshot["loss_total_pct"], 100.0 / 3.0)

    def test_duplicate_and_reordered_packets_do_not_change_metrics(self) -> None:
        self.clock.now = 0.1
        self.metrics.on_packet(0.0, 0.1, 5)
        self.clock.now = 0.25
        self.metrics.on_packet(0.2, 0.25, 6)
        before = self.metrics.snapshot()

        self.clock.now = 0.4
        self.metrics.on_packet(0.0, 0.4, 6)
        self.metrics.on_packet(0.0, 0.4, 4)

        self.assertEqual(self.metrics.snapshot(), before)

    def test_recent_loss_expires_but_cumulative_loss_remains(self) -> None:
        self.clock.now = 0.1
        self.metrics.on_packet(0.0, 0.1, 0)
        self.clock.now = 0.2
        self.metrics.on_packet(0.0, 0.2, 2)
        self.assertAlmostEqual(self.metrics.snapshot()["loss_pct"], 100.0 / 3.0)

        self.clock.now = 5.21
        snapshot = self.metrics.snapshot()
        self.assertIsNone(snapshot["loss_pct"])
        self.assertAlmostEqual(snapshot["loss_total_pct"], 100.0 / 3.0)

    def test_buffer_depth_accepts_only_non_negative_integer_or_none(self) -> None:
        self.metrics.set_buffer_depth(2)
        self.assertEqual(self.metrics.snapshot()["buffer_depth"], 2)
        self.metrics.set_buffer_depth(None)
        self.assertIsNone(self.metrics.snapshot()["buffer_depth"])

        for invalid in (-1, 1.5, True, "2"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "buffer depth"):
                    self.metrics.set_buffer_depth(invalid)

    def test_rejects_invalid_probe_observations(self) -> None:
        with self.assertRaisesRegex(ValueError, "recv_time"):
            self.metrics.on_packet(1.0, 0.0, 0)
        with self.assertRaisesRegex(ValueError, "seq"):
            self.metrics.on_packet(0.0, 1.0, -1)
        with self.assertRaisesRegex(ValueError, "send_time"):
            self.metrics.on_packet(float("nan"), 1.0, 0)


if __name__ == "__main__":
    unittest.main()
