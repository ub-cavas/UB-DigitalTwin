"""Best-effort 60 Hz ego-state sender for one wheel station."""

from __future__ import annotations

import argparse
import math
import os
import socket
from dataclasses import dataclass
from typing import Any, Final

from dtnet import wire


DEFAULT_SERVER_HOST: Final = "127.0.0.1"
DEFAULT_SERVER_PORT: Final = 5006


def _environment_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {value!r}") from error


@dataclass(frozen=True)
class UplinkEndpoint:
    """The authoritative server's UDP ego-state endpoint."""

    host: str = DEFAULT_SERVER_HOST
    port: int = DEFAULT_SERVER_PORT

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host:
            raise ValueError("host must be a non-empty string")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ValueError("port must be an integer from 1 through 65535")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer from 1 through 65535")

    @property
    def address(self) -> tuple[str, int]:
        return self.host, self.port


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the station's server-uplink destination controls."""

    parser.add_argument(
        "--uplink-server-host",
        default=os.environ.get("UB_UPLINK_SERVER_HOST", DEFAULT_SERVER_HOST),
        help="Authoritative server UDP host for ego states (default: %(default)s)",
    )
    parser.add_argument(
        "--uplink-server-port",
        type=int,
        default=_environment_int("UB_UPLINK_SERVER_PORT", DEFAULT_SERVER_PORT),
        help="Authoritative server UDP port for ego states (default: %(default)s)",
    )


def endpoint_from_namespace(args: argparse.Namespace) -> UplinkEndpoint:
    return UplinkEndpoint(args.uplink_server_host, args.uplink_server_port)


class StationUplink:
    """Encode a local ego's post-tick state and send it without blocking."""

    def __init__(self, endpoint: UplinkEndpoint):
        if not isinstance(endpoint, UplinkEndpoint):
            raise TypeError("endpoint must be a UplinkEndpoint")
        self._endpoint = endpoint
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._closed = False

    def send_actor_snapshot(self, actor_snapshot: Any, frame_seq: int) -> None:
        """Send one v1 state packet constructed from a post-tick actor snapshot."""

        state = self._state_from_actor_snapshot(actor_snapshot, frame_seq)
        self._socket.sendto(wire.pack(state), self._endpoint.address)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._socket.close()

    @staticmethod
    def _state_from_actor_snapshot(actor_snapshot: Any, frame_seq: int) -> dict:
        if isinstance(frame_seq, bool) or not isinstance(frame_seq, int):
            raise ValueError("frame_seq must be an integer")
        if not 0 <= frame_seq <= 0xFFFFFFFF:
            raise ValueError("frame_seq must be in the range 0..4294967295")

        transform = actor_snapshot.get_transform()
        location = transform.location
        rotation = transform.rotation
        velocity = actor_snapshot.get_velocity()
        angular_velocity = actor_snapshot.get_angular_velocity()
        values = (
            location.x, location.y, location.z,
            rotation.roll, rotation.pitch, rotation.yaw,
            velocity.x, velocity.y, velocity.z,
            angular_velocity.x, angular_velocity.y, angular_velocity.z,
        )
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise ValueError("actor snapshot must contain finite numeric state")
        return {
            "actor_id": actor_snapshot.id,
            "master_frame_seq": frame_seq,
            "pos_x": location.x,
            "pos_y": location.y,
            "pos_z": location.z,
            "rot_r": rotation.roll,
            "rot_p": rotation.pitch,
            "rot_y": rotation.yaw,
            "vel_x": velocity.x,
            "vel_y": velocity.y,
            "vel_z": velocity.z,
            "ang_x": angular_velocity.x,
            "ang_y": angular_velocity.y,
            "ang_z": angular_velocity.z,
            "steer_angle": 0.0,
            "light_state": 0,
        }
