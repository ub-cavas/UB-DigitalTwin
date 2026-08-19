"""harness.visualizer — non-CARLA visual proof that dtnet/ works.

One job: draw ground-truth position (from harness.publisher directly) next
to interpolated puppet position (from dtnet.clock + dtnet.interp, fed
through harness.impairment), live, with impairment adjustable on screen.

This is the Aug 24 gate artifact. If this isn't convincing by then, every
downstream week slips — see the sprint board.
"""

from __future__ import annotations

import argparse
import threading
import time
from collections.abc import Callable
from typing import Final

from dtnet import wire
from dtnet.clock import ClockEstimator
from dtnet.interp import PuppetInterpolator
from harness.impairment import ImpairmentInjector
from harness.publisher import (
    SyntheticPublisher,
    constant_velocity_trajectory,
    hard_brake_trajectory,
    lane_change_trajectory,
)


Profile = tuple[float, float, float]
Trajectory = Callable[[float], dict]

NO_IMPAIRMENT: Final[Profile] = (0.0, 0.0, 0.0)
METRO_PROFILE: Final[Profile] = (40.0, 10.0, 0.5)
HARSH_PROFILE: Final[Profile] = (40.0, 40.0, 3.0)
RENDER_DELAY_S: Final = 0.04

WINDOW_SIZE: Final = (1100, 700)
PIXELS_PER_METER: Final = 18.0

TRAJECTORIES: Final[dict[str, Trajectory]] = {
    "constant": constant_velocity_trajectory,
    "brake": hard_brake_trajectory,
    "lane-change": lane_change_trajectory,
}


class VisualizerPipeline:
    """Thread-safe state path used by both the pygame loop and unit tests."""

    def __init__(self, trajectory: Trajectory, profile: Profile = METRO_PROFILE):
        if not callable(trajectory):
            raise TypeError("trajectory must be callable")

        self.trajectory = trajectory
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._clock = ClockEstimator()
        self._interpolator = PuppetInterpolator(RENDER_DELAY_S)
        self._profile = tuple(float(value) for value in profile)
        self._impairment = ImpairmentInjector(*self._profile)
        self._started_at: float | None = None
        self._publisher_thread: threading.Thread | None = None

    @property
    def profile(self) -> Profile:
        with self._lock:
            return self._profile

    def start(self) -> None:
        """Launch the 60 Hz synthetic publisher behind the impairment path."""

        if self._publisher_thread is not None:
            raise RuntimeError("visualizer pipeline is already running")

        self._started_at = time.monotonic()
        publisher = SyntheticPublisher(self.trajectory)
        impaired_receive = self._impairment.wrap(self.receive_packet)
        self._publisher_thread = threading.Thread(
            target=publisher.run,
            args=(impaired_receive,),
            kwargs={"stop_event": self._stop_event},
            name="dtnet-synthetic-publisher",
            daemon=True,
        )
        self._publisher_thread.start()

    def reset(self) -> None:
        """Restart the trajectory from frame zero without changing impairment."""

        self._stop_event.set()
        self._impairment.close()
        if self._publisher_thread is not None:
            self._publisher_thread.join(timeout=1.0)

        with self._lock:
            self._clock = ClockEstimator()
            self._interpolator = PuppetInterpolator(RENDER_DELAY_S)
            self._stop_event = threading.Event()
            self._impairment = ImpairmentInjector(*self._profile)
            self._started_at = None
            self._publisher_thread = None
        self.start()

    def close(self) -> None:
        """Stop background work and release the impairment scheduler."""

        self._stop_event.set()
        self._impairment.close()
        if self._publisher_thread is not None:
            self._publisher_thread.join(timeout=1.0)

    def set_profile(self, profile: Profile) -> None:
        """Apply a new impairment profile to packets sent from this point on."""

        delay_ms, jitter_ms, loss_pct = profile
        self._impairment.set_profile(delay_ms, jitter_ms, loss_pct)
        with self._lock:
            self._profile = (float(delay_ms), float(jitter_ms), float(loss_pct))

    def receive_packet(self, packet: bytes, recv_time: float | None = None) -> None:
        """Decode one impaired packet and feed the clock/interpolation path."""

        state = wire.unpack(packet)
        if recv_time is None:
            recv_time = time.monotonic()

        with self._lock:
            # The harness knows only its nominal one-way impairment. Doubling
            # it gives ClockEstimator the RTT-shaped estimate it expects.
            rtt_s = 2.0 * self._profile[0] / 1000.0
            self._clock.on_packet(recv_time, state["master_frame_seq"], rtt_s)
            self._interpolator.on_packet(
                recv_time,
                float(state["master_frame_seq"]),
                state,
            )

    def ground_truth(self, now: float | None = None) -> dict:
        """Return the direct, unimpaired analytic trajectory state."""

        if self._started_at is None:
            raise RuntimeError("visualizer pipeline has not been started")
        if now is None:
            now = time.monotonic()
        return self.trajectory(max(0.0, now - self._started_at))

    def puppet_pose(self, now: float | None = None) -> dict | None:
        """Return the current rendered puppet pose, or None until a packet arrives."""

        if now is None:
            now = time.monotonic()
        with self._lock:
            try:
                render_time = self._clock.estimated_master_time(now)
            except RuntimeError:
                return None
            return self._interpolator.pose_at(render_time)


