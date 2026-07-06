#!/usr/bin/env bash
# The final `ros2 launch` invocation for each Autoware scenario. Scenario
# scripts call start_autoware_container (container.sh) first, then one of
# these, and track AUTOWARE_LAUNCH_STARTED for their own cleanup trap.
#
# These two functions are intentionally verbatim ports of the original
# per-scenario launch_autoware() bodies (including their embedded in-container
# Python runtime patches) rather than a further-decomposed abstraction: the
# patch bodies are long, delicately escaped (nested heredocs, chr(34)/chr(36)
# tricks to dodge quote conflicts) and cannot be exercised in this
# environment, so verbatim relocation carries far less risk than inventing a
# shared micro-function per patch would.

# Plain (self-tick) CARLA + Autoware e2e_simulator launch.
launch_autoware_plain() {
  local launch_cmd
  local exec_args=(exec)
  local optional_launch_args=""

  cd "${AUTOWARE_DOCKER_DIR}"

  if [[ ! -t 0 ]]; then
    exec_args+=(-T)
  fi

  if [[ -n "${AUTOWARE_RVIZ}" ]]; then
    optional_launch_args+=" \\
  rviz:=$(shell_quote "${AUTOWARE_RVIZ}")"
  fi
  if [[ -n "${AUTOWARE_PLANNING_MODULE_PRESET}" ]]; then
    optional_launch_args+=" \\
  planning_module_preset:=$(shell_quote "${AUTOWARE_PLANNING_MODULE_PRESET}")"
  fi

launch_cmd="
set -eo pipefail
export RMW_IMPLEMENTATION=$(shell_quote "${UB_AUTOWARE_RMW_IMPLEMENTATION}")
export CYCLONEDDS_URI=$(shell_quote "${UB_AUTOWARE_CYCLONEDDS_URI}")
if [[ \"\${RMW_IMPLEMENTATION}\" != \"rmw_cyclonedds_cpp\" ]]; then
  echo \"Error: expected CycloneDDS RMW, got RMW_IMPLEMENTATION=\${RMW_IMPLEMENTATION}\" >&2
  exit 1
fi
if [[ \"\${CYCLONEDDS_URI}\" == file://* && ! -f \"\${CYCLONEDDS_URI#file://}\" ]]; then
  echo \"Error: CYCLONEDDS_URI points to a missing file: \${CYCLONEDDS_URI}\" >&2
  exit 1
fi
if [[ -f /opt/ros/humble/setup.bash ]]; then
  source /opt/ros/humble/setup.bash
fi
if [[ -f /autoware/install/setup.bash ]]; then
  source /autoware/install/setup.bash
fi
UB_BACKGROUND_PIDS=\"\"
if [[ $(shell_quote "${UB_AUTOWARE_RESTORE_RUNTIME_PATCHES}") == 1 ]]; then
  python3 - <<'PY'
from pathlib import Path

restore_paths = [
    Path('/autoware/install/awsim_sensor_kit_launch/share/awsim_sensor_kit_launch/launch/lidar.launch.xml'),
    Path('/autoware/build/autoware_carla_interface/src/autoware_carla_interface/carla_ros.py'),
    Path('/autoware/build/autoware_carla_interface/src/autoware_carla_interface/carla_autoware.py'),
    Path('/autoware/install/autoware_launch/share/autoware_launch/launch/autoware.launch.xml'),
    Path('/autoware/install/autoware_launch/share/autoware_launch/launch/e2e_simulator.launch.xml'),
]

for path in restore_paths:
    backup = path.with_suffix(path.suffix + '.ub-original')
    if backup.exists():
        path.write_text(backup.read_text())
        print(f'Restored Autoware runtime file from UB backup: {path}')
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_INSTALL_PY_DEPS}") == 1 ]]; then
  python3 - <<'PY' || python3 -m pip install --upgrade carla==0.9.16 transforms3d==0.4.2
import carla
import transforms3d

def version_tuple(version):
    parts = []
    for part in version.split('.'):
        digits = ''.join(ch for ch in part if ch.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts)

if version_tuple(transforms3d.__version__) < (0, 4, 2):
    raise SystemExit(f'transforms3d {transforms3d.__version__} is older than 0.4.2')
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_CARLA_PLANNING_PRESET}") == 1 ]]; then
  AUTOWARE_PLANNING_MODULE_PRESET_FOR_CARLA=$(shell_quote "${AUTOWARE_PLANNING_MODULE_PRESET:-ub_carla}") python3 - <<'PY'
import os
from pathlib import Path

preset_name = os.environ['AUTOWARE_PLANNING_MODULE_PRESET_FOR_CARLA']
preset_dir = Path('/autoware/install/autoware_launch/share/autoware_launch/config/planning/preset')
source_path = preset_dir / 'default_preset.yaml'
target_path = preset_dir / f'{preset_name}_preset.yaml'

if not source_path.exists():
    print(f'Warning: CARLA planning preset skipped; missing {source_path}')
else:
    text = source_path.read_text()
    disabled_modules = {
        'launch_crosswalk_module',
        'launch_walkway_module',
        'launch_traffic_light_module',
        'launch_virtual_traffic_light_module',
    }
    lines = text.splitlines()
    for index, line in enumerate(lines[:-1]):
        stripped = line.strip()
        if not stripped.startswith('name: '):
            continue
        module_name = stripped.split(':', 1)[1].strip()
        if module_name not in disabled_modules:
            continue
        default_line_index = index + 1
        if 'default:' in lines[default_line_index]:
            indent = lines[default_line_index].split('default:', 1)[0]
            lines[default_line_index] = f'{indent}default: ' + repr('false')
    target_path.write_text('\n'.join(lines) + '\n')
    print(
        'Prepared CARLA planning preset without traffic-light/crosswalk '
        f'behavior modules: {target_path}'
    )
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY}") == 1 ]]; then
  AUTOWARE_SENSOR_MODEL_FOR_CARLA=$(shell_quote "${AUTOWARE_SENSOR_MODEL}") python3 - <<'PY'
import os
from pathlib import Path

sensor_model = os.environ['AUTOWARE_SENSOR_MODEL_FOR_CARLA']
launch_path = Path(
    f'/autoware/install/{sensor_model}_launch/share/'
    f'{sensor_model}_launch/launch/lidar.launch.xml'
)

if not launch_path.exists():
    print(f'Warning: CARLA top-LiDAR override skipped; missing {launch_path}')
else:
    backup_path = launch_path.with_suffix(launch_path.suffix + '.ub-original')
    if not backup_path.exists():
        backup_path.write_text(launch_path.read_text())
    text = backup_path.read_text()
    quote = chr(34)
    old = f'<arg name={quote}use_concat_filter{quote} default={quote}true{quote}/>'
    new = f'<arg name={quote}use_concat_filter{quote} default={quote}false{quote}/>'
    if old in text:
        launch_path.write_text(text.replace(old, new, 1))
        print(f'Disabled Autoware multi-LiDAR concat filter for CARLA: {launch_path}')
    elif new in text:
        print(f'Autoware multi-LiDAR concat filter already disabled for CARLA: {launch_path}')
    else:
        print(f'Warning: use_concat_filter default not found in {launch_path}')
PY
  python3 - <<'PY' &
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from sensor_msgs.msg import PointCloud2

SOURCE_TOPIC = '/sensing/lidar/top/pointcloud_before_sync'
OUTPUT_TOPIC = '/sensing/lidar/concatenated/pointcloud'

rclpy.init()
node = rclpy.create_node('ub_carla_top_lidar_relay')
source_qos = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
)
output_qos = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
)
publisher = node.create_publisher(PointCloud2, OUTPUT_TOPIC, output_qos)

