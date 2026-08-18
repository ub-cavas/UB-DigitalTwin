"""dtnet.interp — ring buffer + interpolation + bounded extrapolation.

One job: given a stream of timestamped poses for one actor and a target
render time (from dtnet.clock), produce the pose to draw right now.

Normal path: buffer 2-3 packets, interpolate between the two that bracket
(estimated_master_time - render_delay). Puppets are shown slightly in the
past, but smoothly.

Fallback path: for a genuinely late packet only. Extrapolate along last
known velocity, but bounded — decide a horizon (propose: 150-200 ms) and
a defined behaviour past it (hold last pose, don't keep extrapolating
forever). Write the chosen horizon and behaviour here once decided, not
just in the sprint doc.

Acceptance (informal, for this sprint): no single-frame position
correction ("snap") visible to the eye, and no velocity sign reversal
during a hard-brake trajectory played through the harness.
"""


class PuppetInterpolator:
    def __init__(self, render_delay_s: float):
        raise NotImplementedError

    def on_packet(self, recv_time: float, master_time: float, pose: dict) -> None:
        """Feed one decoded packet (post dtnet.wire.unpack) in."""
        raise NotImplementedError

    def pose_at(self, render_time: float) -> dict:
        """The pose to draw right now, interpolated or (bounded) extrapolated."""
        raise NotImplementedError
