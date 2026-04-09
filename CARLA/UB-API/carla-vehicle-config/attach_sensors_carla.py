"""
attach_sensors_carla.py
=======================
Attaches sensors to a CARLA 4-wheeled vehicle by parsing three
Autoware calibration/param files at runtime:

  - sensors_calibration.yaml    (base_link → sensor_kit_base_link)
  - sensor_kit_calibration.yaml (sensor_kit_base_link → each sensor)
  - VLP32_param.yaml            (LiDAR driver params → CARLA attributes)

Usage:
  python attach_sensors_carla.py \
      --sensors_cal     sensors_calibration.yaml \
      --sensor_kit_cal  sensor_kit_calibration.yaml \
      --vlp_param       VLP32_param.yaml \
      --save                                          # enable disk logging
"""

import argparse
import math
import os
import sys
import time
from datetime import datetime
from threading import Thread

import numpy as np
import yaml
import carla


# ---------------------------------------------------------------------------
# 1. YAML LOADERS
# ---------------------------------------------------------------------------

def load_yaml(path: str) -> dict:
    if not os.path.isfile(path):
        sys.exit(f"[ERROR] File not found: {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        sys.exit(f"[ERROR] Expected a YAML mapping in: {path}")
    return data


def load_vlp_params(path: str) -> dict:
    """
    Parse VLP32_param.yaml.

    Your file structure:
      /**:
        ros__parameters:
          rotation_speed: 600
          max_range: 300.0
          min_range: 0.3
          return_mode: Dual
          sensor_model: VLP32
    """
    raw = load_yaml(path)

    # Unwrap /**:/ros__parameters/ nesting
    params = raw
    for key in ("/**", "ros__parameters"):
        if isinstance(params, dict) and key in params:
            params = params[key]

    rpm          = float(params.get("rotation_speed", 600))
    hz           = rpm / 60.0
    max_range    = float(params.get("max_range",      200.0))
    min_range    = float(params.get("min_range",      0.3))
    return_mode  = params.get("return_mode", "Dual")
    sensor_model = params.get("sensor_model", "VLP32").upper().replace("-", "")

    model_channels = {
        "VLP16":  16,
        "VLP32":  32,
        "VLP32C": 32,
        "HDL32":  32,
        "HDL64":  64,
        "VLS128": 128,
    }
    channels = model_channels.get(sensor_model, 32)

    upper_fov =  15.0
    lower_fov = -25.0

    points_per_second = int(channels * 1800 * hz)

    result = {
        "channels":           channels,
        "rotation_frequency": hz,
        "range":              max_range,
        "min_range":          min_range,
        "upper_fov":          upper_fov,
        "lower_fov":          lower_fov,
        "points_per_second":  points_per_second,
        "return_mode":        return_mode,
        "sensor_model":       sensor_model,
    }

    print(f"[VLP param] model={sensor_model}  "
          f"{int(rpm)} rpm ({hz} Hz)  "
          f"range={min_range}–{max_range} m  "
          f"return_mode={return_mode}  "
          f"pps={points_per_second:,}")
    return result


# ---------------------------------------------------------------------------
# 2. TRANSFORM PARSING  (chain base_link → kit → each sensor)
# ---------------------------------------------------------------------------

def get_tf(mapping: dict, name: str) -> dict:
    """Extract a transform dict with float values, defaulting missing fields to 0."""
    tf = mapping.get(name, {})
    return {k: float(tf.get(k, 0.0)) for k in ("x", "y", "z", "roll", "pitch", "yaw")}


def rpy_to_rotation_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """
    Build a 3x3 rotation matrix from ROS RPY (intrinsic XYZ) Euler angles in radians.

    ROS convention: extrinsic RPY = rotate around fixed X (roll), then Y (pitch), then Z (yaw).
    This is equivalent to intrinsic Z → Y → X.

    R = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    """
    cr, sr = math.cos(roll),  math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw),   math.sin(yaw)

    Rx = np.array([[1,  0,   0 ],
                   [0,  cr, -sr],
                   [0,  sr,  cr]])

    Ry = np.array([[ cp, 0, sp],
                   [ 0,  1,  0 ],
                   [-sp, 0, cp]])

    Rz = np.array([[cy, -sy, 0],
                   [sy,  cy, 0],
                   [0,   0,  1]])

    return Rz @ Ry @ Rx


