"""Contract tests for the fixed dtnet v1 actor-state packet."""

from __future__ import annotations

import math
import struct
import unittest

from dtnet import wire


STATE = {
    "actor_id": 0x10203040,
    "master_frame_seq": 0x50607080,
    "pos_x": 1.25,
    "pos_y": -2.5,
    "pos_z": 3.75,
    "rot_r": -4.0,
    "rot_p": 5.5,
    "rot_y": -6.25,
    "vel_x": 7.0,
    "vel_y": -8.5,
    "vel_z": 9.125,
    "ang_x": -10.0,
    "ang_y": 11.25,
    "ang_z": -12.5,
    "steer_angle": 13.75,
    "light_state": wire.LIGHT_BRAKE | wire.LIGHT_LEFT_BLINKER,
}


class WireFormatTests(unittest.TestCase):
    def test_exact_little_endian_fixture_and_round_trip(self) -> None:
        packet = wire.pack(STATE)
        expected = struct.pack(
            "<BII13fB",
            wire.VERSION,
            STATE["actor_id"],
            STATE["master_frame_seq"],
            *(
                STATE[field]
                for field in (
                    "pos_x", "pos_y", "pos_z", "rot_r", "rot_p", "rot_y",
                    "vel_x", "vel_y", "vel_z", "ang_x", "ang_y", "ang_z",
                    "steer_angle",
                )
            ),
            STATE["light_state"],
        )

        self.assertEqual(wire.PACKET_SIZE, 62)
        self.assertEqual(packet, expected)
        decoded = wire.unpack(packet)
        self.assertEqual(decoded["version"], wire.VERSION)
        self.assertEqual(decoded["actor_id"], STATE["actor_id"])
        self.assertEqual(decoded["master_frame_seq"], STATE["master_frame_seq"])
        self.assertEqual(decoded["light_state"], STATE["light_state"])
        for field, expected_value in STATE.items():
            if field not in {"actor_id", "master_frame_seq", "light_state"}:
                self.assertTrue(
                    math.isclose(decoded[field], expected_value, rel_tol=1e-6, abs_tol=1e-6),
                    field,
                )

    def test_optional_fields_default_to_zero(self) -> None:
        state = {
            key: value
            for key, value in STATE.items()
            if key not in {"steer_angle", "light_state"}
        }

        decoded = wire.unpack(wire.pack(state))

        self.assertEqual(decoded["steer_angle"], 0.0)
        self.assertEqual(decoded["light_state"], 0)

    def test_unpack_rejects_invalid_packets(self) -> None:
        packet = wire.pack(STATE)

        with self.assertRaises(TypeError):
            wire.unpack("not bytes")
        with self.assertRaises(ValueError):
            wire.unpack(packet[:-1])
        with self.assertRaises(ValueError):
            wire.unpack(packet + b"x")
        with self.assertRaisesRegex(ValueError, "unsupported wire format version"):
            wire.unpack(bytes([wire.VERSION + 1]) + packet[1:])
        nan_packet = struct.pack(
            "<BII13fB",
            wire.VERSION,
            STATE["actor_id"],
            STATE["master_frame_seq"],
            math.nan,
            *(0.0 for _ in range(12)),
            0,
        )
        with self.assertRaisesRegex(ValueError, "pos_x must be a finite float32 value"):
            wire.unpack(nan_packet)

    def test_pack_rejects_invalid_state(self) -> None:
        cases = [
            ({key: value for key, value in STATE.items() if key != "pos_x"}, "missing required field"),
            ({**STATE, "actor_id": -1}, "actor_id must be in the range"),
            ({**STATE, "master_frame_seq": 2**32}, "master_frame_seq must be in the range"),
            ({**STATE, "light_state": 256}, "light_state must be in the range"),
            ({**STATE, "vel_z": math.inf}, "vel_z must be a finite real number"),
            ({**STATE, "ang_x": math.nan}, "ang_x must be a finite real number"),
        ]
        for state, message in cases:
            with self.subTest(state=state):
                with self.assertRaisesRegex(ValueError, message):
                    wire.pack(state)

        with self.assertRaises(TypeError):
            wire.pack([])


if __name__ == "__main__":
    unittest.main()
