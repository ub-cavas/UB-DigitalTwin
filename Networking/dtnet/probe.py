"""Small versioned UDP echo probes used for station link telemetry.

This is deliberately separate from the frozen actor-state ``wire`` v1
packet.  A probe contains only a sequence number; the responder echoes the
exact datagram so the station can measure the round trip locally.
"""

from __future__ import annotations

import struct
from typing import Final


MAGIC: Final = b"DTNP"
VERSION: Final = 1
_FORMAT: Final = struct.Struct("!4sBI")
PACKET_SIZE: Final = _FORMAT.size
MAX_SEQUENCE: Final = 0xFFFFFFFF


def pack(sequence: int) -> bytes:
    """Return one validated, versioned probe request."""

    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise ValueError("probe sequence must be a uint32 integer")
    if not 0 <= sequence <= MAX_SEQUENCE:
        raise ValueError("probe sequence must be a uint32 integer")
    return _FORMAT.pack(MAGIC, VERSION, sequence)


def unpack(packet: bytes) -> int:
    """Validate a probe request or reply and return its sequence."""

    if not isinstance(packet, bytes):
        raise TypeError("probe packet must be bytes")
    if len(packet) != PACKET_SIZE:
        raise ValueError(f"probe packet must be exactly {PACKET_SIZE} bytes")
    magic, version, sequence = _FORMAT.unpack(packet)
    if magic != MAGIC:
        raise ValueError("unrecognized probe magic")
    if version != VERSION:
        raise ValueError(f"unsupported probe version {version}")
    return sequence
