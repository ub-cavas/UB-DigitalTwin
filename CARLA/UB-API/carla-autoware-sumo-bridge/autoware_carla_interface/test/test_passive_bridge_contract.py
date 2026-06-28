from pathlib import Path
import xml.etree.ElementTree as ET
import json
import sys

import numpy


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[3]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))
from autoware_carla_interface.lidar_filter import filter_ego_vehicle_lidar_points

SOURCE = (PACKAGE_ROOT / "src" / "autoware_carla_interface" / "carla_autoware.py").read_text()
CARLA_ROS_SOURCE = (
    PACKAGE_ROOT / "src" / "autoware_carla_interface" / "carla_ros.py"
).read_text()
CARLA_WRAPPER_SOURCE = (
    PACKAGE_ROOT / "src" / "autoware_carla_interface" / "modules" / "carla_wrapper.py"
).read_text()
LAUNCH_SOURCE = (
    PACKAGE_ROOT / "launch" / "autoware_carla_interface.launch.xml"
).read_text()
PASSIVE_START_PATH = REPO_ROOT / "CARLA" / "start_autoware_carla_sumo.sh"
PASSIVE_START_SOURCE = PASSIVE_START_PATH.read_text() if PASSIVE_START_PATH.exists() else ""


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


def test_carla_throttle_is_gain_scaled_and_clamped():
    assert '"carla_throttle_gain": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert '"carla_max_throttle": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert '"carla_brake_deadband": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert '"carla_throttle_tau": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert '"carla_brake_tau": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert '"carla_soft_speed_limit": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert '"carla_speed_taper_start": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert '"carla_longitudinal_control_mode": rclpy.Parameter.Type.STRING' in CARLA_ROS_SOURCE
    assert '"carla_native_throttle_kp": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert '"carla_native_accel_gain": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert '"carla_native_brake_gain": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert '"carla_native_brake_accel_deadband": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert '"carla_native_brake_speed_error_deadband": rclpy.Parameter.Type.DOUBLE' in CARLA_ROS_SOURCE
    assert "from autoware_control_msgs.msg import Control" in CARLA_ROS_SOURCE
    assert 'Control, "/control/command/control_cmd", self.native_control_callback, 1' in (
        CARLA_ROS_SOURCE
    )
    assert 'if self.carla_longitudinal_control_mode != "actuation":' in CARLA_ROS_SOURCE
    assert 'if self.carla_longitudinal_control_mode != "native":' in CARLA_ROS_SOURCE
    assert "def native_longitudinal_targets" in CARLA_ROS_SOURCE
    assert "def native_control_callback" in CARLA_ROS_SOURCE
    assert "in_cmd.longitudinal.velocity" in CARLA_ROS_SOURCE
    assert "in_cmd.longitudinal.acceleration" in CARLA_ROS_SOURCE
    assert "in_cmd.lateral.steering_tire_angle" in CARLA_ROS_SOURCE
    assert "in_cmd.actuation.accel_cmd * self.carla_throttle_gain" in CARLA_ROS_SOURCE
    assert "self.carla_max_throttle" in CARLA_ROS_SOURCE
    assert "self.carla_max_brake" in CARLA_ROS_SOURCE
    assert "self.carla_brake_deadband" in CARLA_ROS_SOURCE
    assert "if target_brake <= self.carla_brake_deadband:" in CARLA_ROS_SOURCE
    assert "self.prev_brake_output = 0.0" in CARLA_ROS_SOURCE
    assert "def filter_longitudinal_control" in CARLA_ROS_SOURCE
    assert "def speed_limited_throttle" in CARLA_ROS_SOURCE
    assert "def set_current_control_from_targets" in CARLA_ROS_SOURCE
    assert "target_throttle = self.speed_limited_throttle(" in CARLA_ROS_SOURCE
    assert "target_throttle = 0.0" in CARLA_ROS_SOURCE
    assert "self._first_order_filter(" in CARLA_ROS_SOURCE
    assert '<arg name="carla_throttle_gain" default="1.0"' in LAUNCH_SOURCE
    assert '<arg name="carla_max_throttle" default="1.0"' in LAUNCH_SOURCE
    assert '<arg name="carla_max_brake" default="1.0"' in LAUNCH_SOURCE
    assert '<arg name="carla_brake_deadband" default="0.0"' in LAUNCH_SOURCE
    assert '<arg name="carla_throttle_tau" default="0.0"' in LAUNCH_SOURCE
    assert '<arg name="carla_brake_tau" default="0.0"' in LAUNCH_SOURCE
    assert '<arg name="carla_soft_speed_limit" default="0.0"' in LAUNCH_SOURCE
    assert '<arg name="carla_speed_taper_start" default="0.0"' in LAUNCH_SOURCE
    assert '<arg name="carla_longitudinal_control_mode" default="native"' in LAUNCH_SOURCE
    assert '<arg name="carla_native_throttle_kp" default="0.18"' in LAUNCH_SOURCE
    assert '<arg name="carla_native_accel_gain" default="0.35"' in LAUNCH_SOURCE
    assert '<arg name="carla_native_brake_gain" default="0.15"' in LAUNCH_SOURCE
    assert '<arg name="carla_native_brake_accel_deadband" default="1.2"' in LAUNCH_SOURCE
    assert (
        '<arg name="carla_native_brake_speed_error_deadband" default="2.0"'
        in LAUNCH_SOURCE
    )


