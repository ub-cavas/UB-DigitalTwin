"""No CARLA installation or server is required for these exporter checks."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

spec = importlib.util.spec_from_file_location(
    "export_vehicle_inventory", Path(__file__).parents[1] / "export_vehicle_inventory.py"
)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class VehicleInventoryTests(unittest.TestCase):
    def test_sorted_inventory_uses_only_read_operations(self):
        client = Mock(spec=["get_server_version", "get_world"])
        client.get_server_version.return_value = "0.9.16"
        client.get_world.return_value.get_blueprint_library.return_value.filter.return_value = [
            SimpleNamespace(id="vehicle.ford.mustang"), SimpleNamespace(id="vehicle.audi.a2")
        ]
        self.assertEqual(exporter.collect_inventory(client), {
            "server_version": "0.9.16",
            "blueprints": ["vehicle.audi.a2", "vehicle.ford.mustang"],
        })
        self.assertEqual(client.mock_calls, [
            call.get_server_version(), call.get_world(),
            call.get_world().get_blueprint_library(),
            call.get_world().get_blueprint_library().filter("vehicle.*"),
        ])


if __name__ == "__main__":
    unittest.main()
