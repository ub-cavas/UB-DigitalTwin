import os
import threading
import time

import carla

if __name__ == "__main__":
    from telemetry import Telemetry
    from utils import get_spawn_point_location
else:
    from modules.telemetry import Telemetry
    from modules.utils import get_spawn_point_location

class MultiAgentRenderer(Telemetry):
    """ This class will inherit Telemetry class and override its methods
    to define the actions to be taken when receiving telemetry messages and connection destroy messages. """

    CARLA_HOST = "localhost"
    CARLA_PORT = 2000
    MAX_SPAWN_ATTEMPTS = 5 # Spawning other vehicles can fail due to collisions with ground, so we retry a few times
    DEFAULT_VEHICLE_COLOR = "255,255,255"  # Default color for vehicles if not specified
    DEFAULT_BLUEPRINT = "vehicle.lincoln.mkz_2020"  # Default vehicle blueprint if not specified
    SILENCE_DURATION = 5
    VEHICLE_CLEANUP_INTERVAL = 1

    def __init__(self):
        super().__init__()

        carla_host = os.environ.get("UB_CARLA_HOST", self.CARLA_HOST)
        carla_port = int(os.environ.get("UB_CARLA_PORT", self.CARLA_PORT))

        self.carla_client = carla.Client(carla_host, carla_port)
        self.carla_client.set_timeout(10.0)
        self.world = self.carla_client.get_world()
        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        self.vehicles = { }
        self.last_message_timestamps = { }
        self._lock = threading.Lock()

        self._is_running = False
        self._cleaner_thread = None
        self._should_stop_cleaner = False

    def on_receive_telemetry(self, parsed_message):
        if "vehicles" not in parsed_message:
            return

        for vehicle_message in parsed_message["vehicles"]:
            vehicle_id = vehicle_message["id"]

            location = get_spawn_point_location(self.world, vehicle_message["location"])
            if location is None:
                print(f"[x] Raycast failed for vehicle ID={vehicle_id}, skipping")
                continue

            spawn_point = carla.Transform(
                location,
                carla.Rotation(yaw=vehicle_message["yaw"])
            )

            try:
                with self._lock:
                    self.last_message_timestamps[vehicle_id] = time.time()

                    if vehicle_id not in self.vehicles:
                        self._add_vehicle(
                            vehicle_id,
                            spawn_point,
                            vehicle_message.get("blueprint", self.DEFAULT_BLUEPRINT),
                            vehicle_message.get("color", self.DEFAULT_VEHICLE_COLOR)
                        )

                    elif self._has_other_vehicle_changed(vehicle_message):
                        self._reload_other_vehicle(vehicle_message, spawn_point)

                    elif vehicle_id in self.vehicles:
                        self.vehicles[vehicle_id].set_transform(spawn_point)
            except Exception as e:
                print(f"[x] Failed to process traffic vehicle ID={vehicle_id}: {e}")

    def handle_fetch_telemetry_data(self):
        hero_just_loaded = False

        while not self.vehicles.get("hero"):
            if self._should_stop_publisher:
                return {}
            hero_just_loaded = True
            self._load_hero_vehicle()
            time.sleep(0.5)

        if not hero_just_loaded:
            self._reload_hero_if_changed()

        hero_vehicle = self.vehicles.get("hero")
        if not hero_vehicle:
            return {}

        transform = hero_vehicle.get_transform()

        return  {
            "location":{
                "x": transform.location.x,
                "y": transform.location.y,
                "z": transform.location.z
            },
            "yaw": transform.rotation.yaw,
            "blueprint": hero_vehicle.type_id,
            "color": hero_vehicle.attributes.get("color", self.DEFAULT_VEHICLE_COLOR)
        }

    def on_receive_conn_destroy(self, conn_id):
        with self._lock:
            if conn_id in self.vehicles:
                self._destroy_vehicle(conn_id)

                print(f"[!] Destroyed vehicle with ID = {conn_id}")

    def destroy_vehicles(self):
        print("[!] Destroying vehicles")

        with self._lock:
            for vehicle_id, vehicle in list(self.vehicles.items()):
                if vehicle_id != "hero":
                    vehicle.destroy()
                    del self.vehicles[vehicle_id]

    def start(self):
        if not self._is_running:
            self.vehicles = { }
            self.last_message_timestamps = { }
            self.start_telemetry_services()
            self.start_cleaner_thread()
            self._is_running = True

    def shutdown(self):
        if self._is_running:
            self.stop_telemetry_services()
            self.stop_cleaner_thread()
            self.destroy_vehicles()

            self._is_running = False
    
    def start_cleaner_thread(self):
        self._should_stop_cleaner = False
        self._cleaner_thread = threading.Thread(target=self._remove_non_responsive_vehicles, daemon=True)
        self._cleaner_thread.start()

        print("[!] Unresponsive vehicle cleaner thread started")

    def stop_cleaner_thread(self):
        if self._cleaner_thread and self._cleaner_thread.is_alive():
            self._should_stop_cleaner = True
            self._cleaner_thread.join(timeout=1)

            print("[!] Unresponsive vehicle cleaner thread stopped")
    
    def _remove_non_responsive_vehicles(self):
        while not self._should_stop_cleaner:
            destroyed_vehicle_ids = []
            current_time = time.time()

            with self._lock:
                for vehicle_id, last_timestamp in list(self.last_message_timestamps.items()):
                    if current_time - last_timestamp >= self.SILENCE_DURATION:
                        self._destroy_vehicle(vehicle_id)
                        destroyed_vehicle_ids.append(vehicle_id)

                        print(f"[!] Destroyed unresponsive vehicle with ID = {vehicle_id}")

                for vehicle_id in destroyed_vehicle_ids:
                    del self.last_message_timestamps[vehicle_id]

            time.sleep(self.VEHICLE_CLEANUP_INTERVAL)

    def _add_vehicle(self, vehicle_id, spawn_point, blueprint, color, verbose = True):
        blueprint_library = self.world.get_blueprint_library()
        vehicle_bp = blueprint_library.find(blueprint)
        vehicle_bp.set_attribute('color', color)

        for attempt in range(self.MAX_SPAWN_ATTEMPTS):
            try:
                spawned_vehicle = self.world.spawn_actor(vehicle_bp, spawn_point)
                spawned_vehicle.set_simulate_physics(False)
                self.vehicles[vehicle_id] = spawned_vehicle

                if verbose:
                    print(f"[!] Spawned vehicle with ID = {vehicle_id} at {spawn_point.location} with blueprint = {blueprint} color = {color}")

                break
            except RuntimeError as e:
                print(f"[x] Spawn failed for ID = {vehicle_id} with exception {e}. Updating Z coordinate and retrying - attempt {attempt + 1}/{self.MAX_SPAWN_ATTEMPTS}")
                spawn_point.location.z += 1.0
        else:
            print(f"[x] Failed to spawn vehicle with ID = {vehicle_id} after {self.MAX_SPAWN_ATTEMPTS} attempts")

    def _load_hero_vehicle(self):
        vehicles = self.world.get_actors().filter("vehicle.*")

        for vehicle in vehicles:
            if vehicle.attributes.get("role_name") == "hero":
                self.vehicles["hero"] = vehicle
                break

    def _reload_hero_if_changed(self):
        current_hero = self.vehicles.get("hero")
        if not current_hero:
            return

        vehicles = self.world.get_actors().filter("vehicle.*")

        for vehicle in vehicles:
            if vehicle.attributes.get("role_name") == "hero":
                if current_hero.id != vehicle.id:
                    self.vehicles["hero"] = vehicle
                    print("[!] Reloaded hero vehicle!")
                break

    def _has_other_vehicle_changed(self, parsed_message):
        vehicle = self.vehicles[parsed_message["id"]]

        return vehicle.type_id != parsed_message["blueprint"] or \
            vehicle.attributes["color"] != parsed_message["color"]

    def _reload_other_vehicle(self, parsed_message, spawn_point):
        self._destroy_vehicle(parsed_message["id"])
        self._add_vehicle(parsed_message["id"], spawn_point, parsed_message["blueprint"], parsed_message["color"], verbose=False)

        print(f"[!] Reloaded vehicle with ID = {parsed_message['id']} with blueprint = {parsed_message['blueprint']} and color = {parsed_message['color']}")

    def _destroy_vehicle(self, vehicle_id):
        if vehicle_id in self.vehicles:
            self.vehicles[vehicle_id].destroy()
            del self.vehicles[vehicle_id]

if __name__ == "__main__":
    multi_agent_renderer = MultiAgentRenderer()
    multi_agent_renderer.start()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("[x] Keyboard interrupt")

    finally:
        multi_agent_renderer.shutdown()
