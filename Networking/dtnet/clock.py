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

from __future__ import annotations

import math
import numbers
from typing import Any, Final


FRAME_RATE_HZ: Final = 60.0
"""The fixed master simulation rate defined by the shared-world architecture."""

EWMA_ALPHA: Final = 0.1
"""Weight given to each new RTT-adjusted offset observation."""

_MAX_FRAME_SEQUENCE: Final = 0xFFFFFFFF


def _sequence_is_newer(sequence: int, previous: int) -> bool:
    """Compare wrapping uint32 frame sequences without accepting equality."""

    difference = (sequence - previous) & _MAX_FRAME_SEQUENCE
    return 0 < difference < 0x80000000


class ClockEstimator:
    """Estimate the master's current 60 Hz frame index from received packets.

    The estimator models the master frame as ``local_time * FRAME_RATE_HZ``
    plus an offset.  A received sequence identifies the master's frame when
    the packet was sent; adding half the measured RTT approximates the frame
    current at receipt.  The resulting offset is smoothed with an EWMA so
    normal WAN jitter does not become visible puppet jitter.
    """

    def __init__(self):
        self._offset_frames: float | None = None
        self._last_master_frame_seq: int | None = None
        self._last_master_time: float | None = None

    def on_packet(self, local_recv_time: float, master_frame_seq: int, rtt: float) -> None:
        """Feed one received master-frame observation into the estimator.

        ``rtt`` is measured in seconds.  Duplicate and older sequence numbers
        are ignored after validation: the frame sequence is authoritative for
        ordering, and delayed UDP packets must not pull the estimate backwards.
        """

        local_recv_time = _finite_real(local_recv_time, "local_recv_time")
        master_frame_seq = _frame_sequence(master_frame_seq)
        rtt = _finite_real(rtt, "rtt")
        if rtt < 0:
            raise ValueError("rtt must be non-negative")

        if self._last_master_frame_seq is not None and not _sequence_is_newer(
            master_frame_seq, self._last_master_frame_seq
        ):
            return

        if self._last_master_frame_seq is None:
            master_time = float(master_frame_seq)
        else:
            assert self._last_master_time is not None
            master_time = self._last_master_time + (
                (master_frame_seq - self._last_master_frame_seq) & _MAX_FRAME_SEQUENCE
            )

        estimated_current_frame = master_time + (rtt / 2.0) * FRAME_RATE_HZ
        observed_offset = estimated_current_frame - local_recv_time * FRAME_RATE_HZ

        if self._offset_frames is None:
            self._offset_frames = observed_offset
        else:
            self._offset_frames += EWMA_ALPHA * (observed_offset - self._offset_frames)
        self._last_master_frame_seq = master_frame_seq
        self._last_master_time = master_time

    def estimated_master_time(self, local_time: float) -> float:
        """Best current estimate of master time, for dtnet.interp to consume."""

        local_time = _finite_real(local_time, "local_time")
        if self._offset_frames is None:
            raise RuntimeError("clock estimator has not received a packet")
        return local_time * FRAME_RATE_HZ + self._offset_frames


def _finite_real(value: Any, field: str) -> float:
    """Validate a finite numeric time value and return it as ``float``."""

    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{field} must be a finite real number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{field} must be a finite real number")
    return value


def _frame_sequence(value: Any) -> int:
    """Validate the uint32 sequence number carried by the frozen v1 packet."""

    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise ValueError("master_frame_seq must be an integer")
    value = int(value)
    if not 0 <= value <= _MAX_FRAME_SEQUENCE:
        raise ValueError(
            f"master_frame_seq must be in the range 0..{_MAX_FRAME_SEQUENCE}"
        )
    return value
