"""Renderer regressions; CARLA/Redis servers and their Python wheels are optional."""
from collections import deque
import json
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
    def receiving_renderer(self):
        r = renderer.MultiTrafficRenderer.__new__(renderer.MultiTrafficRenderer)
        r._state_lock = threading.Lock()
        r.pose_samples = {}
        r.traffic_vehicles = {}
        r.actor_transforms = {}
        r.failed_spawn_timestamps = {}
        r.last_message_timestamps = {}
        r.vehicle_roles = {}
        r._ego_vehicle_ids = set()
        r.skip_local_ids = False
        r._record_observed_role = Mock()
        r._log_follow_waiting = Mock()
        r._sample_timestamp = Mock(return_value=100.)
        r.followed_traffic_id = None
        r._snapped_camera_traffic_ids = set()
        return r

    def ego_packet(self, ego_id, x=1.):
        # Matches the native Unity publisher, including its shared sender ID.
        return json.loads(json.dumps({
            'id': 'ub-mr', 'type': 3, 'timestamp': 999999.,
            'ego': {'id': ego_id, 'blueprint': 'vehicle.lincoln.mkz_2017',
                    'color': '0,0,0', 'location': {'x': x, 'y': 2., 'z': .3}, 'yaw': 45.},
        }))

    def test_multiple_unity_clients_and_numeric_traffic_id_render_separately(self):
        r = self.receiving_renderer()
        with patch.object(renderer.time, 'time', return_value=100.):
            r.on_receive_telemetry({'type': 2, 'server_timestamp': 5., 'vehicles': [{
                'id': '42', 'blueprint': 'vehicle.test', 'role_name': 'manual_vehicle',
                'location': {'x': 10., 'y': 0., 'z': 0.}, 'yaw': 0.,
            }]})
            r.on_receive_telemetry(self.ego_packet('42', 20.))
            r.on_receive_telemetry(self.ego_packet('laptop-b', 30.))
        with patch.object(renderer.time, 'time', return_value=100.1):
            r.on_receive_telemetry(self.ego_packet('42', 21.))
        r.interpolation_delay = 0.
        r.max_extrapolation = .1
        r.actor_smoothing = 1.
        r._should_follow = lambda vehicle_id: False
        r._blueprints = Mock()
        r.world = Mock()
        r.world.try_spawn_actor.side_effect = [Mock(id=1), Mock(id=2), Mock(id=3)]
        r.carla_client = Mock()
        with patch.object(renderer.time, 'time', return_value=100.1):
            r._render_once(1/60)
        self.assertEqual(set(r.traffic_vehicles), {'42', 'ego:42', 'ego:laptop-b'})
        self.assertEqual(r.actor_transforms['42'].location.x, 10.)
        self.assertEqual(r.actor_transforms['ego:42'].location.x, 21.)
        self.assertEqual(r.actor_transforms['ego:laptop-b'].location.x, 30.)
        for actor in r.traffic_vehicles.values():
            actor.set_simulate_physics.assert_called_once_with(False)
        self.assertEqual(r.vehicle_roles['ego:42'], 'external_ego')
        # Only traffic updates the simulation clock estimator.
        r._sample_timestamp.assert_called_once()
        self.assertEqual(r.pose_samples['ego:42'][-1]['timestamp'], 100.1)

    def test_stale_ego_is_removed_while_traffic_and_active_ego_remain(self):
        r = self.receiving_renderer()
        with patch.object(renderer.time, 'time', return_value=100.):
            r.on_receive_telemetry(self.ego_packet('old'))
            r.on_receive_telemetry(self.ego_packet('active'))
        with patch.object(renderer.time, 'time', return_value=102.):
            r.on_receive_telemetry(self.ego_packet('active', 5.))
        old_actor = Mock()
        r.traffic_vehicles['ego:old'] = old_actor
        r.last_message_timestamps['42'] = 100.
        r._cleanup_stale_vehicles(102.1)
        old_actor.destroy.assert_called_once()
        self.assertNotIn('ego:old', r.pose_samples)
        self.assertNotIn('ego:old', r.last_message_timestamps)
        self.assertNotIn('ego:old', r._ego_vehicle_ids)
        self.assertIn('ego:active', r.pose_samples)
        self.assertIn('42', r.last_message_timestamps)
        # A reconnect with the same ego ID starts a new replica history.
        with patch.object(renderer.time, 'time', return_value=103.):
            r.on_receive_telemetry(self.ego_packet('old', 9.))
        self.assertEqual(len(r.pose_samples['ego:old']), 1)
        self.assertEqual(r.pose_samples['ego:old'][0]['x'], 9.)

    def test_missing_ego_blueprint_uses_server_renderer_default(self):
        r = self.receiving_renderer()
        packet = self.ego_packet('laptop')
        del packet['ego']['blueprint']
        r.on_receive_telemetry(packet)
        self.assertEqual(r.pose_samples['ego:laptop'][0]['blueprint'], 'vehicle.lincoln.mkz_2017')

    def test_invalid_ego_poses_and_other_message_types_are_ignored(self):
        r = self.receiving_renderer()
        invalid_egos = [None, {}, {'id': []}, {'id': 'a', 'location': None}]
        for axis in ('x', 'y', 'z'):
            ego = self.ego_packet('a')['ego']
            ego['location'][axis] = float('nan')
            invalid_egos.append(ego)
        ego = self.ego_packet('a')['ego']
        ego['yaw'] = float('inf')
        invalid_egos.append(ego)
        for ego in invalid_egos:
            r.on_receive_telemetry({'type': 3, 'ego': ego})
        r.on_receive_telemetry({'type': 0, 'ego': self.ego_packet('a')['ego']})
        self.assertEqual(r.pose_samples, {})
        self.assertEqual(r.last_message_timestamps, {})

    def test_settled_vehicle_spawns_with_clearance_then_restores_pose(self):
        r = renderer.MultiTrafficRenderer.__new__(renderer.MultiTrafficRenderer)
        r._blueprints = Mock()
        r.vehicle_roles = {'manual': 'manual_vehicle'}
        r.traffic_vehicles = {}
        r.actor_transforms = {}
        r.failed_spawn_timestamps = {}
        vehicle = Mock()
        r.world = Mock()
        r.world.try_spawn_actor.side_effect = [None, vehicle]
        target = carla_stub.Transform(Location(1, 2, -.005), Rotation(yaw=30))
        r._add_vehicle('manual', target, 'vehicle.test', '0,0,255')
        raised = r.world.try_spawn_actor.call_args_list[1].args[1]
        self.assertAlmostEqual(raised.location.z, .995)
        self.assertAlmostEqual(target.location.z, -.005)
        vehicle.set_simulate_physics.assert_called_once_with(False)
        vehicle.set_transform.assert_called_once_with(target)
        self.assertIs(r.traffic_vehicles['manual'], vehicle)

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
