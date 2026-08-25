"""Mocked-CARLA contract tests for station.puppets."""

from __future__ import annotations

import unittest

from dtnet import wire
from station.puppets import PuppetManager


class FakeLocation:
    def __init__(self, *, x, y, z):
        self.x = x
        self.y = y
        self.z = z


class FakeRotation:
    def __init__(self, *, roll, pitch, yaw):
        self.roll = roll
        self.pitch = pitch
        self.yaw = yaw


class FakeTransform:
    def __init__(self, location, rotation):
        self.location = location
        self.rotation = rotation


class FakeCarla:
    Location = FakeLocation
    Rotation = FakeRotation
    Transform = FakeTransform


class FakeBlueprint:
    def __init__(self, blueprint_id):
        self.id = blueprint_id
        self.attributes = {}

    def has_attribute(self, name):
        return name == "role_name"

    def set_attribute(self, name, value):
        self.attributes[name] = value


class FakeBlueprintLibrary:
    def __init__(self):
        self.blueprint = FakeBlueprint("vehicle.lincoln.mkz_2020")
        self.find_calls = []

    def find(self, blueprint_id):
        self.find_calls.append(blueprint_id)
        return self.blueprint


class FakeActor:
    def __init__(self, initial_transform):
        self.initial_transform = initial_transform
        self.transforms = []
        self.physics_enabled = True
        self.destroyed = False

    def set_simulate_physics(self, enabled):
        self.physics_enabled = enabled

    def set_transform(self, transform):
        self.transforms.append(transform)

    def destroy(self):
        self.destroyed = True


class FakeWorld:
    def __init__(self):
        self.blueprint_library = FakeBlueprintLibrary()
        self.spawn_calls = []

    def get_blueprint_library(self):
        return self.blueprint_library

    def spawn_actor(self, blueprint, transform):
        actor = FakeActor(transform)
        self.spawn_calls.append((blueprint.id, dict(blueprint.attributes), transform, actor))
        return actor


class ContendedFakeWorld(FakeWorld):
    def __init__(self):
        super().__init__()
        self.attempts = []

    def spawn_actor(self, blueprint, transform):
        self.attempts.append(transform)
        if len(self.attempts) == 1:
            raise RuntimeError("spawn failed because of collision at spawn position")
        return super().spawn_actor(blueprint, transform)


class PacketSource:
    def __init__(self):
        self.pending = []
        self.generation = 0

    def enqueue(self, packet, recv_time=0.0):
        self.pending.append((packet, recv_time))

    def drain_packets(self):
        pending, self.pending = self.pending, []
        return pending


def packet(
    actor_id,
    sequence,
    *,
    x=0.0,
    y=0.0,
    z=0.0,
    roll=0.0,
    pitch=0.0,
    yaw=0.0,
) -> bytes:
    return wire.pack({
        "actor_id": actor_id,
        "master_frame_seq": sequence,
        "pos_x": x,
        "pos_y": y,
        "pos_z": z,
        "rot_r": roll,
        "rot_p": pitch,
        "rot_y": yaw,
        "vel_x": 0.0,
        "vel_y": 0.0,
        "vel_z": 0.0,
        "ang_x": 0.0,
        "ang_y": 0.0,
        "ang_z": 0.0,
    })


