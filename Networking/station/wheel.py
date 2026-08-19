"""station.wheel — 120 Hz keyboard input and a thread-safe latest-value slot.

DT-24 deliberately uses keyboard control only.  The ``WheelInput`` name and
control contract are retained so a physical-wheel implementation can replace
the polling backend later without changing the station tick path.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Final


INPUT_HZ: Final = 120.0
STALE_INPUT_S: Final = 0.25


def _safe_control(gear: int = 1) -> dict:
    """Return the control applied if the input source is unavailable or stale."""

    return {
        "throttle": 0.0,
        "brake": 1.0,
        "steer": 0.0,
        "gear": gear,
        "hand_brake": False,
    }


class WheelInput:
    """Keyboard-backed driver input with a non-blocking latest-control slot.

    ``device_index`` is retained for source compatibility with the planned
    physical-wheel backend but is unused by the DT-24 keyboard implementation.
    """

    def __init__(
        self,
        device_index: int = 0,
        *,
        poll_hz: float = INPUT_HZ,
        stale_input_s: float = STALE_INPUT_S,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if isinstance(device_index, bool) or not isinstance(device_index, int) or device_index < 0:
            raise ValueError("device_index must be a non-negative integer")
        if isinstance(poll_hz, bool) or not isinstance(poll_hz, (int, float)) or poll_hz <= 0:
            raise ValueError("poll_hz must be positive")
        if (
            isinstance(stale_input_s, bool)
            or not isinstance(stale_input_s, (int, float))
            or stale_input_s <= 0
        ):
            raise ValueError("stale_input_s must be positive")
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")

        self.device_index = device_index
        self._poll_period_s = 1.0 / float(poll_hz)
        self._stale_input_s = float(stale_input_s)
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._control = _safe_control()
        self._last_sample_at: float | None = None
        self._last_keyboard_at: float | None = None
        self._last_poll_at: float | None = None
        self._throttle = 0.0
        self._steer = 0.0
        self._gear = 1
        self._quit_requested = False
        self._pressed = {
            "throttle": False,
            "brake": False,
            "left": False,
            "right": False,
            "hand_brake": False,
        }

    @property
    def quit_requested(self) -> bool:
        """Whether Esc or a close-window event requested a station shutdown."""

        with self._lock:
            return self._quit_requested

    def start(self) -> None:
        """Start the 120 Hz latest-control publisher for the station window."""

        if self._thread is not None:
            raise RuntimeError("keyboard input is already running")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="station-keyboard-input",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        """Stop the latest-control publisher without touching pygame."""

        self._stop_event.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None

    def handle_pygame_input(self, events: list[Any], keys: Any, pygame: Any) -> None:
        """Ingest the camera window's keyboard state without owning its event queue."""

        now = self._monotonic()
        toggle_reverse = False
        quit_requested = False
        for event in events:
            if event.type == pygame.QUIT:
                quit_requested = True
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    quit_requested = True
                elif event.key == pygame.K_q:
                    toggle_reverse = True

        pressed = {
            "throttle": bool(keys[pygame.K_w] or keys[pygame.K_UP]),
            "brake": bool(keys[pygame.K_s] or keys[pygame.K_DOWN]),
            "left": bool(keys[pygame.K_a] or keys[pygame.K_LEFT]),
            "right": bool(keys[pygame.K_d] or keys[pygame.K_RIGHT]),
            "hand_brake": bool(keys[pygame.K_SPACE]),
        }
        with self._lock:
            self._pressed = pressed
            self._last_keyboard_at = now
            if toggle_reverse:
                self._gear *= -1
            if quit_requested:
                self._quit_requested = True

    def latest_control(self) -> dict:
        """Return the current control without blocking the station tick path."""

        with self._lock:
            if (
                self._last_sample_at is None
                or self._monotonic() - self._last_sample_at > self._stale_input_s
            ):
                return _safe_control(self._gear)
            return dict(self._control)

    def _poll_loop(self) -> None:
        next_poll_at = self._monotonic()
        while not self._stop_event.is_set():
            self._poll_once()
            next_poll_at += self._poll_period_s
            wait_s = max(0.0, next_poll_at - self._monotonic())
            self._stop_event.wait(wait_s)

    def _poll_once(self) -> None:
        """Publish one control sample from the latest station-window keyboard state."""

        now = self._monotonic()
        if self._last_poll_at is None:
            dt = self._poll_period_s
        else:
            dt = max(0.0, now - self._last_poll_at)
        self._last_poll_at = now

        with self._lock:
            keyboard_fresh = (
                self._last_keyboard_at is not None
                and now - self._last_keyboard_at <= self._stale_input_s
            )
            pressed = dict(self._pressed)
        if not keyboard_fresh:
            return

        throttle_pressed = pressed["throttle"]
        brake_pressed = pressed["brake"]
        left_pressed = pressed["left"]
        right_pressed = pressed["right"]
        hand_brake = pressed["hand_brake"]

        if throttle_pressed and not brake_pressed and not hand_brake:
            self._throttle = min(1.0, self._throttle + 1.25 * dt)
        else:
            self._throttle = max(0.0, self._throttle - 2.0 * dt)

        steer_target = -1.0 if left_pressed else 1.0 if right_pressed else 0.0
        steer_delta = max(-1.8 * dt, min(1.8 * dt, steer_target - self._steer))
        self._steer += steer_delta
        if steer_target == 0.0:
            self._steer *= max(0.0, 1.0 - 5.0 * dt)

        brake = 1.0 if hand_brake else 0.65 if brake_pressed else 0.0
        if brake:
            self._throttle = 0.0

        with self._lock:
            self._control = {
                "throttle": self._throttle,
                "brake": brake,
                "steer": self._steer,
                "gear": self._gear,
                "hand_brake": hand_brake,
            }
            self._last_sample_at = now
