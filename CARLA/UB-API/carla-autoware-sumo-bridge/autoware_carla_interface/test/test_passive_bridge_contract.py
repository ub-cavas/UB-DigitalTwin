from pathlib import Path
import xml.etree.ElementTree as ET


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[3]
SOURCE = (PACKAGE_ROOT / "src" / "autoware_carla_interface" / "carla_autoware.py").read_text()


def test_passive_mode_waits_for_external_ticks():
    assert "if self.external_tick:" in SOURCE
    assert "snapshot = world.wait_for_tick(self.external_tick_timeout)" in SOURCE
    assert "Timed out waiting for an external CARLA tick" in SOURCE


def test_map_loading_and_settings_are_active_mode_only():
    assert "if not self.external_tick:\n            client.load_world(self.carla_map)" in SOURCE
    assert "else:\n            settings.fixed_delta_seconds = self.fixed_delta_seconds" in SOURCE
    assert "self.world.apply_settings(settings)" in SOURCE


def test_passive_spawn_path_does_not_tick_after_spawn():
    assert "tick=not self.external_tick" in SOURCE
    assert "tick_after_spawn=not self.external_tick" in SOURCE


def test_package_is_ament_python_only():
    package_xml = ET.parse(PACKAGE_ROOT / "package.xml").getroot()
    build_type = package_xml.find("./export/build_type")
    assert build_type is not None
    assert build_type.text == "ament_python"
    assert not (PACKAGE_ROOT / "CMakeLists.txt").exists()


def test_autoware_compose_mounts_bridge_package():
    compose = (
        REPO_ROOT / "Autoware" / "ub-lincoln-docker" / "docker" / "docker-compose.yml"
    ).read_text()
    assert "UB_AUTOWARE_CARLA_INTERFACE_PATH" in compose
    assert (
        "/autoware/src/universe/autoware_universe/simulator/autoware_carla_interface"
        in compose
    )
