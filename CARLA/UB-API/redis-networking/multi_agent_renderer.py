import atexit
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
    DEFAULT_VEHICLE_COLOR = "255, 255, 255"  # Default color for vehicles if not specified
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

        self._is_running = False

    def on_receive_telemetry(self, parsed_message):
        self.last_message_timestamps[parsed_message["id"]] = time.time()

        spawn_point = carla.Transform(
            get_spawn_point_location(self.world, parsed_message["location"]),
            carla.Rotation(yaw=parsed_message["yaw"])
        )

        try:
            if parsed_message["id"] not in self.vehicles:
                self._add_vehicle(parsed_message["id"], spawn_point, parsed_message["blueprint"], parsed_message["color"])

            elif self._has_other_vehicle_changed(parsed_message):
                self._reload_other_vehicle(parsed_message, spawn_point)

            else:
                self.vehicles[parsed_message["id"]].set_transform(spawn_point)

        except Exception as e:
            print(f"[x] Failed to process telemetry message for ID = {parsed_message['id']} with error: {e}. Will retry on next message")

    def handle_fetch_telemetry_data(self):
        was_hero_loaded = False

        while not self.vehicles.get("hero"):
            was_hero_loaded = True
            self._load_hero_vehicle()
            time.sleep(0.5)

        if not was_hero_loaded:
            self._reload_hero_if_changed()

        hero_vehicle = self.vehicles["hero"]
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

    def on_receive_conn_destroy(self, id):
        if id in self.vehicles:
            self._destroy_vehicle(id)

            print(f"[!] Destroyed vehicle with ID = {id}")

    def destroy_vehicles(self):
        print("[!] Destroying vehicles")

        for id, vehicle in self.vehicles.items():
            if id != "hero":
                vehicle.destroy()

    def start(self):
        if not self._is_running:
            self.start_telemetry_services()
            self.start_cleaner_thread()

            self.vehicles = { }
            self._is_running = True

    def shutdown(self):
        if self._is_running:
            self.destroy_vehicles()
            self.stop_telemetry_services()
            self.stop_cleaner_thread()

            self._is_running = False
    
    def start_cleaner_thread(self):
        self._should_stop_cleaner = False
        self._cleaner_thread = threading.Thread(target=self._remove_non_responsive_vehicles)
        self._cleaner_thread.start()

        print("[!] Unresponsive vehicle cleaner thread started")

    def stop_cleaner_thread(self):
        if self._cleaner_thread.is_alive():
            self._should_stop_cleaner = True
            self._cleaner_thread.join(timeout=1)

            print("[!] Unresponsive vehicle cleaner thread stopped")
    
    def _remove_non_responsive_vehicles(self):
        while not self._should_stop_cleaner:
            destroyed_vehicle_ids = []
            current_time = time.time()
            
            for vehicle_id, last_timestamp in self.last_message_timestamps.items():
                if current_time - last_timestamp >= self.SILENCE_DURATION:
                    self._destroy_vehicle(vehicle_id)
                    destroyed_vehicle_ids.append(vehicle_id)

                    print(f"[!] Destroyed unresponsive vehicle with ID = {vehicle_id}")
            
            for vehicle_id in destroyed_vehicle_ids:
                del self.last_message_timestamps[vehicle_id]
            
            time.sleep(self.VEHICLE_CLEANUP_INTERVAL)

    def _add_vehicle(self, id, spawn_point, blueprint, color, verbose = True):
        blueprint_library = self.world.get_blueprint_library()
        vehicle_bp = blueprint_library.find(blueprint)
        vehicle_bp.set_attribute('color', color)

        for attempt in range(self.MAX_SPAWN_ATTEMPTS):
            try:
                spawned_vehicle = self.world.spawn_actor(vehicle_bp, spawn_point)
                spawned_vehicle.set_simulate_physics(False)
                self.vehicles[id] = spawned_vehicle

                if verbose:
                    print(f"[!] Spawned vehicle with ID = {id} at {spawn_point.location} with blueprint = {blueprint} color = {color}")

                break
            except RuntimeError as e:
                print(f"[x] Spawn failed for ID = {id} with exception {e}. Updating Z coordinate and retrying - attempt {attempt + 1}/{self.MAX_SPAWN_ATTEMPTS}")
                spawn_point.location.z += 1.0

    def _load_hero_vehicle(self):
        vehicles = self.world.get_actors().filter("vehicle.*")

        for vehicle in vehicles:
            if vehicle.attributes.get("role_name") == "hero":
                self.vehicles["hero"] = vehicle
                break

    def _reload_hero_if_changed(self):
        vehicles = self.world.get_actors().filter("vehicle.*")

        for vehicle in vehicles:
            if vehicle.attributes.get("role_name") == "hero":
                if self.vehicles["hero"].id != vehicle.id:
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
    atexit.register(multi_agent_renderer.shutdown)

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("[x] Keyboard interrupt")

    finally:
        multi_agent_renderer.shutdown()
