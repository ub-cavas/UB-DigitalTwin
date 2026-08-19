"""station.puppets — spawn and pose physics-disabled remote actors.

One job: for each remote actor announced over the wire, keep a
physics-disabled CARLA actor whose transform is set from
``dtnet.interp.PuppetInterpolator.pose_at(render_time)`` every local tick.

The source is injected, not hardcoded.  It must expose
``drain_packets()`` and return an iterable of ``(packet_bytes,
received_monotonic_time)`` pairs.  The W2 harness can back that contract with
a local queue; the W3 relay can back it with a UDP receive queue.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from dtnet import wire
from dtnet.interp import PuppetInterpolator


DEFAULT_PUPPET_BLUEPRINT = "vehicle.lincoln.mkz_2020"
"""CARLA blueprint used until the actor registry supplies per-actor metadata."""

DEFAULT_RENDER_DELAY_S = 0.04
"""W2 metro-profile render delay, expressed in seconds."""

_LOG = logging.getLogger(__name__)


class PuppetManager:
    """Own local replicas of remote actors without owning local simulation.

    CARLA actor calls happen only from :meth:`update`, so a publisher or UDP
    receiver may enqueue packets from another thread without calling into
    CARLA.  The caller remains responsible for the station's ``world.tick()``.
    """

    def __init__(
        self,
        world: Any,
        data_source: Any,
        *,
        render_delay_s: float = DEFAULT_RENDER_DELAY_S,
        blueprint_id: str = DEFAULT_PUPPET_BLUEPRINT,
        carla_module: Any | None = None,
    ):
        drain_packets = getattr(data_source, "drain_packets", None)
        if not callable(drain_packets):
            raise TypeError("data_source must provide a callable drain_packets()")
        if not isinstance(blueprint_id, str) or not blueprint_id:
            raise ValueError("blueprint_id must be a non-empty string")

        self._world = world
        self._data_source = data_source
        self._render_delay_s = render_delay_s
        self._blueprint_id = blueprint_id
        # CARLA is optional in the unit-test environment.  Delay importing it
        # until a production manager is actually constructed.
        self._carla = carla_module or importlib.import_module("carla")
        self._interpolators: dict[int, PuppetInterpolator] = {}
        self._puppets: dict[int, Any] = {}

    def update(self, render_time: float) -> None:
        """Drain new packets, then pose every existing puppet at ``render_time``.

        Invalid packet items are a network-boundary concern: they are logged
        and ignored rather than allowing corrupt UDP data to interrupt the
        station's local simulation loop.  CARLA failures deliberately remain
        visible to the caller because they indicate a local renderer problem,
        not a transient remote packet.
        """

        for packet_item in self._data_source.drain_packets():
            self._accept_packet(packet_item)

        for actor_id, puppet in self._puppets.items():
            pose = self._interpolators[actor_id].pose_at(render_time)
            puppet.set_transform(self._transform_from_pose(pose))

    def _accept_packet(self, packet_item: Any) -> None:
        """Decode and buffer one source item, spawning a new actor if needed."""

        try:
            packet, recv_time = packet_item
            pose = wire.unpack(packet)
            actor_id = pose["actor_id"]
            interpolator = self._interpolators.get(actor_id)
            if interpolator is None:
                interpolator = PuppetInterpolator(self._render_delay_s)
                self._interpolators[actor_id] = interpolator
            interpolator.on_packet(recv_time, float(pose["master_frame_seq"]), pose)
        except (TypeError, ValueError) as exc:
            _LOG.warning("Discarding invalid puppet packet: %s", exc)
            return

        if actor_id not in self._puppets:
            self._puppets[actor_id] = self._spawn_puppet(actor_id, pose)

    def _spawn_puppet(self, actor_id: int, pose: dict) -> Any:
        """Create the local visual replica at its first known remote pose."""

        blueprint = self._world.get_blueprint_library().find(self._blueprint_id)
        if blueprint.has_attribute("role_name"):
            blueprint.set_attribute("role_name", f"dt_puppet:{actor_id}")
        puppet = self._world.spawn_actor(blueprint, self._transform_from_pose(pose))
        puppet.set_simulate_physics(False)
        return puppet

    def _transform_from_pose(self, pose: dict) -> Any:
        """Map frozen v1 CARLA-coordinate state directly into a transform."""

        return self._carla.Transform(
            self._carla.Location(
                x=pose["pos_x"],
                y=pose["pos_y"],
                z=pose["pos_z"],
            ),
            self._carla.Rotation(
                roll=pose["rot_r"],
                pitch=pose["rot_p"],
                yaw=pose["rot_y"],
            ),
        )
