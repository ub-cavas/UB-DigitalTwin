"""server.uplink — receive a station's own ego state, apply it to that
station's puppet in the master world.

One job. This is what makes Traffic Manager and other server-owned agents
react to the human driver — small amount of code, large demo value.

Unpacks via dtnet.wire, same format as everything else. Late/missing
uplink: dead-reckon from last known velocity rather than stall the master
tick — the master never waits on a participant.
"""


class Uplink:
    def __init__(self, master):
        raise NotImplementedError

    def on_packet(self, data: bytes) -> None:
        """dtnet.wire.unpack, then master.apply_puppet_state(...)."""
        raise NotImplementedError
