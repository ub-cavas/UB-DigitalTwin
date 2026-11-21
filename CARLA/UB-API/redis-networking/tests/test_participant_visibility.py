"""Publisher and standalone replica contract checks with fake CARLA worlds."""
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    command = ModuleType('carla.command')
    for attr in ('SpawnActor', 'SetAutopilot', 'FutureActor', 'DestroyActor'):
        setattr(command, attr, Mock())
    numpy = ModuleType('numpy')
    numpy.random = Mock()
    with patch.dict('sys.modules', {'carla': ModuleType('carla'), 'carla.command': command,
                                    'numpy': numpy, 'redis': ModuleType('redis')}):
        spec.loader.exec_module(module)
    return module


publisher = load('visibility_publisher', 'generate_traffic_modified.py')
standalone = load('visibility_standalone', 'render_ego.py')


class ParticipantContractTests(unittest.TestCase):
    def test_publisher_includes_unique_manuals_excludes_managed_and_names_world(self):
        roles = ['manual_vehicle', 'manual_vehicle:a', 'manual_vehicle:b', 'autopilot', 'hero', 'external_ego', 'ub_mirror:managed']
        actors = []
        for i, role in enumerate(roles):
            actor = Mock(id=i, type_id='vehicle.test', attributes={'role_name': role})
            actor.get_transform.return_value = SimpleNamespace(location=SimpleNamespace(x=1, y=2, z=3), rotation=SimpleNamespace(yaw=0))
            actors.append(actor)
        world = Mock(id='episode-a')
        world.get_actors.return_value.filter.return_value = actors
        world.get_snapshot.return_value = SimpleNamespace(timestamp=SimpleNamespace(elapsed_seconds=10), frame=20)
        instance = publisher.TrafficTelemetryPublisher.__new__(publisher.TrafficTelemetryPublisher)
        import threading
        instance._world, instance._world_lock = world, threading.Lock()
        instance._manual_role_name, instance._logged_manual_actor_ids = 'manual_vehicle', set()
        output = instance.handle_fetch_telemetry_data()
        self.assertEqual(output['world_id'], 'episode-a')
        self.assertEqual([v['role_name'] for v in output['vehicles']], roles[:4])
        for role in roles:
            self.assertEqual(publisher.preserve_vehicle(role), role != 'autopilot')

    def test_standalone_uses_shared_claim_tag_and_owner_safe_cleanup(self):
        receiver, mirrors, actor = Mock(), Mock(), Mock(id=9, type_id='vehicle.test')
        receiver.snapshot.side_effect = [{'a': {'data': {'id': 'a'}, 'received_at': 10}}, KeyboardInterrupt()]
        mirrors.adopt.return_value = None
        mirrors.role.return_value = 'ub_mirror:tag'
        client = Mock()
        with patch.object(standalone.carla, 'Client', return_value=client, create=True), \
             patch.object(standalone, 'EgoTelemetryReceiver', return_value=receiver), \
             patch.object(standalone, 'VehicleMirrors', return_value=mirrors), \
             patch.object(standalone, 'spawn_ego', return_value=actor) as spawn, \
             patch.object(standalone, 'make_transform', return_value='transform'), \
             patch.object(standalone.time, 'time', return_value=10), \
             patch.object(standalone.time, 'sleep'), patch('sys.argv', ['render_ego']):
            with self.assertRaises(KeyboardInterrupt): standalone.main()
        mirrors.claim.assert_called_with('ego', 'a')
        self.assertEqual(spawn.call_args.args[-1], 'ub_mirror:tag')
        mirrors.release.assert_called_once_with('ego', 'a', actor)
        actor.destroy.assert_not_called()
        receiver.stop.assert_called_once()

    def test_standalone_ignores_invalid_poses_without_refresh(self):
        instance = standalone.EgoTelemetryReceiver.__new__(standalone.EgoTelemetryReceiver)
        import threading
        instance._lock, instance._latest = threading.Lock(), {}
        instance.on_receive_telemetry({'type': 3, 'ego': {'id': 'a', 'location': {'x': 1}, 'yaw': 0}})
        self.assertEqual(instance.snapshot(), {})

