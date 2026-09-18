# CARLA / Autoware map configurations

Run from the repository root:

```bash
# Existing behavior: UB is still the default.
./launch/launch_autoware_carla.sh

# Preview or launch the full generated Town10HD map.
./launch/launch_autoware_carla.sh --map town10hd --dry-run
./launch/launch_autoware_carla.sh --map town10hd

# List profiles or select your own JSON configuration.
./launch/launch_autoware_carla.sh --list-maps
./launch/launch_autoware_carla.sh --map-config /path/to/my-map.json --dry-run
```

| Profile | CARLA map | Autoware map | Planning |
| --- | --- | --- | --- |
| `ub` (default) | `UBAutonomousProvingGrounds` | Existing versioned UB map selected by `BUILD_FOLDER` | Existing `ub_carla` preset |
| `town10hd` | `Town10HD_Opt` | `/host_data/maps/town10hd/v1.1.0` | Standard `default` preset |

Names are case-insensitive. `UBAutonomousProvingGrounds`, `Town10HD`, and
`Town10HD_Opt` are also accepted as profile aliases. The Town10HD profile uses
the generated full-map bundle and the native spawn recorded during mapping.
Its unresolved traffic controls and missing speeds still need review; selecting
a profile does not certify autonomous driving readiness.

The wrapper still delegates startup, Docker, DDS setup, and cleanup to
`CARLA/start_autoware_carla.sh`. It starts the normal Compose CARLA server on
port **2000**; it does not reuse the standalone mapping server on port 2100.
`--dry-run` runs the existing preflight and previews commands without starting
services. `--help` and `--list-maps` do not require Docker or installed maps.

## Overrides

Choose the default profile for a shell session with
`AUTOWARE_MAP_PROFILE=town10hd`. An explicit `--map` or `--map-config` takes
precedence over that selector.

Existing exported launcher variables override values in a profile:

```bash
BUILD_FOLDER=v1.0.0 ./launch/launch_autoware_carla.sh --map ub --dry-run
CARLA_ARGS="-prefernvidia -quality-level=Low -nosound" \
  ./launch/launch_autoware_carla.sh --map town10hd
AUTOWARE_MAP_PATH=/host_data/map_reconstruction_runs/my-new-town10-build \
  ./launch/launch_autoware_carla.sh --map town10hd --dry-run
```

Overriding either `AUTOWARE_MAP_PATH` or `AUTOWARE_HOST_MAP_DIR` discards both
profile path defaults so the shared helper derives the matching path. Host
paths may be absolute or relative to the repository root. Container paths must
be absolute. For directories outside the standard `Autoware/host_data` mount,
supply both host and container paths and configure that Docker mount yourself.
Changing `CARLA_MAP` through an environment override also requires explicit map
path and spawn overrides, preventing an unrelated map from using UB's default
files or spawn. Prefer a profile when changing environments.

Common wrapper defaults remain Epic rendering, the top-LiDAR relay, and
`UB_AUTOWARE_EGO_ONLY_PERCEPTION=1`. Profiles can select planning presets;
exported environment overrides remain available for perception and other
existing launcher options. The UB profile retains the original wrapper values.

## Add a map

Create a version 1 JSON file. Profiles are data, not executable shell scripts:

```json
{
  "version": 1,
  "description": "My custom CARLA environment",
  "environment": {
    "BUILD_FOLDER": "v1.1.0",
    "CARLA_MAP": "MyCustomTown",
    "AUTOWARE_MAP_PATH": "/host_data/maps/my_custom_town",
    "AUTOWARE_CARLA_SPAWN_POINT": "10,20,0.6,0,0,90",
    "UB_AUTOWARE_CARLA_PLANNING_PRESET": "0",
    "AUTOWARE_PLANNING_MODULE_PRESET": "default"
  }
}
```

Use `--map-config FILE`, or put the file in `launch/maps/my_custom_town.json`
and select `--map my_custom_town`. An optional `aliases` list adds alternate
names. All `environment` values must be strings. `CARLA_MAP` and
`AUTOWARE_CARLA_SPAWN_POINT` are required; non-UB profiles also require a map
path. Unknown fields and duplicate JSON keys are rejected.

Spawn order is **CARLA x,y,z,roll,pitch,yaw**, in meters and degrees; CARLA Y is
the opposite sign from Autoware Local Y. Use `"None"` for the bridge's random
spawn behavior. Explicit poses must contain six finite numbers. The CARLA map
name must match an advertised map from the selected build.

Supported profile variables are:

- `BUILD_FOLDER`, `CARLA_MAP`, `CARLA_MAP_PATH`, `CARLA_ARGS`
- `AUTOWARE_HOST_MAP_DIR`, `AUTOWARE_MAP_PATH`, `AUTOWARE_CARLA_SPAWN_POINT`
- `AUTOWARE_CARLA_HOST`, `AUTOWARE_VEHICLE_MODEL`, `AUTOWARE_SENSOR_MODEL`, `AUTOWARE_RVIZ`
- `AUTOWARE_PLANNING_MODULE_PRESET`, `UB_AUTOWARE_CARLA_PLANNING_PRESET`
- `UB_AUTOWARE_CARLA_TOP_LIDAR_ONLY`, `UB_AUTOWARE_EGO_ONLY_PERCEPTION`

Map preflight accepts either a nonempty `pointcloud_map.pcd` file or a directory
with nonempty `*.pcd` tiles. Tiled maps additionally require a nonempty
`pointcloud_map_metadata.yaml`. Both forms require nonempty `lanelet2_map.osm`
and `map_projector_info.yaml`. Preflight checks files; use the mapping pipeline's
validator for geometry, coverage, metadata semantics, and regulatory readiness.

## Verification

```bash
python3 -m unittest discover -s launch/tests -v
bash CARLA/tests/test_autoware_map_paths.sh
./launch/launch_autoware_carla.sh --dry-run
./launch/launch_autoware_carla.sh --map town10hd --dry-run
```
