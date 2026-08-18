"""harness.impairment — live-adjustable delay/jitter/loss between
harness.publisher (or server.relay) and whatever's consuming the feed.

This is the demo's centrepiece, not a debugging tool: turning jitter to
40 ms and 3% loss live, in front of the room, and showing the remote
vehicle still move like a vehicle, is the thing people remember. Build
the live-adjustability first, not as an afterthought.

Suggested starting profile (metro): 40 ms delay / 10 ms jitter / 0.5% loss.
"""

from __future__ import annotations

import heapq
import math
import numbers
import random
import threading
import time
from collections.abc import Callable
from typing import Any


class ImpairmentInjector:
    """Apply independent one-way delay, jitter, and loss to sent packets.

    ``delay_ms`` is the nominal one-way delay. Each packet adds a uniformly
    sampled jitter in ``[-jitter_ms, jitter_ms]`` and is clamped to an
    immediately due delivery. This intentionally allows packet reordering,
    just like a real jittery UDP path. ``loss_pct`` is sampled independently
    for every packet.

    Delayed sends are released from a daemon scheduler thread. The caller of
    the wrapped send function only queues a packet, so a 40 ms impairment does
    not reduce a 60 Hz publisher to 25 Hz.
    """

    def __init__(self, delay_ms: float = 40, jitter_ms: float = 10,
                 loss_pct: float = 0.5, *, rng: random.Random | None = None):
        self._condition = threading.Condition()
        self._profile = self._validated_profile(delay_ms, jitter_ms, loss_pct)
        self._rng = rng or random.Random()
        self._pending: list[tuple[float, int, Callable[[Any], None], Any]] = []
        self._next_order = 0
        self._worker: threading.Thread | None = None
        self._closed = False

    def set_profile(self, delay_ms: float, jitter_ms: float, loss_pct: float) -> None:
        """Live-adjustable — called from a UI/CLI during the demo itself."""
        profile = self._validated_profile(delay_ms, jitter_ms, loss_pct)
        with self._condition:
            if self._closed:
                raise RuntimeError("impairment injector is closed")
            # Existing packets retain the profile used when they entered the
            # path. The new settings take effect with the very next packet.
            self._profile = profile

    def wrap(self, send_fn):
        """Return a send_fn wrapper that applies delay/jitter/loss before sending."""
        if not callable(send_fn):
            raise TypeError("send_fn must be callable")

        def impaired_send(packet: Any) -> None:
            with self._condition:
                if self._closed:
                    raise RuntimeError("impairment injector is closed")

                delay_ms, jitter_ms, loss_pct = self._profile
                if self._rng.random() < loss_pct / 100.0:
                    return

                actual_delay_s = max(
                    0.0,
                    (delay_ms + self._rng.uniform(-jitter_ms, jitter_ms)) / 1000.0,
                )
                if actual_delay_s == 0.0:
                    # The disabled profile remains synchronous, which keeps
                    # the no-impairment harness path simple and deterministic.
                    immediate = True
                else:
                    immediate = False
                    heapq.heappush(
                        self._pending,
                        (time.monotonic() + actual_delay_s, self._next_order, send_fn, packet),
                    )
                    self._next_order += 1
                    self._start_worker_locked()
                    self._condition.notify()

            if immediate:
                send_fn(packet)

        return impaired_send

    def close(self) -> None:
        """Stop the scheduler and discard packets that have not been delivered."""

        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._pending.clear()
            self._condition.notify_all()

        if self._worker is not None and self._worker is not threading.current_thread():
            self._worker.join()

    def __enter__(self) -> "ImpairmentInjector":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @staticmethod
    def _validated_profile(delay_ms: float, jitter_ms: float,
                           loss_pct: float) -> tuple[float, float, float]:
        values = {
            "delay_ms": delay_ms,
            "jitter_ms": jitter_ms,
            "loss_pct": loss_pct,
        }
        validated = {}
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise ValueError(f"{name} must be a finite real number")
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"{name} must be a finite real number")
            validated[name] = value

        if validated["delay_ms"] < 0:
            raise ValueError("delay_ms must be non-negative")
        if validated["jitter_ms"] < 0:
            raise ValueError("jitter_ms must be non-negative")
        if not 0 <= validated["loss_pct"] <= 100:
            raise ValueError("loss_pct must be in the range 0..100")
        return (
            validated["delay_ms"],
            validated["jitter_ms"],
            validated["loss_pct"],
        )

    def _start_worker_locked(self) -> None:
        if self._worker is None:
            self._worker = threading.Thread(
                target=self._deliver_pending,
                name="dtnet-impairment",
                daemon=True,
            )
            self._worker.start()

    def _deliver_pending(self) -> None:
        while True:
            with self._condition:
                while not self._closed and not self._pending:
                    self._condition.wait()
                if self._closed:
                    return

                due_at, _, send_fn, packet = self._pending[0]
                wait_s = due_at - time.monotonic()
                if wait_s > 0:
                    self._condition.wait(wait_s)
                    continue
                heapq.heappop(self._pending)

            # User code must not run while holding the queue lock: it may be
            # slow, re-enter the injector, or adjust the profile from a UI.
            send_fn(packet)
