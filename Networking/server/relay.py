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

import socket

from dtnet import wire


class Relay:
    def __init__(self):
        self._participants = {}  # participant_id -> (host, port)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def register(self, participant_id, address) -> None:
        """Register or replace the UDP endpoint for one participant."""

        self._participants[participant_id] = address

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
