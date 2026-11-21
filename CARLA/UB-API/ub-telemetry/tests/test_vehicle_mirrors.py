"""Atomic ownership tests without Redis or CARLA services."""
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parents[1]))
with patch.dict(sys.modules, {"redis": ModuleType("redis")}):
    from ub_telemetry.vehicle_mirrors import VehicleMirrors, valid_ego


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.now = 0
    def _expire(self, key):
        if key in self.values and self.values[key][1] <= self.now:
            del self.values[key]
    def set(self, key, value, nx=False, px=3000):
        self._expire(key)
        if nx and key in self.values: return False
        self.values[key] = (value, self.now + px)
        return True
    def eval(self, script, count, *values):
        if script == VehicleMirrors.RENEW_BATCH:
            keys = values[:count]
            token, *ttls = values[count:]
            return [FakeRedis.eval(self, VehicleMirrors.RENEW, 1, key, token, ttl) for key, ttl in zip(keys, ttls)]
        key, token, *args = values
        self._expire(key)
        if key not in self.values or self.values[key][0] != token: return 0
        if args: self.values[key] = (token, self.now + int(args[0]))
        else: del self.values[key]
        return 1


def world(identity='episode-a', actors=()):
    return SimpleNamespace(id=identity, get_actors=lambda: SimpleNamespace(filter=lambda pattern: list(actors)))


