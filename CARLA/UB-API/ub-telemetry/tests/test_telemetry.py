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
