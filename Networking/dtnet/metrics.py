"""dtnet.metrics — one job: track RTT, jitter, loss, and buffer depth.

Consumed by station/main.py for the on-screen telemetry overlay (the thing
that makes the impairment dial legible to an audience) and read by
dtnet.clock as the RTT filter input.

Not doing logging, not doing Redis, not doing anything persistent this
sprint — that's WP3 in the full plan, deferred past Sep 15. This is just
the live numbers.
"""

from __future__ import annotations

from collections import deque
import math
import numbers
import threading
import time
from collections.abc import Callable
from typing import Any, Final


RECENT_LOSS_WINDOW_S: Final = 5.0
"""Duration of the loss value shown next to the live impairment controls."""

_MAX_SEQUENCE: Final = 0xFFFFFFFF


def _sequence_is_newer(sequence: int, previous: int) -> bool:
    difference = (sequence - previous) & _MAX_SEQUENCE
    return 0 < difference < 0x80000000


def _finite_real(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{name} must be a finite real number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite real number")
    return value


def _sequence(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise ValueError("seq must be an integer")
    value = int(value)
    if not 0 <= value <= _MAX_SEQUENCE:
        raise ValueError(f"seq must be in the range 0..{_MAX_SEQUENCE}")
    return value


class LinkMetrics:
    """Thread-safe link-health values for the station's telemetry overlay.

    ``on_packet`` is for a completed RTT probe: ``send_time`` is the local
    probe-send time and ``recv_time`` is the local reply-receive time.  State
    replication packets do not currently contain enough information to claim
    an RTT, so they must not be passed here until a future probe path exists.

    The sequence is the probe stream's monotonically increasing uint32 value.
    Duplicate and reordered replies are ignored, preventing stale responses
    from distorting either loss or jitter.  Loss is inferred from gaps; it is
    therefore observable when a subsequent reply arrives, as is normal for an
    unreliable datagram stream.
    """

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic):
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._last_seq: int | None = None
        self._received_count = 0
        self._lost_count = 0
        self._last_rtt_ms: float | None = None
        self._previous_rtt_ms: float | None = None
        self._jitter_ms: float | None = None
        self._recent: deque[tuple[float, int, int]] = deque()
        self._buffer_depth: int | None = None

    def on_packet(self, send_time: float, recv_time: float, seq: int) -> None:
        """Record one valid RTT probe reply and its probe-stream sequence."""

        send_time = _finite_real(send_time, "send_time")
        recv_time = _finite_real(recv_time, "recv_time")
        seq = _sequence(seq)
        if recv_time < send_time:
            raise ValueError("recv_time must not precede send_time")
        rtt_ms = (recv_time - send_time) * 1000.0

        with self._lock:
            if self._last_seq is not None and not _sequence_is_newer(seq, self._last_seq):
                return

            missing = (
                0
                if self._last_seq is None
                else ((seq - self._last_seq) & _MAX_SEQUENCE) - 1
            )
            self._last_seq = seq
            self._received_count += 1
            self._lost_count += missing
            self._last_rtt_ms = rtt_ms
            if self._previous_rtt_ms is not None:
                difference = abs(rtt_ms - self._previous_rtt_ms)
                # RFC 3550's running jitter estimator: responsive enough for
                # a live HUD without turning ordinary packet variance into
                # unreadable flicker.
                previous = self._jitter_ms or 0.0
                self._jitter_ms = previous + (difference - previous) / 16.0
            self._previous_rtt_ms = rtt_ms
            self._recent.append((recv_time, missing, 1))
            self._discard_expired_locked(recv_time)

    def set_buffer_depth(self, depth: int | None) -> None:
        """Set the shallowest active puppet interpolation-buffer depth.

        ``None`` means there are no active remote puppets yet.  The future
        station receive path obtains the actual depth from ``PuppetManager``;
        this class intentionally does not know about CARLA or interpolation.
        """

        if depth is not None:
            if isinstance(depth, bool) or not isinstance(depth, numbers.Integral):
                raise ValueError("buffer depth must be a non-negative integer or None")
            depth = int(depth)
            if depth < 0:
                raise ValueError("buffer depth must be a non-negative integer or None")
        with self._lock:
            self._buffer_depth = depth

    def snapshot(self) -> dict[str, float | int | None]:
        """Return the current overlay values without exposing mutable state.

        ``loss_pct`` is the recent five-second loss percentage and
        ``loss_total_pct`` is loss inferred over the complete probe session.
        Values that have not yet been observed are represented by ``None`` so
        a UI can render an honest unavailable marker rather than a false zero.
        """

        now = _finite_real(self._monotonic(), "monotonic result")
        with self._lock:
            self._discard_expired_locked(now)
            recent_lost = sum(missing for _, missing, _ in self._recent)
            recent_received = sum(received for _, _, received in self._recent)
            recent_total = recent_lost + recent_received
            total = self._lost_count + self._received_count
            return {
                "rtt_ms": self._last_rtt_ms,
                "jitter_ms": self._jitter_ms,
                "loss_pct": (
                    recent_lost / recent_total * 100.0 if recent_total else None
                ),
                "loss_total_pct": (
                    self._lost_count / total * 100.0 if total else None
                ),
                "buffer_depth": self._buffer_depth,
            }

    def _discard_expired_locked(self, now: float) -> None:
        cutoff = now - RECENT_LOSS_WINDOW_S
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()
