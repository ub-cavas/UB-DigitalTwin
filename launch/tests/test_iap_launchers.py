"""Launcher lifecycle checks using fake gcloud, SSH, Docker and Unity processes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MOCK_COMMAND = r'''
import json
import os
from pathlib import Path
import signal
import sys
name = Path(sys.argv[0]).name
with open(os.environ['MOCK_EVENTS'], 'a') as stream:
    stream.write(json.dumps({'name': name, 'args': sys.argv[1:]}) + '\n')
if name == 'docker' and sys.argv[1] == 'ps':
    print('ub-mr-container')
if name == 'docker' and sys.argv[1] == 'inspect':
    print(os.environ['MOCK_BUILD'])
if name == 'docker' and sys.argv[1] == 'wait':
    import time
    time.sleep(.3)
    print(0)
if name == 'launch_autoware_carla.sh' and '--dry-run' in sys.argv:
    sys.exit(0)
if name == 'ssh' and '-O' in sys.argv and sys.argv[sys.argv.index('-O') + 1] == 'check':
    sys.exit(int(os.environ.get('MOCK_CHECK_STATUS', '0')))
if name in ('launch_autoware_carla.sh', 'Unity') and os.environ.get('MOCK_INTERRUPT'):
    os.kill(os.getppid(), signal.SIGINT)
    sys.exit(130)
if name == 'ssh' and '-O' in sys.argv and sys.argv[sys.argv.index('-O') + 1] == 'exit':
    sys.exit(0)
sys.exit(int(os.environ.get('MOCK_STATUS_' + name, '0')))
'''


class IapLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = self.root / 'events.jsonl'
        for directory in ('launch/lib', 'UB-MR/Builds/test', 'CARLA', 'bin',
                          'UB-MR/Scripts', 'UB-MR/ProjectSettings'):
            (self.root / directory).mkdir(parents=True)
        for path in ('launch/launch_ub_mr.sh', 'launch/launch_ub_mr_dev.sh', 'launch/lib/iap_tunnel.sh'):
            target = self.root / path
            target.write_text((ROOT / path).read_text().replace('/opt/ros/humble/setup.bash', str(self.root / 'ros-setup')))
            target.chmod(0o755)
        for path in ('bin/gcloud', 'bin/ssh', 'bin/docker', 'bin/Unity',
                     'launch/launch_autoware_carla.sh', 'CARLA/start_autoware_carla.sh',
                     'UB-MR/run_ub_mr.sh'):
            file = self.root / path
            file.write_text(f'#!{sys.executable}\n' + MOCK_COMMAND)
            file.chmod(0o755)
        (self.root / 'ros-setup').touch()
        (self.root / 'UB-MR/Builds/test/UB-MR.x86_64').touch()
        (self.root / 'UB-MR/ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: test\n')
        (self.root / 'UB-MR/Scripts/host_ros2_env.bash').write_text('# Mock ROS environment\n')
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('UB_', 'MOCK_', 'UNITY_', 'AUTOWARE_'))}
        self.env.update(
            PATH=f'{self.root / "bin"}:{os.environ["PATH"]}',
            MOCK_EVENTS=str(self.events), MOCK_BUILD=str(self.root / 'UB-MR/Builds/test'), UB_MR_BUILD_FOLDER='test', UB_MR_LOCALIZATION='0',
            UNITY_EDITOR=str(self.root / 'bin/Unity'),
        )

    def launch(self, *args, editor=False, **env):
        self.events.unlink(missing_ok=True)
        script = 'launch_ub_mr_dev.sh' if editor else 'launch_ub_mr.sh'
        result = subprocess.run(
            ['bash', str(self.root / 'launch' / script), *args],
            env={**self.env, **env}, capture_output=True, text=True,
            timeout=10, start_new_session=True,
        )
        events = [json.loads(line) for line in self.events.read_text().splitlines()] if self.events.exists() else []
        return result, events

    def assert_closed(self, events):
        close = events[-1]
        self.assertEqual(close['name'], 'ssh')
        self.assertEqual(close['args'][2:4], ['-O', 'exit'])
        self.assertFalse(Path(close['args'][1]).parent.exists())

    def test_player_tunnels_only_redis_and_cleans_up(self):
        result, events = self.launch('--iap')
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = next(event for event in events if event['name'] == 'gcloud')['args']
        self.assertEqual(arguments.count('-L'), 1)
        self.assertIn('127.0.0.1:16390:127.0.0.1:6390', arguments)
        self.assertIn('127.0.0.1:16390', result.stdout)
        self.assert_closed(events)

    def test_player_tunnel_overrides(self):
        result, events = self.launch(
            '--iap', UB_IAP_LOCAL_REDIS_PORT='16391', UB_IAP_REDIS_HOST='10.128.0.2',
            UB_IAP_REDIS_PORT='6380', UB_IAP_INSTANCE='other', UB_IAP_PROJECT='project',
            UB_IAP_ZONE='zone',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for arg in ('other', '--project=project', '--zone=zone', '127.0.0.1:16391:10.128.0.2:6380'):
            self.assertIn(arg, next(event for event in events if event['name'] == 'gcloud')['args'])
        self.assert_closed(events)

    def test_dry_run_and_normal_launch_never_open_tunnel(self):
        for args in (('--iap', '--dry-run'), (), ('--help',)):
            with self.subTest(args=args):
                result, events = self.launch(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(event['name'] in ('gcloud', 'ssh') for event in events))
                if '--dry-run' in args:
                    self.assertIn('Redis: 127.0.0.1:16390', result.stdout)

    def test_tunnel_failure_prevents_start_and_preserves_exit_code(self):
        result, events = self.launch('--iap', MOCK_STATUS_gcloud='17')
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertFalse(any(event['name'] == 'launch_autoware_carla.sh' or (event['name'] == 'docker' and event['args'][0] != 'ps') for event in events))
        self.assert_closed(events)

    def test_readiness_failure_prevents_clients(self):
        result, events = self.launch('--iap', MOCK_CHECK_STATUS='1')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(any(event['name'] == 'Unity' or (event['name'] == 'docker' and event['args'][0] != 'ps') for event in events))
        self.assert_closed(events)

    def test_autoware_failure_and_interrupt_both_close_tunnel(self):
        for env, code in [({'MOCK_STATUS_launch_autoware_carla.sh': '42'}, 42),
                          ({'MOCK_INTERRUPT': '1'}, 130)]:
            with self.subTest(env=env):
                result, events = self.launch('--auto', '--iap', **env)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assert_closed(events)

    def test_editor_tunnel_lifecycle_and_unity_arguments(self):
        for args, env, code in [
            (('--iap', '--', '-batchmode'), {}, 0),
            (('--iap',), {'MOCK_INTERRUPT': '1'}, 130),
            (('--iap',), {'MOCK_STATUS_Unity': '42'}, 42),
        ]:
            with self.subTest(args=args, env=env):
                result, events = self.launch(*args, editor=True, **env)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(events[0]['name'], 'gcloud')
                unity = next(event for event in events if event['name'] == 'Unity')
                self.assertEqual(unity['args'][:2], ['-projectPath', str(self.root / 'UB-MR')])
                self.assertNotIn('--iap', unity['args'])
                self.assertEqual(unity['args'][2:4], ['-logFile', str(self.root / 'Client-Logs/ub-mr/unity-editor.log')])
                self.assertEqual(unity['args'][4:], ['-batchmode'] if '--' in args else [])
                self.assert_closed(events)
        result, events = self.launch('--iap', '--dry-run', editor=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, [])
        self.assertIn('Redis: 127.0.0.1:16390', result.stdout)


if __name__ == '__main__':
    unittest.main()
