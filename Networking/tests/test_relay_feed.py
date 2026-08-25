"""Tests for station consumption of authoritative relay snapshots."""

from __future__ import annotations

import unittest

from dtnet import probe, wire
from dtnet.metrics import LinkMetrics
from station.relay_feed import MAX_QUEUED_PACKETS, RelayFeedConfig, RelayPuppetFeed


def state(actor_id: int, sequence: int) -> dict:
    return {
        "actor_id": actor_id,
        "master_frame_seq": sequence,
        "pos_x": 1.0,
        "pos_y": 2.0,
        "pos_z": 3.0,
        "rot_r": 4.0,
        "rot_p": 5.0,
        "rot_y": 6.0,
        "vel_x": 7.0,
        "vel_y": 8.0,
        "vel_z": 9.0,
        "ang_x": 10.0,
        "ang_y": 11.0,
        "ang_z": 12.0,
        "steer_angle": 0.0,
        "light_state": 0,
    }


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


class RelayPuppetFeedTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.metrics = LinkMetrics(monotonic=self.clock.monotonic)
        self.config = RelayFeedConfig("127.0.0.1", 5005, "127.0.0.1", 5007)
        self.feed = RelayPuppetFeed(self.config, self.metrics, monotonic=self.clock.monotonic)

    def _complete_probe(self, sequence=0, sent_at=0.0, received_at=0.1):
        self.feed._pending_probes[sequence] = sent_at
        self.clock.now = received_at
        self.assertTrue(
            self.feed.on_probe_reply(
                probe.pack(sequence), self.config.probe_server_address, received_at
            )
        )

    def test_packets_wait_for_rtt_then_drive_clock_and_puppet_contract(self):
        packet = wire.pack(state(7, 60))
        self.assertTrue(self.feed.on_packet(packet, received_at=1.0))
        self.assertEqual(tuple(self.feed.drain_packets()), ())
        self.assertIsNone(self.feed.render_time())

        self._complete_probe(sent_at=0.0, received_at=0.1)
        self.clock.now = 1.1
        self.assertIsNotNone(self.feed.render_time())
        packets = tuple(self.feed.drain_packets())

        self.assertEqual(packets, ((packet, 1.0),))
        self.assertEqual(self.metrics.snapshot()["rtt_ms"], 100.0)

    def test_rejects_malformed_and_per_actor_stale_packets_but_accepts_same_frame_for_peers(self):
        self.assertFalse(self.feed.on_packet(b"invalid", received_at=1.0))
        self.assertTrue(self.feed.on_packet(wire.pack(state(7, 5)), received_at=1.0))
        self.assertFalse(self.feed.on_packet(wire.pack(state(7, 5)), received_at=1.1))
        self.assertFalse(self.feed.on_packet(wire.pack(state(7, 4)), received_at=1.2))
        self.assertTrue(self.feed.on_packet(wire.pack(state(8, 5)), received_at=1.3))
        self.assertTrue(self.feed.on_packet(wire.pack(state(9, 0xFFFFFFFF)), received_at=1.4))
        self.assertTrue(self.feed.on_packet(wire.pack(state(9, 0)), received_at=1.5))

    def test_queue_is_bounded_and_discards_oldest_received_state(self):
        for sequence in range(MAX_QUEUED_PACKETS + 1):
            self.assertTrue(self.feed.on_packet(wire.pack(state(7, sequence)), sequence))

        self._complete_probe()
        packets = tuple(self.feed.drain_packets())
        self.assertEqual(len(packets), MAX_QUEUED_PACKETS)
        self.assertEqual(wire.unpack(packets[0][0])["master_frame_seq"], 1)
        self.assertEqual(wire.unpack(packets[-1][0])["master_frame_seq"], MAX_QUEUED_PACKETS)

    def test_zero_frame_after_existing_stream_resets_the_master_generation(self):
        self.assertTrue(self.feed.on_packet(wire.pack(state(7, 42)), 1.0))
        self._complete_probe()
        self.assertEqual(len(tuple(self.feed.drain_packets())), 1)

        self.assertTrue(self.feed.on_packet(wire.pack(state(7, 0)), 2.0))
        self.assertEqual(self.feed.generation, 1)
        self.assertIsNotNone(self.feed.render_time())
        self.assertEqual(
            [wire.unpack(packet)["master_frame_seq"] for packet, _ in self.feed.drain_packets()],
            [0],
        )

    def test_probe_replies_require_expected_endpoint_and_outstanding_sequence(self):
        self.feed._pending_probes[2] = 1.0
        self.assertFalse(self.feed.on_probe_reply(probe.pack(2), ("127.0.0.2", 5007), 1.1))
        self.assertFalse(self.feed.on_probe_reply(probe.pack(3), self.config.probe_server_address, 1.1))
        self.assertTrue(self.feed.on_probe_reply(probe.pack(2), self.config.probe_server_address, 1.1))
        self.assertFalse(self.feed.on_probe_reply(probe.pack(2), self.config.probe_server_address, 1.2))


if __name__ == "__main__":
    unittest.main()
