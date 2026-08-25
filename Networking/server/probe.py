"""Best-effort UDP echo responder for station link-health probes."""

from __future__ import annotations

import argparse
import os
import socket
import threading
from dataclasses import dataclass
from typing import Final

from dtnet import probe


DEFAULT_BIND_HOST: Final = "0.0.0.0"
DEFAULT_PORT: Final = 5007


def _environment_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {value!r}") from error


@dataclass(frozen=True)
class ProbeConfig:
    bind_host: str = DEFAULT_BIND_HOST
    port: int = DEFAULT_PORT

    def __post_init__(self) -> None:
        if not isinstance(self.bind_host, str) or not self.bind_host:
            raise ValueError("bind_host must be a non-empty string")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer from 1 through 65535")

    @property
    def address(self) -> tuple[str, int]:
        return self.bind_host, self.port


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--relay-probe-bind-host",
        default=os.environ.get("UB_RELAY_PROBE_BIND_HOST", DEFAULT_BIND_HOST),
        help="UDP bind host for station probe echoes (default: %(default)s)",
    )
    parser.add_argument(
        "--relay-probe-port",
        type=int,
        default=_environment_int("UB_RELAY_PROBE_PORT", DEFAULT_PORT),
        help="UDP port for station probe echoes (default: %(default)s)",
    )


def config_from_namespace(args: argparse.Namespace) -> ProbeConfig:
    return ProbeConfig(args.relay_probe_bind_host, args.relay_probe_port)


class ProbeResponder:
    """Echo valid probes on a daemon thread, outside the CARLA master tick."""

    def __init__(self, config: ProbeConfig):
        self._config = config
        self._stop_event = threading.Event()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("probe responder is already running")
        self._stop_event.clear()
        socket_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        socket_.settimeout(0.1)
        socket_.bind(self._config.address)
        self._socket = socket_
        self._thread = threading.Thread(target=self._run, name="relay-probe", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        socket_, self._socket = self._socket, None
        if socket_ is not None:
            socket_.close()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            socket_ = self._socket
            if socket_ is None:
                return
            try:
                data, address = socket_.recvfrom(probe.PACKET_SIZE + 1)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                reply = self.on_packet(data)
                if reply is not None:
                    socket_.sendto(reply, address)
            except OSError:
                # This path is advisory only; invalid/lost probes never affect
                # the authoritative CARLA clock.
                continue

    @staticmethod
    def on_packet(data: bytes) -> bytes | None:
        """Return an echo for one valid probe, or reject the datagram."""

        try:
            probe.unpack(data)
        except (TypeError, ValueError):
            return None
        return data
