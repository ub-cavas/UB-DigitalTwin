"""server.relay — participant registry + per-destination unicast send.

One job: take the per-tick snapshot from server.master and send it, packed
via dtnet.wire, to every registered participant's address.

For this sprint: one participant (the single station), no radius filtering.
Radius filtering and multi-participant fan-out are real-plan scope (WP2),
not demo scope — don't build them here unless a second station shows up.

This is the module station.puppets swaps its data source to in week 3,
replacing harness.publisher. Both speak dtnet.wire, so the swap should be
a config change, not code.
"""

from __future__ import annotations

import argparse
import os
import socket
from dataclasses import dataclass
from typing import Final

from dtnet import wire


DEFAULT_PARTICIPANT_ID: Final = "station-1"
DEFAULT_PARTICIPANT_HOST: Final = "127.0.0.1"
DEFAULT_PARTICIPANT_PORT: Final = 5005


def _environment_int(name: str, default: int) -> int:
    """Read an integer environment override with a clear configuration error."""

    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {value!r}") from error


@dataclass(frozen=True)
class Participant:
    """One statically configured master snapshot recipient."""

    participant_id: str = DEFAULT_PARTICIPANT_ID
    host: str = DEFAULT_PARTICIPANT_HOST
    port: int = DEFAULT_PARTICIPANT_PORT

    def __post_init__(self) -> None:
        if not isinstance(self.participant_id, str) or not self.participant_id:
            raise ValueError("participant_id must be a non-empty string")
        if not isinstance(self.host, str) or not self.host:
            raise ValueError("host must be a non-empty string")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ValueError("port must be an integer from 1 through 65535")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer from 1 through 65535")

    @property
    def address(self) -> tuple[str, int]:
        """The UDP endpoint passed to :meth:`Relay.register`."""

        return self.host, self.port


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the executable master's static participant controls."""

    parser.add_argument(
        "--participant-id",
        default=os.environ.get("UB_RELAY_PARTICIPANT_ID", DEFAULT_PARTICIPANT_ID),
        help="Static snapshot recipient ID (default: %(default)s)",
    )
    parser.add_argument(
        "--participant-host",
        default=os.environ.get(
            "UB_RELAY_PARTICIPANT_HOST", DEFAULT_PARTICIPANT_HOST
        ),
        help="Static snapshot recipient host (default: %(default)s)",
    )
    parser.add_argument(
        "--participant-port",
        type=int,
        default=_environment_int(
            "UB_RELAY_PARTICIPANT_PORT", DEFAULT_PARTICIPANT_PORT
        ),
        help="Static snapshot recipient UDP port (default: %(default)s)",
    )


def participant_from_namespace(args: argparse.Namespace) -> Participant:
    """Build a validated static participant from master CLI arguments."""

    return Participant(
        participant_id=args.participant_id,
        host=args.participant_host,
        port=args.participant_port,
    )


class Relay:
    def __init__(self):
        self._participants = {}  # participant_id -> (host, port)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._closed = False

    def register(self, participant_id, address) -> None:
        """Register or replace the UDP endpoint for one participant."""

        self._participants[participant_id] = address

    def close(self) -> None:
        """Release the relay socket exactly once."""

        if self._closed:
            return
        self._closed = True
        self._socket.close()

    def send_snapshot(self, frame_seq: int, actor_states: list) -> None:
        """Pack each actor_state via dtnet.wire and unicast to every participant."""

        # A relay with no listeners should not spend master-tick time encoding
        # data that cannot be delivered.  Taking a tuple also makes this call's
        # recipient set stable while its packets are being emitted.
        recipients = tuple(self._participants.values())
        if not recipients:
            return

        for actor_state in actor_states:
            state = dict(actor_state)
            # The caller supplies the master frame owning this snapshot.  Copy
            # before stamping so the master's cached state remains immutable to
            # the relay and callers can safely reuse the input dictionaries.
            state["master_frame_seq"] = frame_seq
            packet = wire.pack(state)
            for address in recipients:
                self._socket.sendto(packet, address)
