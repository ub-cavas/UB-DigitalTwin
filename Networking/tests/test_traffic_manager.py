"""Contract tests for server-owned Traffic Manager background traffic."""

from __future__ import annotations

import argparse
import random
import unittest

from server.traffic_manager import (
    BACKGROUND_TRAFFIC_ROLE_NAME,
    BackgroundTraffic,
    TrafficManagerConfig,
    add_cli_arguments,
    config_from_namespace,
)


class FakeBlueprint:
    def __init__(self, blueprint_id, attributes=("number_of_wheels", "role_name")):
        self.id = blueprint_id
        self._attributes = set(attributes)
        self.set_attributes = []

    def has_attribute(self, name):
        return name in self._attributes

    def set_attribute(self, name, value):
        self.set_attributes.append((name, value))


class FakeBlueprintLibrary:
    def __init__(self, blueprints):
        self.blueprints = blueprints

    def filter(self, pattern):
        self.last_pattern = pattern
        return list(self.blueprints)


class FakeMap:
    def __init__(self, spawn_points):
        self.spawn_points = spawn_points

    def get_spawn_points(self):
        return list(self.spawn_points)


class FakeWorld:
    def __init__(self, blueprints, spawn_points):
        self.library = FakeBlueprintLibrary(blueprints)
        self.map = FakeMap(spawn_points)

    def get_blueprint_library(self):
        return self.library

    def get_map(self):
        return self.map


class FakeTrafficManager:
    def __init__(self, port):
        self.port = port
        self.synchronous_modes = []
        self.seeds = []

    def get_port(self):
        return self.port

    def set_synchronous_mode(self, value):
        self.synchronous_modes.append(value)

    def set_random_device_seed(self, value):
        self.seeds.append(value)


class FakeResponse:
    def __init__(self, actor_id=0, error=""):
        self.actor_id = actor_id
        self.error = error


class FakeClient:
    def __init__(self, traffic_manager, responses):
        self.traffic_manager = traffic_manager
        self.responses = responses
        self.requested_ports = []
        self.spawn_batches = []
        self.destroy_batches = []

    def get_trafficmanager(self, port):
        self.requested_ports.append(port)
        return self.traffic_manager

    def apply_batch_sync(self, commands, do_tick):
        self.spawn_batches.append((list(commands), do_tick))
        return list(self.responses)

    def apply_batch(self, commands):
        self.destroy_batches.append(list(commands))


class FakeSpawnCommand:
    def __init__(self, blueprint, transform):
        self.blueprint = blueprint
        self.transform = transform
        self.autopilot = None

    def then(self, autopilot):
        self.autopilot = autopilot
        return self


class FakeCommandModule:
    FutureActor = object()

    @staticmethod
    def SpawnActor(blueprint, transform):
        return FakeSpawnCommand(blueprint, transform)

    @staticmethod
    def SetAutopilot(actor, enabled, port):
        return (actor, enabled, port)

    @staticmethod
    def DestroyActor(actor_id):
        return ("destroy", actor_id)


class FakeCarla:
    command = FakeCommandModule


class TrafficManagerConfigTests(unittest.TestCase):
    def test_parser_builds_validated_config(self):
        parser = argparse.ArgumentParser()
        add_cli_arguments(parser)

        config = config_from_namespace(
            parser.parse_args(
                ["--traffic-vehicles", "3", "--traffic-seed", "9", "--tm-port", "8010"]
            )
        )

        self.assertEqual(config, TrafficManagerConfig(vehicle_count=3, seed=9, port=8010))

    def test_config_rejects_invalid_vehicle_count_and_port(self):
        with self.assertRaisesRegex(ValueError, "vehicle_count"):
            TrafficManagerConfig(vehicle_count=-1)
        with self.assertRaisesRegex(ValueError, "port"):
            TrafficManagerConfig(port=0)