def relay(message):
    publisher.publish(message)

node.create_subscription(PointCloud2, SOURCE_TOPIC, relay, source_qos)
node.get_logger().info(f'Relaying {SOURCE_TOPIC} -> {OUTPUT_TOPIC}')
try:
    rclpy.spin(node)
except (KeyboardInterrupt, ExternalShutdownException):
    pass
finally:
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
PY
  UB_BACKGROUND_PIDS=\"\${UB_BACKGROUND_PIDS} \$!\"
fi
if [[ $(shell_quote "${UB_AUTOWARE_PATCH_CARLA_BRIDGE}") == 1 ]]; then
  python3 - <<'PY'
from pathlib import Path

source_root = Path('/autoware/build/autoware_carla_interface/src/autoware_carla_interface')
carla_ros_path = source_root / 'carla_ros.py'
carla_autoware_path = source_root / 'carla_autoware.py'
quote = chr(34)

def patch_file(path, replacements):
    if not path.exists():
        print(f'Warning: CARLA bridge patch skipped; missing {path}')
        return
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())
    text = backup.read_text()
    changed = False
    for old, new in replacements:
        if new in text:
            continue
        if old not in text:
            print(f'Warning: CARLA bridge patch pattern not found in {path}: {old!r}')
            continue
        text = text.replace(old, new, 1)
        changed = True
    if changed:
        path.write_text(text)
        print(f'Applied CARLA bridge runtime patch: {path}')

patch_file(
    carla_ros_path,
    [
        (
            'from autoware_vehicle_msgs.msg import ControlModeReport\n',
            'from autoware_vehicle_msgs.msg import ControlModeReport\n'
            'from autoware_vehicle_msgs.srv import ControlModeCommand\n',
        ),
        (
            '        self.current_control = carla.VehicleControl()\n',
            '        self.sub_control_mode_override = self.ros2_node.create_subscription(\n'
            '            ControlModeReport, \'/ub/carla/control_mode\', self.control_mode_override_callback, 1\n'
            '        )\n'
            '        self.srv_control_mode = self.ros2_node.create_service(\n'
            '            ControlModeCommand, \'/control/control_mode_request\', self.control_mode_request_callback\n'
            '        )\n'
            '        self.current_control_mode = ControlModeReport.MANUAL\n'
            '        self.current_control = carla.VehicleControl(brake=1.0, hand_brake=True)\n'
            '        self.received_control_cmd = False\n',
        ),
        (
            '    def control_callback(self, in_cmd):\n'
            ,
            '    def control_mode_override_callback(self, msg):\n'
            '        self.current_control_mode = msg.mode\n\n'
            '    def control_mode_request_callback(self, request, response):\n'
            '        # Accept Autoware operation-mode control ownership requests.\n'
            '        if request.mode == ControlModeCommand.Request.AUTONOMOUS:\n'
            '            self.current_control_mode = ControlModeReport.AUTONOMOUS\n'
            '        elif request.mode == ControlModeCommand.Request.MANUAL:\n'
            '            self.current_control_mode = ControlModeReport.MANUAL\n'
            '            self.current_control = carla.VehicleControl(brake=1.0, hand_brake=True)\n'
            '        else:\n'
            '            self.current_control_mode = request.mode\n'
            '        response.success = True\n'
            '        return response\n\n'
            '    def control_callback(self, in_cmd):\n'
        ),
        (
            '        out_cmd = carla.VehicleControl()\n',
            '        if self.current_control_mode != ControlModeReport.AUTONOMOUS:\n'
            '            return\n'
            '        out_cmd = carla.VehicleControl()\n',
        ),
        (
            '        out_cmd.brake = in_cmd.actuation.brake_cmd\n'
            '        self.current_control = out_cmd\n',
            '        out_cmd.brake = in_cmd.actuation.brake_cmd\n'
            '        out_cmd.hand_brake = False\n'
            '        self.received_control_cmd = True\n'
            '        self.current_control = out_cmd\n',
        ),
        (
            f'            ControlModeReport, {quote}/vehicle/status/control_mode{quote}, 1\n',
            f'            ControlModeReport, {quote}/ub/carla/status/control_mode_raw{quote}, 1\n',
        ),
        (
            '        out_ctrl_mode.stamp = out_vel_state.header.stamp\n'
            '        out_ctrl_mode.mode = ControlModeReport.AUTONOMOUS\n',
            '        out_ctrl_mode.stamp = out_vel_state.header.stamp\n'
            '        out_ctrl_mode.mode = self.current_control_mode\n',
        ),
    ],
)

patch_file(
    carla_autoware_path,
    [
        (
            '        self.interface.physics_control = self.ego_actor.get_physics_control()\n\n'
            '        self.sensor_wrapper = SensorWrapper(self.interface)\n',
            '        self.interface.physics_control = self.ego_actor.get_physics_control()\n'
            '        self.ego_actor.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))\n'
            '        self.ego_actor.set_target_angular_velocity(carla.Vector3D(0.0, 0.0, 0.0))\n'
            '        self.ego_actor.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))\n\n'
            '        self.sensor_wrapper = SensorWrapper(self.interface)\n',
        ),
    ],
)
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_EGO_ONLY_PERCEPTION}") == 1 ]]; then
  python3 - <<'PY'
from pathlib import Path

path = Path('/autoware/install/autoware_launch/share/autoware_launch/launch/autoware.launch.xml')
if not path.exists():
    print(f'Warning: ego-only perception patch skipped; missing {path}')
