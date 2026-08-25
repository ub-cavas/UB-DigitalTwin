"""Tests for DT-22's auxiliary UDP link-health probe."""

from __future__ import annotations

import unittest

from dtnet import probe
from server.probe import ProbeConfig, ProbeResponder


class ProbeWireTests(unittest.TestCase):
    def test_packet_round_trip_and_rejects_non_v1_payloads(self):
        packet = probe.pack(42)
        self.assertEqual(len(packet), probe.PACKET_SIZE)
        self.assertEqual(probe.unpack(packet), 42)
        for invalid in (b"", packet + b"x", b"bad-probe", "not-bytes"):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    probe.unpack(invalid)


class ProbeResponderTests(unittest.TestCase):
    def test_valid_datagram_is_echoed_and_invalid_payload_is_ignored(self):
        responder = ProbeResponder(ProbeConfig("127.0.0.1", 5007))
        request = probe.pack(7)
        self.assertEqual(responder.on_packet(request), request)
        self.assertIsNone(responder.on_packet(b"invalid"))


if __name__ == "__main__":
    unittest.main()