class MirrorTests(unittest.TestCase):
    def test_exclusive_claim_and_episode_channel_kind_isolation(self):
        redis = FakeRedis()
        a = VehicleMirrors(redis, 'session', world())
        b = VehicleMirrors(redis, 'session', world())
        self.assertTrue(a.claim('ego', 'a'))
        self.assertFalse(b.claim('ego', 'a'))
        self.assertTrue(b.claim('traffic', 'a'))
        self.assertTrue(VehicleMirrors(redis, 'other', world()).claim('ego', 'a'))
        self.assertTrue(VehicleMirrors(redis, 'session', world('episode-b')).claim('ego', 'a'))

    def test_expiry_reacquisition_and_late_release_never_touch_new_owner(self):
        redis = FakeRedis()
        actor = Mock(attributes={})
        a = VehicleMirrors(redis, 'session', world(actors=[actor]))
        actor.attributes['role_name'] = a.role('ego', 'a')
        b = VehicleMirrors(redis, 'session', world(actors=[actor]))
        self.assertTrue(a.claim('ego', 'a'))
        redis.now = 3001
        self.assertTrue(b.claim('ego', 'a'))
        a.release('ego', 'a', actor)
        actor.destroy.assert_not_called()
        self.assertTrue(b.owns('ego', 'a'))
        self.assertIs(b.adopt('ego', 'a'), actor)
        b.release('ego', 'a', actor)
        actor.destroy.assert_called_once()

    def test_native_requires_confirmed_world_and_is_never_destroyed(self):
        actor = Mock(id=42, attributes={'role_name': 'manual_vehicle:a'})
        mirrors = VehicleMirrors(FakeRedis(), 's', world(actors=[actor]))
        self.assertIs(mirrors.native('42', 'episode-a'), actor)
        self.assertIsNone(mirrors.native('42', 'episode-b'))
        self.assertIsNone(mirrors.native('42', None))
        self.assertTrue(mirrors.claim('traffic', '42'))
        mirrors.release('traffic', '42', actor)
        actor.destroy.assert_not_called()

    def test_redis_failure_and_missing_episode_fail_closed(self):
        redis = Mock()
        redis.set.side_effect = RuntimeError('offline')
        self.assertFalse(VehicleMirrors(redis, 's', world()).claim('ego', 'a'))
        self.assertFalse(VehicleMirrors(FakeRedis(), 's', world('')).claim('ego', 'a'))

    def test_validation_requires_complete_finite_pose(self):
        ego = {'id': 'a', 'location': {'x': 1, 'y': 2, 'z': 3}, 'yaw': 0}
        self.assertTrue(valid_ego(ego))
        for value in (float('nan'), float('inf'), None, 'bad'):
            self.assertFalse(valid_ego({**ego, 'yaw': value}))
        self.assertFalse(valid_ego({**ego, 'id': True}))
        self.assertFalse(valid_ego({**ego, 'location': {}}))

    def test_world_reload_refuses_old_actor_numbers_even_with_live_lease(self):
        old, new = world('old'), world('new')
        current = [old]
        actor = Mock(attributes={})
        mirrors = VehicleMirrors(FakeRedis(), 's', old, lambda: current[0])
        actor.attributes['role_name'] = mirrors.role('ego', 'a')
        self.assertTrue(mirrors.claim('ego', 'a'))
        current[0] = new
        mirrors.refresh_world()
        self.assertFalse(mirrors.owns('ego', 'a'))
        self.assertFalse(mirrors.claim('ego', 'a'))
        mirrors.release('ego', 'a', actor)
        actor.destroy.assert_not_called()

    def test_thirty_cached_actor_checks_have_no_per_actor_service_calls(self):
        redis = FakeRedis()
        redis.eval = Mock(wraps=redis.eval)
        provider = Mock(return_value=world())
        mirrors = VehicleMirrors(redis, 's', provider(), provider)
        for i in range(30): self.assertTrue(mirrors.claim('traffic', str(i)))
        mirrors.maintain()
        redis.eval.reset_mock()
        provider.reset_mock()
        for _ in range(60):
            self.assertTrue(mirrors.is_current_world())
            for i in range(30): self.assertTrue(mirrors.owns('traffic', str(i)))
        redis.eval.assert_not_called()
        provider.assert_not_called()
        mirrors.maintain()
        self.assertEqual(redis.eval.call_count, 1)
        self.assertEqual(provider.call_count, 1)

    def test_stalled_maintenance_does_not_block_owns_and_local_deadline_expires(self):
        import threading
        import time
        redis = FakeRedis()
        clock = [0.0]
        mirrors = VehicleMirrors(redis, 's', world(), clock=lambda: clock[0])
        self.assertTrue(mirrors.claim('ego', 'a'))
        entered, resume = threading.Event(), threading.Event()
        def stalled(*args):
            entered.set()
            resume.wait(timeout=1)
            raise TimeoutError('bounded service failure')
        redis.eval = stalled
        worker = threading.Thread(target=mirrors.maintain)
        worker.start()
        self.assertTrue(entered.wait(timeout=1))
        began = time.monotonic()
        self.assertTrue(mirrors.owns('ego', 'a'))
        clock[0] = 4
        self.assertFalse(mirrors.owns('ego', 'a'))
        self.assertLess(time.monotonic() - began, .05)
        resume.set()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())

    def test_inflight_ordinary_batch_finishes_before_spawn_reservation(self):
        import threading
        import time
        redis = FakeRedis()
        mirrors = VehicleMirrors(redis, 's', world(), clock=lambda: redis.now / 1000)
        competitor = VehicleMirrors(redis, 's', world(), clock=lambda: redis.now / 1000)
        self.assertTrue(mirrors.claim('ego', 'a'))
        entered, resume = threading.Event(), threading.Event()
        original_eval = redis.eval
        def delayed(script, *args):
            if script == VehicleMirrors.RENEW_BATCH:
                entered.set()
                resume.wait(timeout=1)
            return original_eval(script, *args)
        redis.eval = delayed
        maintenance = threading.Thread(target=mirrors.maintain)
        maintenance.start()
        self.assertTrue(entered.wait(timeout=1))
        reserved = []
        spawn = threading.Thread(target=lambda: reserved.append(mirrors.begin_spawn('ego', 'a')))
        spawn.start()
        began = time.monotonic()
        self.assertTrue(mirrors.owns('ego', 'a'))
        self.assertLess(time.monotonic() - began, .05)
        self.assertTrue(spawn.is_alive())
        resume.set()
        maintenance.join(timeout=1)
        spawn.join(timeout=1)
        self.assertEqual(reserved, [True])
        key = mirrors._key('ego', 'a')
        self.assertEqual(redis.values[key][1], mirrors.SPAWN_TTL_MS)
        self.assertEqual(mirrors._deadlines[key], mirrors.SPAWN_TTL_MS / 1000)
        redis.now = 4000
        self.assertFalse(competitor.claim('ego', 'a'))

    def test_waiting_batch_selects_ttl_inside_operation_lock_after_new_reservation(self):
        import threading
        redis = FakeRedis()
        refreshed = threading.Event()
        w = world()
        mirrors = VehicleMirrors(redis, 's', w, clock=lambda: redis.now / 1000)
        self.assertTrue(mirrors.claim('ego', 'a'))
        original_refresh = mirrors.refresh_world
        def refresh():
            result = original_refresh()
            refreshed.set()
            return result
        mirrors.refresh_world = refresh
        with mirrors._operation_lock:
            maintenance = threading.Thread(target=mirrors.maintain)
            maintenance.start()
            self.assertTrue(refreshed.wait(timeout=1))
            self.assertTrue(mirrors.begin_spawn('ego', 'a'))
        maintenance.join(timeout=1)
        self.assertFalse(maintenance.is_alive())
        key = mirrors._key('ego', 'a')
        self.assertEqual(redis.values[key][1], mirrors.SPAWN_TTL_MS)
        self.assertEqual(mirrors._deadlines[key], mirrors.SPAWN_TTL_MS / 1000)

    def test_nested_spawn_end_cannot_shorten_other_active_reservation(self):
        redis = FakeRedis()
        mirrors = VehicleMirrors(redis, 's', world())
        self.assertTrue(mirrors.begin_spawn('ego', 'a'))
        self.assertTrue(mirrors.begin_spawn('ego', 'a'))
        mirrors.end_spawn('ego', 'a')
        mirrors.maintain()
        key = mirrors._key('ego', 'a')
        self.assertEqual(redis.values[key][1], mirrors.SPAWN_TTL_MS)
        mirrors.end_spawn('ego', 'a')
        mirrors.maintain()
        self.assertEqual(redis.values[key][1], mirrors.TTL_MS)

    def test_changed_episode_rejects_spawn_result_and_destruction_without_maintenance(self):
        old, replacement = world('old'), world('replacement')
        current = [old]
        mirrors = VehicleMirrors(FakeRedis(), 's', old, lambda: current[0])
        self.assertTrue(mirrors.begin_spawn('ego', 'a'))
        returned = Mock(id=7, attributes={'role_name': mirrors.role('ego', 'a')})
        current[0] = replacement
        self.assertFalse(mirrors.finish_spawn('ego', 'a'))
        mirrors.release('ego', 'a', returned)
        returned.destroy.assert_not_called()

    def test_unused_cleanup_waits_for_last_concurrent_reservation(self):
        redis = FakeRedis()
        mirrors = VehicleMirrors(redis, 's', world())
        self.assertTrue(mirrors.begin_spawn('ego', 'a'))
        self.assertTrue(mirrors.begin_spawn('ego', 'a'))
        key = mirrors._key('ego', 'a')
        mirrors.end_spawn('ego', 'a', release_if_unused=True)
        mirrors.maintain()
        self.assertEqual(mirrors._spawn_counts[key], 1)
        self.assertEqual(redis.values[key][1], mirrors.SPAWN_TTL_MS)
        mirrors.end_spawn('ego', 'a', release_if_unused=True)
        mirrors.maintain()
        self.assertNotIn(key, redis.values)
        self.assertNotIn(key, mirrors.claims)

    def test_failed_attempt_preserves_retained_actor_and_other_active_reservation(self):
        redis = FakeRedis()
        actor = Mock(id=7, is_alive=True)
        mirrors = VehicleMirrors(redis, 's', world())
        self.assertTrue(mirrors.begin_spawn('ego', 'a'))
        self.assertTrue(mirrors.begin_spawn('ego', 'a'))
        mirrors.bind('ego', 'a', actor)
        mirrors.end_spawn('ego', 'a', release_if_unused=True)
        mirrors.end_spawn('ego', 'a')
        mirrors.maintain()
        key = mirrors._key('ego', 'a')
        self.assertTrue(mirrors.owns('ego', 'a'))
        self.assertEqual(mirrors._spawn_counts[key], 0)
        self.assertEqual(redis.values[key][1], mirrors.TTL_MS)
        actor.destroy.assert_not_called()
