"""Execute direct-Compose identity resolution without CARLA, Docker or pip."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ENTRYPOINT = Path(__file__).resolve().parents[2] / 'CARLA/UB-API/redis-networking/sidecar-entrypoint.sh'


class SidecarIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.machine = self.root / 'machine-id'
        self.machine.write_text('host-a\n')
        target = self.root / 'wheel'
        (target / 'carla').mkdir(parents=True)
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        fake_python = bin_dir / 'python3'
        fake_python.write_text('#!/usr/bin/python3\nimport json,os\nprint(json.dumps({k:v for k,v in os.environ.items() if k.startswith(("UB_MANUAL_", "UB_RENDER_"))}))\n')
        fake_python.chmod(0o755)
        fake_find = bin_dir / 'find'
        fake_find.write_text('#!/bin/sh\necho /fake/carla-cp310-test.whl\n')
        fake_find.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('UB_', 'CARLA_PYTHON_'))}
        self.env.update(PATH=f'{bin_dir}:{os.environ["PATH"]}', CARLA_PYTHON_TARGET=str(target),
                        UB_MANUAL_HOST_ID_FILE=str(self.machine), UB_MANUAL_INSTANCE_NAME='project-a')

    def run_role(self, role, **env):
        result = subprocess.run(['bash', str(ENTRYPOINT)], env={**self.env, 'UB_REDIS_ROLE': role, **env},
                                text=True, capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_pair(self, env):
        controller = self.run_role('manual-control', **env)
        viewer = self.run_role('traffic-renderer', **env)
        self.assertEqual(controller['UB_MANUAL_CLIENT_ID'], viewer['UB_MANUAL_CLIENT_ID'])
        self.assertEqual(controller['UB_MANUAL_ROLE_NAME'], viewer['UB_RENDER_FOLLOW_ROLE_NAME'])
        self.assertEqual(controller['UB_MANUAL_ACTOR_REDIS_KEY'], viewer['UB_RENDER_MANUAL_ACTOR_REDIS_KEY'])
        return controller, viewer

    def test_default_and_blank_compose_environment_pair_with_host_and_project(self):
        first, _ = self.assert_pair({})
        blank, _ = self.assert_pair(dict(UB_MANUAL_CLIENT_ID='', UB_MANUAL_ROLE_NAME='', UB_MANUAL_ACTOR_REDIS_KEY='',
                                         UB_RENDER_FOLLOW_ROLE_NAME='', UB_RENDER_MANUAL_ACTOR_REDIS_KEY=''))
        self.assertEqual(first['UB_MANUAL_CLIENT_ID'], blank['UB_MANUAL_CLIENT_ID'])
        self.assertIn('project-a', first['UB_MANUAL_CLIENT_ID'])
        self.assertIn('host-a', first['UB_MANUAL_CLIENT_ID'])
        other_project, _ = self.assert_pair({'UB_MANUAL_INSTANCE_NAME': 'project-b'})
        self.assertNotEqual(first['UB_MANUAL_CLIENT_ID'], other_project['UB_MANUAL_CLIENT_ID'])
        self.machine.write_text('host-b\n')
        other_host, _ = self.assert_pair({})
        self.assertNotEqual(first['UB_MANUAL_CLIENT_ID'], other_host['UB_MANUAL_CLIENT_ID'])

    def test_client_id_only_pairs_both_services(self):
        controller, _ = self.assert_pair({'UB_MANUAL_CLIENT_ID': 'chosen'})
        self.assertEqual(controller['UB_MANUAL_ROLE_NAME'], 'manual_vehicle:chosen')
        self.assertEqual(controller['UB_MANUAL_ACTOR_REDIS_KEY'], 'carla:manual_control:actor:chosen')

    def test_explicit_manual_and_viewer_overrides_survive(self):
        env = dict(UB_MANUAL_CLIENT_ID='chosen', UB_MANUAL_ROLE_NAME='legacy', UB_MANUAL_ACTOR_REDIS_KEY='shared',
                   UB_RENDER_FOLLOW_ROLE_NAME='viewer-role', UB_RENDER_MANUAL_ACTOR_REDIS_KEY='viewer-key')
        controller = self.run_role('manual-control', **env)
        viewer = self.run_role('traffic-renderer', **env)
        self.assertEqual(controller['UB_MANUAL_ROLE_NAME'], 'legacy')
        self.assertEqual(controller['UB_MANUAL_ACTOR_REDIS_KEY'], 'shared')
        self.assertEqual(viewer['UB_RENDER_FOLLOW_ROLE_NAME'], 'viewer-role')
        self.assertEqual(viewer['UB_RENDER_MANUAL_ACTOR_REDIS_KEY'], 'viewer-key')

    def test_none_role_does_not_require_manual_host_identity(self):
        self.machine.unlink()
        result = subprocess.run(['bash', str(ENTRYPOINT)], env={**self.env, 'UB_REDIS_ROLE': 'none'}, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('no Redis networking client', result.stdout)

    @unittest.skipUnless(shutil.which('docker'), 'Docker Compose is unavailable')
    def test_resolved_compose_service_environments_pair_defaults_and_id_only(self):
        compose = ENTRYPOINT.parents[2] / 'docker-compose.yml'
        for client_id in ('', 'chosen'):
            result = subprocess.run(['docker', 'compose', '-f', str(compose), '--profile', '*', 'config', '--format', 'json'],
                                    env={**self.env, 'COMPOSE_PROJECT_NAME': 'compose-project', 'UB_MANUAL_CLIENT_ID': client_id},
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, 'Compose configuration failed')
            services = json.loads(result.stdout)['services']
            resolved = {}
            for service in ('manual-control', 'traffic-renderer'):
                env = {k: str(v or '') for k, v in services[service]['environment'].items()
                       if k.startswith(('UB_MANUAL_', 'UB_RENDER_'))}
                resolved[service] = self.run_role(service, **env)
                targets = [volume.get('target') for volume in services[service]['volumes']]
                self.assertIn('/run/ub-host-machine-id', targets)
            controller, viewer = resolved['manual-control'], resolved['traffic-renderer']
            self.assertEqual(controller['UB_MANUAL_CLIENT_ID'], viewer['UB_MANUAL_CLIENT_ID'])
            self.assertEqual(controller['UB_MANUAL_ROLE_NAME'], viewer['UB_RENDER_FOLLOW_ROLE_NAME'])
            self.assertEqual(controller['UB_MANUAL_ACTOR_REDIS_KEY'], viewer['UB_RENDER_MANUAL_ACTOR_REDIS_KEY'])