else:
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())
    text = backup.read_text()
    quote = chr(34)
    dollar = chr(36)
    data_path_arg = (
        f'      <arg name={quote}data_path{quote} '
        f'value={quote}{dollar}(var data_path){quote}/>\n'
    )
    empty_objects_arg = (
        f'      <arg name={quote}use_empty_dynamic_object_publisher{quote} '
        f'value={quote}true{quote}/>\n'
    )
    traffic_light_arg = (
        f'      <arg name={quote}use_traffic_light_recognition{quote} '
        f'value={quote}false{quote}/>\n'
    )
    changed = False
    if traffic_light_arg not in text and empty_objects_arg in text:
        text = text.replace(empty_objects_arg, empty_objects_arg + traffic_light_arg, 1)
        changed = True
    if empty_objects_arg in text:
        path.write_text(text)
        if changed:
            print(f'Disabled CARLA traffic-light recognition: {path}')
        print(f'Ego-only empty object publisher already enabled: {path}')
    elif data_path_arg in text:
        path.write_text(text.replace(data_path_arg, data_path_arg + empty_objects_arg + traffic_light_arg, 1))
        print(f'Enabled ego-only perception for CARLA: {path}')
    else:
        print(f'Warning: perception include data_path arg not found in {path}')
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_CARLA_SPAWN_POINT}") != '' ]]; then
  UB_CARLA_SPAWN_POINT=$(shell_quote "${UB_AUTOWARE_CARLA_SPAWN_POINT}") \\
  UB_CARLA_PROJECT_SPAWN_TO_ROAD=$(shell_quote "${UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD}") \\
  python3 - <<'PY'
import os
from pathlib import Path

spawn_point = os.environ['UB_CARLA_SPAWN_POINT']
project_spawn_to_road = os.environ['UB_CARLA_PROJECT_SPAWN_TO_ROAD']

path = Path('/autoware/install/autoware_launch/share/autoware_launch/launch/e2e_simulator.launch.xml')
if not path.exists():
    print(f'Warning: CARLA spawn point patch skipped; missing {path}')
else:
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())
    text = backup.read_text()
    quote = chr(34)
    dollar = chr(36)
    old = (
        f'<include file={quote}{dollar}(find-pkg-share autoware_carla_interface)/'
        f'autoware_carla_interface.launch.xml{quote}/>'
    )
    new = (
        f'<include file={quote}{dollar}(find-pkg-share autoware_carla_interface)/'
        f'autoware_carla_interface.launch.xml{quote}>\n'
        f'      <arg name={quote}spawn_point{quote} value={quote}{spawn_point}{quote}/>\n'
        f'      <arg name={quote}project_spawn_point_to_road{quote} '
        f'value={quote}{project_spawn_to_road}{quote}/>\n'
        f'    </include>'
    )
    if new in text:
        print(f'CARLA ego spawn point already pinned: {path}')
    elif old in text:
        path.write_text(text.replace(old, new, 1))
        print(f'Pinned CARLA ego spawn point for map alignment: {path}')
    else:
        print(f'Warning: autoware_carla_interface include not found in {path}')
PY
fi
if [[ $(shell_quote "${UB_AUTOWARE_CONTROL_MODE_SHIM}") == 1 ]]; then
python3 - <<'PY' &
import rclpy
from rclpy.executors import ExternalShutdownException
from autoware_vehicle_msgs.msg import ControlModeReport
from autoware_vehicle_msgs.msg import HazardLightsCommand
from autoware_vehicle_msgs.msg import TurnIndicatorsCommand
from autoware_vehicle_msgs.srv import ControlModeCommand
from tier4_system_msgs.msg import OperationModeAvailability

rclpy.init()
node = rclpy.create_node('ub_carla_control_mode_shim')
mode = ControlModeReport.MANUAL
status_pub = node.create_publisher(ControlModeReport, '/vehicle/status/control_mode', 1)
override_pub = node.create_publisher(ControlModeReport, '/ub/carla/control_mode', 1)
hazard_pub = node.create_publisher(HazardLightsCommand, '/control/command/hazard_lights_cmd', 1)
turn_pub = node.create_publisher(TurnIndicatorsCommand, '/control/command/turn_indicators_cmd', 1)
availability_pub = node.create_publisher(
    OperationModeAvailability, '/system/operation_mode/availability', 1
)

def publish_mode():
    msg = ControlModeReport()
    msg.stamp = node.get_clock().now().to_msg()
    msg.mode = mode
    status_pub.publish(msg)
    override_pub.publish(msg)

    hazard = HazardLightsCommand()
    hazard.stamp = msg.stamp
    hazard.command = HazardLightsCommand.DISABLE
    hazard_pub.publish(hazard)

    turn = TurnIndicatorsCommand()
    turn.stamp = msg.stamp
    turn.command = TurnIndicatorsCommand.DISABLE
    turn_pub.publish(turn)

    availability = OperationModeAvailability()
    availability.stamp = msg.stamp
    availability.stop = True
    availability.autonomous = True
    availability.local = True
    availability.remote = True
    availability.emergency_stop = True
    availability.comfortable_stop = False
    availability.pull_over = False
    availability_pub.publish(availability)

def on_request(request, response):
    global mode
    if request.mode == ControlModeCommand.Request.AUTONOMOUS:
        mode = ControlModeReport.AUTONOMOUS
    elif request.mode == ControlModeCommand.Request.MANUAL:
        mode = ControlModeReport.MANUAL
    else:
        mode = request.mode
    publish_mode()
    response.success = True
    return response

node.create_service(ControlModeCommand, '/control/control_mode_request', on_request)
node.create_timer(0.05, publish_mode)
node.get_logger().info(
    'Providing /control/control_mode_request, /vehicle/status/control_mode, '
    '/control/command/hazard_lights_cmd, /control/command/turn_indicators_cmd, '
    'and simulator operation-mode availability'
)
try:
    rclpy.spin(node)
except (KeyboardInterrupt, ExternalShutdownException):
    pass
finally:
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
PY
UB_BACKGROUND_PIDS=\"\${UB_BACKGROUND_PIDS} \$!\"
fi
trap 'for pid in \${UB_BACKGROUND_PIDS:-}; do kill \${pid} 2>/dev/null || true; done' EXIT
ros2 launch autoware_launch e2e_simulator.launch.xml \\
  map_path:=$(shell_quote "${AUTOWARE_MAP_PATH}") \\
  vehicle_model:=$(shell_quote "${AUTOWARE_VEHICLE_MODEL}") \\
  sensor_model:=$(shell_quote "${AUTOWARE_SENSOR_MODEL}") \\
  simulator_type:=carla \\
  host:=$(shell_quote "${AUTOWARE_CARLA_HOST}") \\
  carla_map:=$(shell_quote "${CARLA_MAP}")${optional_launch_args}
"

  echo "Launching Autoware. Press Ctrl+C to stop the ROS launch."
  AUTOWARE_LAUNCH_STARTED=1
  set +e
  docker compose "${exec_args[@]}" "${AUTOWARE_SERVICE}" bash -lc "${launch_cmd}"
  local launch_status=$?
  set -e

  if [[ "${UB_KEEP_AUTOWARE_ROS}" != "1" ]]; then
    cleanup_autoware_launch_processes "Stopping Autoware ROS launch processes. Set UB_KEEP_AUTOWARE_ROS=1 to leave them running." AUTOWARE_E2E_CLEANUP_PATTERNS
    AUTOWARE_LAUNCH_STARTED=0
  fi

  return "${launch_status}"
}

