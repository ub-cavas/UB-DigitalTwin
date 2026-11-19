"""Bridge forwarding and idle expiry, with no simulator or sockets."""
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('traffic_bridge', Path(__file__).parents[1] / 'traffic_bridge.py')
bridge = importlib.util.module_from_spec(spec)
with patch.dict('sys.modules', {'carla': ModuleType('carla'), 'redis': ModuleType('redis')}):
    spec.loader.exec_module(bridge)


def ego(identity):
    return {'id': identity, 'location': {'x': 1, 'y': 2, 'z': 3}, 'yaw': 0}


class BridgeTests(unittest.TestCase):
    def test_forward_legacy_snapshot_and_two_nested_egos_and_poll_idle(self):
        packets = [{'type': 2, 'vehicles': [{'id': '42'}], 'timestamp': 1},
                   {'type': 3, 'id': 'ub-mr', 'ego': ego('a')},
                   {'type': 3, 'id': 'ub-mr', 'ego': ego('b')}]
        pubsub, redis, sock, mirror = Mock(), Mock(), Mock(), Mock()
        redis.pubsub.return_value = pubsub
        pubsub.get_message.side_effect = [*[{'type': 'message', 'data': json.dumps(p)} for p in packets], None, KeyboardInterrupt()]
        with patch.object(bridge, '_load_json_config', return_value={'ego_bridge': False}), \
             patch.object(bridge.redis, 'Redis', return_value=redis, create=True), \
             patch.object(bridge.socket, 'socket', return_value=sock), \
             patch.object(bridge, 'CarlaEgoMirror', return_value=mirror):
            with self.assertRaises(KeyboardInterrupt): bridge.main()
        output = [json.loads(call.args[0]) for call in sock.sendto.call_args_list]
        self.assertEqual(output[0], {'vehicles': [{'id': '42'}], 'timestamp': 1})
        self.assertEqual([p['ego']['id'] for p in output[1:]], ['a', 'b'])
        self.assertEqual(mirror.update.call_count, 2)
        self.assertEqual(mirror.cleanup_if_stale.call_count, 4)
        pubsub.get_message.assert_called_with(timeout=.1)
        mirror.destroy.assert_called_once()

    def test_mirrors_are_per_id_and_expire_without_new_messages(self):
        mirror = bridge.CarlaEgoMirror.__new__(bridge.CarlaEgoMirror)
        mirror._world = Mock()
        mirror._mirrors = Mock()
        mirror._mirrors.adopt.return_value = None
        mirror._actors, mirror._last_updates = {}, {}
        mirror._ego_timeout = 2
        mirror._to_transform = Mock()
        a, b = Mock(is_alive=True), Mock(is_alive=True)
        mirror._world.try_spawn_actor.side_effect = [a, b]
        with patch.object(bridge.time, 'monotonic', return_value=10):
            mirror.update(ego('a'))
            mirror.update(ego('b'))
        with patch.object(bridge.time, 'monotonic', return_value=12.1):
            mirror.cleanup_if_stale()
        self.assertEqual(mirror._actors, {})
        self.assertEqual(mirror._mirrors.release.call_count, 2)
        self.assertEqual([c.args[:2] for c in mirror._mirrors.release.call_args_list], [('ego', 'a'), ('ego', 'b')])

    def test_invalid_pose_does_not_claim_or_refresh(self):
        mirror = bridge.CarlaEgoMirror.__new__(bridge.CarlaEgoMirror)
        mirror._mirrors = Mock()
        mirror.update({**ego('bad'), 'yaw': float('nan')})
        mirror._mirrors.claim.assert_not_called()

    def test_udp_listener_accepts_only_bare_or_explicit_type_three(self):
        valid = ego('a')
        packets = [valid, {'type': 3, 'ego': ego('b')},
                   *[{'type': kind, 'ego': valid} for kind in (0, 2, 99, '3', True)],
                   {'ego': valid}, {'type': 3, 'ego': {**valid, 'yaw': float('nan')}}, []]
        sock, redis = Mock(), Mock()
        sock.recvfrom.side_effect = [(json.dumps(p).encode(), ('127.0.0.1', 1)) for p in packets] + [OSError('done')]
        thread = Mock()
        def start():
            thread.target()
        def make_thread(**kwargs):
            thread.target = kwargs['target']
            thread.start.side_effect = start
            return thread
        with patch.object(bridge.socket, 'socket', return_value=sock), patch.object(bridge.threading, 'Thread', side_effect=make_thread):
            bridge._start_ego_udp_listener(redis, 's', {})
        published = [json.loads(call.args[1]) for call in redis.publish.call_args_list]
        self.assertEqual([p['ego']['id'] for p in published], ['a', 'b'])
        self.assertTrue(all(p['type'] == 3 for p in published))

    def test_episode_changes_after_pose_conversion_without_maintenance(self):
        from ub_telemetry.vehicle_mirrors import VehicleMirrors
        old = SimpleNamespace(id='old', get_actors=lambda: SimpleNamespace(filter=lambda _: []))
        replacement = SimpleNamespace(id='new')
        current = [old]
        mirrors = VehicleMirrors(Mock(), 's', old, lambda: current[0])
        self.assertTrue(mirrors.claim('ego', 'a'))
        actor = Mock(id=7, is_alive=True)
        mirror = bridge.CarlaEgoMirror.__new__(bridge.CarlaEgoMirror)
        mirror._mirrors, mirror._world = mirrors, old
        mirror._actors, mirror._last_updates = {'a': actor}, {}
        def convert(packet):
            current[0] = replacement
            return 'pose'
        mirror._to_transform = convert
        mirror.update(ego('a'))
        actor.set_transform.assert_not_called()
        self.assertEqual(mirror._last_updates, {})
