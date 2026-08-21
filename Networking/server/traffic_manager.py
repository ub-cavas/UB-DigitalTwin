"""Master-managed CARLA Traffic Manager background traffic.

This module owns only Traffic Manager configuration and the actors that it
creates.  ``server.master.Master`` remains the sole owner of world settings
and ``world.tick()``; it invokes this lifecycle after claiming the world.
"""

from __future__ import annotations

import argparse
import os
import random
from dataclasses import dataclass
from typing import Any, Final


DEFAULT_TRAFFIC_VEHICLES: Final = 50
DEFAULT_TRAFFIC_SEED: Final = 27
DEFAULT_TRAFFIC_MANAGER_PORT: Final = 8000
BACKGROUND_TRAFFIC_ROLE_NAME: Final = "dt-background-traffic"


def _environment_int(name: str, default: int) -> int:
    """Read an integer environment override with a clear configuration error."""

    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {value!r}") from error


@dataclass(frozen=True)
class TrafficManagerConfig:
    """Configuration for master-owned CARLA Traffic Manager vehicles."""

    vehicle_count: int = DEFAULT_TRAFFIC_VEHICLES
    seed: int = DEFAULT_TRAFFIC_SEED
    port: int = DEFAULT_TRAFFIC_MANAGER_PORT

    def __post_init__(self) -> None:
        if isinstance(self.vehicle_count, bool) or not isinstance(self.vehicle_count, int):
            raise ValueError("vehicle_count must be a non-negative integer")
        if self.vehicle_count < 0:
            raise ValueError("vehicle_count must be a non-negative integer")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ValueError("port must be an integer from 1 through 65535")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer from 1 through 65535")


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the master CLI controls for background traffic."""

    parser.add_argument(
        "--traffic-vehicles",
        type=int,
        default=_environment_int("UB_TRAFFIC_VEHICLES", DEFAULT_TRAFFIC_VEHICLES),
        help="Traffic Manager vehicles to spawn; 0 disables traffic (default: %(default)s)",
    )
    parser.add_argument(
        "--traffic-seed",
        type=int,
        default=_environment_int("UB_TRAFFIC_SEED", DEFAULT_TRAFFIC_SEED),
        help="Deterministic Traffic Manager spawn seed (default: %(default)s)",
    )
    parser.add_argument(
        "--tm-port",
        type=int,
        default=_environment_int(
            "UB_TRAFFIC_MANAGER_PORT", DEFAULT_TRAFFIC_MANAGER_PORT
        ),
        help="CARLA Traffic Manager port (default: %(default)s)",
    )


def config_from_namespace(args: argparse.Namespace) -> TrafficManagerConfig:
    """Build validated traffic configuration from master CLI arguments."""

    return TrafficManagerConfig(
        vehicle_count=args.traffic_vehicles,
        seed=args.traffic_seed,
        port=args.tm_port,
    )


class BackgroundTraffic:
    """Create and later remove the Traffic Manager actors owned by one master."""

    def __init__(
        self,
        client: Any,
        world: Any,
        carla: Any,
        config: TrafficManagerConfig,
    ):
        self._client = client
        self._world = world
        self._carla = carla
        self._config = config
        self._traffic_manager: Any | None = None
        self._actor_ids: list[int] = []
        self._started = False

    @property
    def actor_ids(self) -> tuple[int, ...]:
        """The immutable IDs of actors currently owned by this lifecycle."""

        return tuple(self._actor_ids)

    def start(self) -> None:
        """Configure synchronous TM and spawn the requested autopilot vehicles."""

        if self._started:
            raise RuntimeError("background traffic is already running")
        if self._config.vehicle_count == 0:
            self._started = True
            return

        try:
            self._traffic_manager = self._client.get_trafficmanager(self._config.port)
            self._traffic_manager.set_synchronous_mode(True)
            self._traffic_manager.set_random_device_seed(self._config.seed)

            blueprints = sorted(
                (
                    blueprint
                    for blueprint in self._world.get_blueprint_library().filter("vehicle.*")
                    if blueprint.has_attribute("number_of_wheels")
                ),
                key=lambda blueprint: blueprint.id,
            )
            if not blueprints:
                raise RuntimeError("the CARLA map exposes no vehicle blueprints")

            spawn_points = list(self._world.get_map().get_spawn_points())
            random.Random(self._config.seed).shuffle(spawn_points)
            if len(spawn_points) < self._config.vehicle_count:
                raise RuntimeError(
                    "the CARLA map has only "
                    f"{len(spawn_points)} spawn points; need "
                    f"{self._config.vehicle_count} background vehicles"
                )

            commands = []
            for index, transform in enumerate(spawn_points[: self._config.vehicle_count]):
                blueprint = blueprints[index % len(blueprints)]
                if blueprint.has_attribute("role_name"):
                    blueprint.set_attribute("role_name", BACKGROUND_TRAFFIC_ROLE_NAME)
                commands.append(
                    self._carla.command.SpawnActor(blueprint, transform).then(
                        self._carla.command.SetAutopilot(
                            self._carla.command.FutureActor,
                            True,
                            self._traffic_manager.get_port(),
                        )
                    )
                )

            # ``do_tick=False`` is intentional: only Master may advance the world.
            responses = self._client.apply_batch_sync(commands, False)
            errors = [response.error for response in responses if response.error]
            self._actor_ids = [
                response.actor_id for response in responses if not response.error
            ]
            if errors or len(self._actor_ids) != self._config.vehicle_count:
                detail = "; ".join(errors[:3]) or "CARLA returned too few spawned actors"
                raise RuntimeError(
                    f"failed to spawn {self._config.vehicle_count} background vehicles: "
                    f"{detail}"
                )
            self._started = True
        except BaseException:
            # Preserve the startup error while doing best-effort cleanup of any
            # successful batch members and the Traffic Manager mode change.
            try:
                self.close()
            except Exception:
                pass
            raise

        print(
            "Background Traffic Manager started "
            f"{len(self._actor_ids)} vehicles on port {self._config.port} "
            f"with seed {self._config.seed}."
        )

    def close(self) -> None:
        """Destroy only actors created here and return TM to asynchronous mode."""

        actor_ids, self._actor_ids = self._actor_ids, []
        traffic_manager, self._traffic_manager = self._traffic_manager, None
        self._started = False
        try:
            if actor_ids:
                self._client.apply_batch(
                    [
                        self._carla.command.DestroyActor(actor_id)
                        for actor_id in actor_ids
                    ]
                )
        finally:
            if traffic_manager is not None:
                traffic_manager.set_synchronous_mode(False)
