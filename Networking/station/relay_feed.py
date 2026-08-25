"""Receive authoritative relay snapshots and maintain station link telemetry."""

from __future__ import annotations

import argparse
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import os
import socket
import threading
import time
from typing import Final

from dtnet import probe, wire
from dtnet.clock import ClockEstimator
from dtnet.metrics import LinkMetrics


DEFAULT_BIND_HOST: Final = "0.0.0.0"
DEFAULT_BIND_PORT: Final = 5005
DEFAULT_PROBE_SERVER_HOST: Final = "127.0.0.1"
DEFAULT_PROBE_SERVER_PORT: Final = 5007
PROBE_INTERVAL_S: Final = 1.0
MAX_QUEUED_PACKETS: Final = 120


def _environment_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {value!r}") from error


@dataclass(frozen=True)
class RelayFeedConfig:
    bind_host: str = DEFAULT_BIND_HOST
    bind_port: int = DEFAULT_BIND_PORT
    probe_server_host: str = DEFAULT_PROBE_SERVER_HOST
    probe_server_port: int = DEFAULT_PROBE_SERVER_PORT

    def __post_init__(self) -> None:
        for name, value in (("bind_host", self.bind_host), ("probe_server_host", self.probe_server_host)):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        for name, value in (("bind_port", self.bind_port), ("probe_server_port", self.probe_server_port)):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
                raise ValueError(f"{name} must be an integer from 1 through 65535")

    @property
    def bind_address(self) -> tuple[str, int]:
        return self.bind_host, self.bind_port

    @property
    def probe_server_address(self) -> tuple[str, int]:
        return self.probe_server_host, self.probe_server_port


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--relay-bind-host",
        default=os.environ.get("UB_RELAY_BIND_HOST", DEFAULT_BIND_HOST),
        help="UDP bind host for authoritative relay snapshots (default: %(default)s)",
    )
    parser.add_argument(
        "--relay-bind-port",
        type=int,
        default=_environment_int("UB_RELAY_BIND_PORT", DEFAULT_BIND_PORT),
        help="UDP bind port for authoritative relay snapshots (default: %(default)s)",
    )
    parser.add_argument(
        "--relay-probe-server-host",
        default=os.environ.get("UB_RELAY_PROBE_SERVER_HOST", DEFAULT_PROBE_SERVER_HOST),
        help="Authoritative server host for UDP probe echoes (default: %(default)s)",
    )
    parser.add_argument(
        "--relay-probe-server-port",
        type=int,
        default=_environment_int("UB_RELAY_PROBE_SERVER_PORT", DEFAULT_PROBE_SERVER_PORT),
        help="Authoritative server UDP probe port (default: %(default)s)",
    )


def config_from_namespace(args: argparse.Namespace) -> RelayFeedConfig:
    return RelayFeedConfig(
        bind_host=args.relay_bind_host,
        bind_port=args.relay_bind_port,
        probe_server_host=args.relay_probe_server_host,
        probe_server_port=args.relay_probe_server_port,
    )


def _sequence_is_newer(sequence: int, previous: int) -> bool:
    difference = (sequence - previous) & 0xFFFFFFFF
    return 0 < difference < 0x80000000


