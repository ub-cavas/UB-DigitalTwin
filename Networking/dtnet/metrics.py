"""dtnet.metrics — one job: track RTT, jitter, loss, and buffer depth.

Consumed by station/main.py for the on-screen telemetry overlay (the thing
that makes the impairment dial legible to an audience) and read by
dtnet.clock as the RTT filter input.

Not doing logging, not doing Redis, not doing anything persistent this
sprint — that's WP3 in the full plan, deferred past Sep 15. This is just
the live numbers.
"""


class LinkMetrics:
    def __init__(self):
        raise NotImplementedError

    def on_packet(self, send_time: float, recv_time: float, seq: int) -> None:
        raise NotImplementedError

    def snapshot(self) -> dict:
        """Returns {rtt_ms, jitter_ms, loss_pct, buffer_depth}."""
        raise NotImplementedError
