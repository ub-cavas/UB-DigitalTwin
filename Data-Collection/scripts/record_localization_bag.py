#!/usr/bin/env python3
"""Preflight and record the Lincoln localization topic set with ROS 2 Humble."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time


ESSENTIAL_TOPICS = (
    '/tf', '/tf_static', '/sensing/lidar/top/aw_points',
    '/sensing/gnss/novatel/oem7/odom', '/localization/kinematic_state',
    '/api/localization/initialization_state', '/map/pointcloud_map',
    '/ub_mr/localization',
)
OPTIONAL_TOPICS = (
    '/initialpose', '/sensing/lidar/top/pointcloud_raw_ex',
    '/sensing/lidar/top/aw_points_ex',
    '/localization/pose_estimator/pose_with_covariance',
    '/sensing/gnss/pose_with_covariance', '/vehicle/status/velocity_status',
    '/sensing/imu/imu_data', '/diagnostics', '/robot_description',
    '/sensing/gnss/novatel/oem7/fix', '/sensing/gnss/novatel/oem7/inspva',
    '/autoware_orientation', '/sensing/gnss/novatel/oem7/imu/data_raw',
    '/parameter_events',
)
TOPICS = ESSENTIAL_TOPICS + OPTIONAL_TOPICS
RETAINED_DEPTHS = {
    '/tf_static': 100, '/map/pointcloud_map': 1,
    '/api/localization/initialization_state': 1, '/robot_description': 1,
}


def discovery_timeout(value):
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise argparse.ArgumentTypeError('must be finite and greater than 0, at most 300 seconds')
    return seconds


def topic_mapping(entries):
    mapping = {}
    for entry in entries:
        source, separator, target = entry.partition('=')
        if not separator or source not in TOPICS:
            raise ValueError(f'unknown or malformed mapping: {entry!r}')
        if source in mapping:
            raise ValueError(f'duplicate mapping source: {source}')
        if not re.fullmatch(r'/[A-Za-z_][A-Za-z_0-9]*(?:/[A-Za-z_][A-Za-z_0-9]*)*', target):
            raise ValueError(f'mapping target must be an absolute ROS topic name: {target!r}')
        mapping[source] = target
    effective = {topic: mapping.get(topic, topic) for topic in TOPICS}
    if len(set(effective.values())) != len(TOPICS):
        raise ValueError('mappings must produce 22 distinct topic names')
    return effective


def discover_publishers(topics, timeout):
    # Keep imports here so --help and unit tests work without a sourced ROS install.
    import rclpy
    from rclpy.context import Context
    from rclpy.signals import SignalHandlerOptions

    context = Context()
    node = None
    try:
        rclpy.init(args=[], context=context, signal_handler_options=SignalHandlerOptions.NO)
        node = rclpy.create_node('localization_bag_preflight', context=context)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=min(0.1, max(0, deadline - time.monotonic())))
        return {topic: node.get_publishers_info_by_topic(topic) for topic in topics}
    finally:
        try:
            if node is not None:
                node.destroy_node()
        finally:
            if context.ok():
                context.shutdown()


def report_publishers(effective, publishers):
    missing = []
    for requested, actual in effective.items():
        essential = requested in ESSENTIAL_TOPICS
        endpoints = publishers[actual]
        types = ', '.join(sorted({endpoint.topic_type for endpoint in endpoints})) or '-'
        print(f'{"essential" if essential else "optional "} {requested} -> {actual}: '
              f'{len(endpoints)} publisher(s); types: {types}')
        if not endpoints:
            print(f'WARNING: missing {"essential" if essential else "optional"} topic {actual}')
            if essential:
                missing.append(actual)
    return missing


def qos_overrides(effective, publishers):
    overrides = {}
    for requested, depth in RETAINED_DEPTHS.items():
        actual = effective[requested]
        endpoints = publishers[actual]
        if not endpoints:
            continue
        # ROS policy enum names also make unknown/system-default policies explicit.
        durability = [getattr(endpoint.qos_profile.durability, 'name', 'UNKNOWN')
                      for endpoint in endpoints]
        reliability = [getattr(endpoint.qos_profile.reliability, 'name', 'UNKNOWN')
                       for endpoint in endpoints]
        retained = all(policy == 'TRANSIENT_LOCAL' for policy in durability)
        reliable = all(policy == 'RELIABLE' for policy in reliability)
        if not retained:
            print(f'WARNING: {actual}: using volatile durability; historical context '
                  'may be unavailable (mixed, volatile, or unknown publisher policy).')
        if any(policy not in ('RELIABLE', 'BEST_EFFORT') for policy in reliability):
            print(f'WARNING: {actual}: unknown reliability; using best_effort.')
        overrides[actual] = {
            'history': 'keep_last', 'depth': depth,
            'durability': 'transient_local' if retained else 'volatile',
            'reliability': 'reliable' if reliable else 'best_effort',
        }
    return overrides


def write_qos(stream, overrides):
    for topic, policies in overrides.items():
        stream.write(f'{json.dumps(topic)}:\n')
        for name, value in policies.items():
            stream.write(f'  {name}: {value}\n')
    stream.flush()


def record(command):
    # A separate group prevents a terminal Ctrl-C reaching rosbag twice.
    child = None
    stop_signal = 0
    interrupt_sent = False
    previous_handlers = {}

    def request_stop(signum, frame):
        nonlocal stop_signal, interrupt_sent
        if not stop_signal:
            stop_signal = signum
        if child is not None and not interrupt_sent:
            interrupt_sent = True
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass  # The recorder exited between poll and signal.

    try:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous_handlers[signum] = signal.signal(signum, request_stop)
        child = subprocess.Popen(command, start_new_session=True)
        if stop_signal:
            request_stop(stop_signal, None)  # Handle a signal received during startup.
        while True:
            try:
                code = child.wait()
                return 128 + stop_signal if stop_signal else (code if code >= 0 else 128 - code)
            except KeyboardInterrupt:
                request_stop(signal.SIGINT, None)
    finally:
        try:
            if child is not None and child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, metavar='BAG_DIRECTORY')
    parser.add_argument('--discovery-timeout', type=discovery_timeout, default=5.0,
                        metavar='SECONDS', help='publisher discovery interval (0 < seconds <= 300; default: 5)')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--allow-missing-essential', action='store_true')
    parser.add_argument('--topic-map', action='append', default=[], metavar='REQUESTED=ACTUAL')
    args = parser.parse_args(argv)
    try:
        effective = topic_mapping(args.topic_map)
        output = args.output.expanduser().absolute()
        if output.exists() or output.is_symlink():
            raise ValueError(f'output already exists; choose a fresh bag directory: {output}')
        print(f'Output: {output}', flush=True)
        if shutil.which('ros2') is None:
            raise RuntimeError('ros2 not found; source /opt/ros/humble/setup.bash and the Autoware overlay')
        publishers = discover_publishers(effective.values(), args.discovery_timeout)
        missing = report_publishers(effective, publishers)
        if missing:
            if not args.allow_missing_essential:
                print('REFUSED: missing essential publishers: ' + ', '.join(missing), file=sys.stderr)
                return 2
            print('WARNING: --allow-missing-essential permits INCOMPLETE capture; missing: '
                  + ', '.join(missing))
        overrides = qos_overrides(effective, publishers)
        if args.check_only:
            print('Preflight complete; no recording started. Publisher discovery does not prove capture.')
            return 0
        output.parent.mkdir(parents=True, exist_ok=True)
        # rosbag itself also refuses an existing destination, including races after preflight.
        with tempfile.TemporaryDirectory(prefix='localization-bag-qos-') as directory:
            command = ['ros2', 'bag', 'record', '--output', str(output)]
            if overrides:
                qos_path = Path(directory) / 'qos.yaml'
                with qos_path.open('w') as stream:
                    write_qos(stream, overrides)
                command += ['--qos-profile-overrides-path', str(qos_path)]
            command += list(effective.values())
            print('Command: ' + shlex.join(command), flush=True)
            return record(command)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f'ERROR: {error}\nCheck the sourced ROS Humble/Autoware custom-message overlays, '
              'ros2 bag availability, ROS_DOMAIN_ID, RMW and container networking.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
