"""server.master — the tick loop. One job: own world.tick() and nothing else.

Synchronous mode, fixed_delta_seconds = 1/60, substepping on, paced against
wall clock, stamping a monotonic frame sequence per tick. Runs headless.

Reads all actor state once per tick via world.get_snapshot() — NOT
actor.get_transform() per actor, which is an RPC round trip each and will
quietly cap you below 60 Hz with any real actor count. (This is the one
technique worth having confirmed against the old traffic-publisher sidecar;
see the "skim sidecars" task.)

Runs Traffic Manager for background traffic. Applies the latest station
ego-state uplink to that station's puppet via set_transform() — see
server.uplink for the receive side.

Guard to build early: refuse to start if another client already holds
apply_settings() / sync mode. This failure mode presents as intermittent
stutter and is expensive to re-diagnose every time it recurs.
"""


class Master:
    def __init__(self, world):
        raise NotImplementedError

    def tick(self) -> int:
        """Advance one frame, return the new frame sequence number."""
        raise NotImplementedError

    def snapshot(self):
        """One world.get_snapshot() call, fanned out to server.relay."""
        raise NotImplementedError
