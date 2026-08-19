"""harness.publisher — synthetic actor-state publisher, no CARLA required.

One job: emit dtnet.wire-packed packets at 60 Hz, sequence-numbered, for a
small set of known analytic trajectories, so dtnet/ and station/ can be
built and tested before server/ exists.

Trajectories to implement (per the sprint doc):
  - constant velocity
  - hard brake from 15 m/s
  - lane change

This is the module station.puppets points at until week 3, when it's
replaced by server.relay behind the same dtnet.wire format.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

from dtnet import wire


_CRUISE_SPEED_MPS = 15.0
_BRAKE_DECELERATION_MPS2 = 8.0
_LANE_WIDTH_M = 3.5
_LANE_CHANGE_DURATION_S = 3.0


def _base_state(*, actor_id: int, pos_x: float, pos_y: float, vel_x: float,
                vel_y: float = 0.0, yaw_deg: float = 0.0,
                ang_z_deg_s: float = 0.0, light_state: int = 0) -> dict:
    """Build a complete v1 actor state shared by the analytic trajectories."""

    return {
        "actor_id": actor_id,
        # SyntheticPublisher assigns the authoritative sequence immediately
        # before packing. Keeping this key here makes trajectories independently
        # encodable in unit tests and useful to direct harness consumers.
        "master_frame_seq": 0,
        "pos_x": pos_x,
        "pos_y": pos_y,
        "pos_z": 0.0,
        "rot_r": 0.0,
        "rot_p": 0.0,
        "rot_y": yaw_deg,
        "vel_x": vel_x,
        "vel_y": vel_y,
        "vel_z": 0.0,
        "ang_x": 0.0,
        "ang_y": 0.0,
        "ang_z": ang_z_deg_s,
        "steer_angle": 0.0,
        "light_state": light_state,
    }


def _elapsed(t: float) -> float:
    """Keep trajectories defined before their zero-time starting point."""

    return max(0.0, float(t))


def constant_velocity_trajectory(t: float) -> dict:
    """A vehicle travelling straight at 15 m/s along the CARLA X axis."""

    t = _elapsed(t)
    return _base_state(actor_id=1, pos_x=_CRUISE_SPEED_MPS * t, pos_y=0.0,
                       vel_x=_CRUISE_SPEED_MPS)


def hard_brake_trajectory(t: float) -> dict:
    """A straight-line 15 m/s vehicle applying a constant 8 m/s² brake.

    The vehicle comes to rest after 1.875 seconds and holds its final pose.
    That hold is deliberate: consumers must never see a negative velocity or a
    backwards correction after the hard-brake portion of the trace.
    """

    t = _elapsed(t)
    stop_time = _CRUISE_SPEED_MPS / _BRAKE_DECELERATION_MPS2
    moving_time = min(t, stop_time)
    velocity = max(0.0, _CRUISE_SPEED_MPS - _BRAKE_DECELERATION_MPS2 * t)
    position = (
        _CRUISE_SPEED_MPS * moving_time
        - 0.5 * _BRAKE_DECELERATION_MPS2 * moving_time**2
    )
    brake_lights = wire.LIGHT_BRAKE if t < stop_time else 0
    return _base_state(actor_id=2, pos_x=position, pos_y=0.0, vel_x=velocity,
                       light_state=brake_lights)


def lane_change_trajectory(t: float) -> dict:
    """A smooth 3.5 m lane change while maintaining a 15 m/s forward speed.

    A cubic smoothstep gives zero lateral velocity at the start and end, so
    the trace is physically continuous without an artificial heading snap.
    """

    t = _elapsed(t)
    u = min(t / _LANE_CHANGE_DURATION_S, 1.0)
    smoothstep = 3.0 * u**2 - 2.0 * u**3
    pos_y = _LANE_WIDTH_M * smoothstep
    if u < 1.0:
        vel_y = _LANE_WIDTH_M * (6.0 * u - 6.0 * u**2) / _LANE_CHANGE_DURATION_S
        accel_y = _LANE_WIDTH_M * (6.0 - 12.0 * u) / _LANE_CHANGE_DURATION_S**2
    else:
        vel_y = 0.0
        accel_y = 0.0

    yaw_rad = math.atan2(vel_y, _CRUISE_SPEED_MPS)
    # d/dt atan(v_y / v_x), with v_x constant for this trajectory.
    yaw_rate_rad_s = (
        _CRUISE_SPEED_MPS * accel_y / (_CRUISE_SPEED_MPS**2 + vel_y**2)
    )
    return _base_state(
        actor_id=3,
        pos_x=_CRUISE_SPEED_MPS * t,
        pos_y=pos_y,
        vel_x=_CRUISE_SPEED_MPS,
        vel_y=vel_y,
        yaw_deg=math.degrees(yaw_rad),
        ang_z_deg_s=math.degrees(yaw_rate_rad_s),
    )


class SyntheticPublisher:
    def __init__(self, trajectory_fn, hz: int = 60):
        if not callable(trajectory_fn):
            raise TypeError("trajectory_fn must be callable")
        if isinstance(hz, bool) or not isinstance(hz, int) or hz <= 0:
            raise ValueError("hz must be a positive integer")

        self.trajectory_fn: Callable[[float], dict] = trajectory_fn
        self.hz = hz

    def _packet(self, elapsed_s: float, frame_seq: int) -> bytes:
        """Encode one trajectory sample with its publisher-owned sequence."""

        state = dict(self.trajectory_fn(elapsed_s))
        state["master_frame_seq"] = frame_seq
        return wire.pack(state)

    def run(self, send_fn, *, stop_event: threading.Event | None = None) -> None:
        """Call ``send_fn`` at the configured rate until stopped, if requested."""
        if not callable(send_fn):
            raise TypeError("send_fn must be callable")
        if stop_event is not None and not isinstance(stop_event, threading.Event):
            raise TypeError("stop_event must be a threading.Event or None")

        period_s = 1.0 / self.hz
        started_at = time.monotonic()
        next_send_at = started_at
        frame_seq = 0

        while True:
            if stop_event is not None and stop_event.is_set():
                return
            now = time.monotonic()
            if now < next_send_at:
                wait_s = next_send_at - now
                if stop_event is None:
                    time.sleep(wait_s)
                elif stop_event.wait(wait_s):
                    return

            now = time.monotonic()
            if stop_event is not None and stop_event.is_set():
                return
            send_fn(self._packet(now - started_at, frame_seq))
            frame_seq += 1
            next_send_at = started_at + frame_seq * period_s

            # Do not burst queued packets after a slow consumer or scheduler
            # pause. Preserve the 60 Hz wall-clock cadence and advance the
            # sequence to the current frame instead.
            if now > next_send_at:
                skipped_frames = int((now - next_send_at) / period_s) + 1
                frame_seq += skipped_frames
                next_send_at = started_at + frame_seq * period_s
