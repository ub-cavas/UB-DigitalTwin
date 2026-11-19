"""Keyboard response checks without CARLA, pygame, or a display."""
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

carla_stub = SimpleNamespace(VehicleControl=lambda **kw: SimpleNamespace(**kw))
pygame_stub = SimpleNamespace(**{name: i for i, name in enumerate(
    ('K_w', 'K_UP', 'K_a', 'K_LEFT', 'K_d', 'K_RIGHT', 'K_SPACE', 'K_s', 'K_DOWN')
)})
spec = importlib.util.spec_from_file_location('manual_control', Path(__file__).parents[1] / 'manual_control.py')
manual = importlib.util.module_from_spec(spec)
with patch.dict('sys.modules', {'carla': carla_stub, 'pygame': pygame_stub, 'redis': ModuleType('redis')}):
    spec.loader.exec_module(manual)

class KeyboardResponseTests(unittest.TestCase):
    def controller(self):
        c = manual.KeyboardController.__new__(manual.KeyboardController)
        c.vehicle = Mock()
        c.max_kmh = 60
        c.reverse = c.quit = False
        c._throttle = c._steer = c._last_time = 0.
        c._draw = Mock()
        c.clock = Mock()
        return c

    def tick(self, c, held):
        keys = {key: key in held for key in range(9)}
        with patch.object(manual.time, 'monotonic', return_value=c._last_time+1/90), \
             patch.object(manual, 'speed_kmh', return_value=0), \
             patch.object(manual, 'pygame', SimpleNamespace(**vars(pygame_stub),
                 event=SimpleNamespace(get=lambda: []), key=SimpleNamespace(get_pressed=lambda: keys))):
            c.tick()
        return c.vehicle.apply_control.call_args.args[0]

    def test_acceleration_and_steering_reach_full_within_quarter_second(self):
        c = self.controller()
        for _ in range(23):
            control = self.tick(c, {pygame_stub.K_w, pygame_stub.K_a})
        self.assertEqual(control.throttle, 1.)
        self.assertEqual(control.steer, -1.)
        c.clock.tick.assert_called_with(90)

    def test_brake_clears_accumulated_throttle(self):
        c = self.controller()
        c._throttle = 1.
        control = self.tick(c, {pygame_stub.K_w, pygame_stub.K_SPACE})
        self.assertEqual(control.brake, 1.)
        self.assertEqual(control.throttle, 0.)
        self.assertEqual(self.tick(c, set()).throttle, 0.)

    def test_release_returns_throttle_and_steering_to_zero(self):
        c = self.controller()
        c._throttle = c._steer = 1.
        for _ in range(23):
            control = self.tick(c, set())
        self.assertEqual(control.throttle, 0.)
        self.assertEqual(control.steer, 0.)

if __name__ == '__main__':
    unittest.main()

class ManualIdentityTests(unittest.TestCase):
    def parse(self, argv=(), env=None):
        with patch.dict(manual.os.environ, env or {}, clear=True), patch('sys.argv', ['manual', *argv]), patch.object(manual, 'configure_network_logging'):
            return manual.parse_args()

    def test_defaults_create_distinct_roles_and_metadata_keys(self):
        a, b = self.parse(), self.parse()
        self.assertNotEqual(a.client_id, b.client_id)
        self.assertNotEqual(a.role_name, b.role_name)
        self.assertNotEqual(a.actor_redis_key, b.actor_redis_key)
        self.assertTrue(a.role_name.endswith(a.client_id))
        self.assertTrue(a.actor_redis_key.endswith(a.client_id))

    def test_environment_and_cli_keep_explicit_legacy_reuse(self):
        args = self.parse(env={'UB_MANUAL_CLIENT_ID': 'a', 'UB_MANUAL_ROLE_NAME': 'manual_vehicle', 'UB_MANUAL_ACTOR_REDIS_KEY': 'shared'})
        self.assertEqual((args.client_id, args.role_name, args.actor_redis_key), ('a', 'manual_vehicle', 'shared'))
        args = self.parse(['--role-name', 'cli', '--actor-redis-key', 'cli-key'])
        self.assertEqual((args.role_name, args.actor_redis_key), ('cli', 'cli-key'))

    def test_metadata_cleanup_uses_atomic_compare_and_delete(self):
        client = Mock()
        client.get.return_value = '{"actor_id":"42"}'
        with patch.object(manual, 'redis_client_from_env', return_value=client):
            manual.clear_actor_metadata(SimpleNamespace(actor_redis_key='a'), '42')
        client.delete.assert_not_called()
        self.assertEqual(client.eval.call_args.args[1:], (1, 'a', '{"actor_id":"42"}'))
        client.eval.reset_mock()
        with patch.object(manual, 'redis_client_from_env', return_value=client):
            manual.clear_actor_metadata(SimpleNamespace(actor_redis_key='a'), '43')
        client.eval.assert_not_called()

    def test_late_cleanup_cannot_clear_same_actor_republished_by_other_client(self):
        client = Mock()
        client.get.return_value = '{"actor_id":"42","client_id":"new-owner"}'
        args = SimpleNamespace(actor_redis_key='shared', client_id='old-owner')
        with patch.object(manual, 'redis_client_from_env', return_value=client):
            manual.clear_actor_metadata(args, '42')
        client.eval.assert_not_called()
        client.delete.assert_not_called()
