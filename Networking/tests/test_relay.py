"""Contract tests for the UDP participant relay."""

from __future__ import annotations

import copy
import argparse
import socket
import unittest
from unittest.mock import MagicMock, patch

from dtnet import wire
from server.relay import Participant, Relay, add_cli_arguments, participant_from_namespace


def actor_state(actor_id: int, *, sequence: int = 0) -> dict:
    """Build a complete, encodable v1 actor state for relay tests."""

    return {
        "actor_id": actor_id,
        "master_frame_seq": sequence,
        "pos_x": float(actor_id),
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
        "steer_angle": 13.0,
        "light_state": wire.LIGHT_BRAKE,
    }


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.socket_constructor = patch("server.relay.socket.socket")
        self.addCleanup(self.socket_constructor.stop)
        self.mock_socket_constructor = self.socket_constructor.start()
        self.udp_socket = MagicMock()
        self.mock_socket_constructor.return_value = self.udp_socket
        self.relay = Relay()

    def test_constructor_creates_one_udp_socket(self):
        self.mock_socket_constructor.assert_called_once_with(
            socket.AF_INET, socket.SOCK_DGRAM
        )

    def test_close_releases_the_socket_once(self):
        self.relay.close()
        self.relay.close()

        self.udp_socket.close.assert_called_once_with()

    def test_registration_upserts_an_existing_participant_endpoint(self):
        self.relay.register("station-a", ("127.0.0.1", 4100))
        self.relay.register("station-a", ("127.0.0.1", 4200))

        self.relay.send_snapshot(7, [actor_state(1)])

        self.udp_socket.sendto.assert_called_once()
        packet, address = self.udp_socket.sendto.call_args.args
        self.assertEqual(address, ("127.0.0.1", 4200))
        self.assertEqual(wire.unpack(packet)["master_frame_seq"], 7)

    def test_snapshot_fans_out_every_actor_packet_to_every_participant(self):
        self.relay.register("station-a", ("127.0.0.1", 4100))
        self.relay.register("station-b", ("127.0.0.1", 4200))

        self.relay.send_snapshot(21, [actor_state(1), actor_state(2)])

        self.assertEqual(self.udp_socket.sendto.call_count, 4)
        deliveries = [
            (wire.unpack(call.args[0]), call.args[1])
            for call in self.udp_socket.sendto.call_args_list
        ]
        self.assertEqual(
            [(packet["actor_id"], address) for packet, address in deliveries],
            [
                (1, ("127.0.0.1", 4100)),
                (1, ("127.0.0.1", 4200)),
                (2, ("127.0.0.1", 4100)),
                (2, ("127.0.0.1", 4200)),
            ],
        )
        self.assertEqual(
            [packet["master_frame_seq"] for packet, _ in deliveries], [21, 21, 21, 21]
        )

    def test_snapshot_stamps_copied_states_with_the_authoritative_sequence(self):
        state = actor_state(17, sequence=3)
        original = copy.deepcopy(state)
        self.relay.register("station-a", ("127.0.0.1", 4100))

        self.relay.send_snapshot(44, [state])

        packet, _ = self.udp_socket.sendto.call_args.args
        self.assertEqual(wire.unpack(packet)["master_frame_seq"], 44)
        self.assertEqual(state, original)

    def test_snapshot_without_participants_is_a_noop(self):
        self.relay.send_snapshot(99, [{}])

        self.udp_socket.sendto.assert_not_called()


class ParticipantTests(unittest.TestCase):
    def test_parser_builds_static_participant(self):
        parser = argparse.ArgumentParser()
        add_cli_arguments(parser)

        participant = participant_from_namespace(
            parser.parse_args(
                [
                    "--participant-id", "wheel-bay",
                    "--participant-host", "10.0.0.24",
                    "--participant-port", "6001",
                ]
            )
        )

        self.assertEqual(participant, Participant("wheel-bay", "10.0.0.24", 6001))
        self.assertEqual(participant.address, ("10.0.0.24", 6001))

    def test_participant_rejects_invalid_endpoint(self):
        with self.assertRaisesRegex(ValueError, "participant_id"):
            Participant(participant_id="")
        with self.assertRaisesRegex(ValueError, "host"):
            Participant(host="")
        with self.assertRaisesRegex(ValueError, "port"):
            Participant(port=0)


if __name__ == "__main__":
    unittest.main()
