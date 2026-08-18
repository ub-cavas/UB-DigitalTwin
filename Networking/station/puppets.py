"""station.puppets — spawn and pose physics-disabled remote actors.

One job: for each remote actor announced over the wire, keep a
physics-disabled CARLA actor whose transform is set from
dtnet.interp.PuppetInterpolator.pose_at(render_time), every local tick.

Data source is injected, not hardcoded — harness.publisher for weeks 1-2,
server.relay from week 3. See station.main for the swap point.
"""


class PuppetManager:
    def __init__(self, world, data_source):
        raise NotImplementedError

    def update(self, render_time: float) -> None:
        """Pull latest packets from data_source, update each puppet's set_transform()."""
        raise NotImplementedError
