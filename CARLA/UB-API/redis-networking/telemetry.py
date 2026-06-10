import json
import os
import threading
import time
import uuid

from collections import deque

import redis


module_name = os.path.splitext(os.path.basename(__file__))[0]

if __name__ == module_name:
    from logger import Logger
else:
    from modules.logger import Logger


class Telemetry:
    """ A class to handle telemetry publishing and subscribing using Redis Pub/Sub. """

    CONFIG_FILE = "telemetry.conf"

    DEFAULT_HOST = "localhost"
    DEFAULT_PORT = 6390
    DEFAULT_PASSWORD = "password"
    DEFAULT_CHANNEL = "DEFAULT_CHANNEL"

    LATENCY_BUFFER_SIZE = 100
    PUBLISH_INTERVAL = 0.01
    MESSAGE_TYPES = { "telemetry": 0, "destroy": 1 }

    def __init__(self):
        self.id = str(uuid.uuid1())
        self.logger = Logger(self.id)

        self._should_stop_publisher = False
        self._should_stop_subscriber = False
        self._publisher_thread = None
        self._subscriber_thread = None
        self._server_latency_buffer = deque(maxlen=self.LATENCY_BUFFER_SIZE)

        self._load_redis_config()

        self.redis_client = redis.Redis(host=self.HOST, port=self.PORT, password=self.PASSWORD)
        self.pubsub = self.redis_client.pubsub()
        self.pubsub.subscribe(self.CHANNEL)
        self.server_latency = float('-inf')
        self.avg_server_latency = float('-inf')
        self.highest_server_latency = float('-inf')
        self.lowest_server_latency = float('inf')

    def start_telemetry_services(self):
        message =  f"Starting telemetry services with ID = {self.id} and PUBLISH_INTERVAL = {self.PUBLISH_INTERVAL} seconds"
        print(f"[!] {message}")

        self.logger.start_logging()
        self.logger.log_telemetry_start(message)

        self._start_telemetry_publisher()
        self._start_telemetry_subscriber()

    def stop_telemetry_services(self):
        message = "Stopping telemetry services"
        print(f"[!] {message}")

        self._stop_telemetry_publisher()
        self._stop_telemetry_subscriber()

        self.logger.log_telemetry_stop(message)
        self.logger.stop_logging()

    def _load_redis_config(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(current_dir, self.CONFIG_FILE)

        try:
            with open(config_path, "r") as file:
                config = json.load(file)

                self.HOST = config.get("host", self.DEFAULT_HOST)
                self.PORT = config.get("port", self.DEFAULT_PORT)
                self.PASSWORD = config.get("password", self.DEFAULT_PASSWORD)
                self.CHANNEL = config.get("channel", self.DEFAULT_CHANNEL)

        except Exception as e:
            raise RuntimeError(f"[!] Error loading telemetry config file: {e}") from e

    def _start_telemetry_publisher(self):
        if self._publisher_thread and self._publisher_thread.is_alive():
            print("[x] Publisher thread is already running")
            return

        self._should_stop_publisher = False
        self._publisher_thread = threading.Thread(target=self._telemetry_publisher, daemon=True)
        self._publisher_thread.start()

        print("[!] Telemetry publisher thread started")

    def _start_telemetry_subscriber(self):
        if self._subscriber_thread and self._subscriber_thread.is_alive():
            print("[x] Subscriber thread is already running")
            return

        self._should_stop_subscriber = False
        self._subscriber_thread = threading.Thread(target=self._telemetry_subscriber, daemon=True)
        self._subscriber_thread.start()

        print("[!] Telemetry subscriber thread started")

    def _stop_telemetry_publisher(self):
        if self._publisher_thread and self._publisher_thread.is_alive():
            self._should_stop_publisher = True
            self._publisher_thread.join(timeout=1)
            self._send_conn_destroy_message()

        print("[!] Telemetry publisher thread stopped")

    def _stop_telemetry_subscriber(self):
        if self._subscriber_thread and self._subscriber_thread.is_alive():
            self._should_stop_subscriber = True
            self._subscriber_thread.join(timeout=1)

        if self.pubsub:
            self.pubsub.unsubscribe(self.CHANNEL)

        print("[!] Telemetry subscriber thread stopped")

    def _telemetry_publisher(self):
        while not self._should_stop_publisher:
            try:
                message = self._create_message(self.handle_fetch_telemetry_data())
                self.redis_client.publish(self.CHANNEL, message)

                self.logger.log_sent(message)
            except Exception as e:
                print(f"[x] Publisher error: {e}")

            time.sleep(self.PUBLISH_INTERVAL)

    def _telemetry_subscriber(self):
        while not self._should_stop_subscriber:
            try:
                message = self.pubsub.get_message(ignore_subscribe_messages=True)

                if not message:
                    time.sleep(0.001)
                    continue

                if message["type"] == "message":
                    parsed_message = json.loads(message["data"])
                    if parsed_message["id"] == self.id:
                        # Estimate one-way latency by dividing round-trip time (RTT) by 2.
                        # This calculation assumes symmetric network paths (equal latency in both directions).
                        self.server_latency = ((time.time() - parsed_message["timestamp"]) / 2) * 1000
                        self._server_latency_buffer.append(self.server_latency)
                        buff_len = len(self._server_latency_buffer)
                        self.avg_server_latency = (
                            sum(self._server_latency_buffer) / buff_len
                            if buff_len
                            else self.server_latency
                        )
                        self.highest_server_latency = max(
                            self.highest_server_latency,
                            self.server_latency
                        )
                        self.lowest_server_latency = min(
                            self.lowest_server_latency,
                            self.server_latency
                        )
                        continue

                    self.logger.log_received(parsed_message)

                    if parsed_message["type"] == self.MESSAGE_TYPES["destroy"]:
                        self.on_receive_conn_destroy(parsed_message["id"])
                        continue

                    self.on_receive_telemetry(parsed_message)
            except Exception as e:
                print(f"[x] Subscriber error: {e}")

    def _send_conn_destroy_message(self):
        destroy_message = self._create_message({}, self.MESSAGE_TYPES["destroy"])
        self.redis_client.publish(self.CHANNEL, destroy_message)

        print(f"[!] Sent connection destroy message for ID = {self.id}")

    def _create_message(self, message, message_type=MESSAGE_TYPES["telemetry"]):
        return json.dumps({ **message, "id": self.id, "type": message_type, "timestamp": time.time() })

    def on_receive_telemetry(self, parsed_message):
        """ Callback function to handle telemetry messages, override this method in subclasses """
        print(f"[!] Received telemetry message: {parsed_message}")

    def on_receive_conn_destroy(self, id):
        """ Callback function to handle destroy messages, override this method in subclasses """
        print(f"[!] Received destroy message for ID: {id}")

    def handle_fetch_telemetry_data(self):
        """ Callback function to fetch the telemetry message to be sent, override this method in subclasses """
        return {}