class BackgroundTrafficTests(unittest.TestCase):
    def setUp(self):
        self.blueprints = [FakeBlueprint("vehicle.z"), FakeBlueprint("vehicle.a")]
        self.spawn_points = ["one", "two", "three", "four"]
        self.world = FakeWorld(self.blueprints, self.spawn_points)
        self.tm = FakeTrafficManager(8010)
        self.client = FakeClient(
            self.tm, [FakeResponse(101), FakeResponse(102), FakeResponse(103)]
        )

    def traffic(self, **overrides):
        config = {"vehicle_count": 3, "seed": 9, "port": 8010}
        config.update(overrides)
        return BackgroundTraffic(
            self.client,
            self.world,
            FakeCarla,
            TrafficManagerConfig(**config),
        )

    def test_starts_deterministic_autopilot_traffic_without_ticking_world(self):
        traffic = self.traffic()

        traffic.start()

        self.assertEqual(self.client.requested_ports, [8010])
        self.assertEqual(self.tm.synchronous_modes, [True])
        self.assertEqual(self.tm.seeds, [9])
        commands, do_tick = self.client.spawn_batches[0]
        self.assertFalse(do_tick)
        expected_points = list(self.spawn_points)
        random.Random(9).shuffle(expected_points)
        self.assertEqual([command.transform for command in commands], expected_points[:3])
        self.assertEqual(
            [command.blueprint.id for command in commands],
            ["vehicle.a", "vehicle.z", "vehicle.a"],
        )
        self.assertTrue(
            all(
                command.autopilot == (FakeCommandModule.FutureActor, True, 8010)
                for command in commands
            )
        )
        self.assertEqual(traffic.actor_ids, (101, 102, 103))
        for blueprint in self.blueprints:
            self.assertIn(("role_name", BACKGROUND_TRAFFIC_ROLE_NAME), blueprint.set_attributes)

        traffic.close()

        self.assertEqual(
            self.client.destroy_batches, [[("destroy", 101), ("destroy", 102), ("destroy", 103)]]
        )
        self.assertEqual(self.tm.synchronous_modes, [True, False])
        traffic.close()
        self.assertEqual(len(self.client.destroy_batches), 1)

    def test_zero_vehicle_configuration_does_not_touch_carla(self):
        traffic = self.traffic(vehicle_count=0)

        traffic.start()
        traffic.close()

        self.assertEqual(self.client.requested_ports, [])
        self.assertEqual(self.client.spawn_batches, [])
        self.assertEqual(self.client.destroy_batches, [])

    def test_rejects_map_without_enough_spawn_points_and_restores_tm(self):
        self.world.map = FakeMap(["only-one"])
        traffic = self.traffic()

        with self.assertRaisesRegex(RuntimeError, "has only 1 spawn points"):
            traffic.start()

        self.assertEqual(self.tm.synchronous_modes, [True, False])
        self.assertEqual(self.client.spawn_batches, [])

    def test_rejects_missing_vehicle_blueprints_and_restores_tm(self):
        self.world.library = FakeBlueprintLibrary([FakeBlueprint("walker", ())])
        traffic = self.traffic()

        with self.assertRaisesRegex(RuntimeError, "no vehicle blueprints"):
            traffic.start()

        self.assertEqual(self.tm.synchronous_modes, [True, False])
        self.assertEqual(self.client.spawn_batches, [])

    def test_partial_spawn_failure_removes_only_successful_actors(self):
        self.client.responses = [
            FakeResponse(101),
            FakeResponse(error="occupied"),
            FakeResponse(103),
        ]
        traffic = self.traffic()

        with self.assertRaisesRegex(RuntimeError, "occupied"):
            traffic.start()

        self.assertEqual(
            self.client.destroy_batches, [[("destroy", 101), ("destroy", 103)]]
        )
        self.assertEqual(self.tm.synchronous_modes, [True, False])
        self.assertEqual(traffic.actor_ids, ())


if __name__ == "__main__":
    unittest.main()