class PuppetManagerTests(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld()
        self.source = PacketSource()
        self.manager = PuppetManager(
            self.world, self.source, render_delay_s=0.0, carla_module=FakeCarla
        )

    def test_first_packet_spawns_physics_disabled_puppet_at_its_pose(self):
        self.source.enqueue(packet(7, 0, x=1.5, y=-2.0, z=0.25, yaw=45.0))

        self.manager.update(0.0)

        self.assertEqual(len(self.world.spawn_calls), 1)
        blueprint_id, attributes, transform, actor = self.world.spawn_calls[0]
        self.assertEqual(blueprint_id, "vehicle.lincoln.mkz_2020")
        self.assertEqual(attributes["role_name"], "dt_puppet:7")
        self.assertFalse(actor.physics_enabled)
        self.assertEqual((transform.location.x, transform.location.y, transform.location.z),
                         (1.5, -2.0, 0.25))
        self.assertEqual(transform.rotation.yaw, 45.0)
        self.assertEqual(len(actor.transforms), 1)

    def test_multiple_actor_ids_have_independent_puppets(self):
        self.source.enqueue(packet(1, 0, x=1.0))
        self.source.enqueue(packet(2, 0, x=2.0))

        self.manager.update(0.0)

        self.assertEqual(len(self.world.spawn_calls), 2)
        spawned = {attributes["role_name"]: actor for _, attributes, _, actor
                   in self.world.spawn_calls}
        self.assertEqual(spawned["dt_puppet:1"].transforms[-1].location.x, 1.0)
        self.assertEqual(spawned["dt_puppet:2"].transforms[-1].location.x, 2.0)

    def test_actor_master_time_unwraps_across_the_v1_uint32_boundary(self):
        self.manager._latest_render_time = float(0xFFFFFFFF)
        self.assertEqual(
            self.manager._unwrapped_master_time(7, 0xFFFFFFFF), float(0xFFFFFFFF)
        )
        self.assertEqual(self.manager._unwrapped_master_time(7, 0), float(0x100000000))

    def test_puppet_uses_elevated_fallback_when_target_pose_is_occupied(self):
        world = ContendedFakeWorld()
        source = PacketSource()
        manager = PuppetManager(world, source, render_delay_s=0.0, carla_module=FakeCarla)
        source.enqueue(packet(7, 0, z=3.0))

        manager.update(0.0)

        self.assertEqual(len(world.attempts), 2)
        self.assertEqual(world.attempts[1].location.z, 53.0)
        self.assertEqual(world.spawn_calls[0][3].transforms[-1].location.z, 3.0)

    def test_source_generation_change_replaces_old_master_stream_puppets(self):
        self.source.enqueue(packet(7, 10))
        self.manager.update(10.0)
        first = self.world.spawn_calls[0][3]

        self.source.generation = 1
        self.source.enqueue(packet(7, 0))
        self.manager.update(0.0)

        self.assertTrue(first.destroyed)
        self.assertEqual(len(self.world.spawn_calls), 2)

    def test_interpolated_pose_maps_all_transform_components(self):
        self.source.enqueue(packet(3, 0, x=0.0, y=2.0, z=4.0,
                                   roll=10.0, pitch=20.0, yaw=30.0))
        self.manager.update(0.0)
        actor = self.world.spawn_calls[0][3]
        actor.transforms.clear()
        self.source.enqueue(packet(3, 10, x=10.0, y=12.0, z=14.0,
                                   roll=50.0, pitch=60.0, yaw=70.0))

        self.manager.update(5.0)

        transform = actor.transforms[-1]
        self.assertEqual((transform.location.x, transform.location.y, transform.location.z),
                         (5.0, 7.0, 9.0))
        self.assertEqual((transform.rotation.roll, transform.rotation.pitch,
                          transform.rotation.yaw), (30.0, 40.0, 50.0))

    def test_invalid_packet_is_ignored_and_empty_update_is_harmless(self):
        self.source.enqueue(packet(5, 0, x=1.0))
        self.manager.update(0.0)
        actor = self.world.spawn_calls[0][3]
        self.source.enqueue(b"not a v1 packet")

        self.manager.update(0.0)
        self.manager.update(0.0)

        self.assertEqual(len(self.world.spawn_calls), 1)
        self.assertFalse(actor.destroyed)
        self.assertEqual(len(actor.transforms), 3)

    def test_repeated_actor_packets_do_not_respawn_or_teardown_on_silence(self):
        self.source.enqueue(packet(9, 0, x=1.0))
        self.manager.update(0.0)
        actor = self.world.spawn_calls[0][3]
        self.source.enqueue(packet(9, 1, x=2.0), recv_time=1.0)

        self.manager.update(1.0)
        self.manager.update(100.0)

        self.assertEqual(len(self.world.spawn_calls), 1)
        self.assertFalse(actor.destroyed)

    def test_buffer_depth_is_the_shallowest_active_puppet_buffer(self):
        self.assertIsNone(self.manager.buffer_depth)

        self.source.enqueue(packet(1, 0))
        self.manager.update(-1.0)
        self.source.enqueue(packet(1, 1))
        self.source.enqueue(packet(2, 0))
        self.manager.update(-1.0)

        self.assertEqual(self.manager._interpolators[1].buffered_sample_count, 2)
        self.assertEqual(self.manager._interpolators[2].buffered_sample_count, 1)
        self.assertEqual(self.manager.buffer_depth, 1)

    def test_constructor_requires_drain_packets_contract(self):
        with self.assertRaisesRegex(TypeError, "drain_packets"):
            PuppetManager(self.world, object(), carla_module=FakeCarla)

    def test_close_destroys_only_managed_puppets_and_is_idempotent(self):
        self.source.enqueue(packet(7, 0))
        self.manager.update(0.0)
        actor = self.world.spawn_calls[0][3]

        self.manager.close()
        self.manager.close()

        self.assertTrue(actor.destroyed)
        self.assertEqual(self.manager.buffer_depth, None)


if __name__ == "__main__":
    unittest.main()
