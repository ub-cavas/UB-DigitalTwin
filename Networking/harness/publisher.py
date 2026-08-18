"""harness.publisher — synthetic actor-state publisher, no CARLA required.

One job: emit dtnet.wire-packed packets at 60 Hz, sequence-numbered, for a
small set of known analytic trajectories, so dtnet/ and station/ can be
built and tested before server/ exists.

Trajectories to implement (per the sprint doc):
  - constant velocity
  - hard brake from 15 m/s
  - lane change

This is the module station.puppets points at until week 3, when it's
replaced by server.relay behind the same dtnet.wire format.
"""


def constant_velocity_trajectory(t: float) -> dict:
    raise NotImplementedError


def hard_brake_trajectory(t: float) -> dict:
    raise NotImplementedError


def lane_change_trajectory(t: float) -> dict:
    raise NotImplementedError


class SyntheticPublisher:
    def __init__(self, trajectory_fn, hz: int = 60):
        raise NotImplementedError

    def run(self, send_fn) -> None:
        """Call send_fn(dtnet.wire.pack(state)) at the configured rate, forever."""
        raise NotImplementedError
