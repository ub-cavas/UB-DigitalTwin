"""harness.impairment — live-adjustable delay/jitter/loss between
harness.publisher (or server.relay) and whatever's consuming the feed.

This is the demo's centrepiece, not a debugging tool: turning jitter to
40 ms and 3% loss live, in front of the room, and showing the remote
vehicle still move like a vehicle, is the thing people remember. Build
the live-adjustability first, not as an afterthought.

Suggested starting profile (metro): 40 ms delay / 10 ms jitter / 0.5% loss.
"""


class ImpairmentInjector:
    def __init__(self, delay_ms: float = 40, jitter_ms: float = 10, loss_pct: float = 0.5):
        raise NotImplementedError

    def set_profile(self, delay_ms: float, jitter_ms: float, loss_pct: float) -> None:
        """Live-adjustable — called from a UI/CLI during the demo itself."""
        raise NotImplementedError

    def wrap(self, send_fn):
        """Return a send_fn wrapper that applies delay/jitter/loss before sending."""
        raise NotImplementedError
