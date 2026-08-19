"""station.main — own the local station CARLA clock.

The station's CARLA world is deliberately independent from the server and
from every network receive path.  This module is its only time master: it
configures a 60 Hz synchronous world and advances it from monotonic
wall-clock deadlines.  Future station tickets compose wheel input, puppets,
and rendering around :class:`LocalStationClock`; none of them may own a tick.
"""

from __future__ import annotations

import argparse
import importlib
import math
import numbers
import os
import time
from collections.abc import Callable
from typing import Any, Final

from dtnet.clock import FRAME_RATE_HZ


FIXED_DELTA_SECONDS: Final = 1.0 / FRAME_RATE_HZ
"""The fixed local simulation step shared by every station."""

DEFAULT_CLIENT_TIMEOUT_S: Final = 10.0


def _positive_real(value: Any, name: str) -> float:
    """Validate a finite, strictly positive timing value."""

    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{name} must be a positive finite real number")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite real number")
    return value


class LocalStationClock:
    """The sole 60 Hz time master for one dedicated local CARLA world.

    The clock has no network dependencies and never calls ``wait_for_tick()``.
    It instead applies one tick per monotonic wall-clock deadline.  A late
    CARLA tick resets the next deadline, avoiding a burst of catch-up frames
    that would make the local simulation visibly race ahead.
    """

    def __init__(
        self,
        world: Any,
        *,
        fixed_delta_seconds: float = FIXED_DELTA_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._world = world
        self._fixed_delta_seconds = _positive_real(
            fixed_delta_seconds, "fixed_delta_seconds"
        )
        if not callable(monotonic) or not callable(sleep):
            raise TypeError("monotonic and sleep must be callable")
        self._monotonic = monotonic
        self._sleep = sleep
        self._previous_settings: Any | None = None
        self._next_deadline: float | None = None

    def start(self) -> None:
        """Configure and claim an asynchronous world as this station's clock."""

        if self._previous_settings is not None:
            raise RuntimeError("local station clock is already running")

        previous_settings = self._world.get_settings()
        if previous_settings.synchronous_mode:
            raise RuntimeError(
                "refusing to start: the local CARLA world already has a synchronous "
                "time master"
            )

        settings = self._world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = self._fixed_delta_seconds
        settings.substepping = True
        settings.max_substep_delta_time = min(0.01, self._fixed_delta_seconds)
        settings.max_substeps = max(
            1,
            math.ceil(self._fixed_delta_seconds / settings.max_substep_delta_time),
        )
        self._world.apply_settings(settings)

        self._previous_settings = previous_settings
        self._next_deadline = self._monotonic() + self._fixed_delta_seconds

    def tick(self) -> int:
        """Pace and issue one local ``world.tick()``, returning CARLA's frame."""

        if self._next_deadline is None:
            raise RuntimeError("local station clock has not been started")

        remaining = self._next_deadline - self._monotonic()
        if remaining > 0:
            self._sleep(remaining)

        frame = self._world.tick()
        now = self._monotonic()
        next_deadline = self._next_deadline + self._fixed_delta_seconds
        # Do not generate rapid catch-up ticks after a slow CARLA RPC or a
        # scheduling pause.  The next physical frame remains one local step
        # away in wall time.  Ordinary sub-frame work keeps the existing
        # absolute schedule; otherwise its small cost would accumulate and
        # lower the station below 60 Hz.
        self._next_deadline = (
            now + self._fixed_delta_seconds
            if now >= next_deadline
            else next_deadline
        )
        return frame

    def run(self, duration_s: float | None = None) -> int:
        """Run until interrupted or ``duration_s`` expires, then restore settings."""

        if duration_s is not None:
            duration_s = _positive_real(duration_s, "duration_s")

        self.start()
        started_at = self._monotonic()
        frames = 0
        try:
            while duration_s is None or self._monotonic() - started_at < duration_s:
                self.tick()
                frames += 1
        finally:
            self.close()
        return frames

    def close(self) -> None:
        """Restore the world settings captured by :meth:`start`, once per run."""

        if self._previous_settings is None:
            return
        previous_settings, self._previous_settings = self._previous_settings, None
        self._next_deadline = None
        self._world.apply_settings(previous_settings)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the dedicated local CARLA clock for one wheel station."
    )
    parser.add_argument("--host", default=os.environ.get("UB_CARLA_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("UB_CARLA_PORT", "2000"))
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_CLIENT_TIMEOUT_S,
        help="CARLA client RPC timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--duration", type=float, default=None,
        help="Stop after this many seconds; omit to run until interrupted.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Connect to a dedicated local CARLA server and run its station clock."""

    args = _parser().parse_args(argv)
    timeout = _positive_real(args.timeout, "timeout")
    if args.duration is not None:
        _positive_real(args.duration, "duration")

    # Import only for the runnable station entrypoint; isolated timing tests
    # and shared dtnet code do not require a local CARLA wheel installation.
    carla = importlib.import_module("carla")
    client = carla.Client(args.host, args.port)
    client.set_timeout(timeout)
    clock = LocalStationClock(client.get_world())

    try:
        frames = clock.run(args.duration)
    except KeyboardInterrupt:
        return 0

    print(f"Station clock completed {frames} frames at {FRAME_RATE_HZ:g} Hz.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
