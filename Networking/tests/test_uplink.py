"""Contract tests for the single-station DT-20 uplink."""

from __future__ import annotations

import argparse
import unittest
from unittest.mock import MagicMock, patch

from dtnet import wire
from server.uplink import (
    ServerPuppet,
    Uplink,
    UplinkConfig,
    add_cli_arguments as add_server_cli_arguments,
    config_from_namespace,
)
from station.uplink import (
    StationUplink,
    UplinkEndpoint,
    add_cli_arguments as add_station_cli_arguments,
    endpoint_from_namespace,
)


def state(sequence: int = 1) -> dict:
    return {
        "actor_id": 7,
        "master_frame_seq": sequence,
        "pos_x": 1.0,
        "pos_y": 2.0,
        "pos_z": 3.0,
        "rot_r": 4.0,
        "rot_p": 5.0,
        "rot_y": 6.0,
        "vel_x": 12.0,
        "vel_y": 18.0,
        "vel_z": 24.0,
        "ang_x": 30.0,
        "ang_y": 36.0,
        "ang_z": 42.0,
        "steer_angle": 0.0,
        "light_state": 0,
    }


class Vector:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class Rotation:
    def __init__(self, roll, pitch, yaw):
        self.roll, self.pitch, self.yaw = roll, pitch, yaw


class Transform:
    def __init__(self, location, rotation):
        self.location, self.rotation = location, rotation


class ActorSnapshot:
    id = 7

    def get_transform(self):
        return Transform(Vector(1, 2, 3), Rotation(4, 5, 6))

    def get_velocity(self):
        return Vector(7, 8, 9)

    def get_angular_velocity(self):
        return Vector(10, 11, 12)


class FakeMaster:
    def __init__(self):
        self.states = []

    def apply_puppet_state(self, packet_state):
        self.states.append(packet_state)


class FakeBlueprint:
    def __init__(self):
        self.attributes = {}

    def has_attribute(self, name):
        return name == "role_name"

    def set_attribute(self, name, value):
        self.attributes[name] = value


class FakeActor:
    def __init__(self, role_name=None, actor_id=99):
        self.id = actor_id
        self.attributes = {} if role_name is None else {"role_name": role_name}
        self.physics = []
        self.transforms = []
        self.destroyed = False

    def set_simulate_physics(self, enabled):
        self.physics.append(enabled)

    def set_transform(self, transform):
        self.transforms.append(transform)

    def destroy(self):
        self.destroyed = True


class FakeWorld:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.blueprint = FakeBlueprint()
        self.spawned = []

    def get_actors(self):
        return list(self.existing)

    def get_blueprint_library(self):
        return type("Library", (), {"find": lambda library, _id: self.blueprint})()

    def try_spawn_actor(self, blueprint, transform):
        actor = FakeActor(blueprint.attributes.get("role_name"))
        actor.transforms.append(transform)
        self.spawned.append(actor)
        return actor


class ContendedFakeWorld(FakeWorld):
    def __init__(self):
        super().__init__()
        self.attempts = []

    def try_spawn_actor(self, blueprint, transform):
        self.attempts.append(transform)
        if len(self.attempts) == 1:
            return None
        return super().try_spawn_actor(blueprint, transform)


class FakeCarla:
    Location = Vector
    Rotation = Rotation
    Transform = Transform


class StationUplinkTests(unittest.TestCase):
    def test_sender_encodes_one_actor_snapshot_to_configured_endpoint(self):
        with patch("station.uplink.socket.socket") as socket_constructor:
            udp_socket = MagicMock()
            socket_constructor.return_value = udp_socket
            uplink = StationUplink(UplinkEndpoint("10.0.0.9", 6006))

            uplink.send_actor_snapshot(ActorSnapshot(), 12)
            packet, address = udp_socket.sendto.call_args.args

        self.assertEqual(address, ("10.0.0.9", 6006))
        packet_state = wire.unpack(packet)
        self.assertEqual(packet_state["actor_id"], 7)
        self.assertEqual(packet_state["master_frame_seq"], 12)
        self.assertEqual(packet_state["vel_z"], 9.0)

    def test_station_cli_builds_the_server_endpoint(self):
        parser = argparse.ArgumentParser()
        add_station_cli_arguments(parser)
        endpoint = endpoint_from_namespace(
            parser.parse_args(["--uplink-server-host", "10.0.0.9", "--uplink-server-port", "6006"])
        )
        self.assertEqual(endpoint, UplinkEndpoint("10.0.0.9", 6006))