def rotation_matrix_to_rpy(R: np.ndarray) -> tuple:
    """
    Extract ROS RPY (radians) from a 3x3 rotation matrix.
    Handles the gimbal-lock singularity at pitch = ±90°.
    """
    pitch = math.asin(max(-1.0, min(1.0, R[2, 0])))    # clamp for float safety

    if abs(R[2, 0]) < 0.9999:
        roll = math.atan2(-R[2, 1],  R[2, 2])
        yaw  = math.atan2(-R[1, 0],  R[0, 0])
    else:
        # Gimbal lock — yaw and roll are coupled; fix yaw = 0
        roll = math.atan2( R[1, 2],  R[1, 1])
        yaw  = 0.0

    return roll, pitch, yaw


def compose_transforms(parent: dict, child: dict) -> tuple:
    """
    Properly compose two ROS transforms using rotation matrices.

    Steps:
      1. Build rotation matrix for the parent (Rp).
      2. Rotate the child's translation vector by Rp, then add the parent's translation.
         t_composed = t_parent + Rp @ t_child
      3. Compose rotations: R_composed = Rp @ Rc
      4. Extract RPY from R_composed.

    This is correct for ANY rotation, not just axis-aligned ones.
    Simple addition (old approach) only works when all angles are zero.

    Returns (x, y, z, roll, pitch, yaw) in ROS convention — metres / radians.
    """
    # Parent rotation matrix
    Rp = rpy_to_rotation_matrix(parent["roll"], parent["pitch"], parent["yaw"])

    # Child translation rotated into parent frame, then offset by parent translation
    t_child  = np.array([child["x"], child["y"], child["z"]])
    t_parent = np.array([parent["x"], parent["y"], parent["z"]])
    t_composed = t_parent + Rp @ t_child

    # Composed rotation
    Rc          = rpy_to_rotation_matrix(child["roll"], child["pitch"], child["yaw"])
    R_composed  = Rp @ Rc
    roll, pitch, yaw = rotation_matrix_to_rpy(R_composed)

    return (
        float(t_composed[0]),
        float(t_composed[1]),
        float(t_composed[2]),
        roll,
        pitch,
        yaw,
    )


def parse_sensor_transforms(sensors_cal_path: str,
                             sensor_kit_cal_path: str) -> dict:
    """
    Parse both calibration YAMLs and return:
        { sensor_name: (x, y, z, roll, pitch, yaw) }
    All values are relative to base_link, in metres / radians.
    """
    sensors_cal    = load_yaml(sensors_cal_path)
    sensor_kit_cal = load_yaml(sensor_kit_cal_path)

    # --- Step 1: base_link → sensor_kit_base_link ---
    base_data = sensors_cal.get("base_link", {})
    kit_key   = next((k for k in base_data if "sensor_kit" in k.lower()), None)
    if kit_key is None:
        sys.exit("[ERROR] Cannot find 'sensor_kit_base_link' under 'base_link' "
                 "in sensors_calibration.yaml")

    kit_tf = get_tf(base_data, kit_key)
    print(f"\n[Cal] base_link → {kit_key}:  "
          f"x={kit_tf['x']}  y={kit_tf['y']}  z={kit_tf['z']}  "
          f"roll={kit_tf['roll']}  pitch={kit_tf['pitch']}  yaw={kit_tf['yaw']}")

    # --- Step 2: sensor_kit_base_link → each sensor ---
    kit_data = sensor_kit_cal.get(kit_key, {})
    if not kit_data:
        first    = next(iter(sensor_kit_cal), None)
        kit_data = sensor_kit_cal.get(first, {})
        print(f"[Cal] '{kit_key}' not found in sensor_kit_calibration.yaml, "
              f"falling back to top-level key '{first}'")

    # --- Step 3: compose using full rotation matrix and report ---
    transforms = {}
    for sensor_name, raw in kit_data.items():
        if not isinstance(raw, dict):
            continue
        sensor_tf = get_tf(kit_data, sensor_name)
        composed  = compose_transforms(kit_tf, sensor_tf)
        transforms[sensor_name] = composed
        print(f"[Cal]   {sensor_name:<45s}  "
              f"x={composed[0]:.3f}  y={composed[1]:.3f}  z={composed[2]:.3f}  "
              f"roll={math.degrees(composed[3]):.2f}°  "
              f"pitch={math.degrees(composed[4]):.2f}°  "
              f"yaw={math.degrees(composed[5]):.2f}°")

    if not transforms:
        sys.exit("[ERROR] No sensors parsed from sensor_kit_calibration.yaml")

    print()
    return transforms


