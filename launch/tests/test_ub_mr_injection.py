"""Explicit injection adapter and the real CARLA relay payload, without ROS."""
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'UB_AUTOWARE_CARLA_TOP_LIDAR_SOURCE_TOPIC'
ORIGINAL = '/sensing/lidar/top/pointcloud_before_sync'


class InjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='injection test ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'launch').mkdir()
        self.adapter = self.root/'launch/launch_autoware_carla_ub_mr_lidar.sh'
        self.adapter.write_text((ROOT/'launch/launch_autoware_carla_ub_mr_lidar.sh').read_text())
        self.delegate = self.root/'launch/launch_autoware_carla.sh'
        self.delegate.write_text('#!/bin/bash\npython3 - <<\'PY\'\nimport json,os,sys\nprint(json.dumps(dict(os.environ)))\nPY\nprintf "arg:%s\\n" "$@"\nexit "${MOCK_STATUS:-0}"\n')
        self.delegate.chmod(0o755)

    def run_adapter(self, *args, **env):
        return subprocess.run(['bash', str(self.adapter), *args], env={**os.environ, **env},
                              capture_output=True, text=True, timeout=5)

    def test_routes_override_conflicts_and_preserve_unrelated_settings(self):
        import json
        for mode in ('lidar', 'boxes', 'both'):
            result = self.run_adapter('--injection', mode, '--dry-run', **{
                SOURCE:'/wrong', 'UB_MR_PERCEPTION_PROFILE':'0', 'UB_AUTOWARE_EGO_ONLY_PERCEPTION':'1',
                'UB_AUTOWARE_CARLA_PUBLISH_DETECTED_OBJECTS':'1', 'UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY':'0',
                'UB_MR_BOUNDING_BOX_TOPIC':'/custom/boxes', 'AUTOWARE_MAP_PROFILE':'town10hd',
                'AUTOWARE_RVIZ':'false', 'BUILD_FOLDER':'custom release'})
            self.assertEqual(result.returncode, 0, result.stderr)
            env = json.loads(next(x for x in result.stdout.splitlines() if x.startswith('{')))
            self.assertEqual(env[SOURCE], ORIGINAL + ('' if mode == 'boxes' else '_modified'))
            for name, value in (('UB_MR_PERCEPTION_PROFILE','1'), ('UB_AUTOWARE_EGO_ONLY_PERCEPTION','0'),
                                ('UB_AUTOWARE_CARLA_PUBLISH_DETECTED_OBJECTS','0'), ('UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY','1'),
                                ('UB_MR_BOUNDING_BOX_TOPIC','/custom/boxes'), ('AUTOWARE_MAP_PROFILE','town10hd'),
                                ('AUTOWARE_RVIZ','false'), ('BUILD_FOLDER','custom release')):
                self.assertEqual(env[name], value)
            self.assertIn('arg:--dry-run', result.stdout)
            self.assertEqual(list(self.root.glob('CARLA/*')), [])
        self.assertIn(ORIGINAL+'_modified', self.run_adapter().stdout)

    def test_rejection_and_delegate_failure(self):
        for args in (('--injection',), ('--injection',''), ('--injection','Both'), ('--bogus',)):
            r = self.run_adapter(*args)
            self.assertEqual(r.returncode, 2)
            self.assertNotIn('arg:', r.stdout)
        self.assertEqual(self.run_adapter('--dry-run', MOCK_STATUS='37').returncode, 37)
        self.delegate.write_text('#!/bin/bash\nkill -TERM $$\n')
        self.assertEqual(self.run_adapter().returncode, -signal.SIGTERM)

    def test_real_launcher_rejects_unsafe_source_before_prerequisites(self):
        for topic in ('', 'relative', '/has space', '/a//b', '/a;touch_bad', '/$(whoami)', '/a\nb'):
            r = subprocess.run(['bash', str(ROOT/'CARLA/start_autoware_carla.sh'), '--dry-run'],
                               env={**os.environ, SOURCE:topic}, capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stdout+r.stderr)
            self.assertIn('Invalid '+SOURCE, r.stderr)

    def test_actual_relay_subscription_and_delivery(self):
        text = (ROOT/'CARLA/start_autoware_carla.sh').read_text()
        # Execute precisely the Python payload used by the real container command.
        payload = re.search(r"python3 - <<'PY' &\n(import os\nimport rclpy.*?)\nPY", text, re.S).group(1)
        self.assertIn('$(shell_quote "${'+SOURCE+'}") python3', text)
        for topic in (ORIGINAL, ORIGINAL+'_modified', '/custom/top_cloud'):
            events = []
            node = types.SimpleNamespace(
                create_publisher=lambda *args: types.SimpleNamespace(publish=lambda msg: events.append(('message',msg))),
                create_subscription=lambda kind, source, callback, qos: (events.append(('source', source)), callback('scan')),
                get_logger=lambda: types.SimpleNamespace(info=lambda msg: None), destroy_node=lambda: None)
            rclpy = types.ModuleType('rclpy')
            rclpy.init=lambda: None; rclpy.create_node=lambda name: node
            rclpy.spin=lambda node: None; rclpy.ok=lambda: True; rclpy.shutdown=lambda: None
            qos = types.ModuleType('rclpy.qos')
            for name in ('DurabilityPolicy','HistoryPolicy','ReliabilityPolicy'):
                setattr(qos, name, types.SimpleNamespace(VOLATILE=0, KEEP_LAST=0, BEST_EFFORT=0, RELIABLE=1))
            qos.QoSProfile=lambda **kwargs: kwargs
            executors=types.ModuleType('rclpy.executors'); executors.ExternalShutdownException=RuntimeError
            msgs=types.ModuleType('sensor_msgs.msg'); msgs.PointCloud2=object
            with patch.dict(sys.modules, {'rclpy':rclpy,'rclpy.qos':qos,'rclpy.executors':executors,
                                         'sensor_msgs':types.ModuleType('sensor_msgs'),'sensor_msgs.msg':msgs}), patch.dict(os.environ, {SOURCE:topic}):
                exec(compile(payload, 'actual-carla-relay', 'exec'), {})
            self.assertEqual(events, [('source',topic), ('message','scan')])