def test_raw_vehicle_converter_receives_actuation_status():
    assert '<arg name="input_actuation_status" default="/vehicle/status/actuation_status"/>' in LAUNCH_SOURCE
    assert (
        '<remap from="~/input/actuation_status" to="$(var input_actuation_status)"/>'
        in LAUNCH_SOURCE
    )


def test_sumo_launcher_feeds_ub_lincoln_imu_pipeline():
    if not PASSIVE_START_SOURCE:
        return
    assert 'UB_AUTOWARE_CARLA_IMU_RELAY="${UB_AUTOWARE_CARLA_IMU_RELAY:-1}"' in (
        PASSIVE_START_SOURCE
    )
    assert "/sensing/imu/tamagawa/imu_raw" in PASSIVE_START_SOURCE
    assert "/sensing/gnss/novatel/oem7/imu/data_raw" in PASSIVE_START_SOURCE
    assert "__node:=ub_carla_imu_relay" in PASSIVE_START_SOURCE
    assert "IMU_RELAY_PID" in PASSIVE_START_SOURCE
    assert "UB_AUTOWARE_CARLA_IMU_RELAY=0" in PASSIVE_START_SOURCE


def test_passive_launcher_disables_steer_convergence_start_hold():
    if not PASSIVE_START_SOURCE:
        return

    assert "UB_AUTOWARE_CARLA_DISABLE_STEER_CONVERGENCE_HOLD" in PASSIVE_START_SOURCE
    assert "enable_keep_stopped_until_steer_convergence: true" in PASSIVE_START_SOURCE
    assert "enable_keep_stopped_until_steer_convergence: false" in PASSIVE_START_SOURCE
    assert 'old = "enable_keep_stopped_until_steer_convergence: true"' not in PASSIVE_START_SOURCE
    assert 'new = "enable_keep_stopped_until_steer_convergence: false"' not in PASSIVE_START_SOURCE


def test_passive_launcher_provides_operation_mode_shim_without_control_mode_ownership():
    if not PASSIVE_START_SOURCE:
        return

    assert "UB_AUTOWARE_OPERATION_MODE_SHIM=\"${UB_AUTOWARE_OPERATION_MODE_SHIM:-1}\"" in (
        PASSIVE_START_SOURCE
    )
    assert "ub_carla_operation_mode_shim" in PASSIVE_START_SOURCE
    assert "OperationModeAvailability" in PASSIVE_START_SOURCE
    assert "'/system/operation_mode/availability'" in PASSIVE_START_SOURCE
    assert "availability.autonomous = True" in PASSIVE_START_SOURCE
    assert "'/control/command/hazard_lights_cmd'" in PASSIVE_START_SOURCE
    assert "'/control/command/turn_indicators_cmd'" in PASSIVE_START_SOURCE
    assert "HazardLightsCommand.DISABLE" in PASSIVE_START_SOURCE
    assert "TurnIndicatorsCommand.DISABLE" in PASSIVE_START_SOURCE
    assert "UB_AUTOWARE_OPERATION_MODE_SHIM=0" in PASSIVE_START_SOURCE
    assert "Driving workflow:" in PASSIVE_START_SOURCE
    assert "click AUTO" in PASSIVE_START_SOURCE

    operation_shim_source = PASSIVE_START_SOURCE.split(
        "if [[ $(shell_quote \"${UB_AUTOWARE_OPERATION_MODE_SHIM}\") == \\\"1\\\" ]]; then",
        1,
    )[1].split("ros2 launch autoware_launch e2e_simulator.launch.xml", 1)[0]
    assert "/vehicle/status/control_mode" not in operation_shim_source
    assert "/control/control_mode_request" not in operation_shim_source
    assert "create_service" not in operation_shim_source
    assert "ControlModeCommand" not in operation_shim_source