# ---------------------------------------------------------------------------
# 3. COORDINATE CONVERSION  ROS → CARLA
#
#  ROS frame  : right-handed  X=forward  Y=left   Z=up    angles in radians
#  CARLA frame: left-handed   X=forward  Y=right  Z=up    angles in degrees
#
#  The only axis that flips is Y (and consequently any rotation that involves Y).
#  Concretely:
#    location :  carla_y = -ros_y
#    rotation :  carla_pitch = -ros_pitch   (rotation around Y flips with Y)
#                carla_yaw   = -ros_yaw     (yaw is rotation in XY plane; Y flip negates it)
#                carla_roll  =  ros_roll    (rotation around X — unchanged)
#  All angles converted from radians → degrees for CARLA.
# ---------------------------------------------------------------------------

def ros_to_carla_transform(x: float, y: float, z: float,
                            roll: float, pitch: float, yaw: float) -> carla.Transform:
    return carla.Transform(
        carla.Location(
            x=x,
            y=-y,       # ROS +left  →  CARLA +right  ∴ negate
            z=z,
        ),
        carla.Rotation(
            roll=math.degrees(roll),
            pitch=-math.degrees(pitch),   # Y-axis flip negates pitch
            yaw=-math.degrees(yaw),       # Y-axis flip negates yaw
        ),
    )


# ---------------------------------------------------------------------------
# 4. SENSOR BLUEPRINTS
# ---------------------------------------------------------------------------

def make_configure_lidar(vlp: dict):
    """Closure that captures VLP params and applies them to a CARLA blueprint."""
    def configure_lidar(bp: carla.ActorBlueprint):
        bp.set_attribute("channels",                    str(vlp["channels"]))
        bp.set_attribute("range",                       str(vlp["range"]))
        bp.set_attribute("points_per_second",           str(vlp["points_per_second"]))
        bp.set_attribute("rotation_frequency",          str(vlp["rotation_frequency"]))
        bp.set_attribute("upper_fov",                   str(vlp["upper_fov"]))
        bp.set_attribute("lower_fov",                   str(vlp["lower_fov"]))
        bp.set_attribute("atmosphere_attenuation_rate", "0.004")
        print(f"[LiDAR cfg] channels={vlp['channels']}  "
              f"pps={vlp['points_per_second']:,}  "
              f"range={vlp['range']} m  "
              f"fov=[{vlp['lower_fov']}°, {vlp['upper_fov']}°]  "
              f"hz={vlp['rotation_frequency']}")
    return configure_lidar


def configure_camera(bp: carla.ActorBlueprint):
    bp.set_attribute("image_size_x", "1920")
    bp.set_attribute("image_size_y", "1080")
    bp.set_attribute("fov",          "60.0")


def build_blueprint_map(vlp_params: dict) -> list:
    """Ordered list — first matchinqg substring wins."""
    return [
        ("velodyne", "sensor.lidar.ray_cast", make_configure_lidar(vlp_params)),
        ("lidar",    "sensor.lidar.ray_cast", make_configure_lidar(vlp_params)),
        ("camera",   "sensor.camera.rgb",     configure_camera),
        ("gnss",     "sensor.other.gnss",     None),
        ("gps",      "sensor.other.gnss",     None),
        ("imu",      "sensor.other.imu",      None),
        ("radar",    "sensor.other.radar",    None),
    ]


def get_blueprint(library: carla.BlueprintLibrary,
                  sensor_name: str,
                  blueprint_map: list):
    lower = sensor_name.lower()
    for substring, bp_id, configure_fn in blueprint_map:
        if substring in lower:
            bp = library.find(bp_id)
            if configure_fn:
                configure_fn(bp)
            return bp
    return None