class ServerUplinkTests(unittest.TestCase):
    def test_receiver_accepts_newer_states_and_rejects_invalid_or_stale_packets(self):
        master = FakeMaster()
        uplink = Uplink(master, UplinkConfig())

        uplink.on_packet(wire.pack(state(9)))
        uplink.on_packet(wire.pack(state(8)))
        uplink.on_packet(b"broken")

        self.assertEqual([packet_state["master_frame_seq"] for packet_state in master.states], [9])

    def test_receiver_accepts_uint32_sequence_wrap(self):
        master = FakeMaster()
        uplink = Uplink(master, UplinkConfig())

        uplink.on_packet(wire.pack(state(0xFFFFFFFF)))
        uplink.on_packet(wire.pack(state(0)))

        self.assertEqual([packet_state["master_frame_seq"] for packet_state in master.states], [0xFFFFFFFF, 0])

    def test_server_cli_builds_receiver_and_puppet_configuration(self):
        parser = argparse.ArgumentParser()
        add_server_cli_arguments(parser)
        config = config_from_namespace(
            parser.parse_args(
                [
                    "--uplink-bind-host", "10.0.0.1",
                    "--uplink-port", "6006",
                    "--uplink-puppet-role-name", "dt_puppet:station-a",
                ]
            )
        )
        self.assertEqual(config, UplinkConfig("10.0.0.1", 6006, "dt_puppet:station-a"))


class ServerPuppetTests(unittest.TestCase):
    def test_spawns_disables_physics_and_dead_reckons_between_packets(self):
        world = FakeWorld()
        puppet = ServerPuppet(world, FakeCarla, UplinkConfig(), fixed_delta_seconds=0.5)
        puppet.on_state(state())

        puppet.advance()
        actor = world.spawned[0]
        self.assertEqual(puppet.actor_id, 99)
        self.assertEqual(world.blueprint.attributes["role_name"], "dt_station_puppet")
        self.assertEqual(actor.physics, [False])
        self.assertEqual(actor.transforms[-1].location.x, 1.0)

        puppet.advance()
        transform = actor.transforms[-1]
        self.assertEqual(transform.location.x, 7.0)
        self.assertEqual(transform.location.y, 11.0)
        self.assertEqual(transform.rotation.yaw, 27.0)

        puppet.close()
        self.assertTrue(actor.destroyed)

    def test_reuses_matching_role_puppet_without_destroying_it(self):
        existing = FakeActor("station-puppet")
        world = FakeWorld([existing])
        puppet = ServerPuppet(
            world,
            FakeCarla,
            UplinkConfig(puppet_role_name="station-puppet"),
            fixed_delta_seconds=1 / 60,
        )
        puppet.on_state(state())
        puppet.advance()
        puppet.close()

        self.assertEqual(world.spawned, [])
        self.assertFalse(existing.destroyed)
        self.assertEqual(existing.physics, [False])

    def test_uses_an_elevated_fallback_spawn_when_traffic_occupies_the_pose(self):
        world = ContendedFakeWorld()
        puppet = ServerPuppet(world, FakeCarla, UplinkConfig(), fixed_delta_seconds=1 / 60)
        puppet.on_state(state())

        puppet.advance()

        self.assertEqual(len(world.attempts), 2)
        self.assertEqual(world.attempts[1].location.z, 53.0)
        self.assertEqual(world.spawned[0].transforms[-1].location.z, 3.0)


if __name__ == "__main__":
    unittest.main()
