import atexit
import json
import math
import os
import threading
import time
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

class MultiTrafficRenderer(Telemetry):
    TRAFFIC_MESSAGE_TYPE = 2
    SILENCE_DURATION = 5.0
    VEHICLE_CLEANUP_INTERVAL = 1.0
    SPAWN_RETRY_INTERVAL = 2.0
    DEFAULT_VEHICLE_COLOR = "255,255,255"
    DEFAULT_MANUAL_ACTOR_REDIS_KEY = "carla:manual_control:actor"

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
        self.failed_spawn_timestamps = {}
        self.last_message_timestamps = {}
        self.vehicle_roles = {}
        self.follow_role_name = os.environ.get("UB_RENDER_FOLLOW_ROLE_NAME", "")
        self.follow_spectator = _env_bool("UB_RENDER_FOLLOW_SPECTATOR", bool(self.follow_role_name))
        self.skip_local_ids = _env_bool("UB_RENDER_SKIP_LOCAL_IDS", False)
        self.followed_traffic_id = None
        self.follow_traffic_id = os.environ.get("UB_RENDER_FOLLOW_TRAFFIC_ID", "")
        self.manual_actor_redis_key = os.environ.get(
            "UB_RENDER_MANUAL_ACTOR_REDIS_KEY",
            self.DEFAULT_MANUAL_ACTOR_REDIS_KEY,
        )
        self._last_manual_actor_lookup = 0.0
        self._last_follow_wait_log = 0.0
        self._last_observed_roles_log = 0.0
        self._observed_roles = {}

        self._should_stop_cleaner = False
        self._cleaner_thread = None
        self._is_running = False

        self._refresh_manual_actor_id(force=True)
        print(f"[!] Traffic renderer listening to Redis {self.HOST}:{self.PORT} channel={self.CHANNEL}")
        if self.follow_spectator and self.follow_role_name:
            print(f"[!] Visual CARLA spectator will follow role_name={self.follow_role_name}")
        if self.follow_spectator and self.follow_traffic_id:
            print(f"[!] Visual CARLA spectator will follow traffic actor ID={self.follow_traffic_id}")

    def on_receive_telemetry(self, parsed_message):
        if parsed_message.get("type") != self.TRAFFIC_MESSAGE_TYPE:
            return

        self._refresh_manual_actor_id()
        vehicles = parsed_message.get("vehicles", [])
        for v_msg in vehicles:
            traffic_id = v_msg["id"]
            self.last_message_timestamps[traffic_id] = time.time()
            self.vehicle_roles[traffic_id] = v_msg.get("role_name", "")
            self._record_observed_role(traffic_id, self.vehicle_roles[traffic_id])

            if self.skip_local_ids and traffic_id in self._local_vehicle_ids():
                continue

            if "location" not in v_msg or "blueprint" not in v_msg:
                continue

            transform = carla.Transform(
                get_spawn_point_location(self.world, v_msg["location"]),
                carla.Rotation(yaw=v_msg.get("yaw", 0))
            )

            if traffic_id not in self.traffic_vehicles:
                if self._should_retry_spawn(traffic_id):
                    self._add_vehicle(
                        traffic_id,
                        transform,
                        v_msg["blueprint"],
                        v_msg.get("color", self.DEFAULT_VEHICLE_COLOR)
                    )
            else:
                self.traffic_vehicles[traffic_id].set_transform(transform)

            if self._should_follow(traffic_id):
                vehicle = self.traffic_vehicles.get(traffic_id)
                if vehicle is not None:
                    self._update_spectator(vehicle.get_transform())
                else:
                    self._update_spectator(transform)

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
        self.failed_spawn_timestamps.pop(vid, None)
        print(f"[!] Spawned mirrored traffic vehicle ID={vid}")

    def _destroy_vehicle(self, vid):
        vehicle = self.traffic_vehicles.pop(vid, None)
        if vehicle:
            vehicle.destroy()
        self.last_message_timestamps.pop(vid, None)
        self.vehicle_roles.pop(vid, None)
        self.failed_spawn_timestamps.pop(vid, None)
        if self.followed_traffic_id == vid:
            print(f"[!] Lost followed traffic vehicle ID={vid}")
            self.followed_traffic_id = None

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

    def _refresh_manual_actor_id(self, force=False):
        if self.follow_traffic_id and not force:
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

    # --------------------------
    # Cleanup thread
    # --------------------------

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
            self._is_running = True

    def shutdown(self):
        if self._is_running:
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