# ---------------------------------------------------------------------------
# 5. VEHICLE SPAWN
# ---------------------------------------------------------------------------

def spawn_vehicle(world: carla.World) -> carla.Vehicle:
    lib = world.get_blueprint_library()
    for model in ["vehicle.lincoln.mcity_mkz",
                  "vehicle.toyota.prius",
                  "vehicle.tesla.model3",
                  "vehicle.lincoln.mkz_2020"]:
        matches = lib.filter(model)
        if matches:
            bp = matches[0]
            break
    else:
        bp = lib.filter("vehicle.*")[0]

    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        sys.exit("[ERROR] No spawn points available in this map.")

    vehicle = world.try_spawn_actor(bp, spawn_points[0])
    if vehicle is None:
        sys.exit("[ERROR] Failed to spawn vehicle — try a different spawn point.")

    print(f"[+] Spawned: {vehicle.type_id}  (id={vehicle.id})")
    return vehicle


# ---------------------------------------------------------------------------
# 6. SENSOR ATTACHMENT
# ---------------------------------------------------------------------------

def attach_sensors(world: carla.World,
                   vehicle: carla.Vehicle,
                   sensor_transforms: dict,
                   blueprint_map: list) -> list:
    library  = world.get_blueprint_library()
    attached = []

    for sensor_name, ros_tf in sensor_transforms.items():
        bp = get_blueprint(library, sensor_name, blueprint_map)
        if bp is None:
            print(f"[!] No blueprint matched for '{sensor_name}' — skipping.")
            continue

        carla_tf = ros_to_carla_transform(*ros_tf)
        sensor   = world.spawn_actor(
            bp, carla_tf,
            attach_to=vehicle,
            attachment_type=carla.AttachmentType.Rigid,
        )
        attached.append((sensor_name, sensor))
        x, y, z = ros_tf[0], ros_tf[1], ros_tf[2]
        print(f"[+] Attached  {sensor_name:<45s}  "
              f"CARLA loc ({x:.3f}, {-y:.3f}, {z:.3f})")

    return attached


# ---------------------------------------------------------------------------
# 7. DATA CALLBACKS
#
#  Logging is DISABLED by default.
#  Pass --save on the CLI to enable disk writes for LiDAR and camera.
#  IMU and GNSS always print to console (they are lightweight).
# ---------------------------------------------------------------------------

SAVE_EVERY_N_FRAMES = 10


def save_async(data, path: str):
    """Non-blocking disk write — returns immediately."""
    Thread(target=data.save_to_disk, args=(path,), daemon=True).start()


def register_callbacks(sensors: list, output_dir: str, save: bool):
    """
    Attach data callbacks to every sensor.

    Args:
        sensors:    list of (name, carla.Actor) tuples
        output_dir: folder to write files into (only used when save=True)
        save:       if True, LiDAR and camera data is written to disk
                    if False, those sensors still run but data is discarded
    """
    if save:
        os.makedirs(output_dir, exist_ok=True)
        print(f"[Callbacks] Disk logging ON  — writing to: {output_dir}")
        print(f"[Callbacks] Saving every {SAVE_EVERY_N_FRAMES} frames")
    else:
        print("[Callbacks] Disk logging OFF — pass --save to enable")

    for name, sensor in sensors:
        safe = name.replace("/", "_")

        if any(k in name.lower() for k in ("velodyne", "lidar")):
            if save:
                sensor.listen(
                    lambda data, n=safe: (
                        save_async(data, os.path.join(output_dir, f"{n}_{data.frame:06d}.ply"))
                        if data.frame % SAVE_EVERY_N_FRAMES == 0 else None
                    )
                )
            else:
                # Still need a listener to drain the sensor queue, but discard data
                sensor.listen(lambda data: None)

        elif "camera" in name.lower():
            if save:
                sensor.listen(
                    lambda data, n=safe: (
                        save_async(data, os.path.join(output_dir, f"{n}_{data.frame:06d}.png"))
                        if data.frame % SAVE_EVERY_N_FRAMES == 0 else None
                    )
                )
            else:
                sensor.listen(lambda data: None)

        elif "imu" in name.lower():
            # Always print — no disk I/O involved
            sensor.listen(
                lambda data: print(
                    f"[IMU]  accel=({data.accelerometer.x:.3f}, "
                    f"{data.accelerometer.y:.3f}, {data.accelerometer.z:.3f})  "
                    f"gyro=({data.gyroscope.x:.3f}, "
                    f"{data.gyroscope.y:.3f}, {data.gyroscope.z:.3f})"
                )
            )

        elif any(k in name.lower() for k in ("gnss", "gps")):
            # Always print — no disk I/O involved
            sensor.listen(
                lambda data: print(
                    f"[GNSS] lat={data.latitude:.6f}  "
                    f"lon={data.longitude:.6f}  "
                    f"alt={data.altitude:.2f} m"
                )
            )


