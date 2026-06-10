import atexit
import time

if __name__ == "__main__":
    from telemetry import Telemetry
else:
    from modules.telemetry import Telemetry


class MultiAgentTemplate(Telemetry):
    """Template class that inherits Telemetry class and provides bare minimum functionality.
    Modify this class to add your own functionality. """

    def __init__(self):
        super().__init__()

        self._is_running = False
        self.vehicles = {}

    def on_receive_telemetry(self, parsed_message):
        """ Callback function to handle telemetry messages, you'll receive a dictionary with the telemetry data
        from other agents. """
        pass

    def handle_fetch_telemetry_data(self):
        """ Callback function to fetch the telemetry data to be sent to other agents.
        Return a dictionary with the telemetry data. """
        pass

    def on_receive_conn_destroy(self, agent_id):
        """ Callback function to clean up when an agent disconnects, you'll get the id of the agent that disconnected. """
        pass

    def start(self):
        """ Start the telemetry services. """
        if not self._is_running:
            self.start_telemetry_services()

            self.vehicles = {}
            self._is_running = True

    def shutdown(self):
        """ Shutdown the telemetry services. """
        if self._is_running:
            self.stop_telemetry_services()

            self._is_running = False

if __name__ == "__main__":
    multi_agent_template = MultiAgentTemplate()
    multi_agent_template.start()
    atexit.register(multi_agent_template.shutdown)

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("[x] Keyboard interrupt")

    finally:
        multi_agent_template.shutdown()
