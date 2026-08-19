"""station.camera — local ego RGB camera and the station's pygame window."""

from __future__ import annotations

import importlib
import math
import numbers
import threading
from collections.abc import Callable, Mapping
from typing import Any, Final


DEFAULT_WIDTH: Final = 1920
DEFAULT_HEIGHT: Final = 1080
DEFAULT_FOV: Final = 90.0

CHASE_VIEW: Final = "chase"
DRIVER_VIEW: Final = "driver"


class EgoCamera:
    """Render the latest local-ego camera image without blocking CARLA ticks."""

    def __init__(
        self,
        world: Any,
        ego: Any,
        *,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        fov: float = DEFAULT_FOV,
        carla_module: Any | None = None,
        pygame_module: Any | None = None,
        telemetry_provider: Callable[[], Mapping[str, Any]] | None = None,
    ):
        if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
            raise ValueError("width must be a positive integer")
        if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
            raise ValueError("height must be a positive integer")
        if isinstance(fov, bool) or not isinstance(fov, (int, float)) or not 0 < fov < 180:
            raise ValueError("fov must be between 0 and 180 degrees")
        if telemetry_provider is not None and not callable(telemetry_provider):
            raise TypeError("telemetry_provider must be callable or None")

        self._world = world
        self._ego = ego
        self.width = width
        self.height = height
        self.fov = float(fov)
        self._carla = carla_module or importlib.import_module("carla")
        self._pygame = pygame_module
        self._telemetry_provider = telemetry_provider
        self._display: Any | None = None
        self._font: Any | None = None
        self._sensor: Any | None = None
        self._view = CHASE_VIEW
        self._quit_requested = False
        self._started = False
        self._frame_lock = threading.Lock()
        self._latest_frame: tuple[int, int, bytes] | None = None

    @property
    def quit_requested(self) -> bool:
        """Whether the camera window requested station shutdown."""

        return self._quit_requested

    @property
    def view(self) -> str:
        """The active camera view name: ``chase`` or ``driver``."""

        return self._view

    @property
    def pygame(self) -> Any:
        """The lazily loaded pygame module used by the station window."""

        if self._pygame is None:
            raise RuntimeError("camera has not been started")
        return self._pygame

    def start(self) -> None:
        """Open the station window and attach the default chase-view sensor."""

        if self._started:
            raise RuntimeError("ego camera is already running")
        pygame = self._load_pygame()
        pygame.init()
        pygame.display.set_caption("UB Digital Twin station camera")
        self._display = pygame.display.set_mode((self.width, self.height))
        self._font = pygame.font.Font(None, 28)
        self._started = True
        self._spawn_sensor()

    def pump_events(self) -> tuple[list[Any], Any]:
        """Drain the sole pygame event queue and apply camera-only shortcuts."""

        if not self._started:
            raise RuntimeError("ego camera has not been started")
        events = list(self.pygame.event.get())
        for event in events:
            if event.type == self.pygame.QUIT:
                self._quit_requested = True
            elif event.type == self.pygame.KEYDOWN:
                if event.key == self.pygame.K_ESCAPE:
                    self._quit_requested = True
                elif event.key == self.pygame.K_f:
                    self.toggle_view()
        return events, self.pygame.key.get_pressed()

    def toggle_view(self) -> None:
        """Switch between the chase and driver sensor attachments."""

        if not self._started:
            raise RuntimeError("ego camera has not been started")
        self._view = DRIVER_VIEW if self._view == CHASE_VIEW else CHASE_VIEW
        self._destroy_sensor()
        with self._frame_lock:
            self._latest_frame = None
        self._spawn_sensor()

    def render(self) -> None:
        """Draw the latest camera frame (or a waiting state) and controls hint."""

        if not self._started:
            raise RuntimeError("ego camera has not been started")
        display = self._display
        assert display is not None
        display.fill((18, 22, 29))
        with self._frame_lock:
            frame = self._latest_frame
        if frame is None:
            self._draw_text("Waiting for camera frame…", (24, 24), (255, 210, 90))
        else:
            width, height, raw_data = frame
            image = self.pygame.image.frombuffer(raw_data, (width, height), "BGRA")
            display.blit(image, (0, 0))
        self._draw_telemetry()
        self._draw_text(
            "W/Up throttle  S/Down brake  A/D steer  Space full brake  "
            "Q reverse  F camera  Esc quit",
            (18, self.height - 34),
            (235, 238, 242),
        )
        self.pygame.display.flip()

    def close(self) -> None:
        """Stop and destroy only the camera sensor, then close pygame once."""

        self._destroy_sensor()
        if self._started and self._pygame is not None:
            self._pygame.quit()
        self._display = None
        self._font = None
        self._started = False

    def _load_pygame(self) -> Any:
        if self._pygame is None:
            try:
                self._pygame = importlib.import_module("pygame")
            except ImportError as exc:
                raise RuntimeError(
                    "DT-11 camera view requires pygame; install it with "
                    "`python3 -m pip install pygame`."
                ) from exc
        return self._pygame

    def _spawn_sensor(self) -> None:
        blueprint = self._world.get_blueprint_library().find("sensor.camera.rgb")
        blueprint.set_attribute("image_size_x", str(self.width))
        blueprint.set_attribute("image_size_y", str(self.height))
        blueprint.set_attribute("fov", str(self.fov))
        blueprint.set_attribute("sensor_tick", "0.0")
        transform, attachment_type = self._attachment()
        self._sensor = self._world.spawn_actor(
            blueprint,
            transform,
            attach_to=self._ego,
            attachment_type=attachment_type,
        )
        self._sensor.listen(self._on_image)

    def _attachment(self) -> tuple[Any, Any]:
        if self._view == CHASE_VIEW:
            return (
                self._carla.Transform(
                    self._carla.Location(x=-10.0, z=5.0),
                    self._carla.Rotation(pitch=-0.0),
                ),
                self._carla.AttachmentType.SpringArmGhost,
            )
        return (
            self._carla.Transform(self._carla.Location(x=1.5, z=1.6)),
            self._carla.AttachmentType.Rigid,
        )

    def _on_image(self, image: Any) -> None:
        """Store copied BGRA bytes; CARLA invokes this from a sensor callback."""

        frame = (image.width, image.height, bytes(image.raw_data))
        with self._frame_lock:
            self._latest_frame = frame

    def _destroy_sensor(self) -> None:
        sensor, self._sensor = self._sensor, None
        if sensor is None:
            return
        try:
            sensor.stop()
        finally:
            sensor.destroy()

    def _draw_text(self, text: str, position: tuple[int, int], color: tuple[int, int, int]) -> None:
        assert self._display is not None
        assert self._font is not None
        self._display.blit(self._font.render(text, True, color), position)

    def _draw_telemetry(self) -> None:
        """Render network health without allowing diagnostics to stop driving."""

        snapshot: Mapping[str, Any] = {}
        if self._telemetry_provider is not None:
            try:
                candidate = self._telemetry_provider()
                if isinstance(candidate, Mapping):
                    snapshot = candidate
            except Exception:
                # Telemetry is observational. A future probe/receiver failure
                # must never stop the local, physics-enabled ego from rendering.
                snapshot = {}

        rtt = self._format_number(snapshot.get("rtt_ms"), " ms")
        jitter = self._format_number(snapshot.get("jitter_ms"), " ms")
        loss_recent = self._format_number(snapshot.get("loss_pct"), "%")
        loss_total = self._format_number(snapshot.get("loss_total_pct"), "%")
        depth = self._format_depth(snapshot.get("buffer_depth"))
        color = (238, 241, 245)
        self._draw_text(f"RTT {rtt}   Jitter {jitter}", (24, 24), color)
        self._draw_text(f"Loss {loss_recent} (5s) / {loss_total} total", (24, 52), color)
        self._draw_text(f"Buffer {depth}", (24, 80), color)

    @staticmethod
    def _format_number(value: Any, suffix: str) -> str:
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            return "—"
        value = float(value)
        if not math.isfinite(value):
            return "—"
        return f"{value:.1f}{suffix}"

    @staticmethod
    def _format_depth(value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, numbers.Integral):
            return "—"
        return f"{int(value)} samples" if value >= 0 else "—"