# SUMO/passive: external-tick custom autoware_carla_interface bridge +
# Autoware e2e_simulator, both launched together and torn down together.
launch_autoware_sumo() {
  local exec_args=(exec)
  local optional_bridge_args=""
  local optional_launch_args=""
  local launch_cmd

  cd "${AUTOWARE_DOCKER_DIR}"

  if [[ ! -t 0 ]]; then
    exec_args+=(-T)
  fi

  if [[ -n "${AUTOWARE_RVIZ}" ]]; then
    optional_launch_args+=" \\
  rviz:=$(shell_quote "${AUTOWARE_RVIZ}")"
  fi
  if [[ "${UB_AUTOWARE_CARLA_PLANNING_PRESET}" == "1" && -z "${AUTOWARE_PLANNING_MODULE_PRESET}" ]]; then
    AUTOWARE_PLANNING_MODULE_PRESET="ub_carla"
  fi
  if [[ -n "${AUTOWARE_PLANNING_MODULE_PRESET}" ]]; then
    optional_launch_args+=" \\
  planning_module_preset:=$(shell_quote "${AUTOWARE_PLANNING_MODULE_PRESET}")"
  fi
  if [[ -n "${UB_AUTOWARE_LIDAR_DETECTION_MODEL}" ]]; then
    optional_launch_args+=" \\
  lidar_detection_model:=$(shell_quote "${UB_AUTOWARE_LIDAR_DETECTION_MODEL}")"
  fi
  if [[ -n "${UB_AUTOWARE_CARLA_OBJECTS_DEFINITION_FILE}" ]]; then
    optional_bridge_args+=" \\
  objects_definition_file:=$(shell_quote "${UB_AUTOWARE_CARLA_OBJECTS_DEFINITION_FILE}")"
  fi
  if [[ -n "${UB_AUTOWARE_CARLA_RAW_VEHICLE_CMD_CONVERTER_CONFIG}" ]]; then
    optional_bridge_args+=" \\
  config_file:=$(shell_quote "${UB_AUTOWARE_CARLA_RAW_VEHICLE_CMD_CONVERTER_CONFIG}")"
  fi
  if [[ -n "${UB_AUTOWARE_CARLA_VEHICLE_COLOR}" ]]; then
    optional_bridge_args+=" \\
  vehicle_color:=$(shell_quote "${UB_AUTOWARE_CARLA_VEHICLE_COLOR}")"
  fi
  optional_bridge_args+=" \\
  align_base_link_to_rear_axle:=$(shell_quote "${UB_AUTOWARE_CARLA_ALIGN_BASE_LINK_TO_REAR_AXLE}")"
  optional_bridge_args+=" \\
  publish_simulator_tf:=$(shell_quote "${UB_AUTOWARE_CARLA_PUBLISH_SIMULATOR_TF}")"
  optional_bridge_args+=" \\
  filter_ego_vehicle_lidar_points:=$(shell_quote "${UB_AUTOWARE_CARLA_FILTER_EGO_LIDAR_POINTS}")"
  optional_bridge_args+=" \\
  ego_lidar_filter_x_min:=$(shell_quote "${UB_AUTOWARE_CARLA_EGO_LIDAR_FILTER_X_MIN}")"
  optional_bridge_args+=" \\
  ego_lidar_filter_x_max:=$(shell_quote "${UB_AUTOWARE_CARLA_EGO_LIDAR_FILTER_X_MAX}")"
  optional_bridge_args+=" \\
  ego_lidar_filter_y_min:=$(shell_quote "${UB_AUTOWARE_CARLA_EGO_LIDAR_FILTER_Y_MIN}")"
  optional_bridge_args+=" \\
  ego_lidar_filter_y_max:=$(shell_quote "${UB_AUTOWARE_CARLA_EGO_LIDAR_FILTER_Y_MAX}")"
  optional_bridge_args+=" \\
  ego_lidar_filter_z_min:=$(shell_quote "${UB_AUTOWARE_CARLA_EGO_LIDAR_FILTER_Z_MIN}")"
  optional_bridge_args+=" \\
  ego_lidar_filter_z_max:=$(shell_quote "${UB_AUTOWARE_CARLA_EGO_LIDAR_FILTER_Z_MAX}")"
  optional_bridge_args+=" \\
  carla_throttle_gain:=$(shell_quote "${UB_AUTOWARE_CARLA_THROTTLE_GAIN}")"
  optional_bridge_args+=" \\
  carla_max_throttle:=$(shell_quote "${UB_AUTOWARE_CARLA_MAX_THROTTLE}")"
  optional_bridge_args+=" \\
  carla_max_brake:=$(shell_quote "${UB_AUTOWARE_CARLA_MAX_BRAKE}")"
  optional_bridge_args+=" \\
  carla_brake_deadband:=$(shell_quote "${UB_AUTOWARE_CARLA_BRAKE_DEADBAND}")"
  optional_bridge_args+=" \\
  carla_throttle_tau:=$(shell_quote "${UB_AUTOWARE_CARLA_THROTTLE_TAU}")"
  optional_bridge_args+=" \\
  carla_brake_tau:=$(shell_quote "${UB_AUTOWARE_CARLA_BRAKE_TAU}")"
  optional_bridge_args+=" \\
  carla_soft_speed_limit:=$(shell_quote "${UB_AUTOWARE_CARLA_SOFT_SPEED_LIMIT}")"
  optional_bridge_args+=" \\
  carla_speed_taper_start:=$(shell_quote "${UB_AUTOWARE_CARLA_SPEED_TAPER_START}")"
  optional_bridge_args+=" \\
  carla_longitudinal_control_mode:=$(shell_quote "${UB_AUTOWARE_CARLA_LONGITUDINAL_CONTROL_MODE}")"
  optional_bridge_args+=" \\
  carla_native_throttle_kp:=$(shell_quote "${UB_AUTOWARE_CARLA_NATIVE_THROTTLE_KP}")"
  optional_bridge_args+=" \\
  carla_native_accel_gain:=$(shell_quote "${UB_AUTOWARE_CARLA_NATIVE_ACCEL_GAIN}")"
  optional_bridge_args+=" \\
  carla_native_brake_gain:=$(shell_quote "${UB_AUTOWARE_CARLA_NATIVE_BRAKE_GAIN}")"
  optional_bridge_args+=" \\
  carla_native_brake_accel_deadband:=$(shell_quote "${UB_AUTOWARE_CARLA_NATIVE_BRAKE_ACCEL_DEADBAND}")"
  optional_bridge_args+=" \\
  carla_native_brake_speed_error_deadband:=$(shell_quote "${UB_AUTOWARE_CARLA_NATIVE_BRAKE_SPEED_ERROR_DEADBAND}")"
  optional_bridge_args+=" \\
  carla_stop_steer_recenter_enabled:=$(shell_quote "${UB_AUTOWARE_CARLA_STOP_STEER_RECENTER}")"
  optional_bridge_args+=" \\
  carla_stop_steer_speed_threshold:=$(shell_quote "${UB_AUTOWARE_CARLA_STOP_STEER_SPEED_THRESHOLD}")"
  optional_bridge_args+=" \\
  carla_stop_steer_desired_speed_threshold:=$(shell_quote "${UB_AUTOWARE_CARLA_STOP_STEER_DESIRED_SPEED_THRESHOLD}")"
  optional_bridge_args+=" \\
  carla_stop_steer_brake_threshold:=$(shell_quote "${UB_AUTOWARE_CARLA_STOP_STEER_BRAKE_THRESHOLD}")"
  optional_bridge_args+=" \\
  publish_detected_objects:=$(shell_quote "${UB_AUTOWARE_CARLA_PUBLISH_DETECTED_OBJECTS}")"
  optional_bridge_args+=" \\
  detected_objects_topic:=$(shell_quote "${UB_AUTOWARE_CARLA_DETECTED_OBJECTS_TOPIC}")"
  optional_bridge_args+=" \\
  detected_objects_frame_id:=$(shell_quote "${UB_AUTOWARE_CARLA_DETECTED_OBJECTS_FRAME_ID}")"
  optional_bridge_args+=" \\
  detected_objects_max_distance:=$(shell_quote "${UB_AUTOWARE_CARLA_DETECTED_OBJECTS_MAX_DISTANCE}")"
  if [[ -n "${UB_AUTOWARE_CARLA_DETECTED_OBJECTS_ROLE_NAME}" ]]; then
    optional_bridge_args+=" \\
  detected_objects_role_name:=$(shell_quote "${UB_AUTOWARE_CARLA_DETECTED_OBJECTS_ROLE_NAME}")"
  fi

launch_cmd="
set -eo pipefail
export RMW_IMPLEMENTATION=$(shell_quote "${UB_AUTOWARE_RMW_IMPLEMENTATION}")
export CYCLONEDDS_URI=$(shell_quote "${UB_AUTOWARE_CYCLONEDDS_URI}")
source /opt/ros/humble/setup.bash
source /autoware/install/setup.bash
ros2 pkg prefix autoware_carla_interface >/dev/null
ros2 pkg prefix ub_lincoln_vehicle_launch >/dev/null
ros2 pkg prefix ub_lincoln_sensor_kit_launch >/dev/null

if [[ $(shell_quote "${UB_AUTOWARE_CARLA_DISABLE_STEER_CONVERGENCE_HOLD}") == \"1\" ]]; then
  python3 - <<'PY'
from pathlib import Path

paths = [
    Path('/autoware/install/autoware_launch/share/autoware_launch/config/control/trajectory_follower/longitudinal/pid.param.yaml'),
    Path('/autoware/src/launcher/autoware_launch/autoware_launch/config/control/trajectory_follower/longitudinal/pid.param.yaml'),
]

old = 'enable_keep_stopped_until_steer_convergence: true'
new = 'enable_keep_stopped_until_steer_convergence: false'

for path in paths:
    if not path.exists():
        continue
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())
    text = path.read_text()
    if new in text:
        print(f'Autoware CARLA steer-convergence hold already disabled: {path}')
    elif old in text:
        path.write_text(text.replace(old, new, 1))
        print(f'Disabled Autoware steer-convergence launch hold for CARLA: {path}')
    else:
        print(f'Warning: steer-convergence hold parameter not found in {path}')
PY
fi

if [[ $(shell_quote "${UB_AUTOWARE_CARLA_TUNE_SPEED}") == \"1\" ]]; then
UB_CARLA_MAX_VEL=$(shell_quote "${UB_AUTOWARE_CARLA_MAX_VEL}") \\
UB_CARLA_MAX_ACCEL=$(shell_quote "${UB_AUTOWARE_CARLA_MAX_ACCEL}") \\
UB_CARLA_ENGAGE_VELOCITY=$(shell_quote "${UB_AUTOWARE_CARLA_ENGAGE_VELOCITY}") \\
UB_CARLA_TURN_LATERAL_ACCEL_LIMITS=$(shell_quote "${UB_AUTOWARE_CARLA_TURN_LATERAL_ACCEL_LIMITS}") \\
UB_CARLA_MIN_TURN_VEL=$(shell_quote "${UB_AUTOWARE_CARLA_MIN_TURN_VEL}") \\
UB_CARLA_INTERSECTION_TURN_VEL=$(shell_quote "${UB_AUTOWARE_CARLA_INTERSECTION_TURN_VEL}") \\
python3 - <<'PY'
import os
from pathlib import Path
import re

def backup_file(path):
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())

def set_scalar(path, key, value):
    if not path.exists():
        return False
    backup_file(path)
    text = path.read_text()
    pattern = re.compile(
        rf'^(\\s*{re.escape(key)}:\\s*)[-+0-9.eE]+(\\s*(?:#.*)?)$',
        re.MULTILINE,
    )
    updated, count = pattern.subn(rf'\\g<1>{value}\\g<2>', text, count=1)
    if count:
        path.write_text(updated)
        print(f'Set {key}: {value} in {path}')
        return True
    print(f'Warning: {key} not found in {path}')
    return False

def set_number_list(path, key, csv_values):
    if not path.exists():
        return False
    values = [value.strip() for value in csv_values.split(',') if value.strip()]
    if not values:
        print(f'Warning: no values provided for {key}')
        return False
    backup_file(path)
    text = path.read_text()
    pattern = re.compile(
        rf'^(\\s*{re.escape(key)}:\\s*)\\[[^\\]]*\\](\\s*(?:#.*)?)$',
        re.MULTILINE,
    )
    list_text = ', '.join(values)
    replacement = rf'\\g<1>[{list_text}]\\g<2>'
    updated, count = pattern.subn(replacement, text, count=1)
    if count:
        path.write_text(updated)
        print(f'Set {key}: [{list_text}] in {path}')
        return True
    print(f'Warning: {key} not found in {path}')
    return False

def glob_existing(patterns):
    paths = []
    for pattern in patterns:
        paths.extend(Path('/').glob(pattern.lstrip('/')))
    return sorted(set(path for path in paths if path.exists()))

def set_scalar_if_present(paths, key, value):
    updated = False
    key_pattern = re.compile(rf'^\\s*{re.escape(key)}:\\s*[-+0-9.eE]+', re.MULTILINE)
    for path in paths:
        if key_pattern.search(path.read_text()):
            updated = set_scalar(path, key, value) or updated
    if not updated:
        print(f'Warning: {key} not found in candidate Autoware turn-speed configs')
    return updated

max_vel = os.environ['UB_CARLA_MAX_VEL']
max_accel = os.environ['UB_CARLA_MAX_ACCEL']
engage_velocity = os.environ['UB_CARLA_ENGAGE_VELOCITY']
turn_lateral_accel_limits = os.environ['UB_CARLA_TURN_LATERAL_ACCEL_LIMITS']
min_turn_vel = os.environ['UB_CARLA_MIN_TURN_VEL']
intersection_turn_vel = os.environ['UB_CARLA_INTERSECTION_TURN_VEL']

common_paths = [
    Path('/autoware/install/autoware_launch/share/autoware_launch/config/planning/scenario_planning/common/common.param.yaml'),
    Path('/autoware/src/launcher/autoware_launch/autoware_launch/config/planning/scenario_planning/common/common.param.yaml'),
]
velocity_smoother_paths = [
    Path('/autoware/install/autoware_launch/share/autoware_launch/config/planning/scenario_planning/common/autoware_velocity_smoother/velocity_smoother.param.yaml'),
    Path('/autoware/src/launcher/autoware_launch/autoware_launch/config/planning/scenario_planning/common/autoware_velocity_smoother/velocity_smoother.param.yaml'),
]
analytical_paths = [
    Path('/autoware/install/autoware_launch/share/autoware_launch/config/planning/scenario_planning/common/autoware_velocity_smoother/Analytical.param.yaml'),
    Path('/autoware/src/launcher/autoware_launch/autoware_launch/config/planning/scenario_planning/common/autoware_velocity_smoother/Analytical.param.yaml'),
]

for path in common_paths:
    set_scalar(path, 'max_vel', max_vel)
    set_scalar(path, 'max_acc', max_accel)

for path in velocity_smoother_paths:
    set_scalar(path, 'max_vel', max_vel)
    set_scalar(path, 'engage_velocity', engage_velocity)
    set_number_list(path, 'lateral_acceleration_limits', turn_lateral_accel_limits)
    set_scalar(path, 'min_curve_velocity', min_turn_vel)

for path in analytical_paths:
    set_scalar(path, 'max_acc', max_accel)
    set_number_list(path, 'lateral_acceleration_limits', turn_lateral_accel_limits)
    set_scalar(path, 'min_curve_velocity', min_turn_vel)

turn_speed_paths = glob_existing([
    '/autoware/install/autoware_launch/share/autoware_launch/config/planning/**/*.yaml',
    '/autoware/src/launcher/autoware_launch/autoware_launch/config/planning/**/*.yaml',
])
turn_speed_paths = [
    path for path in turn_speed_paths
    if any(token in str(path) for token in ('velocity', 'intersection', 'curve', 'turn'))
]
for key, value in [
    ('min_curve_velocity', min_turn_vel),
    ('curve_velocity', min_turn_vel),
    ('turn_velocity', intersection_turn_vel),
    ('intersection_velocity', intersection_turn_vel),
    ('max_turn_velocity', intersection_turn_vel),
]:
    set_scalar_if_present(turn_speed_paths, key, value)
PY
else
  echo \"Keeping Autoware speed and throttle settings from the image/config files.\"
fi

if [[ $(shell_quote "${UB_AUTOWARE_CARLA_PLANNING_PRESET}") == \"1\" ]]; then
AUTOWARE_PLANNING_MODULE_PRESET_FOR_CARLA=$(shell_quote "${AUTOWARE_PLANNING_MODULE_PRESET}") python3 - <<'PY'
import os
from pathlib import Path

preset_name = os.environ['AUTOWARE_PLANNING_MODULE_PRESET_FOR_CARLA']
preset_dir = Path('/autoware/install/autoware_launch/share/autoware_launch/config/planning/preset')
source_path = preset_dir / 'default_preset.yaml'
target_path = preset_dir / f'{preset_name}_preset.yaml'

if not source_path.exists():
    print(f'Warning: CARLA planning preset skipped; missing {source_path}')
else:
    text = source_path.read_text()
    disabled_modules = {
        'launch_crosswalk_module',
        'launch_walkway_module',
        'launch_traffic_light_module',
        'launch_virtual_traffic_light_module',
    }
    lines = text.splitlines()
    for index, line in enumerate(lines[:-1]):
        stripped = line.strip()
        if not stripped.startswith('name: '):
            continue
        module_name = stripped.split(':', 1)[1].strip()
        if module_name not in disabled_modules:
            continue
        default_line_index = index + 1
        if 'default:' in lines[default_line_index]:
            indent = lines[default_line_index].split('default:', 1)[0]
            lines[default_line_index] = f'{indent}default: ' + repr('false')
    target_path.write_text('\n'.join(lines) + '\n')
    print(
        'Prepared CARLA planning preset without traffic-light/crosswalk '
        f'behavior modules: {target_path}'
    )
PY
fi

if [[ $(shell_quote "${UB_AUTOWARE_EGO_ONLY_PERCEPTION}") == \"1\" ]]; then
python3 - <<'PY'
from pathlib import Path

path = Path('/autoware/install/autoware_launch/share/autoware_launch/launch/autoware.launch.xml')
if not path.exists():
    print(f'Warning: ego-only perception patch skipped; missing {path}')
else:
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())
    text = backup.read_text()
    quote = chr(34)
    dollar = chr(36)
    data_path_arg = (
        f'      <arg name={quote}data_path{quote} '
        f'value={quote}{dollar}(var data_path){quote}/>\n'
    )
    empty_objects_arg = (
        f'      <arg name={quote}use_empty_dynamic_object_publisher{quote} '
        f'value={quote}true{quote}/>\n'
    )
    traffic_light_arg = (
        f'      <arg name={quote}use_traffic_light_recognition{quote} '
        f'value={quote}false{quote}/>\n'
    )
    changed = False
    if traffic_light_arg not in text and empty_objects_arg in text:
        text = text.replace(empty_objects_arg, empty_objects_arg + traffic_light_arg, 1)
        changed = True
    if empty_objects_arg in text:
        path.write_text(text)
        if changed:
            print(f'Disabled CARLA traffic-light recognition: {path}')
        print(f'Ego-only empty object publisher already enabled: {path}')
    elif data_path_arg in text:
        path.write_text(text.replace(data_path_arg, data_path_arg + empty_objects_arg + traffic_light_arg, 1))
        print(f'Enabled ego-only perception for CARLA: {path}')
    else:
        print(f'Warning: perception include data_path arg not found in {path}')
PY
else
python3 - <<'PY'
from pathlib import Path

path = Path('/autoware/install/autoware_launch/share/autoware_launch/launch/autoware.launch.xml')
backup = path.with_suffix(path.suffix + '.ub-original')
if backup.exists():
    path.write_text(backup.read_text())
    print(f'Restored Autoware perception launch file from UB backup: {path}')
PY
fi

UB_LIDAR_DETECTION_MODEL=$(shell_quote "${UB_AUTOWARE_LIDAR_DETECTION_MODEL}") python3 - <<'PY'
import os
from pathlib import Path

model = os.environ['UB_LIDAR_DETECTION_MODEL']

autoware_launch_paths = [
    Path('/autoware/install/autoware_launch/share/autoware_launch/launch/autoware.launch.xml'),
    Path('/autoware/src/launcher/autoware_launch/autoware_launch/launch/autoware.launch.xml'),
]
e2e_launch_paths = [
    Path('/autoware/install/autoware_launch/share/autoware_launch/launch/e2e_simulator.launch.xml'),
    Path('/autoware/src/launcher/autoware_launch/autoware_launch/launch/e2e_simulator.launch.xml'),
]

def backup_file(path):
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())

def patch_file(path, replacements):
    if not path.exists():
        print(f'Warning: learned LiDAR detector launch patch skipped; missing {path}')
        return
    backup_file(path)
    text = path.read_text()
    changed = False
    for marker, insertion, presence in replacements:
        if presence in text:
            continue
        if marker not in text:
            print(f'Warning: learned LiDAR detector patch marker not found in {path}: {marker.strip()}')
            continue
        text = text.replace(marker, marker + insertion, 1)
        changed = True
    if changed:
        path.write_text(text)
        print(f'Enabled learned LiDAR detector launch forwarding: {path}')
    else:
        print(f'Learned LiDAR detector launch forwarding already enabled: {path}')

quote = chr(34)
dollar = chr(36)
autoware_perception_arg = (
    f'  <arg name={quote}perception_mode{quote} default={quote}lidar{quote} '
    f'description={quote}select perception mode. camera_lidar_radar_fusion, camera_lidar_fusion, lidar_radar_fusion, lidar, radar{quote}/>\n'
)
autoware_detector_arg = (
    f'  <arg name={quote}lidar_detection_model{quote} default={quote}{model}{quote} '
    f'description={quote}learned LiDAR detector model, e.g. centerpoint/centerpoint_tiny{quote}/>\n'
)
autoware_data_pass = (
    f'      <arg name={quote}data_path{quote} value={quote}{dollar}(var data_path){quote}/>\n'
)
autoware_detector_pass = (
    f'      <arg name={quote}lidar_detection_model{quote} '
    f'value={quote}{dollar}(var lidar_detection_model){quote}/>\n'
)

e2e_data_arg = (
    f'  <arg name={quote}data_path{quote} default={quote}{dollar}(env HOME)/autoware_data{quote} '
    f'description={quote}packages data and artifacts directory path{quote}/>\n'
)
e2e_detector_arg = (
    f'  <arg name={quote}lidar_detection_model{quote} default={quote}{model}{quote} '
    f'description={quote}learned LiDAR detector model, e.g. centerpoint/centerpoint_tiny{quote}/>\n'
)
e2e_data_pass = (
    f'      <arg name={quote}data_path{quote} value={quote}{dollar}(var data_path){quote}/>\n'
)
e2e_detector_pass = (
    f'      <arg name={quote}lidar_detection_model{quote} '
    f'value={quote}{dollar}(var lidar_detection_model){quote}/>\n'
)

for path in autoware_launch_paths:
    patch_file(
        path,
        [
            (autoware_perception_arg, autoware_detector_arg, f'name={quote}lidar_detection_model{quote}'),
            (autoware_data_pass, autoware_detector_pass, f'name={quote}lidar_detection_model{quote} value={quote}{dollar}(var lidar_detection_model){quote}'),
        ],
    )

for path in e2e_launch_paths:
    patch_file(
        path,
        [
            (e2e_data_arg, e2e_detector_arg, f'name={quote}lidar_detection_model{quote}'),
            (e2e_data_pass, e2e_detector_pass, f'name={quote}lidar_detection_model{quote} value={quote}{dollar}(var lidar_detection_model){quote}'),
        ],
    )
PY

if [[ $(shell_quote "${UB_AUTOWARE_CARLA_PUBLISH_DETECTED_OBJECTS}") == \"true\" ]]; then
UB_CARLA_DETECTED_OBJECTS_TOPIC=$(shell_quote "${UB_AUTOWARE_CARLA_DETECTED_OBJECTS_TOPIC}") python3 - <<'PY'
import os
from pathlib import Path

topic = os.environ['UB_CARLA_DETECTED_OBJECTS_TOPIC']
paths = [
    Path('/autoware/install/autoware_launch/share/autoware_launch/config/perception/object_recognition/tracking/multi_object_tracker/input_channels.param.yaml'),
    Path('/autoware/src/launcher/autoware_launch/autoware_launch/config/perception/object_recognition/tracking/multi_object_tracker/input_channels.param.yaml'),
    Path('/autoware/install/autoware_multi_object_tracker/share/autoware_multi_object_tracker/config/input_channels.param.yaml'),
    Path('/autoware/src/universe/autoware_universe/perception/autoware_multi_object_tracker/config/input_channels.param.yaml'),
]

def route_detected_objects_topic(text, topic):
    lines = text.splitlines(keepends=True)
    for block_index, line in enumerate(lines):
        if line.strip() != 'detected_objects:':
            continue
        block_indent = len(line) - len(line.lstrip())
        for index in range(block_index + 1, len(lines)):
            stripped = lines[index].strip()
            indent = len(lines[index]) - len(lines[index].lstrip())
            if stripped and indent <= block_indent:
                return text, 0
            if stripped.startswith('topic:'):
                newline = '\n' if lines[index].endswith('\n') else ''
                lines[index] = f'{lines[index][:indent]}topic: "{topic}"{newline}'
                return ''.join(lines), 1
        return text, 0
    return text, 0

for path in paths:
    if not path.exists():
        continue
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())
    text = path.read_text()
    updated, count = route_detected_objects_topic(text, topic)
    if count:
        path.write_text(updated)
        print(f'Routed Autoware detected_objects tracker input to CARLA ground truth: {path}')
    else:
        print(f'Warning: detected_objects tracker input topic not found in {path}')
PY
else
python3 - <<'PY'
from pathlib import Path

paths = [
    Path('/autoware/install/autoware_launch/share/autoware_launch/config/perception/object_recognition/tracking/multi_object_tracker/input_channels.param.yaml'),
    Path('/autoware/src/launcher/autoware_launch/autoware_launch/config/perception/object_recognition/tracking/multi_object_tracker/input_channels.param.yaml'),
    Path('/autoware/install/autoware_multi_object_tracker/share/autoware_multi_object_tracker/config/input_channels.param.yaml'),
    Path('/autoware/src/universe/autoware_universe/perception/autoware_multi_object_tracker/config/input_channels.param.yaml'),
]
for path in paths:
    backup = path.with_suffix(path.suffix + '.ub-original')
    if backup.exists():
        path.write_text(backup.read_text())
        print(f'Restored Autoware detected_objects tracker input config: {path}')
PY
fi

python3 - <<'PY'
from pathlib import Path

paths = [
    Path('/autoware/install/ub_lincoln_sensor_kit_launch/share/ub_lincoln_sensor_kit_launch/launch/camera.launch.xml'),
    Path('/autoware/src/launcher/autoware_launch/sensor_kit/ub_lincoln_sensor_kit_launch/ub_lincoln_sensor_kit_launch/launch/camera.launch.xml'),
]

dollar = chr(36)
quote = chr(34)
apostrophe = chr(39)
old = (
    '<node pkg=' + quote + 'vimbax_camera' + quote
    + ' exec=' + quote + 'vimbax_camera_node' + quote
    + ' name=' + quote + 'vimbax_camera' + quote
    + ' output=' + quote + 'log' + quote + '>'
)
new = (
    '<node if=' + quote + dollar + '(eval &quot;' + apostrophe
    + dollar + '(var launch_driver)' + apostrophe + ' == '
    + apostrophe + 'true' + apostrophe + '&quot;)' + quote
    + ' pkg=' + quote + 'vimbax_camera' + quote
    + ' exec=' + quote + 'vimbax_camera_node' + quote
    + ' name=' + quote + 'vimbax_camera' + quote
    + ' output=' + quote + 'log' + quote + '>'
)

for path in paths:
    if not path.exists():
        continue
    backup = path.with_suffix(path.suffix + '.ub-original')
    if not backup.exists():
        backup.write_text(path.read_text())
    text = path.read_text()
    if new in text:
        print(f'UB-Lincoln camera driver launch guard already applied: {path}')
    elif old in text:
        path.write_text(text.replace(old, new, 1))
        print(f'Applied UB-Lincoln camera driver launch guard for simulation: {path}')
    else:
        print(f'Warning: UB-Lincoln VimbaX camera node not found in {path}')
PY

ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml \\
  host:=$(shell_quote "${AUTOWARE_CARLA_HOST}") \\
  port:=$(shell_quote "${AUTOWARE_CARLA_PORT}") \\
  carla_map:=$(shell_quote "${CARLA_MAP}") \\
  fixed_delta_seconds:=$(shell_quote "${UB_SUMO_STEP_LENGTH}") \\
  ego_vehicle_role_name:=$(shell_quote "${UB_AUTOWARE_CARLA_EGO_ROLE_NAME}") \\
  vehicle_type:=$(shell_quote "${UB_AUTOWARE_CARLA_VEHICLE_TYPE}") \\
  spawn_point:=$(shell_quote "${UB_AUTOWARE_CARLA_SPAWN_POINT}") \\
  project_spawn_point_to_road:=$(shell_quote "${UB_AUTOWARE_CARLA_PROJECT_SPAWN_TO_ROAD}") \\
  external_tick:=True \\
  external_tick_timeout:=$(shell_quote "${UB_AUTOWARE_CARLA_EXTERNAL_TICK_TIMEOUT}")${optional_bridge_args} &
BRIDGE_PID=\$!
RELAY_PID=
IMU_RELAY_PID=
OPERATION_MODE_SHIM_PID=

cleanup_bridge_processes() {
  kill \${BRIDGE_PID} 2>/dev/null || true
  if [[ -n \"\${RELAY_PID}\" ]]; then
    kill \${RELAY_PID} 2>/dev/null || true
  fi
  if [[ -n \"\${IMU_RELAY_PID}\" ]]; then
    kill \${IMU_RELAY_PID} 2>/dev/null || true
  fi
  if [[ -n \"\${OPERATION_MODE_SHIM_PID}\" ]]; then
    kill \${OPERATION_MODE_SHIM_PID} 2>/dev/null || true
  fi
}
trap cleanup_bridge_processes EXIT

sleep 5
if ! kill -0 \${BRIDGE_PID} 2>/dev/null; then
  echo \"Error: autoware_carla_interface exited before Autoware launch started.\" >&2
  wait \${BRIDGE_PID} || true
  exit 1
fi

if [[ $(shell_quote "${AUTOWARE_CARLA_POINTCLOUD_RELAY}") == \"1\" ]]; then
  ros2 run topic_tools relay \\
    /sensing/lidar/top/pointcloud_before_sync \\
    /sensing/lidar/concatenated/pointcloud &
  RELAY_PID=\$!
fi

if [[ $(shell_quote "${UB_AUTOWARE_CARLA_IMU_RELAY}") == \"1\" ]]; then
  ros2 run topic_tools relay \\
    /sensing/imu/tamagawa/imu_raw \\
    /sensing/gnss/novatel/oem7/imu/data_raw \\
    --ros-args -r __node:=ub_carla_imu_relay &
  IMU_RELAY_PID=\$!
fi

if [[ $(shell_quote "${UB_AUTOWARE_OPERATION_MODE_SHIM}") == \"1\" ]]; then
python3 - <<'PY' &
import rclpy
from rclpy.executors import ExternalShutdownException
from autoware_vehicle_msgs.msg import HazardLightsCommand
from autoware_vehicle_msgs.msg import TurnIndicatorsCommand
from tier4_system_msgs.msg import OperationModeAvailability

rclpy.init()
node = rclpy.create_node('ub_carla_operation_mode_shim')
hazard_pub = node.create_publisher(HazardLightsCommand, '/control/command/hazard_lights_cmd', 1)
turn_pub = node.create_publisher(TurnIndicatorsCommand, '/control/command/turn_indicators_cmd', 1)
availability_pub = node.create_publisher(
    OperationModeAvailability, '/system/operation_mode/availability', 1
)

def publish_operation_mode_inputs():
    stamp = node.get_clock().now().to_msg()

    hazard = HazardLightsCommand()
    hazard.stamp = stamp
    hazard.command = HazardLightsCommand.DISABLE
    hazard_pub.publish(hazard)

    turn = TurnIndicatorsCommand()
    turn.stamp = stamp
    turn.command = TurnIndicatorsCommand.DISABLE
    turn_pub.publish(turn)

    availability = OperationModeAvailability()
    availability.stamp = stamp
    availability.stop = True
    availability.autonomous = True
    availability.local = True
    availability.remote = True
    availability.emergency_stop = True
    availability.comfortable_stop = False
    availability.pull_over = False
    availability_pub.publish(availability)

node.create_timer(0.05, publish_operation_mode_inputs)
node.get_logger().info(
    'Publishing simulator operation-mode availability and disabled light commands'
)
try:
    rclpy.spin(node)
except (KeyboardInterrupt, ExternalShutdownException):
    pass
finally:
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
PY
OPERATION_MODE_SHIM_PID=\$!
fi

ros2 launch autoware_launch e2e_simulator.launch.xml \\
  map_path:=$(shell_quote "${AUTOWARE_MAP_PATH}") \\
  vehicle_model:=$(shell_quote "${AUTOWARE_VEHICLE_MODEL}") \\
  sensor_model:=$(shell_quote "${AUTOWARE_SENSOR_MODEL}") \\
  simulator_type:=$(shell_quote "${AUTOWARE_E2E_SIMULATOR_TYPE}")${optional_launch_args}
"

  echo "Launching passive CARLA interface and Autoware. Press Ctrl+C to stop the ROS launch."
  AUTOWARE_LAUNCH_STARTED=1
  set +e
  docker compose "${exec_args[@]}" "${AUTOWARE_SERVICE}" bash -lc "${launch_cmd}"
  local launch_status=$?
  set -e

  if [[ "${UB_KEEP_AUTOWARE_ROS}" != "1" ]]; then
    cleanup_autoware_launch_processes "Stopping Autoware ROS launch processes. Set UB_KEEP_AUTOWARE_ROS=1 to leave them running." AUTOWARE_SUMO_CLEANUP_PATTERNS
    AUTOWARE_LAUNCH_STARTED=0
  fi

  return "${launch_status}"
}
