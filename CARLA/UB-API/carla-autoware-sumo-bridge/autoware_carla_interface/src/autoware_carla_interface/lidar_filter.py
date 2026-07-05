import math

import numpy


def _degrees_to_radians(value, units):
    if units == "degrees":
        return math.radians(value)
    return value


def _rotation_matrix_from_rpy(roll, pitch, yaw):
    cr = math.cos(roll)
    sr = math.sin(roll)
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cy = math.cos(yaw)
    sy = math.sin(yaw)

    return numpy.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ],
        dtype=numpy.float32,
    )


def _sensor_transform_from_spec(sensor_spec):
    spawn_point = sensor_spec["spawn_point"]
    units = sensor_spec.get("rotation_units", "degrees")
    roll = _degrees_to_radians(spawn_point["roll"], units)
    pitch = _degrees_to_radians(spawn_point["pitch"], units)
    yaw = _degrees_to_radians(spawn_point["yaw"], units)

    translation = numpy.array(
        [spawn_point["x"], spawn_point["y"], spawn_point["z"]],
        dtype=numpy.float32,
    )
    rotation = _rotation_matrix_from_rpy(roll, pitch, yaw)
    return translation, rotation


def ego_vehicle_lidar_keep_mask(lidar_points, sensor_spec, bounds):
    if lidar_points.shape[0] == 0:
        return numpy.ones((0,), dtype=bool)
    if sensor_spec is None or sensor_spec.get("spawn_point_frame") != "base_link":
        return numpy.ones((lidar_points.shape[0],), dtype=bool)

    translation, rotation = _sensor_transform_from_spec(sensor_spec)
    points_base_link = lidar_points[:, :3] @ rotation.T + translation

    inside = (
        (points_base_link[:, 0] >= bounds["x_min"])
        & (points_base_link[:, 0] <= bounds["x_max"])
        & (points_base_link[:, 1] >= bounds["y_min"])
        & (points_base_link[:, 1] <= bounds["y_max"])
        & (points_base_link[:, 2] >= bounds["z_min"])
        & (points_base_link[:, 2] <= bounds["z_max"])
    )
    return ~inside


def filter_ego_vehicle_lidar_points(lidar_data, sensor_spec, bounds, enabled=True):
    if not enabled:
        return lidar_data, 0

    keep_mask = ego_vehicle_lidar_keep_mask(lidar_data, sensor_spec, bounds)
    removed_count = int(lidar_data.shape[0] - numpy.count_nonzero(keep_mask))
    if removed_count == 0:
        return lidar_data, 0
    return lidar_data[keep_mask], removed_count