class SpawnReservationCleanupTests(unittest.TestCase):
    def fixture(self):
        # Reuse the atomic fake used by the ownership suite, with the real helper.
        fake_path = ROOT.parent / 'ub-telemetry/tests/test_vehicle_mirrors.py'
        spec = importlib.util.spec_from_file_location('visibility_lease_fakes', fake_path)
        fakes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fakes)
        redis = fakes.FakeRedis()
        world = fakes.world()
        mirrors = standalone.VehicleMirrors(redis, 's', world)
        actor = Mock(id=7, is_alive=True, attributes={'role_name': mirrors.role('ego', 'a')})
        return redis, world, mirrors, actor

    def standalone_attempt(self, world, mirrors, blueprint_error=False):
        transform = SimpleNamespace(location=SimpleNamespace(x=0, y=0, z=0), rotation=SimpleNamespace(yaw=0))
        with patch.object(standalone, 'pick_blueprint', side_effect=RuntimeError('blueprint failed') if blueprint_error else None, return_value=Mock()), \
             patch.object(standalone.carla, 'Location', lambda x, y, z: SimpleNamespace(x=x, y=y, z=z), create=True), \
             patch.object(standalone.carla, 'Transform', lambda location, rotation: SimpleNamespace(location=location, rotation=rotation), create=True):
            return standalone.spawn_ego(world, {'id': 'a'}, 'vehicle.test', transform, mirrors.role('ego', 'a'), mirrors=mirrors)

    def test_standalone_failed_then_successful_attempt_restores_normal_ttl(self):
        redis, world, mirrors, actor = self.fixture()
        world.try_spawn_actor = Mock(side_effect=[None, actor])
        self.assertIsNone(self.standalone_attempt(world, mirrors))
        key = mirrors._key('ego', 'a')
        self.assertNotIn(key, mirrors.claims)
        mirrors.maintain()
        self.assertNotIn(key, redis.values)
        self.assertIs(self.standalone_attempt(world, mirrors), actor)
        mirrors.maintain()
        self.assertEqual(mirrors._spawn_counts[key], 0)
        self.assertEqual(redis.values[key][1], mirrors.TTL_MS)

    def test_standalone_spawn_and_blueprint_exceptions_release_unused_claims(self):
        for blueprint_error in (False, True):
            with self.subTest(blueprint_error=blueprint_error):
                redis, world, mirrors, actor = self.fixture()
                world.try_spawn_actor = Mock(side_effect=RuntimeError('spawn failed'))
                with self.assertRaises(RuntimeError): self.standalone_attempt(world, mirrors, blueprint_error)
                mirrors.maintain()
                key = mirrors._key('ego', 'a')
                self.assertEqual(mirrors._spawn_counts.get(key, 0), 0)
                self.assertNotIn(key, mirrors.claims)
                self.assertNotIn(key, redis.values)

    def bridge_fixture(self):
        bridge = load('visibility_cleanup_bridge', 'traffic_bridge.py')
        redis, world, mirrors, actor = self.fixture()
        mirror = bridge.CarlaEgoMirror.__new__(bridge.CarlaEgoMirror)
        mirror._mirrors, mirror._world = mirrors, world
        mirror._actors, mirror._last_updates = {}, {}
        mirror._to_transform = Mock(return_value='pose')
        world.get_blueprint_library = Mock(return_value=Mock())
        return redis, world, mirrors, actor, mirror

    def test_bridge_failed_then_successful_attempt_restores_normal_ttl(self):
        redis, world, mirrors, actor, mirror = self.bridge_fixture()
        world.try_spawn_actor = Mock(side_effect=[None, actor])
        pose = {'id': 'a', 'location': {'x': 0, 'y': 0, 'z': 0}, 'yaw': 0}
        mirror.update(pose)
        key = mirrors._key('ego', 'a')
        mirrors.maintain()
        self.assertNotIn(key, mirrors.claims)
        self.assertNotIn(key, redis.values)
        mirror.update(pose)
        mirrors.maintain()
        self.assertIs(mirror._actors['a'], actor)
        self.assertEqual(mirrors._spawn_counts[key], 0)
        self.assertEqual(redis.values[key][1], mirrors.TTL_MS)

    def test_bridge_spawn_and_blueprint_exceptions_release_unused_claims(self):
        for blueprint_error in (False, True):
            with self.subTest(blueprint_error=blueprint_error):
                redis, world, mirrors, actor, mirror = self.bridge_fixture()
                world.try_spawn_actor = Mock(side_effect=RuntimeError('spawn failed'))
                if blueprint_error: world.get_blueprint_library.side_effect = RuntimeError('blueprint failed')
                pose = {'id': 'a', 'location': {'x': 0, 'y': 0, 'z': 0}, 'yaw': 0}
                with self.assertRaises(RuntimeError): mirror.update(pose)
                mirrors.maintain()
                key = mirrors._key('ego', 'a')
                self.assertEqual(mirrors._spawn_counts.get(key, 0), 0)
                self.assertNotIn(key, mirrors.claims)
                self.assertNotIn(key, redis.values)
