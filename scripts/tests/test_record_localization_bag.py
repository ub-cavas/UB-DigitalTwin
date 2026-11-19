"""Exercise recording preparation without ROS, hardware, or a running recorder."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('record_localization_bag', ROOT / 'Data-Collection/scripts/record_localization_bag.py')
bag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bag)


def endpoint(durability='TRANSIENT_LOCAL', reliability='RELIABLE'):
    return types.SimpleNamespace(
        topic_type='example_msgs/msg/Example',
        qos_profile=types.SimpleNamespace(
            durability=types.SimpleNamespace(name=durability),
            reliability=types.SimpleNamespace(name=reliability)))


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'bag with spaces'
        self.effective = bag.topic_mapping([])
        self.publishers = {topic: [endpoint()] for topic in bag.TOPICS}
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(self.stdout))
        self.stack.enter_context(contextlib.redirect_stderr(self.stderr))
        self.stack.enter_context(mock.patch.object(bag.shutil, 'which', return_value='/usr/bin/ros2'))
        self.discovery = self.stack.enter_context(mock.patch.object(
            bag, 'discover_publishers', return_value=self.publishers))
        self.recorder = self.stack.enter_context(mock.patch.object(bag, 'record', return_value=0))

    def run_main(self, *args):
        return bag.main(['--output', str(self.output), *args])

    def test_exact_topics_and_help_without_ros(self):
        self.assertEqual(bag.ESSENTIAL_TOPICS, (
            '/tf', '/tf_static', '/sensing/lidar/top/aw_points',
            '/sensing/gnss/novatel/oem7/odom', '/localization/kinematic_state',
            '/api/localization/initialization_state', '/map/pointcloud_map', '/ub_mr/localization'))
        self.assertEqual(bag.OPTIONAL_TOPICS, (
            '/initialpose', '/sensing/lidar/top/pointcloud_raw_ex', '/sensing/lidar/top/aw_points_ex',
            '/localization/pose_estimator/pose_with_covariance', '/sensing/gnss/pose_with_covariance',
            '/vehicle/status/velocity_status', '/sensing/imu/imu_data', '/diagnostics',
            '/robot_description', '/sensing/gnss/novatel/oem7/fix',
            '/sensing/gnss/novatel/oem7/inspva', '/autoware_orientation',
            '/sensing/gnss/novatel/oem7/imu/data_raw', '/parameter_events'))
        result = subprocess.run([sys.executable, '-S', str(ROOT / 'Data-Collection/scripts/record_localization_bag.py'),
                                 '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--check-only', result.stdout)

    def test_invalid_maps_refused_before_discovery(self):
        for entry in ('/tf', '/unknown=/x', '/tf=relative', '/tf=/bad//name',
                      '/tf=/9bad', '/tf=/tf_static', '/tf=/bad-name', '/tf=/x=y'):
            with self.subTest(entry=entry):
                self.assertEqual(self.run_main('--topic-map', entry), 1)
        self.assertEqual(self.run_main('--topic-map', '/tf=/x', '--topic-map', '/tf=/y'), 1)
        self.discovery.assert_not_called()
        self.recorder.assert_not_called()

    def test_mapping_affects_readiness_command_and_qos(self):
        self.publishers['/custom/static'] = self.publishers.pop('/tf_static')
        self.assertEqual(self.run_main('--topic-map', '/tf_static=/custom/static'), 0)
        command = self.recorder.call_args.args[0]
        self.assertIn('/custom/static', command)
        self.assertNotIn('/tf_static', command)
        self.assertIn('/tf_static -> /custom/static: 1 publisher', self.stdout.getvalue())
        self.assertIn('/custom/static', list(self.discovery.call_args.args[0]))

    def test_missing_essential_refused_and_override_keeps_all_names(self):
        self.publishers['/tf'] = []  # Subscribers alone never populate publisher endpoints.
        self.assertEqual(self.run_main(), 2)
        self.recorder.assert_not_called()
        self.assertEqual(self.run_main('--check-only'), 2)
        self.assertEqual(self.run_main('--allow-missing-essential'), 0)
        self.assertEqual(self.recorder.call_args.args[0][-22:], list(bag.TOPICS))
        self.assertIn('INCOMPLETE', self.stdout.getvalue())
        self.assertIn('/tf', self.stderr.getvalue())

    def test_optional_absent_keeps_discovery_and_explicit_output(self):
        for topic in bag.OPTIONAL_TOPICS:
            self.publishers[topic] = []
        self.assertEqual(self.run_main(), 0)
        command = self.recorder.call_args.args[0]
        self.assertEqual(command[-22:], list(bag.TOPICS))
        self.assertEqual(command[:5], ['ros2', 'bag', 'record', '--output', str(self.output.absolute())])
        for flag in ('--all', '--no-discovery', '--use-sim-time', '--include-hidden-topics'):
            self.assertNotIn(flag, command)
        self.assertNotIn('/clock', command)
        self.assertIn("'" + str(self.output) + "'", self.stdout.getvalue())

    def test_check_only_never_records_or_creates_destination(self):
        self.assertEqual(self.run_main('--check-only'), 0)
        self.recorder.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_existing_output_and_bad_timeouts(self):
        self.output.mkdir()
        self.assertEqual(self.run_main(), 1)
        self.discovery.assert_not_called()
        for value in ('0', '-1', 'nan', 'inf', '301', 'nonsense'):
            with self.subTest(value=value), self.assertRaises(SystemExit) as error:
                self.run_main('--discovery-timeout', value)
            self.assertEqual(error.exception.code, 2)
        self.assertEqual(bag.discovery_timeout('0.01'), 0.01)

    def test_qos_snapshot_and_tempfile_lifetime_on_success_and_failure(self):
        paths = []
        def record(command):
            path = Path(command[command.index('--qos-profile-overrides-path') + 1])
            paths.append(path)
            self.assertTrue(path.is_file())
            text = path.read_text()
            self.assertIn('"/tf_static":', text)
            self.assertNotIn('"/tf":', text)
            self.assertIn('durability: transient_local', text)
            return 7
        self.recorder.side_effect = record
        self.assertEqual(self.run_main(), 7)
        self.assertFalse(paths[0].exists())
        def failing_record(command):
            record(command)
            raise OSError('mock failure')
        self.recorder.side_effect = failing_record
        self.assertEqual(self.run_main(), 1)
        self.assertFalse(paths[1].exists())
        self.assertFalse(paths[1].parent.exists())

    def test_missing_ros_is_actionable(self):
        with mock.patch.object(bag.shutil, 'which', return_value=None):
            self.assertEqual(self.run_main(), 1)
        self.assertIn('source /opt/ros/humble', self.stderr.getvalue())
        self.discovery.assert_not_called()


class QosTests(unittest.TestCase):
    def test_policy_combinations_and_selectivity(self):
        cases = (
            ([endpoint()], 'transient_local', 'reliable', False),
            ([endpoint('VOLATILE')], 'volatile', 'reliable', True),
            ([endpoint(), endpoint('VOLATILE', 'BEST_EFFORT')], 'volatile', 'best_effort', True),
            ([endpoint(reliability='BEST_EFFORT')], 'transient_local', 'best_effort', False),
            ([endpoint('SYSTEM_DEFAULT', 'SYSTEM_DEFAULT')], 'volatile', 'best_effort', True),
            ([endpoint('UNKNOWN', 'UNKNOWN')], 'volatile', 'best_effort', True),
        )
        for endpoints, durability, reliability, warns in cases:
            with self.subTest(durability=durability, reliability=reliability):
                effective = bag.topic_mapping(['/tf_static=/mapped/static'])
                publishers = {topic: [] for topic in effective.values()}
                publishers['/mapped/static'] = endpoints
                publishers['/tf'] = [endpoint()]
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    overrides = bag.qos_overrides(effective, publishers)
                self.assertEqual(set(overrides), {'/mapped/static'})
                self.assertEqual(overrides['/mapped/static'], {
                    'history': 'keep_last', 'depth': 100,
                    'durability': durability, 'reliability': reliability})
                self.assertEqual('WARNING:' in output.getvalue(), warns)


class DiscoveryTests(unittest.TestCase):
    def test_publisher_only_query_and_cleanup_on_success_and_error(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                context = mock.Mock()
                node = mock.Mock()
                node.get_publishers_info_by_topic.return_value = []
                ros = types.ModuleType('rclpy')
                ros.init = mock.Mock()
                ros.create_node = mock.Mock(return_value=node)
                ros.spin_once = mock.Mock(side_effect=RuntimeError('discovery failed') if fail else None)
                context_module = types.ModuleType('rclpy.context')
                context_module.Context = mock.Mock(return_value=context)
                signals_module = types.ModuleType('rclpy.signals')
                signals_module.SignalHandlerOptions = types.SimpleNamespace(NO=0)
                with mock.patch.dict(sys.modules, {'rclpy': ros, 'rclpy.context': context_module,
                                                   'rclpy.signals': signals_module}), \
                        mock.patch.object(bag.time, 'monotonic', side_effect=[0, 0, 0, 2]):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, 'discovery failed'):
                            bag.discover_publishers(['/tf'], 1)
                    else:
                        self.assertEqual(bag.discover_publishers(['/tf'], 1), {'/tf': []})
                        node.get_publishers_info_by_topic.assert_called_once_with('/tf')
                        node.get_topic_names_and_types.assert_not_called()
                node.destroy_node.assert_called_once()
                context.shutdown.assert_called_once()


class LifecycleTests(unittest.TestCase):
    def test_exit_and_ctrl_c_wait_for_finalization(self):
        for code in (0, 7, -15):
            with mock.patch.object(bag.subprocess, 'Popen') as popen:
                child = popen.return_value
                child.wait.return_value = code
                child.poll.return_value = code
                self.assertEqual(bag.record(['ros2', 'bag', 'record']), code if code >= 0 else 143)
                popen.assert_called_once_with(['ros2', 'bag', 'record'], start_new_session=True)
        with mock.patch.object(bag.subprocess, 'Popen') as popen, \
                mock.patch.object(bag.os, 'killpg') as killpg, \
                contextlib.redirect_stdout(io.StringIO()):
            child = popen.return_value
            child.wait.side_effect = [KeyboardInterrupt, KeyboardInterrupt, 0]
            child.poll.side_effect = [None, 0]
            self.assertEqual(bag.record(['ros2']), 130)
            killpg.assert_called_once_with(child.pid, signal.SIGINT)
            self.assertEqual(child.wait.call_count, 3)

    def test_termination_signals_wait_and_restore_handlers(self):
        for signum in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signum=signum), \
                    mock.patch.object(bag.subprocess, 'Popen') as popen, \
                    mock.patch.object(bag.os, 'killpg') as killpg:
                original = {number: signal.getsignal(number) for number in
                            (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
                child = popen.return_value
                child.poll.side_effect = [None, 0]
                def finalize():
                    handler = signal.getsignal(signum)
                    handler(signum, None)
                    handler(signum, None)  # Repeated requests still send only one interrupt.
                    killpg.assert_called_once_with(child.pid, signal.SIGINT)
                    return 0
                child.wait.side_effect = finalize
                self.assertEqual(bag.record(['ros2']), 128 + signum)
                child.wait.assert_called_once_with()
                for number, handler in original.items():
                    self.assertEqual(signal.getsignal(number), handler)

    def test_signal_during_startup_is_forwarded_after_child_starts(self):
        with mock.patch.object(bag.subprocess, 'Popen') as popen, \
                mock.patch.object(bag.os, 'killpg') as killpg:
            child = mock.Mock()
            child.wait.return_value = 0
            child.poll.side_effect = [None, 0]
            def start(*args, **kwargs):
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                return child
            popen.side_effect = start
            self.assertEqual(bag.record(['ros2']), 143)
            killpg.assert_called_once_with(child.pid, signal.SIGINT)
            child.wait.assert_called_once_with()

    def test_unexpected_wait_failure_reaps_child(self):
        with mock.patch.object(bag.subprocess, 'Popen') as popen, \
                mock.patch.object(bag.os, 'killpg') as killpg:
            child = popen.return_value
            child.wait.side_effect = [OSError('wait failed'), subprocess.TimeoutExpired('ros2', 5), 0]
            child.poll.return_value = None
            with self.assertRaises(OSError):
                bag.record(['ros2'])
            self.assertEqual(killpg.call_args_list, [mock.call(child.pid, signal.SIGTERM),
                                                    mock.call(child.pid, signal.SIGKILL)])
            self.assertEqual(child.wait.call_count, 3)


if __name__ == '__main__':
    unittest.main()
