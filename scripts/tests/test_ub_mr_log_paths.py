"""Check host bind mounts without starting Docker or Unity."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class UbMrLogPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ('UB-MR/Builds/test', 'CARLA', 'bin'):
            (self.root / directory).mkdir(parents=True)
        self.script = self.root / 'UB-MR/run_ub_mr.sh'
        shutil.copyfile(ROOT / 'UB-MR/run_ub_mr.sh', self.script)
        self.args_file = self.root / 'docker-args.json'
        docker = self.root / 'bin/docker'
        docker.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
if sys.argv[1] == 'run':
    Path(os.environ['MOCK_DOCKER_ARGS']).write_text(json.dumps(sys.argv[1:]))
''')
        docker.chmod(0o755)
        xhost = self.root / 'bin/xhost'
        xhost.write_text('#!/bin/sh\nexit 0\n')
        xhost.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('UB_', 'MOCK_'))}
        self.env.update(PATH=f'{self.root / "bin"}:{os.environ["PATH"]}', DISPLAY=':1',
                        MOCK_DOCKER_ARGS=str(self.args_file))

    def launch(self, **env):
        result = subprocess.run(['bash', str(self.script), 'test'], env={**self.env, **env},
                                cwd='/tmp', capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(self.args_file.read_text())

    def test_default_logs_bind_to_repository_root(self):
        arguments = self.launch()
        self.assertIn(str(self.root / 'Client-Logs/ub-mr') + ':/app/Logs', arguments)
        self.assertTrue((self.root / 'Client-Logs/ub-mr/experiments').is_dir())

    def test_root_override_and_existing_log_override(self):
        custom = self.root / 'custom log root'
        arguments = self.launch(UB_CLIENT_LOG_ROOT=str(custom))
        self.assertIn(str(custom / 'ub-mr') + ':/app/Logs', arguments)
        previous_override = self.root / 'specific client'
        experiments = self.root / 'specific experiments'
        arguments = self.launch(UB_CLIENT_LOG_ROOT=str(custom), UB_MR_LOG_DIR=str(previous_override),
                                UB_EXPERIMENT_HOST_DIR=str(experiments))
        self.assertIn(str(previous_override) + ':/app/Logs', arguments)
        self.assertIn(str(experiments) + ':/app/Logs/experiments', arguments)


if __name__ == '__main__':
    unittest.main()
