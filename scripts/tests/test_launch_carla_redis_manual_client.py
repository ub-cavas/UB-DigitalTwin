import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


LAUNCHER = Path(__file__).resolve().parents[1] / 'launch_carla_redis_manual_client.sh'
STANDALONE = Path(__file__).resolve().parents[2] / 'CARLA/start_manual_client.sh'
MOCK_COMMAND = r'''
import json
import os
from pathlib import Path
import signal
import sys

name = Path(sys.argv[0]).name
with open(os.environ['MOCK_EVENTS'], 'a') as stream:
    stream.write(json.dumps({
        'command': name,
        'args': sys.argv[1:],
        'env': {key: value for key, value in os.environ.items()
                if key.startswith(('UB_REDIS_', 'UB_MANUAL_', 'UB_RENDER_', 'UB_EXPERIMENT_', 'UB_CLIENT_'))},
    }) + '\n')
if name == 'docker' and os.environ.get('MOCK_INTERRUPT'):
    os.kill(os.getppid(), signal.SIGINT)
    sys.exit(130)
if name == 'ssh' and '-O' in sys.argv and sys.argv[sys.argv.index('-O') + 1] == 'exit':
    sys.exit(0)
sys.exit(int(os.environ.get('MOCK_' + name.upper() + '_STATUS', '0')))
'''


class ManualClientLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = self.root / 'events.jsonl'
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        for name in ('gcloud', 'ssh', 'docker', 'xhost'):
            command = bin_dir / name
            command.write_text(f'#!{sys.executable}\n' + MOCK_COMMAND)
            command.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('UB_', 'MOCK_', 'CARLA_', 'COMPOSE_'))}
        self.env.update(
            PATH=f'{bin_dir}:{os.environ["PATH"]}',
            MOCK_EVENTS=str(self.events),
            UB_EXPERIMENT_HOST_DIR=str(self.root / 'experiments'),
            UB_CLIENT_LOG_ROOT=str(self.root / 'Client-Logs'),
        )

    def launch(self, *args, standalone=False, **env):
        self.events.unlink(missing_ok=True)
        result = subprocess.run(
            ['bash', str(STANDALONE if standalone else LAUNCHER), *args], env={**self.env, **env},
            capture_output=True, text=True, timeout=10, start_new_session=True,
        )
        events = [json.loads(line) for line in self.events.read_text().splitlines()] if self.events.exists() else []
        return result, events

    def test_default_identity_pairs_controller_renderer_and_changes_per_launch(self):
        first, events = self.launch()
        self.assertEqual(first.returncode, 0, first.stderr)
        a = next(event['env'] for event in events if event['command'] == 'docker')
        second, events = self.launch()
        self.assertEqual(second.returncode, 0, second.stderr)
        b = next(event['env'] for event in events if event['command'] == 'docker')
        self.assertNotEqual(a['UB_MANUAL_CLIENT_ID'], b['UB_MANUAL_CLIENT_ID'])
        self.assertNotEqual(a['UB_MANUAL_ROLE_NAME'], b['UB_MANUAL_ROLE_NAME'])
        self.assertNotEqual(a['UB_MANUAL_ACTOR_REDIS_KEY'], b['UB_MANUAL_ACTOR_REDIS_KEY'])
        self.assertEqual(a['UB_MANUAL_ACTOR_REDIS_KEY'], a['UB_RENDER_MANUAL_ACTOR_REDIS_KEY'])
        self.assertEqual(a['UB_MANUAL_ROLE_NAME'], a['UB_RENDER_FOLLOW_ROLE_NAME'])

    def test_explicit_pairing_overrides_are_preserved(self):
        result, events = self.launch(UB_MANUAL_CLIENT_ID='chosen', UB_MANUAL_ROLE_NAME='manual_vehicle',
                                     UB_MANUAL_ACTOR_REDIS_KEY='legacy', UB_RENDER_MANUAL_ACTOR_REDIS_KEY='viewer')
        self.assertEqual(result.returncode, 0, result.stderr)
        env = next(event['env'] for event in events if event['command'] == 'docker')
        self.assertEqual(env['UB_MANUAL_CLIENT_ID'], 'chosen')
        self.assertEqual(env['UB_MANUAL_ROLE_NAME'], 'manual_vehicle')
        self.assertEqual(env['UB_MANUAL_ACTOR_REDIS_KEY'], 'legacy')
        self.assertEqual(env['UB_RENDER_MANUAL_ACTOR_REDIS_KEY'], 'viewer')

    def assert_tunnel_closed(self, events):
        checks = [event for event in events if event['command'] == 'ssh']
        self.assertEqual(checks[-1]['args'][2:4], ['-O', 'exit'])
        socket = Path(checks[-1]['args'][1])
        self.assertFalse(socket.parent.exists(), 'Temporary control directory was not removed')

    def test_iap_forwards_and_password_reach_client(self):
        password = "test password '$literal;$(do-not-run)"
        result, events = self.launch('--iap', password)
        self.assertEqual(result.returncode, 0, result.stderr)
        gcloud = events[0]
        self.assertEqual(gcloud['command'], 'gcloud')
        self.assertEqual(gcloud['args'][:3], ['compute', 'ssh', 'carla'])
        for argument in (
            '--project=buf-prj-digitaltwin-svxz', '--zone=us-central1-a',
            '--tunnel-through-iap', 'ExitOnForwardFailure=yes',
            '127.0.0.1:16390:127.0.0.1:6390',
            '127.0.0.1:12000:127.0.0.1:2000',
            '127.0.0.1:2001:127.0.0.1:2001',
        ):
            self.assertIn(argument, gcloud['args'])
        self.assertNotIn(password, gcloud['args'])
        self.assertNotIn(password, result.stdout + result.stderr)
        docker = next(event for event in events if event['command'] == 'docker')
        self.assertEqual(docker['args'], [
            'compose', 'up', '--build', 'carla', 'map-loader', 'traffic-renderer', 'manual-control',
        ])
        for key, value in {
            'UB_REDIS_PASSWORD': password, 'UB_REDIS_HOST': '127.0.0.1',
            'UB_REDIS_PORT': '16390', 'UB_MANUAL_CARLA_HOST': '127.0.0.1',
            'UB_MANUAL_CARLA_PORT': '12000', 'UB_RENDER_CARLA_PORT': '2100',
            'UB_EXPERIMENT_NETWORK_HOST': 'tunnel.cloudproxy.app',
        }.items():
            self.assertEqual(docker['env'][key], value)
        self.assertEqual(events[1]['args'][2:4], ['-O', 'check'])
        self.assert_tunnel_closed(events)

    def test_logging_options_override_environment_for_both_launchers(self):
        for standalone in (False, True):
            with self.subTest(standalone=standalone):
                output = self.root / 'logs with spaces'
                result, events = self.launch(
                    '--log-network', '--log-dir', str(output), '--network-interface', 'eth0',
                    standalone=standalone, UB_EXPERIMENT_ENABLED='0',
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                docker = next(event for event in events if event['command'] == 'docker')
                self.assertEqual(docker['env']['UB_EXPERIMENT_ENABLED'], '1')
                self.assertEqual(docker['env']['UB_EXPERIMENT_HOST_DIR'], str(output))
                self.assertEqual(docker['env']['UB_EXPERIMENT_INTERFACE'], 'eth0')
                result, events = self.launch('--no-log-network', standalone=standalone, UB_EXPERIMENT_ENABLED='1')
                self.assertEqual(result.returncode, 0, result.stderr)
                docker = next(event for event in events if event['command'] == 'docker')
                self.assertEqual(docker['env']['UB_EXPERIMENT_ENABLED'], '0')

    def test_default_client_output_is_centralized(self):
        for standalone in (False, True):
            with self.subTest(standalone=standalone):
                result, events = self.launch(standalone=standalone, UB_EXPERIMENT_HOST_DIR='')
                self.assertEqual(result.returncode, 0, result.stderr)
                docker = next(event for event in events if event['command'] == 'docker')
                client = self.root / 'Client-Logs/manual-control'
                self.assertEqual(docker['env']['UB_CLIENT_LOG_HOST_DIR'], str(client))
                self.assertEqual(docker['env']['UB_EXPERIMENT_HOST_DIR'], str(client / 'experiments'))
                self.assertTrue((client / 'manual-control.log').is_file())

    def test_logging_options_combine_with_iap_and_preserve_network_host_override(self):
        result, events = self.launch(
            '--log-network', '--iap', 'test', '--network-interface', 'none',
            UB_EXPERIMENT_NETWORK_HOST='custom-iap-gateway',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        docker = next(event for event in events if event['command'] == 'docker')
        self.assertEqual(docker['env']['UB_EXPERIMENT_ENABLED'], '1')
        self.assertEqual(docker['env']['UB_EXPERIMENT_NETWORK_HOST'], 'custom-iap-gateway')
        self.assertEqual(docker['env']['UB_EXPERIMENT_INTERFACE'], 'none')
        self.assert_tunnel_closed(events)

    def test_iap_overrides_and_loopback_client_hosts(self):
        result, events = self.launch(
            '--iap', 'test', UB_IAP_INSTANCE='other-vm', UB_IAP_PROJECT='other-project',
            UB_IAP_ZONE='other-zone', UB_IAP_REDIS_HOST='10.128.0.2',
            UB_IAP_REDIS_PORT='6380', UB_IAP_CARLA_HOST='10.128.0.3',
            UB_IAP_CARLA_PORT='3000', UB_IAP_CARLA_STREAMING_PORT='3001',
            UB_REDIS_PORT='16391', UB_MANUAL_CARLA_PORT='12001',
            UB_REDIS_HOST='stale-host', UB_MANUAL_CARLA_HOST='stale-host',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for argument in (
            'other-vm', '--project=other-project', '--zone=other-zone',
            '127.0.0.1:16391:10.128.0.2:6380', '127.0.0.1:12001:10.128.0.3:3000',
            '127.0.0.1:3001:10.128.0.3:3001',
        ):
            self.assertIn(argument, events[0]['args'])
        docker = next(event for event in events if event['command'] == 'docker')
        self.assertEqual(docker['env']['UB_REDIS_HOST'], '127.0.0.1')
        self.assertEqual(docker['env']['UB_MANUAL_CARLA_HOST'], '127.0.0.1')
        self.assert_tunnel_closed(events)

    def test_failure_stops_startup_and_cleans_tunnel(self):
        for command, status in [('gcloud', 17), ('ssh', 1), ('docker', 42)]:
            with self.subTest(command=command):
                result, events = self.launch('--iap', 'test', **{f'MOCK_{command.upper()}_STATUS': str(status)})
                self.assertEqual(result.returncode, status, result.stderr)
                if command != 'docker':
                    self.assertFalse(any(event['command'] == 'docker' for event in events))
                self.assert_tunnel_closed(events)

    def test_interrupt_closes_tunnel(self):
        result, events = self.launch('--iap', 'test', MOCK_INTERRUPT='1')
        self.assertEqual(result.returncode, 130, result.stderr)
        self.assert_tunnel_closed(events)

    def test_direct_mode_is_preserved(self):
        for arguments, env in [
            (('192.168.1.50',), {}),
            ((), {'UB_REDIS_HOST': '192.168.1.50', 'UB_MANUAL_CARLA_HOST': '192.168.1.50'}),
        ]:
            with self.subTest(arguments=arguments):
                result, events = self.launch(*arguments, UB_REDIS_PASSWORD='existing-password', **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(event['command'] in ('gcloud', 'ssh') for event in events))
                docker = next(event for event in events if event['command'] == 'docker')
                self.assertEqual(docker['env']['UB_REDIS_HOST'], '192.168.1.50')
                self.assertEqual(docker['env']['UB_MANUAL_CARLA_HOST'], '192.168.1.50')
                self.assertEqual(docker['env']['UB_MANUAL_CARLA_PORT'], '2000')
                self.assertEqual(docker['env']['UB_REDIS_PASSWORD'], 'existing-password')

    def test_invalid_arguments_do_not_start_services(self):
        for arguments in [('--iap',), ('--iap', ''), ('--iap', 'test', 'extra'), ('--unknown',),
                          ('--log-dir',), ('--network-interface',), ('--log-dir', '--iap')]:
            with self.subTest(arguments=arguments):
                result, events = self.launch(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(events, [])


if __name__ == '__main__':
    unittest.main()