def _require_pygame():
    try:
        import pygame
    except ImportError as exc:
        raise RuntimeError(
            "DT-10 visualizer requires pygame; install it with `python3 -m pip install pygame`."
        ) from exc
    return pygame


def _draw_car(pygame, surface, pose: dict, *, color, camera_x: float, label: str) -> None:
    x = WINDOW_SIZE[0] / 2.0 + (pose["pos_x"] - camera_x) * PIXELS_PER_METER
    y = WINDOW_SIZE[1] / 2.0 - pose["pos_y"] * PIXELS_PER_METER
    rect = pygame.Rect(round(x - 10), round(y - 6), 20, 12)
    pygame.draw.rect(surface, color, rect, border_radius=3)
    pygame.draw.circle(surface, color, (round(x + 8), round(y)), 3)
    font = pygame.font.Font(None, 24)
    surface.blit(font.render(label, True, color), (round(x - 24), round(y - 28)))


def _draw_frame(pygame, surface, pipeline: VisualizerPipeline, now: float) -> None:
    surface.fill((18, 22, 29))
    truth = pipeline.ground_truth(now)
    puppet = pipeline.puppet_pose(now)
    camera_x = truth["pos_x"]

    road_top = WINDOW_SIZE[1] / 2 - 80
    road_height = 160
    pygame.draw.rect(surface, (45, 49, 56), (0, road_top, WINDOW_SIZE[0], road_height))
    pygame.draw.line(
        surface, (230, 200, 80), (0, WINDOW_SIZE[1] / 2),
        (WINDOW_SIZE[0], WINDOW_SIZE[1] / 2), 2,
    )
    _draw_car(pygame, surface, truth, color=(80, 230, 125), camera_x=camera_x,
              label="ground truth")
    if puppet is not None:
        _draw_car(pygame, surface, puppet, color=(70, 205, 255), camera_x=camera_x,
                  label="puppet")

    delay_ms, jitter_ms, loss_pct = pipeline.profile
    font = pygame.font.Font(None, 28)
    text = (
        f"delay {delay_ms:.0f} ms   jitter {jitter_ms:.0f} ms   "
        f"loss {loss_pct:.1f}%"
    )
    surface.blit(font.render(text, True, (238, 241, 245)), (24, 24))
    help_text = "R: reset  0: clear  M: metro  H: harsh   arrows: delay/jitter   PgUp/PgDn: loss"
    surface.blit(font.render(help_text, True, (180, 188, 198)), (24, 54))
    if puppet is None:
        surface.blit(font.render("Waiting for first packet…", True, (255, 210, 90)), (24, 84))


def _handle_key(pygame, event, pipeline: VisualizerPipeline) -> None:
    delay_ms, jitter_ms, loss_pct = pipeline.profile
    if event.key == pygame.K_0:
        pipeline.set_profile(NO_IMPAIRMENT)
    elif event.key == pygame.K_r:
        pipeline.reset()
    elif event.key == pygame.K_m:
        pipeline.set_profile(METRO_PROFILE)
    elif event.key == pygame.K_h:
        pipeline.set_profile(HARSH_PROFILE)
    elif event.key == pygame.K_LEFT:
        pipeline.set_profile((max(0.0, delay_ms - 5.0), jitter_ms, loss_pct))
    elif event.key == pygame.K_RIGHT:
        pipeline.set_profile((delay_ms + 5.0, jitter_ms, loss_pct))
    elif event.key == pygame.K_DOWN:
        pipeline.set_profile((delay_ms, max(0.0, jitter_ms - 5.0), loss_pct))
    elif event.key == pygame.K_UP:
        pipeline.set_profile((delay_ms, jitter_ms + 5.0, loss_pct))
    elif event.key == pygame.K_PAGEDOWN:
        pipeline.set_profile((delay_ms, jitter_ms, max(0.0, loss_pct - 0.5)))
    elif event.key == pygame.K_PAGEUP:
        pipeline.set_profile((delay_ms, jitter_ms, min(100.0, loss_pct + 0.5)))


def main(argv: list[str] | None = None) -> None:
    """Run the DT-10 ground-truth-versus-puppet visual acceptance demo."""

    parser = argparse.ArgumentParser(description="Run the DT-10 impairment visualizer")
    parser.add_argument("--trajectory", choices=TRAJECTORIES, default="lane-change")
    args = parser.parse_args(argv)

    pygame = _require_pygame()
    pygame.init()
    screen = pygame.display.set_mode(WINDOW_SIZE)
    pygame.display.set_caption("DT-10: Ground Truth vs Interpolated Puppet")
    frame_clock = pygame.time.Clock()
    pipeline = VisualizerPipeline(TRAJECTORIES[args.trajectory])
    pipeline.start()

    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False
                    else:
                        _handle_key(pygame, event, pipeline)
            _draw_frame(pygame, screen, pipeline, time.monotonic())
            pygame.display.flip()
            frame_clock.tick(60)
    finally:
        pipeline.close()
        pygame.quit()


if __name__ == "__main__":
    main()
