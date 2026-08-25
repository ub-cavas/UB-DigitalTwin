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
from dtnet.metrics import LinkMetrics
from harness.publisher import (
    constant_velocity_trajectory,
    hard_brake_trajectory,
    lane_change_trajectory,
)
from station.camera import EgoCamera
from station.puppets import PuppetManager
from station.synthetic_feed import SyntheticPuppetFeed, place_trajectory
from station.uplink import (
    StationUplink,
    add_cli_arguments as add_uplink_cli_arguments,
    endpoint_from_namespace as uplink_endpoint_from_namespace,
)
from station.wheel import WheelInput


FIXED_DELTA_SECONDS: Final = 1.0 / FRAME_RATE_HZ
"""The fixed local simulation step shared by every station."""

DEFAULT_CLIENT_TIMEOUT_S: Final = 10.0
DEFAULT_EGO_BLUEPRINT: Final = "vehicle.lincoln.mkz_2020"
DEFAULT_EGO_ROLE_NAME: Final = "dt_station_ego"
DEFAULT_REMOTE_START_BEHIND_M: Final = 25.0
DEFAULT_REMOTE_LATERAL_OFFSET_M: Final = 3.5

SYNTHETIC_TRAJECTORIES: Final = {
    "constant": constant_velocity_trajectory,
    "brake": hard_brake_trajectory,
    "lane-change": lane_change_trajectory,
}


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

    def tick(
        self,
        *,
        before_tick: Callable[[], None] | None = None,
        after_tick: Callable[[], None] | None = None,
    ) -> int:
        """Pace and issue one local ``world.tick()``, returning CARLA's frame."""

        if self._next_deadline is None:
            raise RuntimeError("local station clock has not been started")
        if before_tick is not None and not callable(before_tick):
            raise TypeError("before_tick must be callable or None")
        if after_tick is not None and not callable(after_tick):
            raise TypeError("after_tick must be callable or None")

        remaining = self._next_deadline - self._monotonic()
        if remaining > 0:
            self._sleep(remaining)

        if before_tick is not None:
            before_tick()
        frame = self._world.tick()
        if after_tick is not None:
            after_tick()
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

    def run(
        self,
        duration_s: float | None = None,
        *,
        before_tick: Callable[[], None] | None = None,
        after_tick: Callable[[], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> int:
        """Run until interrupted or ``duration_s`` expires, then restore settings."""

        if duration_s is not None:
            duration_s = _positive_real(duration_s, "duration_s")
        if before_tick is not None and not callable(before_tick):
            raise TypeError("before_tick must be callable or None")
        if after_tick is not None and not callable(after_tick):
            raise TypeError("after_tick must be callable or None")
        if should_stop is not None and not callable(should_stop):
            raise TypeError("should_stop must be callable or None")

        self.start()
        started_at = self._monotonic()
        frames = 0
        try:
            while duration_s is None or self._monotonic() - started_at < duration_s:
                if should_stop is not None and should_stop():
                    break
                self.tick(before_tick=before_tick, after_tick=after_tick)
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
        description="Run the dedicated local CARLA clock for one keyboard station."
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
    parser.add_argument(
        "--ego-blueprint", default=os.environ.get("UB_STATION_EGO_BLUEPRINT", DEFAULT_EGO_BLUEPRINT),
        help="CARLA blueprint for the physics-enabled local ego.",
    )
    parser.add_argument(
        "--ego-role-name", default=os.environ.get("UB_STATION_EGO_ROLE_NAME", DEFAULT_EGO_ROLE_NAME),
        help="CARLA role_name assigned to the station ego.",
    )
    parser.add_argument(
        "--spawn-index", type=int, default=int(os.environ.get("UB_STATION_SPAWN_INDEX", "0")),
        help="Preferred map spawn point; later points are tried if it is occupied.",
    )
    parser.add_argument(
        "--remote-trajectory",
        choices=sorted(SYNTHETIC_TRAJECTORIES),
        default="constant",
        help="Synthetic remote vehicle motion for the DT-19 local acceptance run.",
    )
    parser.add_argument(
        "--remote-start-behind-m",
        type=float,
        default=DEFAULT_REMOTE_START_BEHIND_M,
        help="Place the synthetic remote this many metres behind the ego (default: %(default)s).",
    )
    parser.add_argument(
        "--remote-lateral-offset-m",
        type=float,
        default=DEFAULT_REMOTE_LATERAL_OFFSET_M,
        help="Place the synthetic remote this many metres to the ego's side (default: %(default)s).",
    )
    add_uplink_cli_arguments(parser)
    return parser


def spawn_station_ego(
    world: Any,
    *,
    blueprint_id: str,
    role_name: str,
    spawn_index: int,
) -> Any:
    """Spawn one physics-enabled ego, trying every map point after the preferred one."""

    if not isinstance(blueprint_id, str) or not blueprint_id:
        raise ValueError("blueprint_id must be a non-empty string")
    if not isinstance(role_name, str) or not role_name:
        raise ValueError("role_name must be a non-empty string")
    if isinstance(spawn_index, bool) or not isinstance(spawn_index, int):
        raise ValueError("spawn_index must be an integer")

    blueprint = world.get_blueprint_library().find(blueprint_id)
    if blueprint.has_attribute("role_name"):
        blueprint.set_attribute("role_name", role_name)

    spawn_points = list(world.get_map().get_spawn_points())
    if not spawn_points:
        raise RuntimeError("the current CARLA map has no vehicle spawn points")
    start = spawn_index % len(spawn_points)
    for transform in spawn_points[start:] + spawn_points[:start]:
        ego = world.try_spawn_actor(blueprint, transform)
        if ego is not None:
            ego.set_simulate_physics(True)
            return ego
    raise RuntimeError("unable to spawn the station ego at any map spawn point")


def _vehicle_control(carla: Any, control: dict) -> Any:
    """Translate the input-slot representation to CARLA's local control type."""

    gear = int(control["gear"])
    return carla.VehicleControl(
        throttle=max(0.0, min(1.0, float(control["throttle"]))),
        brake=max(0.0, min(1.0, float(control["brake"]))),
        steer=max(-1.0, min(1.0, float(control["steer"]))),
        gear=gear,
        reverse=gear < 0,
        hand_brake=bool(control["hand_brake"]),
    )


def synthetic_remote_origin(
    ego: Any,
    *,
    behind_m: float,
    lateral_offset_m: float,
) -> tuple[float, float, float, float]:
    """Return a road-relative start for the scripted vehicle that passes the ego."""

    behind_m = _positive_real(behind_m, "remote_start_behind_m")
    if isinstance(lateral_offset_m, bool) or not isinstance(lateral_offset_m, numbers.Real):
        raise ValueError("remote_lateral_offset_m must be a finite real number")
    lateral_offset_m = float(lateral_offset_m)
    if not math.isfinite(lateral_offset_m):
        raise ValueError("remote_lateral_offset_m must be a finite real number")

    transform = ego.get_transform()
    location, rotation = transform.location, transform.rotation
    yaw_deg = float(rotation.yaw)
    yaw_rad = math.radians(yaw_deg)
    forward_x, forward_y = math.cos(yaw_rad), math.sin(yaw_rad)
    right_x, right_y = -math.sin(yaw_rad), math.cos(yaw_rad)
    return (
        float(location.x) - behind_m * forward_x + lateral_offset_m * right_x,
        float(location.y) - behind_m * forward_y + lateral_offset_m * right_y,
        float(location.z),
        yaw_deg,
    )


def main(argv: list[str] | None = None) -> int:
    """Connect to a dedicated local CARLA server and run its station clock."""

    args = _parser().parse_args(argv)
    timeout = _positive_real(args.timeout, "timeout")
    if args.duration is not None:
        _positive_real(args.duration, "duration")
    _positive_real(args.remote_start_behind_m, "remote_start_behind_m")
    if not math.isfinite(args.remote_lateral_offset_m):
        raise ValueError("remote_lateral_offset_m must be a finite real number")

    # Import only for the runnable station entrypoint; isolated timing tests
    # and shared dtnet code do not require a local CARLA wheel installation.
    carla = importlib.import_module("carla")
    client = carla.Client(args.host, args.port)
    client.set_timeout(timeout)
    world = client.get_world()
    clock = LocalStationClock(world)
    ego = None
    camera = None
    input_source = None
    feed = None
    puppets = None
    uplink = None
    metrics = LinkMetrics()

    try:
        ego = spawn_station_ego(
            world,
            blueprint_id=args.ego_blueprint,
            role_name=args.ego_role_name,
            spawn_index=args.spawn_index,
        )
        uplink = StationUplink(uplink_endpoint_from_namespace(args))
        origin_x, origin_y, origin_z, heading_yaw_deg = synthetic_remote_origin(
            ego,
            behind_m=args.remote_start_behind_m,
            lateral_offset_m=args.remote_lateral_offset_m,
        )
        feed = SyntheticPuppetFeed(
            place_trajectory(
                SYNTHETIC_TRAJECTORIES[args.remote_trajectory],
                origin_x=origin_x,
                origin_y=origin_y,
                origin_z=origin_z,
                heading_yaw_deg=heading_yaw_deg,
            )
        )
        puppets = PuppetManager(world, feed, carla_module=carla)
        feed.start()
        camera = EgoCamera(
            world,
            ego,
            carla_module=carla,
            telemetry_provider=metrics.snapshot,
            impairment_provider=lambda: feed.profile,
        )
        camera.start()
        input_source = WheelInput()
        input_source.start()

        def after_tick() -> None:
            snapshot = world.get_snapshot()
            local_frame = snapshot.frame
            for actor_snapshot in snapshot:
                if actor_snapshot.id == ego.id:
                    try:
                        uplink.send_actor_snapshot(actor_snapshot, local_frame)
                    except OSError:
                        # UDP delivery is deliberately best-effort and must
                        # never interfere with a driver's local simulation.
                        pass
                    break
            events, keys = camera.pump_events()
            input_source.handle_pygame_input(events, keys, camera.pygame)
            feed.handle_pygame_input(events, camera.pygame)
            render_time = feed.render_time()
            if render_time is not None:
                puppets.update(render_time)
                metrics.set_buffer_depth(puppets.buffer_depth)
            camera.render()

        frames = clock.run(
            args.duration,
            before_tick=lambda: ego.apply_control(_vehicle_control(carla, input_source.latest_control())),
            after_tick=after_tick,
            should_stop=lambda: input_source.quit_requested or camera.quit_requested,
        )
    except KeyboardInterrupt:
        return 0
    finally:
        if camera is not None:
            camera.close()
        if input_source is not None:
            input_source.close()
        if feed is not None:
            feed.close()
        if puppets is not None:
            puppets.close()
        if uplink is not None:
            uplink.close()
        if ego is not None:
            ego.destroy()

    print(f"Station ego completed {frames} frames at {FRAME_RATE_HZ:g} Hz.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
