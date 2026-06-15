import atexit
import json
import math
import os
import threading
import time
from collections import deque

import carla

from telemetry import Telemetry

# Utility to convert location dict to CARLA location
def get_spawn_point_location(world, loc_dict):
    return carla.Location(x=loc_dict["x"], y=loc_dict["y"], z=loc_dict["z"])


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in ("0", "false", "no", "off")


def _env_float(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        print(f"[x] Invalid {name}={value!r}; using {default}")
        return default


def _finite_float(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _env_choice(name, default, choices):
    value = os.environ.get(name, default).strip().lower()
    if value in choices:
        return value
    print(f"[x] Invalid {name}={value!r}; using {default!r}")
    return default


def _normalize_angle_degrees(angle):
    return (angle + 180.0) % 360.0 - 180.0


def _lerp(a, b, alpha):
    return a + (b - a) * alpha


def _lerp_angle_degrees(a, b, alpha):
    return _normalize_angle_degrees(a + _normalize_angle_degrees(b - a) * alpha)


def _lerp_location(a, b, alpha):
    return carla.Location(
        x=_lerp(a.x, b.x, alpha),
        y=_lerp(a.y, b.y, alpha),
        z=_lerp(a.z, b.z, alpha),
    )


def _location_distance(a, b):
    dx = a.x - b.x
    dy = a.y - b.y
    dz = a.z - b.z
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _sample_to_transform(sample):
    return carla.Transform(
        carla.Location(
            x=sample["x"],
            y=sample["y"],
            z=sample["z"],
        ),
        carla.Rotation(yaw=sample["yaw"]),
    )


def _interpolate_samples(before, after, target_time):
    dt = after["timestamp"] - before["timestamp"]
    if dt <= 1e-6:
        return dict(after)

    alpha = max(0.0, min(1.0, (target_time - before["timestamp"]) / dt))
    sample = dict(after)
    sample.update({
        "timestamp": target_time,
        "x": _lerp(before["x"], after["x"], alpha),
        "y": _lerp(before["y"], after["y"], alpha),
        "z": _lerp(before["z"], after["z"], alpha),
        "yaw": _lerp_angle_degrees(before["yaw"], after["yaw"], alpha),
    })
    return sample


def _extrapolate_sample(previous, latest, target_time, max_extrapolation_seconds):
    if previous is None:
        return dict(latest)

    sample_dt = latest["timestamp"] - previous["timestamp"]
    if sample_dt <= 1e-6:
        return dict(latest)

    extrapolation_dt = min(
        max(0.0, target_time - latest["timestamp"]),
        max_extrapolation_seconds,
    )
    sample = dict(latest)
    sample.update({
        "timestamp": latest["timestamp"] + extrapolation_dt,
        "x": latest["x"] + ((latest["x"] - previous["x"]) / sample_dt) * extrapolation_dt,
        "y": latest["y"] + ((latest["y"] - previous["y"]) / sample_dt) * extrapolation_dt,
        "z": latest["z"] + ((latest["z"] - previous["z"]) / sample_dt) * extrapolation_dt,
        "yaw": _normalize_angle_degrees(
            latest["yaw"]
            + (_normalize_angle_degrees(latest["yaw"] - previous["yaw"]) / sample_dt)
            * extrapolation_dt
        ),
    })
    return sample


def _select_render_sample(samples, target_time, max_extrapolation_seconds):
    if not samples:
        return None
    if len(samples) == 1:
        return dict(samples[0])

    if target_time <= samples[0]["timestamp"]:
        return dict(samples[0])

    for index in range(1, len(samples)):
        before = samples[index - 1]
        after = samples[index]
        if target_time <= after["timestamp"]:
            return _interpolate_samples(before, after, target_time)

    return _extrapolate_sample(samples[-2], samples[-1], target_time, max_extrapolation_seconds)


def _blend_transforms(current, target, alpha):
    return carla.Transform(
        carla.Location(
            x=_lerp(current.location.x, target.location.x, alpha),
            y=_lerp(current.location.y, target.location.y, alpha),
            z=_lerp(current.location.z, target.location.z, alpha),
        ),
        carla.Rotation(
            pitch=_lerp(current.rotation.pitch, target.rotation.pitch, alpha),
            yaw=_lerp_angle_degrees(current.rotation.yaw, target.rotation.yaw, alpha),
            roll=_lerp(current.rotation.roll, target.rotation.roll, alpha),
        ),
    )


def _frame_scaled_alpha(alpha, dt, reference_hz=60.0):
    alpha = max(0.0, min(1.0, alpha))
    if alpha <= 0.0 or alpha >= 1.0:
        return alpha
    reference_dt = 1.0 / reference_hz
    return 1.0 - ((1.0 - alpha) ** max(0.0, dt / reference_dt))


class MultiTrafficRenderer(Telemetry):
    TRAFFIC_MESSAGE_TYPE = 2
    SILENCE_DURATION = 5.0
    VEHICLE_CLEANUP_INTERVAL = 1.0
    SPAWN_RETRY_INTERVAL = 2.0
    SAMPLE_HISTORY_SECONDS = 2.0
    DEFAULT_VEHICLE_COLOR = "255,255,255"
    DEFAULT_MANUAL_ACTOR_REDIS_KEY = "carla:manual_control:actor"
    CAMERA_MODE_CONTINUOUS = "continuous"
    CAMERA_MODE_SNAP_ONCE = "snap_once"
    CAMERA_MODE_OFF = "off"

    def __init__(self, carla_host=None, carla_port=None):
        super().__init__()
        carla_host = carla_host or os.environ.get(
            "UB_RENDER_CARLA_HOST",
            os.environ.get("UB_CARLA_HOST", "localhost")
        )
        carla_port = carla_port or int(os.environ.get(
            "UB_RENDER_CARLA_PORT",
            os.environ.get("UB_CARLA_PORT", "2000")
        ))
        print(f"[!] Traffic renderer connecting to visual CARLA at {carla_host}:{carla_port}")
        self.carla_client = carla.Client(carla_host, carla_port)
        self.carla_client.set_timeout(10.0)
        self.world = self.carla_client.get_world()
        print(f"[!] Traffic renderer connected to visual CARLA map={self.world.get_map().name}")
        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        self.traffic_vehicles = {}
        self.actor_transforms = {}
        self.failed_spawn_timestamps = {}
        self.pose_samples = {}
        self.last_message_timestamps = {}
        self.vehicle_roles = {}
        self.follow_role_name = os.environ.get("UB_RENDER_FOLLOW_ROLE_NAME", "")
        self.follow_spectator = _env_bool("UB_RENDER_FOLLOW_SPECTATOR", bool(self.follow_role_name))
        self.skip_local_ids = _env_bool("UB_RENDER_SKIP_LOCAL_IDS", False)
        self.interpolation_delay = _env_float("UB_RENDER_INTERPOLATION_DELAY_MS", 125.0) / 1000.0
        self.max_extrapolation = _env_float("UB_RENDER_MAX_EXTRAPOLATION_MS", 100.0) / 1000.0
        self.update_hz = max(1.0, _env_float("UB_RENDER_UPDATE_HZ", 60.0))
        self.actor_smoothing = max(0.0, min(1.0, _env_float("UB_RENDER_ACTOR_SMOOTHING", 0.45)))
        self.camera_smoothing = max(0.0, min(1.0, _env_float("UB_RENDER_CAMERA_SMOOTHING", 0.15)))
        self.camera_position_deadband = max(
            0.0,
            _env_float("UB_RENDER_CAMERA_POSITION_DEADBAND_M", 0.10),
        )
        self.camera_yaw_deadband = max(
            0.0,
            _env_float("UB_RENDER_CAMERA_YAW_DEADBAND_DEG", 0.50),
        )
        self.camera_target_smoothing = max(
            0.0,
            min(1.0, _env_float("UB_RENDER_CAMERA_TARGET_SMOOTHING", 0.14)),
        )
        self.camera_yaw_smoothing = max(
            0.0,
            min(1.0, _env_float("UB_RENDER_CAMERA_YAW_SMOOTHING", 0.04)),
        )
        self.camera_distance = max(0.0, _env_float("UB_RENDER_CAMERA_DISTANCE_M", 8.0))
        self.camera_height = _env_float("UB_RENDER_CAMERA_HEIGHT_M", 4.0)
        self.camera_pitch = _env_float("UB_RENDER_CAMERA_PITCH_DEG", -15.0)
        self.camera_mode = _env_choice(
            "UB_RENDER_CAMERA_MODE",
            self.CAMERA_MODE_CONTINUOUS,
            {
                self.CAMERA_MODE_CONTINUOUS,
                self.CAMERA_MODE_SNAP_ONCE,
                self.CAMERA_MODE_OFF,
            },
        )
        self.timestamp_offset_smoothing = max(
            0.0,
            min(1.0, _env_float("UB_RENDER_TIMESTAMP_OFFSET_SMOOTHING", 0.10)),
        )
        self.followed_traffic_id = None
        self.follow_traffic_id = os.environ.get("UB_RENDER_FOLLOW_TRAFFIC_ID", "")
        self.follow_traffic_id_is_explicit = bool(self.follow_traffic_id)
        self.manual_actor_redis_key = os.environ.get(
            "UB_RENDER_MANUAL_ACTOR_REDIS_KEY",
            self.DEFAULT_MANUAL_ACTOR_REDIS_KEY,
        )
        self._last_manual_actor_lookup = 0.0
        self._last_follow_wait_log = 0.0
        self._last_observed_roles_log = 0.0
        self._observed_roles = {}
        self._server_time_offset = None
        self._snapped_camera_traffic_ids = set()
        self._camera_transform = None
        self._camera_desired_transform = None
        self._camera_anchor_location = None
        self._camera_anchor_yaw = None
        self._state_lock = threading.Lock()

        self._should_stop_cleaner = False
        self._cleaner_thread = None
        self._should_stop_render = False
        self._render_thread = None
        self._is_running = False

        self._refresh_manual_actor_id(force=True)
        print(f"[!] Traffic renderer listening to Redis {self.HOST}:{self.PORT} channel={self.CHANNEL}")
        print(
            "[!] Traffic renderer smoothing: "
            f"delay={self.interpolation_delay * 1000:.0f}ms "
            f"max_extrapolation={self.max_extrapolation * 1000:.0f}ms "
            f"update_hz={self.update_hz:.0f} "
            f"actor_smoothing={self.actor_smoothing:.2f} "
            f"camera_smoothing={self.camera_smoothing:.2f} "
            f"camera_position_deadband={self.camera_position_deadband:.2f}m "
            f"camera_yaw_deadband={self.camera_yaw_deadband:.2f}deg "
            f"camera_target_smoothing={self.camera_target_smoothing:.2f} "
            f"camera_yaw_smoothing={self.camera_yaw_smoothing:.2f} "
            f"camera_distance={self.camera_distance:.1f}m "
            f"camera_height={self.camera_height:.1f}m "
            f"camera_pitch={self.camera_pitch:.1f}deg "
            f"camera_mode={self.camera_mode} "
            f"timestamp_offset_smoothing={self.timestamp_offset_smoothing:.2f}"
        )
        if self.follow_spectator and self.follow_role_name:
            print(f"[!] Visual CARLA spectator will follow role_name={self.follow_role_name}")
        if self.follow_spectator and self.follow_traffic_id:
            print(f"[!] Visual CARLA spectator will follow traffic actor ID={self.follow_traffic_id}")

    def on_receive_telemetry(self, parsed_message):
        if parsed_message.get("type") != self.TRAFFIC_MESSAGE_TYPE:
            return

        receive_time = time.time()
        sample_timestamp = self._sample_timestamp(parsed_message, receive_time)
        self._refresh_manual_actor_id()
        vehicles = parsed_message.get("vehicles", [])
        for v_msg in vehicles:
            traffic_id = v_msg["id"]
            self.last_message_timestamps[traffic_id] = receive_time
            self.vehicle_roles[traffic_id] = v_msg.get("role_name", "")
            self._record_observed_role(traffic_id, self.vehicle_roles[traffic_id])

            if self.skip_local_ids and traffic_id in self._local_vehicle_ids():
                continue

            if "location" not in v_msg or "blueprint" not in v_msg:
                continue

            self._record_pose_sample(traffic_id, v_msg, sample_timestamp)

        self._log_follow_waiting()

    def on_receive_conn_destroy(self, traffic_id):
        if traffic_id in self.traffic_vehicles:
            self._destroy_vehicle(traffic_id)

    def handle_fetch_telemetry_data(self):
        return {}  # Subscriber does not send traffic

    # --------------------------
    # Internal helpers
    # --------------------------

    def _local_vehicle_ids(self):
        return {str(v.id) for v in self.world.get_actors().filter("vehicle.*")}

    def _add_vehicle(self, vid, transform, blueprint, color):
        bp = self.world.get_blueprint_library().find(blueprint)
        if bp.has_attribute("color"):
            bp.set_attribute("color", color)
        try:
            vehicle = self.world.try_spawn_actor(bp, transform)
        except RuntimeError as exc:
            print(f"[x] Could not spawn mirrored traffic vehicle ID={vid}: {exc}")
            self.failed_spawn_timestamps[vid] = time.time()
            return
        if vehicle is None:
            print(f"[x] Could not spawn mirrored traffic vehicle ID={vid}: collision at spawn position")
            self.failed_spawn_timestamps[vid] = time.time()
            return
        vehicle.set_simulate_physics(False)
        self.traffic_vehicles[vid] = vehicle
        self.actor_transforms[vid] = transform
        self.failed_spawn_timestamps.pop(vid, None)
        print(f"[!] Spawned mirrored traffic vehicle ID={vid}")

    def _sample_timestamp(self, parsed_message, receive_time):
        server_timestamp = _finite_float(parsed_message.get("server_timestamp"))
        if server_timestamp is None:
            return receive_time

        offset_estimate = receive_time - server_timestamp
        if self._server_time_offset is None or abs(offset_estimate - self._server_time_offset) > 1.0:
            self._server_time_offset = offset_estimate
        else:
            alpha = self.timestamp_offset_smoothing
            self._server_time_offset = (
                (1.0 - alpha) * self._server_time_offset
                + alpha * offset_estimate
            )

        return server_timestamp + self._server_time_offset

    def _record_pose_sample(self, traffic_id, v_msg, sample_timestamp):
        location = v_msg["location"]
        sample = {
            "timestamp": sample_timestamp,
            "x": float(location["x"]),
            "y": float(location["y"]),
            "z": float(location["z"]),
            "yaw": float(v_msg.get("yaw", 0.0)),
            "blueprint": v_msg["blueprint"],
            "color": v_msg.get("color", self.DEFAULT_VEHICLE_COLOR),
            "role_name": v_msg.get("role_name", ""),
        }

        with self._state_lock:
            samples = self.pose_samples.setdefault(traffic_id, deque())
            samples.append(sample)
            cutoff = sample["timestamp"] - self.SAMPLE_HISTORY_SECONDS
            while samples and samples[0]["timestamp"] < cutoff:
                samples.popleft()

    def _destroy_vehicle(self, vid):
        vehicle = self.traffic_vehicles.pop(vid, None)
        if vehicle:
            vehicle.destroy()
        self.actor_transforms.pop(vid, None)
        self.last_message_timestamps.pop(vid, None)
        self.vehicle_roles.pop(vid, None)
        self.failed_spawn_timestamps.pop(vid, None)
        with self._state_lock:
            self.pose_samples.pop(vid, None)
        if self.followed_traffic_id == vid:
            print(f"[!] Lost followed traffic vehicle ID={vid}")
            self.followed_traffic_id = None
            self._reset_camera_state()
        self._snapped_camera_traffic_ids.discard(vid)

    def _should_retry_spawn(self, traffic_id):
        last_attempt = self.failed_spawn_timestamps.get(traffic_id)
        return last_attempt is None or time.time() - last_attempt >= self.SPAWN_RETRY_INTERVAL

    def _should_follow(self, traffic_id):
        if not self.follow_spectator:
            return False
        if self.follow_traffic_id:
            matches_target = str(traffic_id) == str(self.follow_traffic_id)
        else:
            matches_target = (
                self.follow_role_name
                and self.vehicle_roles.get(traffic_id) == self.follow_role_name
            )
        if not matches_target:
            return False
        if self.followed_traffic_id is None:
            self.followed_traffic_id = traffic_id
            role_name = self.vehicle_roles.get(traffic_id, "")
            print(f"[!] Following mirrored traffic vehicle ID={traffic_id} role_name={role_name}")
            return True
        return self.followed_traffic_id == traffic_id

    def _update_spectator(self, transform):
        yaw = math.radians(transform.rotation.yaw)
        location = transform.location + carla.Location(
            x=-8.0 * math.cos(yaw),
            y=-8.0 * math.sin(yaw),
            z=4.0,
        )
        rotation = carla.Rotation(pitch=-15.0, yaw=transform.rotation.yaw, roll=0.0)
        self.world.get_spectator().set_transform(carla.Transform(location, rotation))

    def _smooth_update_spectator(self, target_transform, dt):
        self._update_camera_anchor(target_transform, dt)
        desired = self._get_chase_camera_transform_from_anchor(
            self._camera_anchor_location,
            self._camera_anchor_yaw,
        )
        self._camera_desired_transform = desired

        if self._camera_transform is None:
            self._set_spectator_transform(desired)
            return

        if self.camera_smoothing >= 1.0:
            self._set_spectator_transform(desired)
            return

        alpha = _frame_scaled_alpha(self.camera_smoothing, dt)
        self._set_spectator_transform(_blend_transforms(self._camera_transform, desired, alpha))

    def _update_camera_anchor(self, target_transform, dt):
        target_location = target_transform.location
        target_yaw = target_transform.rotation.yaw
        if self._camera_anchor_location is None or self._camera_anchor_yaw is None:
            self._camera_anchor_location = carla.Location(
                x=target_location.x,
                y=target_location.y,
                z=target_location.z,
            )
            self._camera_anchor_yaw = target_yaw
            return

        position_delta = _location_distance(self._camera_anchor_location, target_location)
        if position_delta >= self.camera_position_deadband:
            position_alpha = _frame_scaled_alpha(self.camera_target_smoothing, dt)
            self._camera_anchor_location = _lerp_location(
                self._camera_anchor_location,
                target_location,
                position_alpha,
            )

        yaw_delta = abs(_normalize_angle_degrees(target_yaw - self._camera_anchor_yaw))
        if yaw_delta >= self.camera_yaw_deadband:
            yaw_alpha = _frame_scaled_alpha(self.camera_yaw_smoothing, dt)
            self._camera_anchor_yaw = _lerp_angle_degrees(
                self._camera_anchor_yaw,
                target_yaw,
                yaw_alpha,
            )

    def _set_spectator_transform(self, transform):
        self.world.get_spectator().set_transform(transform)
        self._camera_transform = transform

    def _reset_camera_state(self):
        self._camera_transform = None
        self._camera_desired_transform = None
        self._camera_anchor_location = None
        self._camera_anchor_yaw = None

    def _get_chase_camera_transform(self, target_transform):
        return self._get_chase_camera_transform_from_anchor(
            target_transform.location,
            target_transform.rotation.yaw,
        )

    def _get_chase_camera_transform_from_anchor(self, anchor_location, anchor_yaw):
        yaw = math.radians(anchor_yaw)
        location = anchor_location + carla.Location(
            x=-self.camera_distance * math.cos(yaw),
            y=-self.camera_distance * math.sin(yaw),
            z=self.camera_height,
        )
        rotation = carla.Rotation(pitch=self.camera_pitch, yaw=anchor_yaw, roll=0.0)
        return carla.Transform(location, rotation)

    def _update_follow_camera(self, traffic_id, target_transform, dt):
        if self.camera_mode == self.CAMERA_MODE_OFF:
            return

        if self.camera_mode == self.CAMERA_MODE_SNAP_ONCE:
            if traffic_id in self._snapped_camera_traffic_ids:
                return
            self._set_spectator_transform(self._get_chase_camera_transform(target_transform))
            self._camera_desired_transform = self._camera_transform
            self._snapped_camera_traffic_ids.add(traffic_id)
            print(f"[!] Snapped visual CARLA spectator to traffic vehicle ID={traffic_id}")
            return

        self._smooth_update_spectator(target_transform, dt)

    def _refresh_manual_actor_id(self, force=False):
        if self.follow_traffic_id_is_explicit:
            return
        now = time.time()
        if not force and now - self._last_manual_actor_lookup < 1.0:
            return
        self._last_manual_actor_lookup = now

        try:
            raw = self.redis_client.get(self.manual_actor_redis_key)
        except Exception as exc:
            if force:
                print(f"[x] Could not read manual actor metadata from Redis: {exc}")
            return
        if not raw:
            return

        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            print(f"[x] Invalid manual actor metadata in Redis key {self.manual_actor_redis_key}: {exc}")
            return

        actor_id = payload.get("actor_id")
        if not actor_id:
            return
        actor_id = str(actor_id)
        if actor_id != self.follow_traffic_id:
            self.follow_traffic_id = actor_id
            self.followed_traffic_id = None
            self._snapped_camera_traffic_ids.discard(actor_id)
            self._reset_camera_state()
            print(f"[!] Loaded manual actor ID={actor_id} from Redis key {self.manual_actor_redis_key}")

    def _record_observed_role(self, traffic_id, role_name):
        role_name = role_name or "<empty>"
        if role_name not in self._observed_roles:
            self._observed_roles[role_name] = set()
        self._observed_roles[role_name].add(str(traffic_id))

    def _log_follow_waiting(self):
        if not self.follow_spectator or self.followed_traffic_id:
            return
        now = time.time()
        if now - self._last_follow_wait_log < 5.0:
            return
        self._last_follow_wait_log = now

        if self.follow_traffic_id:
            print(f"[!] Waiting for mirrored manual traffic actor ID={self.follow_traffic_id}")
        elif self.follow_role_name:
            print(f"[!] Waiting for mirrored manual traffic role_name={self.follow_role_name}")

        if self._observed_roles and now - self._last_observed_roles_log >= 10.0:
            self._last_observed_roles_log = now
            summary = {
                role: sorted(ids)[:5]
                for role, ids in sorted(self._observed_roles.items())
            }
            print(f"[!] Observed traffic roles from Redis: {summary}")

    def _render_once(self, dt):
        target_time = time.time() - self.interpolation_delay
        with self._state_lock:
            render_samples = {
                traffic_id: _select_render_sample(
                    list(samples),
                    target_time,
                    self.max_extrapolation,
                )
                for traffic_id, samples in self.pose_samples.items()
            }

        for traffic_id, sample in render_samples.items():
            if sample is None:
                continue

            transform = _sample_to_transform(sample)
            visual_transform = self.actor_transforms.get(traffic_id, transform)
            if traffic_id not in self.traffic_vehicles:
                if self._should_retry_spawn(traffic_id):
                    self._add_vehicle(
                        traffic_id,
                        transform,
                        sample["blueprint"],
                        sample.get("color", self.DEFAULT_VEHICLE_COLOR),
                    )
                    visual_transform = self.actor_transforms.get(traffic_id, transform)
            else:
                vehicle = self.traffic_vehicles[traffic_id]
                alpha = _frame_scaled_alpha(self.actor_smoothing, dt)
                visual_transform = _blend_transforms(visual_transform, transform, alpha)
                vehicle.set_transform(visual_transform)
                self.actor_transforms[traffic_id] = visual_transform

            if self._should_follow(traffic_id):
                self._update_follow_camera(traffic_id, visual_transform, dt)

    # --------------------------
    # Render and cleanup threads
    # --------------------------

    def _start_render_thread(self):
        self._should_stop_render = False
        self._render_thread = threading.Thread(target=self._render_loop, daemon=True)
        self._render_thread.start()

    def _stop_render_thread(self):
        self._should_stop_render = True
        if self._render_thread:
            self._render_thread.join(timeout=1)

    def _render_loop(self):
        interval = 1.0 / self.update_hz
        last_render_time = time.time()
        while not self._should_stop_render:
            self._wait_for_render_tick(interval)
            start = time.time()
            if start - last_render_time < interval * 0.9:
                continue
            dt = min(0.1, max(0.001, start - last_render_time))
            last_render_time = start
            try:
                self._render_once(dt)
            except Exception as exc:
                print(f"[x] Render loop error: {exc}")

    def _wait_for_render_tick(self, interval):
        start = time.time()
        try:
            self.world.wait_for_tick(seconds=max(0.1, interval * 2.0))
        except RuntimeError:
            elapsed = time.time() - start
            remaining = interval - elapsed
            if remaining > 0.0:
                time.sleep(max(0.001, remaining))

    def _start_cleaner_thread(self):
        self._should_stop_cleaner = False
        self._cleaner_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleaner_thread.start()

    def _stop_cleaner_thread(self):
        self._should_stop_cleaner = True
        if self._cleaner_thread:
            self._cleaner_thread.join(timeout=1)

    def _cleanup_loop(self):
        while not self._should_stop_cleaner:
            now = time.time()
            stale_ids = [vid for vid, ts in self.last_message_timestamps.items()
                         if now - ts > self.SILENCE_DURATION]
            for vid in stale_ids:
                self._destroy_vehicle(vid)
            time.sleep(self.VEHICLE_CLEANUP_INTERVAL)

    # --------------------------
    # Lifecycle
    # --------------------------

    def start(self):
        if not self._is_running:
            self.start_telemetry_services()
            self._start_cleaner_thread()
            self._start_render_thread()
            self._is_running = True

    def shutdown(self):
        if self._is_running:
            self._stop_render_thread()
            for vid in list(self.traffic_vehicles.keys()):
                self._destroy_vehicle(vid)
            self.stop_telemetry_services()
            self._stop_cleaner_thread()
            self._is_running = False

# --------------------------
# Run standalone
# --------------------------

if __name__ == "__main__":
    renderer = MultiTrafficRenderer()
    renderer.start()
    atexit.register(renderer.shutdown)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        renderer.shutdown()
