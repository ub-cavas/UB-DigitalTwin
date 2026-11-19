"""Experiment integration: transport accounting without a Redis/CARLA server."""
import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))
with patch.dict(sys.modules, {"redis": ModuleType("redis")}):
    from ub_telemetry.telemetry import Telemetry


class ExperimentTransportChecks(unittest.TestCase):
    def test_received_and_sent_unicode_payload_bytes(self):
        from ub_experiment import Recorder
        with tempfile.TemporaryDirectory() as directory:
            with Recorder(directory, plots=False) as recorder:
                transport = Telemetry.__new__(Telemetry)
                transport.experiment = recorder
                transport.id = "client"
                transport.CHANNEL = "test"
                transport.logger = Mock()
                transport._should_stop_subscriber = False
                packet = {"id": "server", "type": 2, "vehicles": [], "name": "雪"}
                payload = json.dumps(packet, ensure_ascii=False).encode("utf-8")
                def read(**kwargs):
                    transport._should_stop_subscriber = True
                    return {"type": "message", "data": payload}
                transport.pubsub = Mock(get_message=read)
                transport.on_receive_telemetry = Mock()
                transport._telemetry_subscriber()
                transport.on_receive_telemetry.assert_called_once_with(packet)

                transport._should_stop_publisher = False
                transport.handle_fetch_telemetry_data = Mock(return_value={"name": "雪"})
                def publish(*args):
                    transport._should_stop_publisher = True
                transport.redis_client = Mock(publish=Mock(side_effect=publish))
                transport._telemetry_publisher()
                sent = transport.redis_client.publish.call_args.args[1]
            with (Path(directory) / "metrics.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            rate = next(row for row in rows if row["metric"] == "throughput")
            self.assertEqual(int(rate["rx_bytes"]), len(payload))
            self.assertEqual(int(rate["tx_bytes"]), len(sent.encode("utf-8")))
            self.assertEqual(sum(row["metric"] == "fetch_to_publish" for row in rows), 1)
            self.assertEqual(sum(row["metric"] == "receive_to_handler" for row in rows), 1)

    def test_disabled_bridge_has_no_shared_package_dependency(self):
        from ub_telemetry.experiments import experiment
        with patch.dict(os.environ, {"UB_EXPERIMENT_ENABLED": "0"}), patch.dict(sys.modules, {"ub_experiment": None}):
            with experiment() as recorder:
                self.assertIsNone(recorder)