class RelayPuppetFeed:
    """Station-side, non-blocking relay source for :class:`PuppetManager`."""

    def __init__(
        self,
        config: RelayFeedConfig,
        metrics: LinkMetrics,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if not isinstance(metrics, LinkMetrics):
            raise TypeError("metrics must be a LinkMetrics instance")
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")
        self._config = config
        self._metrics = metrics
        self._monotonic = monotonic
        self._clock = ClockEstimator()
        self._packets: deque[tuple[bytes, float]] = deque(maxlen=MAX_QUEUED_PACKETS)
        self._packet_lock = threading.Lock()
        self._last_sequence_by_actor: dict[int, int] = {}
        self._pending_probes: dict[int, float] = {}
        self._pending_lock = threading.Lock()
        self._next_probe_sequence = 0
        self._stop_event = threading.Event()
        self._relay_socket: socket.socket | None = None
        self._probe_socket: socket.socket | None = None
        self._receive_thread: threading.Thread | None = None
        self._probe_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._receive_thread is not None or self._probe_thread is not None:
            raise RuntimeError("relay puppet feed is already running")
        self._stop_event.clear()
        relay_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            relay_socket.settimeout(0.1)
            relay_socket.bind(self._config.bind_address)
            probe_socket.settimeout(0.1)
        except BaseException:
            relay_socket.close()
            probe_socket.close()
            raise
        self._relay_socket = relay_socket
        self._probe_socket = probe_socket
        self._receive_thread = threading.Thread(target=self._receive_loop, name="station-relay", daemon=True)
        self._probe_thread = threading.Thread(target=self._probe_loop, name="station-probe", daemon=True)
        self._receive_thread.start()
        self._probe_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        relay_socket, self._relay_socket = self._relay_socket, None
        probe_socket, self._probe_socket = self._probe_socket, None
        for socket_ in (relay_socket, probe_socket):
            if socket_ is not None:
                socket_.close()
        for attribute in ("_receive_thread", "_probe_thread"):
            thread = getattr(self, attribute)
            setattr(self, attribute, None)
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1.0)

    def on_packet(self, data: bytes, received_at: float | None = None) -> bool:
        """Validate and enqueue one state datagram; useful for deterministic tests."""

        received_at = self._monotonic() if received_at is None else float(received_at)
        try:
            state = wire.unpack(data)
        except (TypeError, ValueError):
            return False
        actor_id = state["actor_id"]
        sequence = state["master_frame_seq"]
        with self._packet_lock:
            previous = self._last_sequence_by_actor.get(actor_id)
            if previous is not None and not _sequence_is_newer(sequence, previous):
                return False
            self._last_sequence_by_actor[actor_id] = sequence
            self._packets.append((data, received_at))
        return True

    def drain_packets(self) -> Iterable[tuple[bytes, float]]:
        """Return accepted packets once an RTT observation initializes the clock."""

        rtt_ms = self._metrics.snapshot()["rtt_ms"]
        if rtt_ms is None:
            return ()
        rtt_s = float(rtt_ms) / 1000.0
        with self._packet_lock:
            packets = tuple(self._packets)
            self._packets.clear()
        for packet, received_at in packets:
            state = wire.unpack(packet)
            self._clock.on_packet(received_at, state["master_frame_seq"], rtt_s)
        return packets

    def render_time(self) -> float | None:
        try:
            return self._clock.estimated_master_time(self._monotonic())
        except RuntimeError:
            return None

    def on_probe_reply(
        self,
        data: bytes,
        address: tuple[str, int],
        received_at: float | None = None,
    ) -> bool:
        """Accept one matching echo reply and update shared telemetry."""

        if address != self._config.probe_server_address:
            return False
        try:
            sequence = probe.unpack(data)
        except (TypeError, ValueError):
            return False
        with self._pending_lock:
            sent_at = self._pending_probes.pop(sequence, None)
        if sent_at is None:
            return False
        received_at = self._monotonic() if received_at is None else float(received_at)
        try:
            self._metrics.on_packet(sent_at, received_at, sequence)
        except ValueError:
            return False
        return True

    def _receive_loop(self) -> None:
        while not self._stop_event.is_set():
            socket_ = self._relay_socket
            if socket_ is None:
                return
            try:
                data, _address = socket_.recvfrom(wire.PACKET_SIZE + 1)
            except socket.timeout:
                continue
            except OSError:
                return
            self.on_packet(data)

    def _probe_loop(self) -> None:
        next_send = self._monotonic()
        while not self._stop_event.is_set():
            now = self._monotonic()
            if now >= next_send:
                self._send_probe(now)
                next_send = now + PROBE_INTERVAL_S
            socket_ = self._probe_socket
            if socket_ is None:
                return
            try:
                data, address = socket_.recvfrom(probe.PACKET_SIZE + 1)
            except socket.timeout:
                continue
            except OSError:
                return
            self.on_probe_reply(data, address)

    def _send_probe(self, sent_at: float) -> None:
        socket_ = self._probe_socket
        if socket_ is None:
            return
        sequence = self._next_probe_sequence
        self._next_probe_sequence = (sequence + 1) & 0xFFFFFFFF
        try:
            packet = probe.pack(sequence)
            socket_.sendto(packet, self._config.probe_server_address)
        except OSError:
            return
        with self._pending_lock:
            self._pending_probes[sequence] = sent_at
