"""dtnet.clock — one job: estimate the master's current frame index.

Every incoming packet carries master_frame_seq. This module turns a stream
of (local_recv_time, master_frame_seq) observations into a smoothed
estimate of "what frame is the master on right now," expressed as an
offset from local time, filtered against measured RTT.

Explicitly NOT this module's job:
  - deciding what to render (that's dtnet.interp)
  - the LAN "skip ahead if >2-3 frames behind" heuristic — it thrashes
    under WAN jitter and stays out permanently, not just for this sprint.

Tuning target for the demo: ~40 ms render delay / ~10 ms jitter profile.
Acceptance (informal, for this sprint): offset converges from cold start
within ~5s and then holds within a couple of frames under the harness's
metro-jitter impairment profile.
"""


class ClockEstimator:
    def __init__(self):
        raise NotImplementedError

    def on_packet(self, local_recv_time: float, master_frame_seq: int, rtt: float) -> None:
        """Feed one observation in."""
        raise NotImplementedError

    def estimated_master_time(self, local_time: float) -> float:
        """Best current estimate of master time, for dtnet.interp to consume."""
        raise NotImplementedError
