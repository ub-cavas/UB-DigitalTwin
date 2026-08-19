"""dtnet.interp — ring buffer + interpolation + bounded extrapolation.

One job: given a stream of timestamped poses for one actor and a target
render time (from dtnet.clock), produce the pose to draw right now.

Normal path: buffer 2-3 packets, interpolate between the two that bracket
(estimated_master_time - render_delay). Puppets are shown slightly in the
past, but smoothly.

Fallback path: for a genuinely late packet only. Extrapolate along the last
known linear and angular velocities for at most 200 ms, then hold that
projected pose. This prevents a long outage from becoming unbounded drift.

Acceptance (informal, for this sprint): no single-frame position
correction ("snap") visible to the eye, and no velocity sign reversal
during a hard-brake trajectory played through the harness.
"""

from __future__ import annotations

import bisect
import math
import numbers
from dataclasses import dataclass
from typing import Any, Final

from dtnet import wire
from dtnet.clock import FRAME_RATE_HZ


EXTRAPOLATION_HORIZON_S: Final = 0.2
"""Maximum duration for velocity-based extrapolation after the newest packet."""

EXTRAPOLATION_HORIZON_FRAMES: Final = EXTRAPOLATION_HORIZON_S * FRAME_RATE_HZ

_CONTINUOUS_FIELDS: Final = (
    "pos_x",
    "pos_y",
    "pos_z",
    "rot_r",
    "rot_p",
    "rot_y",
    "vel_x",
    "vel_y",
    "vel_z",
    "ang_x",
    "ang_y",
    "ang_z",
    "steer_angle",
)


@dataclass(frozen=True)
class _Sample:
    """One canonical decoded wire state, indexed by master-frame time."""

    master_time: float
    pose: dict


def _finite_real(value: Any, field: str) -> float:
    """Validate a finite numeric value and return it as a float."""

    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{field} must be a finite real number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{field} must be a finite real number")
    return value


class PuppetInterpolator:
    """Smoothly render one actor's decoded v1 states on the master timeline.

    ``master_time`` and ``render_time`` are frame values, not seconds. The
    constructor takes seconds only because render-delay tuning is naturally
    specified in milliseconds; it is converted using the fixed 60 Hz master
    tick rate before any comparisons are made.
    """

    def __init__(self, render_delay_s: float):
        render_delay_s = _finite_real(render_delay_s, "render_delay_s")
        if render_delay_s < 0:
            raise ValueError("render_delay_s must be non-negative")

        self._render_delay_frames = render_delay_s * FRAME_RATE_HZ
        self._samples: list[_Sample] = []

    @property
    def buffered_sample_count(self) -> int:
        """The number of retained samples available for interpolation."""

        return len(self._samples)

    def on_packet(self, recv_time: float, master_time: float, pose: dict) -> None:
        """Feed one decoded packet (post dtnet.wire.unpack) in."""

        # ``recv_time`` is deliberately validated despite not affecting sample
        # ordering: delayed UDP delivery must never supersede master time.
        _finite_real(recv_time, "recv_time")
        master_time = _finite_real(master_time, "master_time")
        canonical_pose = wire.unpack(wire.pack(pose))

        times = [sample.master_time for sample in self._samples]
        index = bisect.bisect_left(times, master_time)
        sample = _Sample(master_time, canonical_pose)
        if index < len(self._samples) and self._samples[index].master_time == master_time:
            self._samples[index] = sample
        else:
            self._samples.insert(index, sample)

    def pose_at(self, render_time: float) -> dict:
        """The pose to draw right now, interpolated or (bounded) extrapolated."""

        render_time = _finite_real(render_time, "render_time")
        if not self._samples:
            raise RuntimeError("puppet interpolator has not received a packet")

        target_time = render_time - self._render_delay_frames
        times = [sample.master_time for sample in self._samples]
        right_index = bisect.bisect_right(times, target_time)

        if right_index == 0:
            return dict(self._samples[0].pose)
        if right_index == len(self._samples):
            result = self._extrapolate(self._samples[-1], target_time)
            self._discard_superseded_samples(len(self._samples) - 1)
            return result

        left = self._samples[right_index - 1]
        right = self._samples[right_index]
        result = self._interpolate(left, right, target_time)
        self._discard_superseded_samples(right_index - 1)
        return result

    @staticmethod
    def _interpolate(left: _Sample, right: _Sample, target_time: float) -> dict:
        """Interpolate continuous fields, retaining discrete state from left."""

        fraction = (target_time - left.master_time) / (right.master_time - left.master_time)
        result = dict(left.pose)
        for field in _CONTINUOUS_FIELDS:
            result[field] = left.pose[field] + fraction * (right.pose[field] - left.pose[field])
        return result

    @staticmethod
    def _extrapolate(sample: _Sample, target_time: float) -> dict:
        """Project a pose for a bounded horizon and then hold it indefinitely."""

        elapsed_frames = min(
            max(0.0, target_time - sample.master_time),
            EXTRAPOLATION_HORIZON_FRAMES,
        )
        elapsed_s = elapsed_frames / FRAME_RATE_HZ
        result = dict(sample.pose)
        for axis in ("x", "y", "z"):
            result[f"pos_{axis}"] += sample.pose[f"vel_{axis}"] * elapsed_s
        for rotation_axis, angular_axis in (("r", "x"), ("p", "y"), ("y", "z")):
            result[f"rot_{rotation_axis}"] += sample.pose[f"ang_{angular_axis}"] * elapsed_s
        return result

    def _discard_superseded_samples(self, left_index: int) -> None:
        """Keep the active interpolation bracket, or only the newest sample.

        Rendering proceeds monotonically in normal use.  Once a target has
        consumed a sample as its left bracket, older samples can never affect a
        future frame and are removed, making this a bounded ring buffer.
        """

        if len(self._samples) < 2:
            return

        # The left side of the just-used interval must remain as the bracket
        # for the next render. Every older sample can no longer contribute.
        if left_index > 0:
            del self._samples[:left_index]
