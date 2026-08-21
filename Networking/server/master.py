"""The authoritative CARLA world clock and wire-ready snapshot source.

``Master`` claims one asynchronous CARLA world, advances it on a 60 Hz
monotonic schedule, and converts the one post-tick ``WorldSnapshot`` into the
plain actor-state dictionaries consumed by the relay.  The module can also be
run directly as the headless world's clock owner.
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
"""The fixed simulation step shared by the authoritative world and stations."""

MAX_FRAME_SEQUENCE: Final = 0xFFFFFFFF
"""The largest frame sequence that the frozen v1 wire format can carry."""

DEFAULT_CLIENT_TIMEOUT_S: Final = 10.0
"""CARLA client RPC timeout used by the executable world master."""


def _positive_real(value: Any, name: str) -> float:
    """Validate a finite, strictly positive timing value."""

    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{name} must be a positive finite real number")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite real number")
    return value


class Master:
    """The sole synchronous tick owner for one authoritative CARLA world.

    Call :meth:`start`, then repeatedly call :meth:`tick` followed by
    :meth:`snapshot`. Every successful tick uses exactly one
    ``world.get_snapshot()`` call; snapshot extraction never calls
    ``world.get_actors()`` or any live actor method.
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
        self._next_sequence = 0
        self._latest_states: list[dict[str, int | float]] | None = None

    def start(self) -> None:
        """Claim an asynchronous world and configure 60 Hz synchronous mode."""

        if self._previous_settings is not None:
            raise RuntimeError("master is already running")

        previous_settings = self._world.get_settings()
        if previous_settings.synchronous_mode:
            raise RuntimeError(
                "refusing to start: the CARLA world already has a synchronous "
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
        self._latest_states = None

    def tick(self) -> int:
        """Pace, advance, and capture one authoritative frame sequence.

        A failure after this master has claimed the world restores its prior
        settings immediately. The frame sequence is reserved only after both
        CARLA's tick and the post-tick snapshot have completed successfully.
        """

        if self._next_deadline is None:
            raise RuntimeError("master has not been started")
        if self._next_sequence > MAX_FRAME_SEQUENCE:
            raise RuntimeError("master frame sequence exhausted the v1 uint32 range")

        remaining = self._next_deadline - self._monotonic()
        if remaining > 0:
            self._sleep(remaining)

        sequence = self._next_sequence
        try:
            self._world.tick()
            self._latest_states = self._states_from_world_snapshot(sequence)
        except Exception:
            self.close()
            raise

        now = self._monotonic()
        next_deadline = self._next_deadline + self._fixed_delta_seconds
        # A slow CARLA RPC or snapshot conversion must not trigger a burst of
        # catch-up frames, which would make the authoritative world race ahead.
        self._next_deadline = (
            now + self._fixed_delta_seconds
            if now >= next_deadline
            else next_deadline
        )
        self._next_sequence += 1
        return sequence

    def snapshot(self) -> list[dict[str, int | float]]:
        """Return defensive copies of the states captured by the latest tick."""

        if self._latest_states is None:
            raise RuntimeError("master has not completed a successful tick")
        return [dict(state) for state in self._latest_states]

    def run(self, duration_s: float | None = None) -> int:
        """Tick until interrupted or the optional duration expires.

        The prior CARLA settings are restored for every exit path after this
        master successfully claims the world.  Relay and uplink work remains
        outside this clock-owner loop.
        """

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
        """Restore the pre-master settings exactly once."""

        if self._previous_settings is None:
            return
        previous_settings, self._previous_settings = self._previous_settings, None
        self._next_deadline = None
        self._latest_states = None
        self._world.apply_settings(previous_settings)

    def _states_from_world_snapshot(self, sequence: int) -> list[dict[str, int | float]]:
        """Convert one CARLA ``WorldSnapshot`` without live actor RPCs."""

        return [
            self._state_from_actor_snapshot(actor_snapshot, sequence)
            for actor_snapshot in self._world.get_snapshot()
        ]

    @staticmethod
    def _state_from_actor_snapshot(
        actor_snapshot: Any, sequence: int
    ) -> dict[str, int | float]:
        transform = actor_snapshot.get_transform()
        location = transform.location
        rotation = transform.rotation
        velocity = actor_snapshot.get_velocity()
        angular_velocity = actor_snapshot.get_angular_velocity()
        return {
            "actor_id": actor_snapshot.id,
            "master_frame_seq": sequence,
            "pos_x": location.x,
            "pos_y": location.y,
            "pos_z": location.z,
            "rot_r": rotation.roll,
            "rot_p": rotation.pitch,
            "rot_y": rotation.yaw,
            "vel_x": velocity.x,
            "vel_y": velocity.y,
            "vel_z": velocity.z,
            "ang_x": angular_velocity.x,
            "ang_y": angular_velocity.y,
            "ang_z": angular_velocity.z,
            # These fields are not exposed by ActorSnapshot. Using defaults
            # keeps this extraction free of per-actor RPCs.
            "steer_angle": 0.0,
            "light_state": 0,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the authoritative headless CARLA world master."
    )
    parser.add_argument("--host", default=os.environ.get("UB_CARLA_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("UB_CARLA_PORT", "2000"))
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("UB_CARLA_TIMEOUT", DEFAULT_CLIENT_TIMEOUT_S)),
        help="CARLA client RPC timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop after this many seconds; omit to run until interrupted.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Connect to CARLA and run its sole authoritative world clock."""

    args = _parser().parse_args(argv)
    timeout = _positive_real(args.timeout, "timeout")
    if args.duration is not None:
        _positive_real(args.duration, "duration")

    # The library remains importable without the CARLA wheel for isolated
    # contract tests.  Only the executable entrypoint loads the wheel.
    carla = importlib.import_module("carla")
    client = carla.Client(args.host, args.port)
    client.set_timeout(timeout)
    master = Master(client.get_world())

    try:
        frames = master.run(args.duration)
    except KeyboardInterrupt:
        return 0

    print(f"World master completed {frames} frames at {FRAME_RATE_HZ:g} Hz.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