def test_passive_launcher_uses_ub_lincoln_defaults_with_configurable_speed_tuning():
    if not PASSIVE_START_SOURCE:
        return

    assert "AUTOWARE_VEHICLE_MODEL:-ub_lincoln_vehicle" in PASSIVE_START_SOURCE
    assert "AUTOWARE_SENSOR_MODEL:-ub_lincoln_sensor_kit" in PASSIVE_START_SOURCE
    assert "UB_AUTOWARE_CARLA_VEHICLE_TYPE:-vehicle.lincoln.mkz_2020" in PASSIVE_START_SOURCE
    assert 'UB_AUTOWARE_CARLA_PLANNING_PRESET="${UB_AUTOWARE_CARLA_PLANNING_PRESET:-1}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_EGO_ONLY_PERCEPTION="${UB_AUTOWARE_EGO_ONLY_PERCEPTION:-1}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'AUTOWARE_PLANNING_MODULE_PRESET="ub_carla"' in PASSIVE_START_SOURCE
    assert "launch_crosswalk_module" in PASSIVE_START_SOURCE
    assert "launch_traffic_light_module" in PASSIVE_START_SOURCE
    assert "launch_virtual_traffic_light_module" in PASSIVE_START_SOURCE
    assert "use_empty_dynamic_object_publisher" in PASSIVE_START_SOURCE
    assert "use_traffic_light_recognition" in PASSIVE_START_SOURCE
    assert "objects_ub_lincoln.json" in PASSIVE_START_SOURCE
    assert "raw_vehicle_cmd_converter.ub_lincoln.param.yaml" in PASSIVE_START_SOURCE
    assert "align_base_link_to_rear_axle:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "debug_lidar_marker:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "UB_AUTOWARE_CARLA_FILTER_EGO_LIDAR_POINTS" in PASSIVE_START_SOURCE
    assert "filter_ego_vehicle_lidar_points:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "UB_AUTOWARE_CARLA_EGO_LIDAR_FILTER_X_MIN:--1.30" in PASSIVE_START_SOURCE
    assert "UB_AUTOWARE_CARLA_EGO_LIDAR_FILTER_X_MAX:-4.35" in PASSIVE_START_SOURCE
    assert "ros2 pkg prefix ub_lincoln_vehicle_launch" in PASSIVE_START_SOURCE
    assert "ros2 pkg prefix ub_lincoln_sensor_kit_launch" in PASSIVE_START_SOURCE
    assert 'UB_AUTOWARE_CARLA_TUNE_SPEED="${UB_AUTOWARE_CARLA_TUNE_SPEED:-1}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_MAX_VEL="${UB_AUTOWARE_CARLA_MAX_VEL:-11.12}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_MAX_ACCEL="${UB_AUTOWARE_CARLA_MAX_ACCEL:-1.5}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_ENGAGE_VELOCITY="${UB_AUTOWARE_CARLA_ENGAGE_VELOCITY:-1.0}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_THROTTLE_GAIN="${UB_AUTOWARE_CARLA_THROTTLE_GAIN:-2.6}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_MAX_THROTTLE="${UB_AUTOWARE_CARLA_MAX_THROTTLE:-0.55}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_MAX_BRAKE="${UB_AUTOWARE_CARLA_MAX_BRAKE:-0.45}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_BRAKE_DEADBAND="${UB_AUTOWARE_CARLA_BRAKE_DEADBAND:-0.30}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_THROTTLE_TAU="${UB_AUTOWARE_CARLA_THROTTLE_TAU:-0.45}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_BRAKE_TAU="${UB_AUTOWARE_CARLA_BRAKE_TAU:-0.25}"' in (
        PASSIVE_START_SOURCE
    )
    assert (
        'UB_AUTOWARE_CARLA_SOFT_SPEED_LIMIT="${UB_AUTOWARE_CARLA_SOFT_SPEED_LIMIT:-${UB_AUTOWARE_CARLA_MAX_VEL}}"'
        in PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_SPEED_TAPER_START="${UB_AUTOWARE_CARLA_SPEED_TAPER_START:-8.0}"' in (
        PASSIVE_START_SOURCE
    )
    assert (
        'UB_AUTOWARE_CARLA_LONGITUDINAL_CONTROL_MODE="${UB_AUTOWARE_CARLA_LONGITUDINAL_CONTROL_MODE:-native}"'
        in PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_NATIVE_THROTTLE_KP="${UB_AUTOWARE_CARLA_NATIVE_THROTTLE_KP:-0.18}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_NATIVE_ACCEL_GAIN="${UB_AUTOWARE_CARLA_NATIVE_ACCEL_GAIN:-0.35}"' in (
        PASSIVE_START_SOURCE
    )
    assert 'UB_AUTOWARE_CARLA_NATIVE_BRAKE_ACCEL_DEADBAND="${UB_AUTOWARE_CARLA_NATIVE_BRAKE_ACCEL_DEADBAND:-1.2}"' in (
        PASSIVE_START_SOURCE
    )
    assert "set_scalar(path, 'max_vel', max_vel)" in PASSIVE_START_SOURCE
    assert "set_scalar(path, 'engage_velocity', engage_velocity)" in PASSIVE_START_SOURCE
    assert "set_scalar(path, 'max_acc', max_accel)" in PASSIVE_START_SOURCE
    assert "carla_throttle_gain:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_max_throttle:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_max_brake:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_throttle_tau:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_brake_tau:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_soft_speed_limit:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_speed_taper_start:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_longitudinal_control_mode:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_native_throttle_kp:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_native_accel_gain:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_native_brake_gain:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_native_brake_accel_deadband:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "carla_native_brake_speed_error_deadband:=$(shell_quote" in PASSIVE_START_SOURCE
    assert "set_scalar(path, 'max_throttle', max_throttle)" not in PASSIVE_START_SOURCE
    assert "UB_AUTOWARE_CARLA_TUNE_SPEED=0" in PASSIVE_START_SOURCE
    assert "Keeping Autoware speed and throttle settings" in PASSIVE_START_SOURCE
    assert "'launch_stop_line_module'" not in PASSIVE_START_SOURCE
    assert "without stop-line" not in PASSIVE_START_SOURCE
    assert "engage_velocity: 0.25" not in PASSIVE_START_SOURCE
    assert "Restored Autoware velocity smoother config from stale CARLA speed patch" not in (
        PASSIVE_START_SOURCE
    )


def test_launch_defaults_to_ub_lincoln_bridge_config():
    assert '<arg name="vehicle_type" default="vehicle.lincoln.mkz_2020"/>' in LAUNCH_SOURCE
    assert '<arg name="align_base_link_to_rear_axle" default="true"' in LAUNCH_SOURCE
    assert '<arg name="debug_lidar_marker" default="false"' in LAUNCH_SOURCE
    assert '<arg name="filter_ego_vehicle_lidar_points" default="true"' in LAUNCH_SOURCE
    assert '<arg name="ego_lidar_filter_x_min" default="-1.30"/>' in LAUNCH_SOURCE
    assert '<arg name="ego_lidar_filter_x_max" default="4.35"/>' in LAUNCH_SOURCE
    assert 'raw_vehicle_cmd_converter.ub_lincoln.param.yaml' in LAUNCH_SOURCE
    assert "velodyne_top_changed" not in LAUNCH_SOURCE
    assert "tamagawa/imu_link_changed" not in LAUNCH_SOURCE


def test_ub_lincoln_object_config_uses_base_link_sensor_calibration():
    objects = json.loads((PACKAGE_ROOT / "config" / "objects_ub_lincoln.json").read_text())
    sensors = {sensor["id"]: sensor for sensor in objects["sensors"]}

    assert sensors["top"]["spawn_point_frame"] == "base_link"
    assert sensors["top"]["coordinate_system"] == "ros"
    assert sensors["top"]["frame_id"] == "velodyne_top_base_link"
    assert sensors["top"]["spawn_point"]["x"] == 0.9
    assert sensors["top"]["spawn_point"]["z"] == 2.0
    assert sensors["imu"]["frame_id"] == "gnss_link"
    assert sensors["rgb_front"]["frame_id"] == "traffic_light_left_camera/camera_optical_link"


def test_bridge_aligns_base_link_to_rear_axle_and_converts_sensor_offsets():
    assert '"align_base_link_to_rear_axle": rclpy.Parameter.Type.BOOL' in CARLA_ROS_SOURCE
    assert "def compute_rear_axle_offset" in CARLA_ROS_SOURCE
    assert "def _actor_transform_from_base_link" in CARLA_ROS_SOURCE
    assert "def _base_link_transform" in CARLA_ROS_SOURCE
    assert "self.id_to_frame_id_map" in CARLA_ROS_SOURCE
    assert "filter_ego_vehicle_lidar_points(" in CARLA_ROS_SOURCE
    assert "self.ego_lidar_filter_bounds" in CARLA_ROS_SOURCE
    assert "configure_ego_actor" in SOURCE
    assert "base_link_offset=self.interface.base_link_offset" in SOURCE
    assert "debug_lidar_marker=self.debug_lidar_marker" in SOURCE
    assert "def sensor_spec_to_carla_transform" in CARLA_WRAPPER_SOURCE
    assert 'spawn_point_frame == "base_link"' in CARLA_WRAPPER_SOURCE
    assert 'coordinate_system == "ros"' in CARLA_WRAPPER_SOURCE
    assert "def _draw_lidar_debug_point" in CARLA_WRAPPER_SOURCE
    assert "world.try_spawn_actor" not in CARLA_WRAPPER_SOURCE
    assert "_debug_lidar_sensors" in CARLA_WRAPPER_SOURCE
    assert "carla.Color(r=0, g=0, b=255)" in CARLA_WRAPPER_SOURCE
    assert "size=0.5" in CARLA_WRAPPER_SOURCE
    assert "life_time=0.15" in CARLA_WRAPPER_SOURCE


def test_ego_vehicle_lidar_filter_removes_points_inside_body_box():
    sensor_spec = {
        "spawn_point_frame": "base_link",
        "rotation_units": "radians",
        "spawn_point": {
            "x": 0.9,
            "y": 0.0,
            "z": 2.0,
            "roll": 0.0,
            "pitch": 0.0,
            "yaw": 0.0,
        },
    }
    bounds = {
        "x_min": -1.30,
        "x_max": 4.35,
        "y_min": -1.35,
        "y_max": 1.35,
        "z_min": -0.50,
        "z_max": 1.65,
    }
    points = numpy.array(
        [
            [0.0, 0.0, -0.5, 10.0, 0.0, 1.0],
            [4.0, 0.0, 0.0, 20.0, 0.0, 2.0],
            [0.0, 2.0, -0.5, 30.0, 0.0, 3.0],
        ],
        dtype=numpy.float32,
    )

    filtered, removed_count = filter_ego_vehicle_lidar_points(
        points,
        sensor_spec,
        bounds,
        enabled=True,
    )

    assert removed_count == 1
    assert filtered.shape[0] == 2
    assert filtered[:, 3].tolist() == [20.0, 30.0]
    assert filtered[:, 5].tolist() == [2.0, 3.0]


def test_ego_vehicle_lidar_filter_can_be_disabled():
    sensor_spec = {
        "spawn_point_frame": "base_link",
        "spawn_point": {"x": 0.0, "y": 0.0, "z": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0},
    }
    bounds = {
        "x_min": -1.0,
        "x_max": 1.0,
        "y_min": -1.0,
        "y_max": 1.0,
        "z_min": -1.0,
        "z_max": 1.0,
    }
    points = numpy.array([[0.0, 0.0, 0.0, 10.0, 0.0, 1.0]], dtype=numpy.float32)

    filtered, removed_count = filter_ego_vehicle_lidar_points(
        points,
        sensor_spec,
        bounds,
        enabled=False,
    )

    assert removed_count == 0
    assert filtered.shape[0] == 1
