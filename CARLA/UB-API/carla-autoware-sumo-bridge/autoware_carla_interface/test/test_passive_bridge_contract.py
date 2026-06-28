from pathlib import Path
import xml.etree.ElementTree as ET


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[3]
SOURCE = (PACKAGE_ROOT / "src" / "autoware_carla_interface" / "carla_autoware.py").read_text()
CARLA_ROS_SOURCE = (
    PACKAGE_ROOT / "src" / "autoware_carla_interface" / "carla_ros.py"
).read_text()
LAUNCH_SOURCE = (
    PACKAGE_ROOT / "launch" / "autoware_carla_interface.launch.xml"
).read_text()


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
    compose_path = REPO_ROOT / "Autoware" / "ub-lincoln-docker" / "docker" / "docker-compose.yml"
    if not compose_path.exists():
        return

    compose = compose_path.read_text()
    assert "UB_AUTOWARE_CARLA_INTERFACE_PATH" in compose
    assert (
        "/autoware/src/universe/autoware_universe/simulator/autoware_carla_interface"
        in compose
    )


def test_bridge_provides_control_mode_request_service():
    assert "from autoware_vehicle_msgs.srv import ControlModeCommand" in CARLA_ROS_SOURCE
    assert "self.srv_control_mode = self.ros2_node.create_service(" in CARLA_ROS_SOURCE
    assert '"/control/control_mode_request"' in CARLA_ROS_SOURCE
    assert "self.control_mode_request_callback" in CARLA_ROS_SOURCE


def test_control_mode_report_is_not_hard_coded_autonomous():
    assert "self.current_control_mode = ControlModeReport.MANUAL" in CARLA_ROS_SOURCE
    assert "out_ctrl_mode.mode = self.current_control_mode" in CARLA_ROS_SOURCE
    assert "out_ctrl_mode.mode = ControlModeReport.AUTONOMOUS" not in CARLA_ROS_SOURCE


def test_actuation_commands_are_ignored_until_autonomous_mode():
    assert "def create_hold_control(self):" in CARLA_ROS_SOURCE
    assert "carla.VehicleControl(brake=1.0, hand_brake=True)" in CARLA_ROS_SOURCE
    assert "if self.current_control_mode != ControlModeReport.AUTONOMOUS:" in CARLA_ROS_SOURCE
    assert "out_cmd.hand_brake = False" in CARLA_ROS_SOURCE


def test_raw_vehicle_converter_receives_actuation_status():
    assert '<arg name="input_actuation_status" default="/vehicle/status/actuation_status"/>' in LAUNCH_SOURCE
    assert (
        '<remap from="~/input/actuation_status" to="$(var input_actuation_status)"/>'
        in LAUNCH_SOURCE
    )
