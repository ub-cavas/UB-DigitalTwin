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


class Relay:
    def __init__(self):
        self._participants = {}  # participant_id -> (host, port)

    def register(self, participant_id, address) -> None:
        raise NotImplementedError

    def send_snapshot(self, frame_seq: int, actor_states: list) -> None:
        """Pack each actor_state via dtnet.wire and unicast to every participant."""
        raise NotImplementedError
