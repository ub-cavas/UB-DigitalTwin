"""Renderer regressions; CARLA/Redis servers and their Python wheels are optional."""
from collections import deque
from pathlib import Path
from types import SimpleNamespace, ModuleType
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))

class Location:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z

class Rotation:
    def __init__(self, pitch=0, yaw=0, roll=0):
        self.pitch, self.yaw, self.roll = pitch, yaw, roll

carla_stub = SimpleNamespace(
    Location=Location, Rotation=Rotation,
    Transform=lambda location, rotation: SimpleNamespace(location=location, rotation=rotation),
    command=SimpleNamespace(ApplyTransform=lambda actor, transform: (actor, transform)),
)
with patch.dict(sys.modules, {'carla': carla_stub, 'redis': ModuleType('redis')}):
    from ub_telemetry import multi_traffic_renderer as renderer


def pose(t, x):
    return dict(timestamp=t, x=x, y=0., z=0., yaw=0., blueprint='vehicle.test')


class RendererTests(unittest.TestCase):
    def test_interpolates_constant_speed_through_irregular_packet_spacing(self):
        samples = [pose(t, 10*t) for t in (0, .017, .038, .1, .118, .2)]
        for target in (.01, .025, .05, .125, .18):
            self.assertAlmostEqual(renderer._select_render_sample(samples, target, .1)['x'], 10*target)

    def test_extrapolation_stops_at_configured_limit(self):
        result = renderer._select_render_sample([pose(0, 0), pose(.1, 1)], .5, .1)
        self.assertAlmostEqual(result['x'], 2.)

    def test_window_min_offset_rejects_queue_delay(self):
        r = renderer.MultiTrafficRenderer.__new__(renderer.MultiTrafficRenderer)
        r._server_time_offset = None
        r._offset_samples = deque()
        r.offset_window = 5.
        r.offset_resync_threshold = 1.
        r._sample_timestamp({'server_timestamp': 1}, 101)
        self.assertEqual(r._sample_timestamp({'server_timestamp': 1.1}, 101.3), 101.1)
        self.assertEqual(r._sample_timestamp({}, 102), 102)

    def test_traffic_and_camera_are_sent_in_one_acknowledged_batch(self):
        r = renderer.MultiTrafficRenderer.__new__(renderer.MultiTrafficRenderer)
        r.interpolation_delay = .125
        r.max_extrapolation = .1
        r.actor_smoothing = 1.
        r._state_lock = threading.Lock()
        r.pose_samples = {'a': deque([pose(0, 0), pose(1, 10)]), 'b': deque([pose(0, 1), pose(1, 11)])}
        r.traffic_vehicles = {'a': Mock(id=11), 'b': Mock(id=12)}
        r.actor_transforms = {}
        r._spectator = Mock(id=99)
        r._should_follow = lambda traffic_id: traffic_id == 'a'
        r._update_follow_camera = lambda traffic_id, transform, dt: r._set_spectator_transform(transform)
        r.carla_client = Mock()
        with patch.object(renderer.time, 'time', return_value=.625):
            r._render_once(1/60)
        r.carla_client.apply_batch_sync.assert_called_once()
        commands, tick = r.carla_client.apply_batch_sync.call_args.args
        self.assertFalse(tick)
        self.assertEqual([command[0] for command in commands], [11, 99, 12])
        self.assertEqual([command[1].location.x for command in commands], [5, 5, 6])
        for actor in r.traffic_vehicles.values():
            actor.set_transform.assert_not_called()
        r._spectator.set_transform.assert_not_called()

    def test_fast_local_ticks_are_not_discarded(self):
        r = renderer.MultiTrafficRenderer.__new__(renderer.MultiTrafficRenderer)
        r.update_hz = 60.
        r._should_stop_render = False
        r._wait_for_render_tick = Mock()
        count = []
        def render(dt):
            count.append(dt)
            if len(count) == 3:
                r._should_stop_render = True
        r._render_once = render
        with patch.object(renderer.time, 'monotonic', side_effect=[0, .008, .016, .024]):
            r._render_loop()
        self.assertEqual(len(count), 3)

    def test_packet_receiver_does_not_poll_remote_metadata(self):
        r = renderer.MultiTrafficRenderer.__new__(renderer.MultiTrafficRenderer)
        r._sample_timestamp = Mock(return_value=1)
        r._refresh_manual_actor_id = Mock()
        r._log_follow_waiting = Mock()
        r.on_receive_telemetry({'type': r.TRAFFIC_MESSAGE_TYPE, 'vehicles': []})
        r._refresh_manual_actor_id.assert_not_called()

if __name__ == '__main__':
    unittest.main()
