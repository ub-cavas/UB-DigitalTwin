"""Payload logging stays opt-in without retaining messages in the log queue."""
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).parents[1]))
with patch.dict(sys.modules, {'redis': ModuleType('redis')}):
    from ub_telemetry.logger import Logger


class LoggerTests(unittest.TestCase):
    def make_logger(self, payload_setting=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'telemetry.log'
        with patch.dict(os.environ):
            os.environ.pop(Logger.ENV_LOG_PAYLOADS, None)
            if payload_setting is not None:
                os.environ[Logger.ENV_LOG_PAYLOADS] = payload_setting
            logger = Logger(str(uuid.uuid4()), filename=str(path))
        self.addCleanup(self.close_logger, logger)
        return logger, path

    @staticmethod
    def close_logger(logger):
        logger.stop_logging()
        for handler in logger._logger.handlers[:]:
            handler.close()
            logger._logger.removeHandler(handler)

    def test_default_discards_payloads_but_keeps_lifecycle_events(self):
        logger, path = self.make_logger()
        # A stopped worker must not let high-rate payloads accumulate in memory.
        for _ in range(1000):
            logger.log_sent('sent-payload-marker')
            logger.log_received({'payload': 'received-payload-marker'})
        self.assertTrue(logger._log_queue.empty())
        logger.start_logging()
        logger.log_telemetry_start('services started')
        logger.log_telemetry_stop('services stopped')
        logger.stop_logging()
        contents = path.read_text()
        self.assertIn('services started', contents)
        self.assertIn('services stopped', contents)
        self.assertNotIn('payload-marker', contents)

    def test_explicit_opt_in_records_sent_and_received_payloads(self):
        for value in ('1', 'true', 'yes', 'on', ' TRUE '):
            with self.subTest(value=value):
                logger, path = self.make_logger(value)
                logger.start_logging()
                logger.log_sent('sent-payload-marker')
                logger.log_received({'payload': 'received-payload-marker'})
                logger.stop_logging()
                contents = path.read_text()
                self.assertIn('sent-payload-marker', contents)
                self.assertIn('received-payload-marker', contents)

    def test_false_or_unknown_settings_do_not_enable_payload_logging(self):
        for value in ('0', 'false', 'no', 'off', '', 'invalid'):
            with self.subTest(value=value):
                logger, path = self.make_logger(value)
                logger.log_sent('sent-payload-marker')
                logger.log_received({'payload': 'received-payload-marker'})
                self.assertTrue(logger._log_queue.empty())
                self.assertEqual(path.read_text(), '')

    def test_client_directory_is_used_for_default_filename(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'UB_CLIENT_LOG_DIR': str(Path(directory) / 'client logs'),
        }):
            logger = Logger(str(uuid.uuid4()))
            self.addCleanup(self.close_logger, logger)
            logger.start_logging()
            logger.log_telemetry_start('centralized log')
            logger.stop_logging()
            self.assertIn('centralized log', (Path(directory) / 'client logs/telemetry.log').read_text())

    def test_explicit_filename_takes_precedence_over_client_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'UB_CLIENT_LOG_DIR': str(Path(directory) / 'unused'),
        }):
            explicit = Path(directory) / 'explicit.log'
            logger = Logger(str(uuid.uuid4()), filename=str(explicit))
            self.addCleanup(self.close_logger, logger)
            self.assertTrue(explicit.is_file())
            self.assertFalse((Path(directory) / 'unused').exists())


if __name__ == '__main__':
    unittest.main()
