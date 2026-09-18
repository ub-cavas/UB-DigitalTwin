"""Profile selection and environment contracts; no simulator processes start."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('map_config', ROOT/'launch/autoware_map_config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class MapConfigurationTests(unittest.TestCase):
    def profile(self, name):
        return config.read_profile(config.find_profile(name))

    def test_default_ub_preserves_original_wrapper_and_version_selection(self):
        environment = config.configure_environment(self.profile('ub'), {'BUILD_FOLDER': 'v1.0.0'})
        self.assertEqual(environment['CARLA_MAP'], 'UBAutonomousProvingGrounds')
        self.assertEqual(environment['AUTOWARE_CARLA_SPAWN_POINT'], '-214.130,3.295,0.030,0,0,0.722')
        self.assertEqual(environment['BUILD_FOLDER'], 'v1.0.0')
        self.assertNotIn('AUTOWARE_MAP_PATH', environment)
        self.assertNotIn('AUTOWARE_HOST_MAP_DIR', environment)
        self.assertEqual(environment['CARLA_ARGS'], '-prefernvidia -quality-level=Epic -nosound')
        for key in ('UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY', 'UB_AUTOWARE_EGO_ONLY_PERCEPTION', 'UB_AUTOWARE_CARLA_PLANNING_PRESET'):
            self.assertEqual(environment[key], '1')
        self.assertEqual(environment['AUTOWARE_PLANNING_MODULE_PRESET'], 'ub_carla')

    def test_town_selects_map_bundle_spawn_and_generic_planning(self):
        environment = config.configure_environment(self.profile('Town10HD_Opt'), {})
        self.assertEqual(environment['CARLA_MAP'], 'Town10HD_Opt')
        self.assertEqual(environment['AUTOWARE_MAP_PATH'], '/host_data/maps/town10hd/v1.1.0')
        self.assertTrue(environment['AUTOWARE_CARLA_SPAWN_POINT'].startswith('-64.644844,24.471010,'))
        self.assertEqual(environment['UB_AUTOWARE_CARLA_PLANNING_PRESET'], '0')
        self.assertEqual(environment['AUTOWARE_PLANNING_MODULE_PRESET'], 'default')
        self.assertEqual(config.find_profile('Town10HD'), config.find_profile('town10hd'))

    def test_environment_overrides_preserved_and_map_paths_paired(self):
        original = {'AUTOWARE_HOST_MAP_DIR': 'Autoware/host_data/my new run',
                    'AUTOWARE_CARLA_SPAWN_POINT': 'None', 'CARLA_ARGS': '-quality-level=Low',
                    'UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY': '0', 'AUTOWARE_PLANNING_MODULE_PRESET': 'custom'}
        environment = config.configure_environment(self.profile('town10hd'), original)
        self.assertEqual(environment['AUTOWARE_HOST_MAP_DIR'], str(ROOT/'Autoware/host_data/my new run'))
        self.assertNotIn('AUTOWARE_MAP_PATH', environment)
        for key in original.keys()-{'AUTOWARE_HOST_MAP_DIR'}:
            self.assertEqual(environment[key], original[key])
        self.assertEqual(original['AUTOWARE_HOST_MAP_DIR'], 'Autoware/host_data/my new run')

    def test_container_only_override_drops_profile_host_path(self):
        profile = self.profile('town10hd')
        profile['environment']['AUTOWARE_HOST_MAP_DIR'] = 'Autoware/host_data/old'
        environment = config.configure_environment(profile, {'AUTOWARE_MAP_PATH': '/host_data/new'})
        self.assertEqual(environment['AUTOWARE_MAP_PATH'], '/host_data/new')
        self.assertNotIn('AUTOWARE_HOST_MAP_DIR', environment)

    def test_custom_profile_uses_data_not_shell_code(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'custom.json'
            literal = '/host_data/map with spaces;$(touch NEVER_EXECUTE)'
            path.write_text(json.dumps({'version': 1, 'environment': {
                'CARLA_MAP': 'CustomTown', 'AUTOWARE_MAP_PATH': literal,
                'AUTOWARE_CARLA_SPAWN_POINT': 'None'}}))
            environment = config.configure_environment(config.read_profile(path), {})
            self.assertEqual(environment['AUTOWARE_MAP_PATH'], literal)
            self.assertEqual(environment['CARLA_MAP'], 'CustomTown')
            self.assertEqual(environment['AUTOWARE_PLANNING_MODULE_PRESET'], 'default')

    def test_invalid_profiles_and_spawn_fail_before_launch(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'bad.json'
            for text in ('{"version":1,"version":1}', '{"version":true}', '{"version":2}',
                         '{"version":1,"environment":{"LD_PRELOAD":"bad.so"}}'):
                path.write_text(text)
                with self.assertRaises(ValueError): config.read_profile(path)
        with self.assertRaises(ValueError): config.find_profile('../unknown')
        for spawn in ('1,2,3', '1,2,3,0,0,nan', '1,2,3,0,0,inf'):
            with self.assertRaises(ValueError):
                config.configure_environment(self.profile('ub'), {'AUTOWARE_CARLA_SPAWN_POINT': spawn})
        with self.assertRaises(ValueError):
            config.configure_environment(self.profile('ub'), {'CARLA_MAP': 'UnrelatedTown'})
        with self.assertRaises(ValueError):
            config.configure_environment(self.profile('town10hd'), {'CARLA_MAP_PATH': '/Game/Carla/Maps/UBAutonomousProvingGrounds'})

    def test_main_selects_default_and_passes_dry_run_to_existing_launcher(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(config.os, 'execve') as execute:
            config.main(['--dry-run'])
        command, args, environment = execute.call_args.args
        self.assertEqual(command, str(ROOT/'CARLA/start_autoware_carla.sh'))
        self.assertEqual(args, [command, '--dry-run'])
        self.assertEqual(environment['CARLA_MAP'], 'UBAutonomousProvingGrounds')

    def test_profile_environment_default_and_cli_precedence(self):
        with patch.dict(os.environ, {'AUTOWARE_MAP_PROFILE': 'town10hd'}, clear=True), patch.object(config.os, 'execve') as execute:
            config.main([])
            self.assertEqual(execute.call_args.args[2]['CARLA_MAP'], 'Town10HD_Opt')
            config.main(['--map', 'ub'])
            self.assertEqual(execute.call_args.args[2]['CARLA_MAP'], 'UBAutonomousProvingGrounds')

    def test_wrapper_help_list_and_unknown_map_without_docker(self):
        wrapper = ROOT/'launch/launch_autoware_carla.sh'
        for args, code, expected in [(['--help'], 0, '--map-config'),
                                     (['--list-maps'], 0, 'town10hd:'),
                                     (['--map', 'does-not-exist', '--dry-run'], 2, 'Unknown or ambiguous'),
                                     (['--map'], 2, 'expected one argument')]:
            result = subprocess.run(['bash', str(wrapper), *args], text=True, capture_output=True)
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertIn(expected, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
