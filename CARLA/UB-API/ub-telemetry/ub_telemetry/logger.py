import logging
import queue
import threading

class Logger:
    """A custom logger class to handle telemetry logging."""

    DEFAULT_LOG_LEVEL = logging.INFO
    DEFAULT_LOG_FILE = "telemetry.log"
    DEFAULT_LOG_FORMAT = "%(asctime)s - ID: %(id)s - %(levelname)s - %(message)s"

    QUEUE_TIMEOUT = 0.01

    START_TELEMETRY_LOG_LEVEL = 21
    STOP_TELEMETRY_LOG_LEVEL = 22
    SENT_LOG_LEVEL = 23
    RECEIVED_LOG_LEVEL = 24

    def __init__(self, id, filename=DEFAULT_LOG_FILE, level=DEFAULT_LOG_LEVEL, format=DEFAULT_LOG_FORMAT):
        self.id = id

        self._logger = logging.getLogger(f"{__name__}.{id}")
        self._logger.setLevel(level)

        formatter = logging.Formatter(format)
        file_handler = logging.FileHandler(filename)
        file_handler.setFormatter(formatter)

        file_handler.addFilter(self._create_id_filter())
        self._logger.addHandler(file_handler)
        self._logger.propagate = False

        self._log_queue = queue.Queue()
        self._is_logging = threading.Event()
        self._worker = None

        logging.addLevelName(self.START_TELEMETRY_LOG_LEVEL, 'START')
        logging.addLevelName(self.STOP_TELEMETRY_LOG_LEVEL, 'STOP')
        logging.addLevelName(self.SENT_LOG_LEVEL, 'SENT')
        logging.addLevelName(self.RECEIVED_LOG_LEVEL, 'RECEIVED')

    def start_logging(self):
        if self._worker and self._worker.is_alive():
            print("[x] Logger is already running")

            return

        self._is_logging.set()
        self._worker = threading.Thread(target=self._process_queue, daemon=True)
        self._worker.start()

        print("[!] Logging started")

    def stop_logging(self):
        self._is_logging.clear()

        print("[!] Waiting for logger to finish logging")

        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=5)
            if self._worker.is_alive():
                print("[x] Logger thread did not stop within timeout")

        print("[!] Completed logging")

    def log_telemetry_start(self, message):
        self._log_queue.put((self._logger.log, (self.START_TELEMETRY_LOG_LEVEL, message)))

    def log_telemetry_stop(self, message):
        self._log_queue.put((self._logger.log, (self.STOP_TELEMETRY_LOG_LEVEL, message)))

    def log_sent(self, message):
        self._log_queue.put((self._logger.log, (self.SENT_LOG_LEVEL, message)))

    def log_received(self, message):
        self._log_queue.put((self._logger.log, (self.RECEIVED_LOG_LEVEL, message)))

    def _create_id_filter(self):
        logger_id = self.id

        class IdFilter(logging.Filter):
            def filter(self, record):
                record.id = logger_id
                return True

        return IdFilter()

    def _process_queue(self):
        while self._is_logging.is_set() or not self._log_queue.empty():
            try:
                func, args = self._log_queue.get(timeout=self.QUEUE_TIMEOUT)
                func(*args)
            except queue.Empty:
                continue
