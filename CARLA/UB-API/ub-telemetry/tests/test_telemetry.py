"""Transport receive-loop regression tests without a Redis server."""
import json
from pathlib import Path
from types import ModuleType
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))
with patch.dict(sys.modules, {'redis': ModuleType('redis')}):
    from ub_telemetry.telemetry import Telemetry


class SubscriberTests(unittest.TestCase):
    def test_bounded_read_delivers_traffic_and_can_stop(self):
        t = Telemetry.__new__(Telemetry)
        t.id = 'client'
        t._should_stop_subscriber = False
        t.logger = Mock()
        t.on_receive_telemetry = Mock()
        packet = {'id': 'server', 'type': 2, 'vehicles': []}
        calls = []
        def read(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return None  # Idle subscription must remain interruptible.
            t._should_stop_subscriber = True
            return {'type': 'message', 'data': json.dumps(packet)}
        t.pubsub = Mock(get_message=read)
        t._telemetry_subscriber()
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertTrue(call['ignore_subscribe_messages'])
            self.assertGreater(call['timeout'], 0)
            self.assertLess(call['timeout'], 1)
        t.on_receive_telemetry.assert_called_once_with(packet)

if __name__ == '__main__':
    unittest.main()

class TransportTimeoutTests(unittest.TestCase):
    def test_actual_transport_constructor_bounds_connect_socket_and_retries(self):
        instance = Telemetry.__new__(Telemetry)
        def config():
            instance.HOST, instance.PORT, instance.PASSWORD, instance.CHANNEL = 'redis', 6390, '', 's'
        constructor = Mock()
        fake_redis = ModuleType('redis')
        fake_redis.Redis = constructor
        with patch.dict(Telemetry.__init__.__globals__, {'redis': fake_redis, 'Logger': Mock()}), \
             patch.object(instance, '_load_redis_config', side_effect=config):
            Telemetry.__init__(instance)
        kwargs = constructor.call_args.kwargs
        self.assertGreater(kwargs['socket_connect_timeout'], 0)
        self.assertLessEqual(kwargs['socket_connect_timeout'], .5)
        self.assertGreater(kwargs['socket_timeout'], 0)
        self.assertLessEqual(kwargs['socket_timeout'], .5)
        self.assertIsNone(kwargs['retry'])
        self.assertFalse(kwargs['retry_on_timeout'])

    def test_subscriber_timeout_can_stop_without_dispatching_or_ownership(self):
        t = Telemetry.__new__(Telemetry)
        t._should_stop_subscriber = False
        t.on_receive_telemetry = Mock()
        def timeout(**kwargs):
            t._should_stop_subscriber = True
            raise TimeoutError('service stalled')
        t.pubsub = Mock(get_message=timeout)
        t._telemetry_subscriber()
        t.on_receive_telemetry.assert_not_called()
