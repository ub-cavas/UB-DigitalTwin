"""Synthetic impaired packet feed for the DT-19 station acceptance run.

The feed deliberately satisfies the same ``drain_packets`` contract as the
future UDP receiver.  It lets the station exercise real puppet interpolation
and lifecycle behavior before DT-22 swaps the source to the master relay.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from collections.abc import Callable
from typing import Final

from dtnet import wire
from dtnet.clock import ClockEstimator
from harness.impairment import ImpairmentInjector
from harness.publisher import SyntheticPublisher


Profile = tuple[float, float, float]
Trajectory = Callable[[float], dict]

NO_IMPAIRMENT: Final[Profile] = (0.0, 0.0, 0.0)
METRO_PROFILE: Final[Profile] = (40.0, 10.0, 0.5)
HARSH_PROFILE: Final[Profile] = (40.0, 40.0, 3.0)


def place_trajectory(
    trajectory: Trajectory,
    *,
    origin_x: float,
    origin_y: float,
    origin_z: float,
    heading_yaw_deg: float,
) -> Trajectory:
    """Place a local analytic trajectory into CARLA world coordinates."""

    if not callable(trajectory):
        raise TypeError("trajectory must be callable")
    values = (origin_x, origin_y, origin_z, heading_yaw_deg)
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
        raise ValueError("trajectory placement values must be finite real numbers")

    radians = math.radians(heading_yaw_deg)
    cosine = math.cos(radians)
    sine = math.sin(radians)

    def placed(elapsed_s: float) -> dict:
        state = dict(trajectory(elapsed_s))
        local_x, local_y = state["pos_x"], state["pos_y"]
        state["pos_x"] = origin_x + cosine * local_x - sine * local_y
        state["pos_y"] = origin_y + sine * local_x + cosine * local_y
        state["pos_z"] = origin_z + state["pos_z"]

        local_vx, local_vy = state["vel_x"], state["vel_y"]
        state["vel_x"] = cosine * local_vx - sine * local_vy
        state["vel_y"] = sine * local_vx + cosine * local_vy
        state["rot_y"] += heading_yaw_deg
        return state

    return placed


class SyntheticPuppetFeed:
    """Run one synthetic vehicle through a live impairment path into a queue."""

    def __init__(self, trajectory: Trajectory, *, profile: Profile = METRO_PROFILE):
        if not callable(trajectory):
            raise TypeError("trajectory must be callable")
        self._trajectory = trajectory
        self._lock = threading.Lock()
        self._profile = self._validated_profile(profile)
        self._clock = ClockEstimator()
        self._packets: queue.SimpleQueue[tuple[bytes, float]] = queue.SimpleQueue()
        self._stop_event = threading.Event()
        self._impairment = ImpairmentInjector(*self._profile)
        self._impaired_receive = self._impairment.wrap(self._receive)
        self._publisher_thread: threading.Thread | None = None

    @property
    def profile(self) -> Profile:
        with self._lock:
            return self._profile

    def start(self) -> None:
        """Start the 60 Hz publisher without blocking the station tick loop."""

        if self._publisher_thread is not None:
            raise RuntimeError("synthetic puppet feed is already running")

        publisher = SyntheticPublisher(self._trajectory)
        self._publisher_thread = threading.Thread(
            target=publisher.run,
            args=(self._publish,),
            kwargs={"stop_event": self._stop_event},
            name="station-synthetic-publisher",
            daemon=True,
        )
        self._publisher_thread.start()

    def close(self) -> None:
        """Stop synthetic delivery and discard packets that were still delayed."""

        self._stop_event.set()
        self._impairment.close()
        if self._publisher_thread is not None and self._publisher_thread is not threading.current_thread():
            self._publisher_thread.join(timeout=1.0)
        self._publisher_thread = None

    def set_profile(self, profile: Profile) -> None:
        """Use a profile for every synthetic packet published from this point."""

        profile = self._validated_profile(profile)
        self._impairment.set_profile(*profile)
        with self._lock:
            self._profile = profile

    def handle_pygame_input(self, events: list[object], pygame: object) -> None:
        """Apply the DT-19 live impairment shortcuts from the shared window."""

        keydown = getattr(pygame, "KEYDOWN", None)
        for event in events:
            if getattr(event, "type", None) != keydown:
                continue
            if getattr(event, "key", None) == getattr(pygame, "K_0", None):
                self.set_profile(NO_IMPAIRMENT)
            elif getattr(event, "key", None) == getattr(pygame, "K_m", None):
                self.set_profile(METRO_PROFILE)
            elif getattr(event, "key", None) == getattr(pygame, "K_h", None):
                self.set_profile(HARSH_PROFILE)

    def drain_packets(self) -> list[tuple[bytes, float]]:
        """Return all delivered packets without ever waiting for network work."""

        packets = []
        while True:
            try:
                packets.append(self._packets.get_nowait())
            except queue.Empty:
                return packets

    def render_time(self, now: float | None = None) -> float | None:
        """Return the current master-frame estimate, once the first packet arrives."""

        with self._lock:
            try:
                return self._clock.estimated_master_time(time.monotonic() if now is None else now)
            except RuntimeError:
                return None

    def _publish(self, packet: bytes) -> None:
        with self._lock:
            profile = self._profile
        self._impaired_receive((packet, profile))

    def _receive(self, item: tuple[bytes, Profile]) -> None:
        packet, profile = item
        received_at = time.monotonic()
        state = wire.unpack(packet)
        with self._lock:
            self._clock.on_packet(
                received_at,
                state["master_frame_seq"],
                2.0 * profile[0] / 1000.0,
            )
        self._packets.put((packet, received_at))

    @staticmethod
    def _validated_profile(profile: Profile) -> Profile:
        if not isinstance(profile, tuple) or len(profile) != 3:
            raise ValueError("profile must be a (delay_ms, jitter_ms, loss_pct) tuple")
        try:
            values = tuple(float(value) for value in profile)
        except (TypeError, ValueError) as exc:
            raise ValueError("profile values must be finite real numbers") from exc
        if not all(math.isfinite(value) for value in values):
            raise ValueError("profile values must be finite real numbers")
        delay_ms, jitter_ms, loss_pct = values
        if delay_ms < 0 or jitter_ms < 0 or not 0 <= loss_pct <= 100:
            raise ValueError("profile must have non-negative delay/jitter and 0..100 loss")
        return values
