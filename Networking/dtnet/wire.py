"""dtnet.wire — the frozen per-actor state packet: pack, unpack, nothing else.

One job: given an actor's state, produce bytes that go on the wire; given
bytes off the wire, produce that state back. No networking, no CARLA types
in or out — plain Python values in, bytes out, and the reverse.

Format (v1, ~60-80 bytes, all little-endian):
    version:            uint8
    actor_id:            uint32
    master_frame_seq:    uint32
    pos_x, pos_y, pos_z:  float32 x3
    rot_r, rot_p, rot_y:  float32 x3   (roll, pitch, yaw)
    vel_x, vel_y, vel_z:  float32 x3   (linear velocity)
    ang_x, ang_y, ang_z:  float32 x3   (angular velocity)
    steer_angle:          float32       (optional; 0.0 if not applicable)
    light_state:          uint8         (bitmask; 0 if not applicable)

This spec is the actual contract. If you change a field, bump `VERSION` and
keep the old unpack path working for one demo cycle — the vehicle ingest
(not built yet) will be a second, independent implementation of this same
format, in a different language, and it must never have to guess.
"""

VERSION = 1


def pack(actor_state: dict) -> bytes:
    """actor_state -> wire bytes. Not yet implemented."""
    raise NotImplementedError


def unpack(data: bytes) -> dict:
    """wire bytes -> actor_state. Not yet implemented."""
    raise NotImplementedError
