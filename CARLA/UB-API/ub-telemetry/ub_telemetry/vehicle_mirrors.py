"""Episode-scoped replica leases with local render-path ownership checks."""
import hashlib
import math
import threading
import time
import uuid
from collections import deque
from functools import wraps

MANAGED_ROLE_PREFIX = "ub_mirror:"


def managed_role(role):
    return str(role or "").startswith(MANAGED_ROLE_PREFIX)


def valid_ego(ego):
    if not isinstance(ego, dict):
        return False
    identity = ego.get("id")
    if isinstance(identity, bool) or not isinstance(identity, (str, int)) or not str(identity).strip():
        return False
    try:
        values = [ego["location"][axis] for axis in ("x", "y", "z")] + [ego["yaw"]]
        return all(not isinstance(value, bool) and math.isfinite(float(value)) for value in values)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _lease_operation(method):
    @wraps(method)
    def serialized(self, *args, **kwargs):
        # Service ordering is independent of the nonblocking local ownership lock.
        with self._operation_lock:
            return method(self, *args, **kwargs)
    return serialized


class VehicleMirrors:
    TTL_MS = 3000
    # Covers bounded 10-second spawn/fallback and world-verification RPCs.
    SPAWN_TTL_MS = 60000
    REFRESH_SECONDS = 0.5
    WORLD_MAX_AGE = 1.5
    RENEW = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('pexpire',KEYS[1],ARGV[2]) else return 0 end"
    RELEASE = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"
    RENEW_BATCH = "local r={} for i,k in ipairs(KEYS) do if redis.call('get',k)==ARGV[1] then r[i]=redis.call('pexpire',k,ARGV[i+1]) else r[i]=0 end end return r"

    def __init__(self, redis_client, channel, world, world_provider=None, clock=None):
        self.redis = redis_client
        self.world = world
        self.world_provider = world_provider
        self.world_id = str(getattr(world, "id", ""))
        self.channel = channel
        self.token = uuid.uuid4().hex
        self.clock = clock or time.monotonic
        self.claims = set()
        self._deadlines = {}
        self._ttls = {}
        self._identities = {}
        self._preferred = {}
        self._lock = threading.RLock()
        self._operation_lock = threading.RLock()
        self._spawn_counts = {}
        self._releases = deque()
        self._releasing = set()
        self._stop = threading.Event()
        self._thread = None
        self.replacement_world = None
        self._world_valid = False
        self._world_checked = float('-inf')
        self._actors = []
        self.refresh_world()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._maintenance_loop, daemon=True)
            self._thread.start()
        return self

    def close(self):
        self._stop.set()
        with self._lock:
            self._deadlines.clear()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.75)
        with self._lock:
            releases = list(self._releases)
            self._releases.clear()
        for args in releases:
            self._release_now(*args)

    def role(self, kind, identity):
        scope = [str(self.channel), self.world_id, kind, str(identity)]
        return MANAGED_ROLE_PREFIX + hashlib.sha256("\0".join(scope).encode()).hexdigest()

    def _key(self, kind, identity):
        return "ub:mirror:lease:" + self.role(kind, identity)

    def refresh_world(self):
        # Called only by maintenance/spawn paths, never by owns()/native().
        started = self.clock()
        try:
            current = self.world_provider() if self.world_provider else self.world
            valid = bool(self.world_id) and str(current.id) == self.world_id
            actors = list(current.get_actors().filter("vehicle.*")) if valid else []
        except Exception:
            current = self.world
            valid, actors = False, []
        with self._lock:
            self.replacement_world = current if not valid and str(current.id) != self.world_id else None
            self._world_valid, self._actors = valid, actors
            self._world_checked = started
        return valid

    def check_world(self, allow_closed=False):
        """Fresh episode check before actor command dispatch; no actor scan."""
        started = self.clock()
        try:
            current = self.world_provider() if self.world_provider else self.world
            valid = bool(self.world_id) and str(current.id) == self.world_id
        except Exception:
            current, valid = None, False
        with self._lock:
            self._world_valid = valid
            self._world_checked = started
            self.replacement_world = current if current is not None and not valid else None
        return valid and (allow_closed or not self._stop.is_set())

    def is_current_world(self):
        with self._lock:
            return not self._stop.is_set() and self._world_valid and self.clock() - self._world_checked < self.WORLD_MAX_AGE

    def _forget(self, key):
        with self._lock:
            self.claims.discard(key)
            self._deadlines.pop(key, None)
            self._ttls.pop(key, None)
            self._identities.pop(key, None)
            self._spawn_counts.pop(key, None)

    @_lease_operation
    def _renew(self, kind, identity, ttl):
        if self._stop.is_set(): return False
        key = self._key(kind, identity)
        with self._lock:
            if self._spawn_counts.get(key, 0): ttl = max(ttl, self.SPAWN_TTL_MS)
        started = self.clock()
        try:
            ok = self.redis.eval(self.RENEW, 1, key, self.token, ttl)
        except Exception:
            ok = False
        if ok and self.clock() < started + ttl / 1000.0:
            with self._lock:
                self.claims.add(key)
                self._deadlines[key] = started + ttl / 1000.0
                self._ttls[key] = ttl
                self._identities[key] = (kind, str(identity))
            return True
        self._forget(key)
        return False

    @_lease_operation
    def claim(self, kind, identity):
        if self._stop.is_set(): return False
        if self.owns(kind, identity):
            return True
        key = self._key(kind, identity)
        with self._lock:
            if key in self._releasing: return False
        if not self.refresh_world():
            return False
        started = self.clock()
        try:
            ok = self.redis.set(key, self.token, nx=True, px=self.TTL_MS)
        except Exception:
            ok = False
        if ok and self.clock() < started + self.TTL_MS / 1000.0:
            with self._lock:
                self.claims.add(key)
                self._deadlines[key] = started + self.TTL_MS / 1000.0
                self._ttls[key] = self.TTL_MS
                self._identities[key] = (kind, str(identity))
            return True
        self._forget(key)
        return False

    def owns(self, kind, identity):
        # Conservative local deadlines avoid one Redis/world RPC per actor/frame.
        with self._lock:
            return (self._key(kind, identity) not in self._releasing and self.is_current_world() and
                    self.clock() < self._deadlines.get(self._key(kind, identity), float('-inf')))

    @_lease_operation
    def begin_spawn(self, kind, identity):
        if not self.check_world(): return False
        if not (self.claim(kind, identity) and self._renew(kind, identity, self.SPAWN_TTL_MS)):
            return False
        with self._lock:
            key = self._key(kind, identity)
            self._spawn_counts[key] = self._spawn_counts.get(key, 0) + 1
        return True

    @_lease_operation
    def finish_spawn(self, kind, identity):
        # Always verify the token again after the blocking CARLA spawn RPC.
        return self._renew(kind, identity, self.SPAWN_TTL_MS) and self.check_world()

    def bind(self, kind, identity, actor):
        if self.owns(kind, identity):
            with self._lock:
                self._preferred[self._key(kind, identity)] = actor

    @_lease_operation
    def end_spawn(self, kind, identity, release_if_unused=False, actor=None):
        with self._lock:
            key = self._key(kind, identity)
            remaining = max(0, self._spawn_counts.get(key, 0) - 1)
            if key in self.claims:
                self._spawn_counts[key] = remaining
                self._ttls[key] = self.SPAWN_TTL_MS if remaining else self.TTL_MS
            else:
                self._spawn_counts.pop(key, None)
                self._ttls.pop(key, None)
            preferred = self._preferred.get(key)
            if preferred is not None and not getattr(preferred, "is_alive", True):
                self._preferred.pop(key, None)
            unused = not remaining and key not in self._preferred
        if release_if_unused and unused:
            self.release(kind, identity, actor)

    def adopt(self, kind, identity):
        if not self.owns(kind, identity):
            return None
        role = self.role(kind, identity)
        with self._lock:
            actors = list(self._actors)
        matches = [a for a in actors if a.attributes.get("role_name") == role and getattr(a, "is_alive", True)]
        actor = matches[0] if matches else None
        return actor

    def native(self, identity, source_world):
        if not self.is_current_world() or source_world is None or str(source_world) != self.world_id:
            return None
        with self._lock:
            actors = list(self._actors)
        return next((a for a in actors if str(a.id) == str(identity) and not managed_role(a.attributes.get("role_name"))), None)

    @_lease_operation
    def _release_now(self, kind, identity, actor):
        key = self._key(kind, identity)
        try:
            if (actor is not None and
                    self.redis.eval(self.RENEW, 1, key, self.token, self.SPAWN_TTL_MS) and
                    actor.attributes.get("role_name") == self.role(kind, identity) and self.check_world(allow_closed=True)):
                actor.destroy()
            self.redis.eval(self.RELEASE, 1, key, self.token)
        except Exception:
            pass
        self._forget(key)
        with self._lock:
            self._releasing.discard(key)
            self._preferred.pop(key, None)

    def release(self, kind, identity, actor=None):
        if self._thread is not None and not self._stop.is_set():
            with self._lock:
                self._deadlines.pop(self._key(kind, identity), None)
                self._releasing.add(self._key(kind, identity))
                self._releases.append((kind, identity, actor))
        else:
            self._release_now(kind, identity, actor)

    def maintain(self):
        self.refresh_world()
        with self._lock:
            releases = list(self._releases)
            self._releases.clear()
        for args in releases:
            self._release_now(*args)
        self._renew_claims()
        # Reconcile a late result from a spawn whose reservation was lost.
        with self._lock:
            identities, actors, preferred = dict(self._identities), list(self._actors), dict(self._preferred)
        for key, (kind, identity) in identities.items():
            matches = [a for a in actors if a.attributes.get("role_name") == self.role(kind, identity) and getattr(a, "is_alive", True)]
            keep = preferred.get(key)
            if keep not in matches:
                keep = matches[0] if matches else None
            for actor in matches:
                if actor != keep:
                    self._destroy_duplicate(kind, identity, actor)

    @_lease_operation
    def _destroy_duplicate(self, kind, identity, actor):
        if self._renew(kind, identity, self.SPAWN_TTL_MS) and self.check_world():
            actor.destroy()
            with self._lock:
                key = self._key(kind, identity)
                self._ttls[key] = self.SPAWN_TTL_MS if self._spawn_counts.get(key, 0) else self.TTL_MS

    @_lease_operation
    def _renew_claims(self):
        with self._lock:
            keys = list(self.claims)
        if keys and self.is_current_world():
            started = self.clock()
            with self._lock:
                ttls = [self._ttls.get(key, self.TTL_MS) for key in keys]
            try:
                renewed = self.redis.eval(self.RENEW_BATCH, len(keys), *keys, self.token, *ttls)
            except Exception:
                renewed = [False] * len(keys)
            for key, ttl, ok in zip(keys, ttls, renewed):
                if ok:
                    with self._lock:
                        self._deadlines[key] = started + ttl / 1000.0
                else:
                    self._forget(key)

    def _maintenance_loop(self):
        while not self._stop.wait(self.REFRESH_SECONDS):
            try:
                self.maintain()
            except Exception:
                # Local world/lease freshness deadlines expire even if a service stalls.
                pass
