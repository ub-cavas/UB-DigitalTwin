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
        r._state_lock = threading.RLock()
        r._native_vehicles = {}
        r._mirrors = Mock()
        r._mirrors.native.return_value = None
        r._mirrors.adopt.return_value = None
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
        r._mirrors.release.assert_called_once_with("ego", "old", actor=old_actor)
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
        r._mirrors = Mock()
        r._mirrors.adopt.return_value = None
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
        r._mirrors = Mock()
        r._native_vehicles = {}
        r.interpolation_delay = .125
        r.max_extrapolation = .1
        r.actor_smoothing = 1.
        r._state_lock = threading.RLock()
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
        r._state_lock = threading.RLock()
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
        r._state_lock = threading.RLock()
        r.pose_samples = {}
        r._native_vehicles = {}
        r._sample_timestamp = Mock(return_value=1)
        r._refresh_manual_actor_id = Mock()
        r._log_follow_waiting = Mock()
        r.on_receive_telemetry({'type': r.TRAFFIC_MESSAGE_TYPE, 'vehicles': []})
        r._refresh_manual_actor_id.assert_not_called()

if __name__ == '__main__':
    unittest.main()

class NativeAndOwnershipTests(unittest.TestCase):
    receiving_renderer = RendererTests.receiving_renderer
    ego_packet = RendererTests.ego_packet
    def test_confirmed_native_is_followed_without_pose_or_replica(self):
        r = self.receiving_renderer()
        actor = Mock(id=42)
        r._mirrors.native.return_value = actor
        packet = {'type': 2, 'world_id': 'same', 'vehicles': [{
            'id': '42', 'blueprint': 'vehicle.test', 'role_name': 'manual_vehicle:a',
            'location': {'x': 1, 'y': 2, 'z': 3}, 'yaw': 0}]}
        r.on_receive_telemetry(packet)
        self.assertIs(r._native_vehicles['42'], actor)
        self.assertEqual(r.pose_samples, {})
        r.interpolation_delay, r.max_extrapolation = 0, .1
        r._should_follow = lambda identity: identity == '42'
        r._update_follow_camera = Mock()
        r._render_once(.02)
        r._update_follow_camera.assert_called_once_with('42', actor.get_transform(), .02)
        actor.set_transform.assert_not_called()
        r.on_receive_telemetry({'type': 2, 'vehicles': []})
        self.assertEqual(r._native_vehicles, {})
        actor.destroy.assert_not_called()

    def test_lease_loss_drops_reference_without_transform_or_destroy(self):
        r = self.receiving_renderer()
        r.on_receive_telemetry(self.ego_packet('remote'))
        actor = Mock(id=7)
        r.traffic_vehicles['ego:remote'] = actor
        r._mirrors.owns.return_value = False
        r.interpolation_delay, r.max_extrapolation = 0, .1
        r._render_once(.02)
        actor.set_transform.assert_not_called()
        actor.destroy.assert_not_called()
        self.assertNotIn('ego:remote', r.traffic_vehicles)

    def test_empty_traffic_preserves_egos_and_invalid_pose_does_not_refresh(self):
        r = self.receiving_renderer()
        with patch.object(renderer.time, 'time', return_value=100):
            r.on_receive_telemetry(self.ego_packet('remote'))
        r.on_receive_telemetry({'type': 2, 'vehicles': []})
        invalid = self.ego_packet('remote')
        invalid['ego']['yaw'] = float('nan')
        r.on_receive_telemetry(invalid)
        self.assertEqual(r.last_message_timestamps['ego:remote'], 100)
        self.assertEqual(len(r.pose_samples['ego:remote']), 1)

    def test_explicit_self_id_is_filtered(self):
        r = self.receiving_renderer()
        with patch.dict(renderer.os.environ, {'UB_EGO_ID': 'self'}):
            r.on_receive_telemetry(self.ego_packet('self'))
            r.on_receive_telemetry(self.ego_packet('other'))
        self.assertEqual(set(r.pose_samples), {'ego:other'})

    def test_paired_metadata_selects_own_actor_and_refreshes_after_respawn(self):
        r = self.receiving_renderer()
        r.follow_traffic_id_is_explicit = False
        r.follow_traffic_id = ''
        r.manual_actor_redis_key = 'carla:manual_control:actor:client-a'
        r.redis_client = Mock()
        r.redis_client.get.side_effect = [json.dumps({'actor_id': '42', 'client_id': 'client-a'}),
                                         json.dumps({'actor_id': '43', 'client_id': 'client-a'})]
        r._reset_camera_state = Mock()
        r._refresh_manual_actor_id(force=True)
        self.assertEqual(r.follow_traffic_id, '42')
        r.followed_traffic_id = '42'
        r._refresh_manual_actor_id(force=True)
        self.assertEqual(r.follow_traffic_id, '43')
        self.assertIsNone(r.followed_traffic_id)
        r.redis_client.get.assert_called_with('carla:manual_control:actor:client-a')
        self.assertEqual(r._reset_camera_state.call_count, 2)

    def test_world_reload_drops_old_handles_without_actor_rpcs(self):
        r = self.receiving_renderer()
        r._mirrors.is_current_world.return_value = False
        r._mirrors.world_id = 'old'
        current = Mock(id='new')
        r.carla_client = Mock()
        r.carla_client.get_world.return_value = current
        r._mirrors.replacement_world = current
        r.redis_client, r.CHANNEL = Mock(), 'session'
        r.traffic_vehicles = {'ego:a': Mock(id=7)}
        old = r.traffic_vehicles['ego:a']
        r.pose_samples = {'ego:a': deque([pose(1, 1)])}
        r._reset_camera_state = Mock()
        with patch.object(renderer, 'VehicleMirrors') as factory:
            r._render_once(.02)
        self.assertEqual(r.traffic_vehicles, {})
        self.assertEqual(r.pose_samples, {})
        self.assertIs(r.world, current)
        factory.assert_called_once_with(r.redis_client, 'session', current, r.carla_client.get_world)
        old.destroy.assert_not_called()
        old.set_transform.assert_not_called()
        r.carla_client.apply_batch_sync.assert_not_called()

    def test_real_lease_reservation_survives_slow_spawn(self):
        from test_vehicle_mirrors import FakeRedis
        redis, actors = FakeRedis(), []
        w = SimpleNamespace(id='world', get_actors=lambda: SimpleNamespace(filter=lambda _: list(actors)))
        a = renderer.VehicleMirrors(redis, 's', w, clock=lambda: redis.now / 1000)
        b = renderer.VehicleMirrors(redis, 's', w, clock=lambda: redis.now / 1000)
        r = self.receiving_renderer()
        r._mirrors, r.world, r._blueprints = a, w, Mock()
        actor = Mock(id=1, attributes={'role_name': a.role('ego', 'a')}, is_alive=True)
        def spawn(*args):
            redis.now = 4000  # Longer than the ordinary three-second lease.
            self.assertFalse(b.claim('ego', 'a'))
            actors.append(actor)
            return actor
        w.try_spawn_actor = spawn
        r._add_vehicle('ego:a', carla_stub.Transform(Location(), Rotation()), 'vehicle.test', '0,0,0')
        self.assertEqual(actors, [actor])
        actor.set_simulate_physics.assert_called_once_with(False)
        self.assertIs(r.traffic_vehicles['ego:a'], actor)

    def test_real_lease_loss_during_spawn_never_mutates_late_actor_and_owner_deduplicates(self):
        from test_vehicle_mirrors import FakeRedis
        redis, actors = FakeRedis(), []
        w = SimpleNamespace(id='world', get_actors=lambda: SimpleNamespace(filter=lambda _: list(actors)))
        a = renderer.VehicleMirrors(redis, 's', w, clock=lambda: redis.now / 1000)
        b = renderer.VehicleMirrors(redis, 's', w, clock=lambda: redis.now / 1000)
        r = self.receiving_renderer()
        r._mirrors, r.world, r._blueprints = a, w, Mock()
        late = Mock(id=1, attributes={'role_name': a.role('ego', 'a')}, is_alive=True)
        current = Mock(id=2, attributes={'role_name': b.role('ego', 'a')}, is_alive=True)
        def spawn(*args):
            redis.now = a.SPAWN_TTL_MS + 1
            self.assertTrue(b.claim('ego', 'a'))
            actors.append(current)
            b.bind('ego', 'a', current)
            actors.append(late)
            return late
        w.try_spawn_actor = spawn
        r._add_vehicle('ego:a', carla_stub.Transform(Location(), Rotation()), 'vehicle.test', '0,0,0')
        late.set_simulate_physics.assert_not_called()
        late.set_transform.assert_not_called()
        self.assertEqual(r.traffic_vehicles, {})
        b.maintain()
        late.destroy.assert_called_once()
        current.destroy.assert_not_called()

    def test_real_helper_thirty_actor_frame_checks_episode_once_without_actor_scans_or_redis(self):
        from test_vehicle_mirrors import FakeRedis
        redis = FakeRedis()
        redis.eval = Mock(wraps=redis.eval)
        w = SimpleNamespace(id='world', get_actors=Mock(return_value=SimpleNamespace(filter=lambda _: [])))
        provider = Mock(return_value=w)
        mirrors = renderer.VehicleMirrors(redis, 's', w, provider)
        r = self.receiving_renderer()
        r._mirrors, r.world, r.carla_client = mirrors, w, Mock()
        r.interpolation_delay, r.max_extrapolation, r.actor_smoothing = 0, .1, 1
        r._should_follow = lambda _: False
        for i in range(30):
            identity = str(i)
            self.assertTrue(mirrors.claim('traffic', identity))
            r.pose_samples[identity] = deque([pose(0, i)])
            r.traffic_vehicles[identity] = Mock(id=i)
        redis.eval.reset_mock()
        provider.reset_mock()
        w.get_actors.reset_mock()
        r._render_once(.02)
        redis.eval.assert_not_called()
        provider.assert_called_once_with()
        w.get_actors.assert_not_called()
        self.assertEqual(len(r.carla_client.apply_batch_sync.call_args.args[0]), 30)

    def test_stalled_real_maintenance_allows_pose_callback_progress(self):
        from test_vehicle_mirrors import FakeRedis, world
        import time
        redis = FakeRedis()
        mirrors = renderer.VehicleMirrors(redis, 's', world())
        self.assertTrue(mirrors.claim('ego', 'a'))
        r = self.receiving_renderer()
        r._mirrors = mirrors
        entered, resume = threading.Event(), threading.Event()
        def stalled(*args):
            entered.set()
            resume.wait(timeout=1)
            raise TimeoutError('offline')
        redis.eval = stalled
        thread = threading.Thread(target=mirrors.maintain)
        thread.start()
        self.assertTrue(entered.wait(timeout=1))
        started = time.monotonic()
        r.on_receive_telemetry(self.ego_packet('new-peer'))
        self.assertLess(time.monotonic() - started, .05)
        self.assertIn('ego:new-peer', r.pose_samples)
        resume.set()
        thread.join(timeout=1)
        self.assertFalse(mirrors.owns('ego', 'a'))

    def test_reload_between_maintenance_cycles_blocks_old_numeric_batch(self):
        from test_vehicle_mirrors import FakeRedis, world
        current = [world('old')]
        provider = Mock(side_effect=lambda: current[0])
        mirrors = renderer.VehicleMirrors(FakeRedis(), 's', current[0], provider)
        self.assertTrue(mirrors.claim('traffic', '7'))
        r = self.receiving_renderer()
        r._mirrors = mirrors
        r.interpolation_delay, r.max_extrapolation, r.actor_smoothing = 0, .1, 1
        r._should_follow = lambda _: False
        r.carla_client = Mock()
        old_actor = Mock(id=7)
        replacement_native = Mock(id=7, attributes={'role_name': 'manual_vehicle:new'})
        r.pose_samples['7'] = deque([pose(0, 1)])
        r.traffic_vehicles['7'] = old_actor
        current[0] = world('new', actors=[replacement_native])
        # No maintain()/refresh_world(): cached ownership still describes the old episode.
        self.assertTrue(mirrors.owns('traffic', '7'))
        provider.reset_mock()
        r._render_once(.02)
        provider.assert_called_once_with()
        r.carla_client.apply_batch_sync.assert_not_called()
        replacement_native.set_transform.assert_not_called()
        replacement_native.destroy.assert_not_called()
        old_actor.set_transform.assert_not_called()

    def test_episode_lookup_failure_blocks_dispatch_without_waiting_for_maintenance(self):
        from test_vehicle_mirrors import FakeRedis, world
        provider = Mock(return_value=world())
        mirrors = renderer.VehicleMirrors(FakeRedis(), 's', provider(), provider)
        self.assertTrue(mirrors.claim('traffic', '7'))
        r = self.receiving_renderer()
        r._mirrors, r.carla_client = mirrors, Mock()
        r.interpolation_delay, r.max_extrapolation, r.actor_smoothing = 0, .1, 1
        r._should_follow = lambda _: False
        r.pose_samples['7'] = deque([pose(0, 1)])
        r.traffic_vehicles['7'] = Mock(id=7)
        provider.side_effect = TimeoutError('world unavailable')
        r._render_once(.02)
        r.carla_client.apply_batch_sync.assert_not_called()
        self.assertFalse(mirrors.owns('traffic', '7'))

    def test_failed_spawn_then_success_balances_real_reservation_and_restores_normal_ttl(self):
        from test_vehicle_mirrors import FakeRedis, world
        redis, actors = FakeRedis(), []
        w = world(actors=actors)
        mirrors = renderer.VehicleMirrors(redis, 's', w)
        r = self.receiving_renderer()
        r._mirrors, r.world, r._blueprints = mirrors, w, Mock()
        actor = Mock(id=7, is_alive=True, attributes={'role_name': mirrors.role('ego', 'a')})
        w.try_spawn_actor = Mock(side_effect=[None, None, actor])
        target = carla_stub.Transform(Location(), Rotation())
        r._add_vehicle('ego:a', target, 'vehicle.test', '0,0,0')
        key = mirrors._key('ego', 'a')
        self.assertNotIn(key, mirrors.claims)
        self.assertNotIn(key, redis.values)
        self.assertEqual(mirrors._spawn_counts.get(key, 0), 0)
        mirrors.maintain()
        self.assertNotIn(key, redis.values)
        r._add_vehicle('ego:a', target, 'vehicle.test', '0,0,0')
        self.assertEqual(mirrors._spawn_counts[key], 0)
        self.assertIs(r.traffic_vehicles['ego:a'], actor)
        mirrors.maintain()
        self.assertEqual(redis.values[key][1], mirrors.TTL_MS)

    def test_real_reservation_is_released_after_spawn_or_blueprint_exception(self):
        from test_vehicle_mirrors import FakeRedis, world
        for blueprint_error in (False, True):
            with self.subTest(blueprint_error=blueprint_error):
                redis, w = FakeRedis(), world()
                mirrors = renderer.VehicleMirrors(redis, 's', w)
                r = self.receiving_renderer()
                r._mirrors, r.world, r._blueprints = mirrors, w, Mock()
                w.try_spawn_actor = Mock(side_effect=RuntimeError('spawn unavailable'))
                if blueprint_error: r._blueprints.find.side_effect = RuntimeError('blueprint unavailable')
                target = carla_stub.Transform(Location(), Rotation())
                if blueprint_error:
                    with self.assertRaises(RuntimeError): r._add_vehicle('ego:a', target, 'vehicle.test', '0,0,0')
                else:
                    r._add_vehicle('ego:a', target, 'vehicle.test', '0,0,0')
                key = mirrors._key('ego', 'a')
                self.assertEqual(mirrors._spawn_counts.get(key, 0), 0)
                mirrors.maintain()
                self.assertNotIn(key, mirrors.claims)
                self.assertNotIn(key, redis.values)
