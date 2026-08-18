"""Encode and decode the frozen v1 per-actor state packet.

This module deliberately has one job: convert plain Python actor-state
dictionaries to and from the bytes that travel on the state plane. It has no
networking or CARLA dependency, so the same contract can be implemented by a
station, the server, the harness, or a future vehicle ingest process.

Wire layout (v1, exactly 62 bytes, little-endian, no padding)::

    <BII13fB
    version:            uint8
    actor_id:            uint32
    master_frame_seq:    uint32
    pos_x, pos_y, pos_z: float32 x3
    rot_r, rot_p, rot_y: float32 x3  (roll, pitch, yaw)
    vel_x, vel_y, vel_z: float32 x3
    ang_x, ang_y, ang_z: float32 x3
    steer_angle:         float32
    light_state:         uint8

The state uses CARLA world coordinates (left-handed, Z-up): position is in
metres, rotations and steering angle are in degrees, linear velocity is in
metres per second, and angular velocity is in degrees per second. The
``light_state`` value is a bitmask made from the ``LIGHT_*`` constants below.
Unsupported light concepts are intentionally outside v1.

``steer_angle`` and ``light_state`` are optional on input and default to zero.
All other field names are required. Add a new version rather than changing
this layout; retain the old decoder for one demo cycle when that happens.
"""

from __future__ import annotations

import math
import numbers
import struct
from typing import Any, Final


VERSION: Final = 1
"""The only packet version accepted by :func:`unpack` in this release."""

FORMAT: Final = "<BII13fB"
"""The fixed v1 ``struct`` layout: little-endian and explicitly unpadded."""

_PACKET: Final = struct.Struct(FORMAT)
PACKET_SIZE: Final = _PACKET.size
"""The size in bytes of every v1 packet (62)."""

# These values intentionally match the lower eight CARLA vehicle-light bits,
# while remaining a protocol-owned, CARLA-independent representation.
LIGHT_POSITION: Final = 1 << 0
LIGHT_LOW_BEAM: Final = 1 << 1
LIGHT_HIGH_BEAM: Final = 1 << 2
LIGHT_BRAKE: Final = 1 << 3
LIGHT_RIGHT_BLINKER: Final = 1 << 4
LIGHT_LEFT_BLINKER: Final = 1 << 5
LIGHT_REVERSE: Final = 1 << 6
LIGHT_FOG: Final = 1 << 7

_REQUIRED_INTEGER_FIELDS: Final = ("actor_id", "master_frame_seq")
_REQUIRED_FLOAT_FIELDS: Final = (
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
)


def _uint(value: Any, field: str, maximum: int) -> int:
    """Validate and return an unsigned integral field.

    Booleans are rejected even though Python models them as integers: accepting
    them would hide a caller bug in an identifier, sequence number, or mask.
    """

    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise ValueError(f"{field} must be an integer")
    value = int(value)
    if not 0 <= value <= maximum:
        raise ValueError(f"{field} must be in the range 0..{maximum}")
    return value


def _finite_float(value: Any, field: str) -> float:
    """Validate and return a finite numeric field as a Python float."""

    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{field} must be a finite real number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{field} must be a finite real number")
    return value


def pack(actor_state: dict) -> bytes:
    """Serialize one v1 actor-state dictionary into a 62-byte packet.

    Required keys are ``actor_id``, ``master_frame_seq``, and the 12 pose and
    velocity names documented in the module layout. ``steer_angle`` and
    ``light_state`` default to ``0.0`` and ``0`` respectively.
    """

    if not isinstance(actor_state, dict):
        raise TypeError("actor_state must be a dict")

    try:
        actor_id, master_frame_seq = (
            _uint(actor_state[field], field, 0xFFFFFFFF)
            for field in _REQUIRED_INTEGER_FIELDS
        )
        floats = tuple(
            _finite_float(actor_state[field], field) for field in _REQUIRED_FLOAT_FIELDS
        )
    except KeyError as exc:
        raise ValueError(f"missing required field: {exc.args[0]}") from None

    steer_angle = _finite_float(actor_state.get("steer_angle", 0.0), "steer_angle")
    light_state = _uint(actor_state.get("light_state", 0), "light_state", 0xFF)

    try:
        return _PACKET.pack(
            VERSION, actor_id, master_frame_seq, *floats, steer_angle, light_state
        )
    except OverflowError as exc:
        # A finite Python float can still be too large to represent as float32.
        raise ValueError("float field is outside the float32 range") from exc


def unpack(data: bytes) -> dict:
    """Decode one exact-length v1 packet into a flat actor-state dictionary."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like")

    data = bytes(data)
    if len(data) != PACKET_SIZE:
        raise ValueError(f"v1 packet must be exactly {PACKET_SIZE} bytes")

    values = _PACKET.unpack(data)
    if values[0] != VERSION:
        raise ValueError(f"unsupported wire format version: {values[0]}")

    version, actor_id, master_frame_seq, *state_values = values
    float_fields = (*_REQUIRED_FLOAT_FIELDS, "steer_angle")
    fields = (*float_fields, "light_state")
    for field, value in zip(float_fields, state_values):
        if not math.isfinite(value):
            raise ValueError(f"{field} must be a finite float32 value")
    return {
        "version": version,
        "actor_id": actor_id,
        "master_frame_seq": master_frame_seq,
        **dict(zip(fields, state_values)),
    }
