#!/usr/bin/env python3
"""Select a CARLA/Autoware map profile, then exec the existing lifecycle launcher.

Profiles are JSON data, never shell code. Exported environment overrides win.
The UB profile deliberately leaves map paths to autoware_map_paths.sh so the
existing BUILD_FOLDER and legacy v1.0.0 fallback semantics stay intact.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = Path(__file__).resolve().parent / 'maps'
COMMON_DEFAULTS = {
    'CARLA_ARGS': '-prefernvidia -quality-level=Epic -nosound',
    'UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY': '1',
    'UB_AUTOWARE_EGO_ONLY_PERCEPTION': '1',
    'UB_AUTOWARE_CARLA_PLANNING_PRESET': '0',
    'AUTOWARE_PLANNING_MODULE_PRESET': 'default',
}
MAP_PATH_KEYS = ('AUTOWARE_HOST_MAP_DIR', 'AUTOWARE_MAP_PATH')
ALLOWED_KEYS = set(COMMON_DEFAULTS) | {
    'BUILD_FOLDER', 'CARLA_MAP', 'CARLA_MAP_PATH', *MAP_PATH_KEYS,
    'AUTOWARE_CARLA_HOST', 'AUTOWARE_CARLA_SPAWN_POINT',
    'AUTOWARE_VEHICLE_MODEL', 'AUTOWARE_SENSOR_MODEL', 'AUTOWARE_RVIZ',
}


def read_profile(path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate configuration key: {key}')
            result[key] = value
        return result

    data = json.loads(path.read_text(), object_pairs_hook=unique_keys)
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError(f'{path}: expected a JSON object with version: 1')
    if set(data) - {'version', 'description', 'aliases', 'environment'}:
        raise ValueError(f'{path}: unknown profile fields')
    values = data.get('environment')
    if not isinstance(values, dict) or set(values) - ALLOWED_KEYS:
        raise ValueError(f'{path}: environment must contain supported launcher variables only')
    if any(not isinstance(v, str) or any(c in v for c in '\0\n\r') for v in values.values()):
        raise ValueError(f'{path}: environment values must be single-line strings')
    if not values.get('CARLA_MAP') or not values.get('AUTOWARE_CARLA_SPAWN_POINT'):
        raise ValueError(f'{path}: CARLA_MAP and AUTOWARE_CARLA_SPAWN_POINT are required')
    if values['CARLA_MAP'] != 'UBAutonomousProvingGrounds' and not any(values.get(k) for k in MAP_PATH_KEYS):
        raise ValueError(f'{path}: non-UB profiles require an Autoware map path')
    aliases = data.get('aliases', [])
    if not isinstance(aliases, list) or any(not isinstance(a, str) or not a for a in aliases):
        raise ValueError(f'{path}: aliases must be a list of nonempty strings')
    if not isinstance(data.get('description', ''), str):
        raise ValueError(f'{path}: description must be a string')
    return data


def find_profile(name):
    matches = []
    for path in sorted(PROFILE_DIR.glob('*.json')):
        data = read_profile(path)
        names = [path.stem, *data.get('aliases', [])]
        if name.casefold() in {value.casefold() for value in names}:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError(f'Unknown or ambiguous map profile {name!r}; use --list-maps or --map-config FILE')
    return matches[0]


def configure_environment(profile, inherited, repo_root=REPO_ROOT):
    environment = dict(inherited)
    defaults = {**COMMON_DEFAULTS, **profile['environment']}
    # Treat the host/container map paths as a pair. An override of either side
    # must let the existing path helper derive the other side, not retain a
    # conflicting path from the profile.
    if any(environment.get(key) for key in MAP_PATH_KEYS):
        for key in MAP_PATH_KEYS:
            defaults.pop(key, None)
    for key, value in defaults.items():
        if not environment.get(key):
            environment[key] = value
    if environment['CARLA_MAP'] != profile['environment']['CARLA_MAP']:
        if not any(inherited.get(k) for k in MAP_PATH_KEYS) or not inherited.get('AUTOWARE_CARLA_SPAWN_POINT'):
            raise ValueError('Changing CARLA_MAP also requires explicit Autoware map path and spawn overrides; select --map or --map-config instead')
        if not inherited.get('CARLA_MAP_PATH'):
            environment.pop('CARLA_MAP_PATH', None)
    if environment.get('CARLA_MAP_PATH') and environment['CARLA_MAP_PATH'].rsplit('/', 1)[-1] != environment['CARLA_MAP']:
        raise ValueError('CARLA_MAP_PATH and CARLA_MAP select different maps')
    if environment.get('AUTOWARE_HOST_MAP_DIR'):
        path = Path(environment['AUTOWARE_HOST_MAP_DIR']).expanduser()
        environment['AUTOWARE_HOST_MAP_DIR'] = str((repo_root / path).resolve())
    if environment.get('AUTOWARE_MAP_PATH') and not environment['AUTOWARE_MAP_PATH'].startswith('/'):
        raise ValueError('AUTOWARE_MAP_PATH must be an absolute path inside the container')
    spawn = environment['AUTOWARE_CARLA_SPAWN_POINT']
    if spawn.lower() == 'none':
        environment['AUTOWARE_CARLA_SPAWN_POINT'] = 'None'
    else:
        try:
            values = [float(x) for x in spawn.split(',')]
        except ValueError:
            values = []
        if len(values) != 6 or not all(math.isfinite(x) for x in values):
            raise ValueError('AUTOWARE_CARLA_SPAWN_POINT must be None or six finite x,y,z,roll,pitch,yaw values')
    return environment


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='launch_autoware_carla.sh',
        description='Launch CARLA and Autoware with a matching map profile. UB is the default.',
        epilog='Exported launcher variables override profile values. See launch/maps/README.md for custom configurations.')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--map', metavar='PROFILE', help='Named profile: ub, town10hd, or an alias')
    selection.add_argument('--map-config', type=Path, metavar='FILE', help='Version 1 JSON profile file')
    parser.add_argument('--list-maps', action='store_true', help='List bundled map profiles and exit')
    parser.add_argument('--dry-run', action='store_true', help='Check prerequisites and preview commands without launching')
    args = parser.parse_args(argv)
    try:
        if args.list_maps:
            for path in sorted(PROFILE_DIR.glob('*.json')):
                data = read_profile(path)
                print(f'{path.stem}: {data.get("description", data["environment"]["CARLA_MAP"])}')
            return 0
        path = args.map_config or find_profile(args.map or os.environ.get('AUTOWARE_MAP_PROFILE') or 'ub')
        environment = configure_environment(read_profile(path), os.environ)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f'Map configuration: {path.stem} ({environment["CARLA_MAP"]})', flush=True)
    launcher = str(REPO_ROOT / 'CARLA/start_autoware_carla.sh')
    os.execve(launcher, [launcher] + (['--dry-run'] if args.dry_run else []), environment)


if __name__ == '__main__':
    sys.exit(main())
