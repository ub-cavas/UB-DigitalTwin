"""Receive one station's ego state and apply it as a server-world puppet."""

from __future__ import annotations

import argparse
import logging
import math
import os
import queue
import socket
import threading
from dataclasses import dataclass
from typing import Any, Final

from dtnet import wire


DEFAULT_BIND_HOST: Final = "0.0.0.0"
DEFAULT_PORT: Final = 5006
DEFAULT_PUPPET_ROLE_NAME: Final = "dt_station_puppet"
DEFAULT_PUPPET_BLUEPRINT: Final = "vehicle.lincoln.mkz_2020"
PUPPET_FALLBACK_SPAWN_HEIGHT_M: Final = 50.0
_LOG = logging.getLogger(__name__)


def _environment_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {value!r}") from error


@dataclass(frozen=True)
class UplinkConfig:
    bind_host: str = DEFAULT_BIND_HOST
    port: int = DEFAULT_PORT
    puppet_role_name: str = DEFAULT_PUPPET_ROLE_NAME
    puppet_blueprint: str = DEFAULT_PUPPET_BLUEPRINT

    def __post_init__(self) -> None:
        for name, value in (
            ("bind_host", self.bind_host),
            ("puppet_role_name", self.puppet_role_name),
            ("puppet_blueprint", self.puppet_blueprint),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ValueError("port must be an integer from 1 through 65535")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer from 1 through 65535")

    @property
    def address(self) -> tuple[str, int]:
        return self.bind_host, self.port


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    """Register master controls for its station ego-state receiver and puppet."""

    parser.add_argument(
        "--uplink-bind-host",
        default=os.environ.get("UB_UPLINK_BIND_HOST", DEFAULT_BIND_HOST),
        help="UDP bind host for station ego states (default: %(default)s)",
    )
    parser.add_argument(
        "--uplink-port",
        type=int,
        default=_environment_int("UB_UPLINK_PORT", DEFAULT_PORT),
        help="UDP port for station ego states (default: %(default)s)",
    )
    parser.add_argument(
        "--uplink-puppet-role-name",
        default=os.environ.get("UB_UPLINK_PUPPET_ROLE_NAME", DEFAULT_PUPPET_ROLE_NAME),
        help="Stable role_name for the server-side station puppet (default: %(default)s)",
    )
    parser.add_argument(
        "--uplink-puppet-blueprint",
        default=os.environ.get("UB_UPLINK_PUPPET_BLUEPRINT", DEFAULT_PUPPET_BLUEPRINT),
        help="CARLA blueprint for the server-side station puppet (default: %(default)s)",
    )


def config_from_namespace(args: argparse.Namespace) -> UplinkConfig:
    return UplinkConfig(
        bind_host=args.uplink_bind_host,
        port=args.uplink_port,
        puppet_role_name=args.uplink_puppet_role_name,
        puppet_blueprint=args.uplink_puppet_blueprint,
    )


def _sequence_is_newer(sequence: int, previous: int) -> bool:
    """Compare wrapping uint32 frame sequences without treating equality as new."""

    difference = (sequence - previous) & 0xFFFFFFFF
    return 0 < difference < 0x80000000


class ServerPuppet:
    """Master-thread-only puppet owner with one-step dead reckoning."""

    def __init__(self, world: Any, carla: Any, config: UplinkConfig, *, fixed_delta_seconds: float):
        if not isinstance(fixed_delta_seconds, (int, float)) or not math.isfinite(fixed_delta_seconds) or fixed_delta_seconds <= 0:
            raise ValueError("fixed_delta_seconds must be a positive finite real number")
        self._world = world
        self._carla = carla
        self._config = config
        self._fixed_delta_seconds = float(fixed_delta_seconds)
        self._actor: Any | None = None
        self._owned = False
        self._state: dict | None = None
        self._fresh_state = False

    @property
    def actor_id(self) -> int | None:
        """The managed actor's ephemeral CARLA ID, when it has been created."""

        actor = self._actor
        return None if actor is None else int(actor.id)

    def on_state(self, state: dict) -> None:
        self._state = dict(state)
        self._fresh_state = True

    def advance(self) -> None:
        """Apply the newest pose, or extrapolate exactly one authoritative frame."""

        if self._state is None:
            return
        if self._actor is None:
            self._actor = self._find_existing_puppet()
            if self._actor is None:
                self._actor = self._spawn_puppet(self._state)
                self._owned = self._actor is not None
            if self._actor is None:
                return
            self._actor.set_simulate_physics(False)

        if not self._fresh_state:
            self._dead_reckon()
        self._actor.set_transform(self._transform_from_state(self._state))
        self._fresh_state = False

    def close(self) -> None:
        actor, self._actor = self._actor, None
        owned, self._owned = self._owned, False
        self._state = None
        self._fresh_state = False
        if owned and actor is not None:
            actor.destroy()

    def _find_existing_puppet(self) -> Any | None:
        for actor in self._world.get_actors():
            attributes = getattr(actor, "attributes", {})
            if attributes.get("role_name") == self._config.puppet_role_name:
                return actor
        return None

    def _spawn_puppet(self, state: dict) -> Any | None:
        blueprint = self._world.get_blueprint_library().find(self._config.puppet_blueprint)
        if blueprint.has_attribute("role_name"):
            blueprint.set_attribute("role_name", self._config.puppet_role_name)
        actor = self._world.try_spawn_actor(blueprint, self._transform_from_state(state))
        if actor is None:
            # Traffic may already occupy the station ego's initial map pose.
            # Spawn clear of traffic, disable physics in ``advance``, then set
            # the exact authoritative transform in that same master frame.
            actor = self._world.try_spawn_actor(
                blueprint,
                self._carla.Transform(
                    self._carla.Location(
                        x=state["pos_x"],
                        y=state["pos_y"],
                        z=state["pos_z"] + PUPPET_FALLBACK_SPAWN_HEIGHT_M,
                    ),
                    self._carla.Rotation(
                        roll=state["rot_r"],
                        pitch=state["rot_p"],
                        yaw=state["rot_y"],
                    ),
                ),
            )
        if actor is None:
            _LOG.warning("Unable to spawn uplink puppet %s; will retry", self._config.puppet_role_name)
        return actor

    def _dead_reckon(self) -> None:
        assert self._state is not None
        delta = self._fixed_delta_seconds
        for position, velocity in (("pos_x", "vel_x"), ("pos_y", "vel_y"), ("pos_z", "vel_z")):
            self._state[position] += self._state[velocity] * delta
        for rotation, angular_velocity in (("rot_r", "ang_x"), ("rot_p", "ang_y"), ("rot_y", "ang_z")):
            self._state[rotation] += self._state[angular_velocity] * delta

    def _transform_from_state(self, state: dict) -> Any:
        return self._carla.Transform(
            self._carla.Location(x=state["pos_x"], y=state["pos_y"], z=state["pos_z"]),
            self._carla.Rotation(roll=state["rot_r"], pitch=state["rot_p"], yaw=state["rot_y"]),
        )


class Uplink:
    """Own the UDP receive thread; apply queued packets only on the master thread."""

    def __init__(self, master: Any, config: UplinkConfig):
        self._master = master
        self._config = config
        self._packets: queue.SimpleQueue[bytes] = queue.SimpleQueue()
        self._stop_event = threading.Event()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._last_sequence: int | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("uplink is already running")
        self._stop_event.clear()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.settimeout(0.1)
        self._socket.bind(self._config.address)
        self._thread = threading.Thread(target=self._receive, name="server-uplink", daemon=True)
        self._thread.start()

    def drain_packets(self) -> None:
        """Decode queued datagrams and apply them while the master owns CARLA."""

        while True:
            try:
                self.on_packet(self._packets.get_nowait())
            except queue.Empty:
                return

    def on_packet(self, data: bytes) -> None:
        """Decode one packet and retain only a newer station-frame state."""

        try:
            state = wire.unpack(data)
        except (TypeError, ValueError) as error:
            _LOG.warning("Discarding invalid station uplink packet: %s", error)
            return
        sequence = state["master_frame_seq"]
        if self._last_sequence is not None and not _sequence_is_newer(sequence, self._last_sequence):
            return
        self._last_sequence = sequence
        self._master.apply_puppet_state(state)

    def close(self) -> None:
        self._stop_event.set()
        udp_socket, self._socket = self._socket, None
        if udp_socket is not None:
            udp_socket.close()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _receive(self) -> None:
        while not self._stop_event.is_set():
            socket_ = self._socket
            if socket_ is None:
                return
            try:
                # Read one byte beyond the fixed wire size so an oversized
                # datagram is rejected by ``wire.unpack`` rather than silently
                # accepted after OS-level truncation.
                data, _address = socket_.recvfrom(wire.PACKET_SIZE + 1)
            except socket.timeout:
                continue
            except OSError:
                return
            self._packets.put(data)
