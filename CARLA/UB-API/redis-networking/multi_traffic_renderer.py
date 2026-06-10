import atexit
import threading
import time
import carla

from telemetry import Telemetry

# Utility to convert location dict to CARLA location
def get_spawn_point_location(world, loc_dict):
    return carla.Location(x=loc_dict["x"], y=loc_dict["y"], z=loc_dict["z"])

class MultiTrafficRenderer(Telemetry):
    TRAFFIC_MESSAGE_TYPE = 2
    SILENCE_DURATION = 5.0
    VEHICLE_CLEANUP_INTERVAL = 1.0
    DEFAULT_VEHICLE_COLOR = "255,255,255"

    def __init__(self, carla_host="localhost", carla_port=2000):
        super().__init__()
        self.carla_client = carla.Client(carla_host, carla_port)
        self.carla_client.set_timeout(10.0)
        self.world = self.carla_client.get_world()
        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        self.traffic_vehicles = {}
        self.last_message_timestamps = {}

        self._should_stop_cleaner = False
        self._cleaner_thread = None
        self._is_running = False

    def on_receive_telemetry(self, parsed_message):
        if parsed_message.get("type") != self.TRAFFIC_MESSAGE_TYPE:
            return

        vehicles = parsed_message.get("vehicles", [])
        for v_msg in vehicles:
            traffic_id = v_msg["id"]
            self.last_message_timestamps[traffic_id] = time.time()

            if traffic_id in self._local_vehicle_ids():
                continue

            if "location" not in v_msg or "blueprint" not in v_msg:
                continue

            transform = carla.Transform(
                get_spawn_point_location(self.world, v_msg["location"]),
                carla.Rotation(yaw=v_msg.get("yaw", 0))
            )

            if traffic_id not in self.traffic_vehicles:
                self._add_vehicle(
                    traffic_id,
                    transform,
                    v_msg["blueprint"],
                    v_msg.get("color", self.DEFAULT_VEHICLE_COLOR)
                )
            else:
                self.traffic_vehicles[traffic_id].set_transform(transform)

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
        vehicle = self.world.spawn_actor(bp, transform)
        vehicle.set_simulate_physics(False)
        self.traffic_vehicles[vid] = vehicle
        print(f"[!] Spawned mirrored traffic vehicle ID={vid}")

    def _destroy_vehicle(self, vid):
        vehicle = self.traffic_vehicles.pop(vid, None)
        if vehicle:
            vehicle.destroy()
        self.last_message_timestamps.pop(vid, None)

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