# ---------------------------------------------------------------------------
# 8. CLI
# ---------------------------------------------------------------------------

def parse_args():
    here = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(
        description="Attach Autoware-configured sensors to a CARLA vehicle."
    )
    p.add_argument(
        "--sensors_cal",
        default=os.path.join(here, "sensors_calibration.yaml"),
        help="base_link → sensor_kit_base_link",
    )
    p.add_argument(
        "--sensor_kit_cal",
        default=os.path.join(here, "sensor_kit_calibration.yaml"),
        help="sensor_kit_base_link → each sensor",
    )
    p.add_argument(
        "--vlp_param",
        default=os.path.join(here, "VLP32.param.yaml"),
        help="Velodyne driver param file",
    )
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", default=2000, type=int)
    p.add_argument(
        "--save",
        action="store_true",          # False unless flag is present
        help="Enable disk logging of LiDAR (.ply) and camera (.png) data",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# 9. MAIN
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    print("\n" + "=" * 60)
    print("  Step 1 — Parsing YAML files")
    print("=" * 60)
    vlp_params        = load_vlp_params(args.vlp_param)
    sensor_transforms = parse_sensor_transforms(args.sensors_cal, args.sensor_kit_cal)
    blueprint_map     = build_blueprint_map(vlp_params)

    print("=" * 60)
    print("  Step 2 — Connecting to CARLA")
    print("=" * 60)
    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    world  = client.get_world()

    # Traffic Manager must be configured BEFORE synchronous mode
    traffic_manager = client.get_trafficmanager(8000)
    traffic_manager.set_synchronous_mode(True)
    traffic_manager.set_global_distance_to_leading_vehicle(2.0)

    settings = world.get_settings()
    settings.synchronous_mode    = True
    settings.fixed_delta_seconds = 0.05   # 20 Hz
    world.apply_settings(settings)
    print("[+] Synchronous mode ON  (20 Hz)")

    # Create a timestamped run folder (only written to if --save is passed)
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "runs", f"run_{timestamp}"
    )

    print("\n" + "=" * 60)
    print("  Step 3 — Spawning vehicle & sensors")
    print("=" * 60)
    vehicle = spawn_vehicle(world)
    vehicle.set_autopilot(True, traffic_manager.get_port())
    traffic_manager.set_desired_speed(vehicle, 30.0)
    traffic_manager.auto_lane_change(vehicle, True)
    traffic_manager.ignore_lights_percentage(vehicle, 0.0)
    print("[+] Autopilot ON  (30 km/h)")

    sensors = attach_sensors(world, vehicle, sensor_transforms, blueprint_map)
    register_callbacks(sensors, output_dir=output_dir, save=args.save)

    spectator = world.get_spectator()

    print("\nRunning — press Ctrl-C to stop.\n")
    try:
        while True:
            world.tick()
            tf = vehicle.get_transform()
            spectator.set_transform(carla.Transform(
                tf.transform(carla.Location(x=-8.0, z=4.0)),
                carla.Rotation(pitch=-15.0, yaw=tf.rotation.yaw, roll=0.0),
            ))
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nCleaning up...")
        for name, sensor in sensors:
            sensor.destroy()
            print(f"[-] Destroyed {name}")
        vehicle.destroy()
        print("[-] Destroyed vehicle")
        settings.synchronous_mode    = False
        settings.fixed_delta_seconds = 0.0
        world.apply_settings(settings)
        traffic_manager.set_synchronous_mode(False)
        print("[+] Server restored to async mode")


if __name__ == "__main__":
    main()