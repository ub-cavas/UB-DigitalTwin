# CARLA → Autoware mapping

Generate an Autoware Lanelet map from OpenDRIVE and capture an aligned static
point cloud from CARLA. The tools target **CARLA 0.9.16 with matching Python
bindings** and the installed Autoware environment. They use `projector_type:
Local`, preserving the source origin: **CARLA `(x, y, z)` becomes Local
`(x, -y, z)`**. OpenDRIVE coordinates are already in the Local frame.

This is a conversion and review pipeline, not a guarantee that an arbitrary
scene is ready for autonomous driving. Automatic Lanelet generation requires
usable OpenDRIVE roads. Mesh/PCD road inference, GNSS projection, UE5, and other
CARLA versions are outside its scope. Installed maps and backups are never
replaced by generation.

## Setup

Run examples from the repository root. Use Python 3.10, not the default Conda
Python on this machine:

```bash
source /opt/ros/humble/setup.bash
/usr/bin/python3 -m venv --system-site-packages Map-Reconstruction/.venv
source Map-Reconstruction/.venv/bin/activate
python -m pip install -r Map-Reconstruction/requirements.txt
python -m pip install CARLA/Builds/v1.1.0/PythonAPI/carla/dist/carla-0.9.16-cp310-cp310-linux_x86_64.whl
python -c 'import carla, lanelet2, numpy, scipy, shapely, yaml, pyproj, matplotlib'
```

OpenDRIVE generation itself does not import CARLA. Native routing validation
needs Lanelet2; geometry validation needs Shapely. Missing dependencies are
reported as **untested**, never passed.

## Complete build example

Start a **dedicated** server in another terminal:

```bash
CARLA/Builds/v1.1.0/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping \
  CarlaUE4 -carla-rpc-port=2100 -RenderOffScreen -quality-level=Low -nosound -unattended
```

Do not run driving clients or another synchronous ticker on this server. The
collector refuses existing vehicles, walkers, and sensors, verifies versions,
and restores its world settings and spectator pose when it finishes. It owns
and destroys only the sensor it creates. It does not stop the server process.

Preview the full network offline, then create a separate live build:

```bash
XODR=CARLA/Builds/v1.1.0/CarlaUE4/Content/Carla/Maps/OpenDrive/Town10HD_Opt.xodr
PLAN=Map-Reconstruction/output/town10-plan
RUN=Map-Reconstruction/output/town10-build

python Map-Reconstruction/map.py build --plan-only \
  --opendrive "$XODR" --output-dir "$PLAN"

python Map-Reconstruction/map.py build \
  --host 127.0.0.1 --port 2100 --map Town10HD_Opt \
  --opendrive "$XODR" --output-dir "$RUN" \
  --config Map-Reconstruction/examples/config.yaml

python Map-Reconstruction/map.py validate --output-dir "$RUN"
```

Use fresh directories. `--plan-only` performs generation and planning without
capture; its directory is not a capture checkpoint. `--map` explicitly loads
an advertised server map. **Omitting `--map` retains the currently loaded map**.
A supplied `--opendrive` must match the server's canonical OpenDRIVE fingerprint.
Without it, live commands snapshot the loaded map.

For UB, use `--map UBAutonomousProvingGrounds` and its `.xodr`. No previous
Lanelet is required. The default survey covers all driving components,
including disconnected roads. `--bounds XMIN YMIN XMAX YMAX` restricts stations
in Local XY; it does not collapse vertically stacked roads. Intersecting
Lanelet segments remain whole, and LiDAR returns can extend outside the bounds.
Use `--limit 5` for a short live probe; its coverage status stays incomplete.

Generation exits 0 when review artifacts were written successfully, even if
those artifacts are not ready. `validate` exits **0 only when ready**, **2 for
failed or untested acceptance checks**, and 1 for an execution error.

## Commands and outputs

| Command | Purpose |
| --- | --- |
| `inspect --opendrive MAP.xodr` | Inventory roads, components, controls, diagnostics, and station plan. |
| `build` | Generate Lanelet and capture PCD in one run; supports `--plan-only`, `--resume`. |
| `lanelet --opendrive MAP.xodr` | Generate Lanelet offline; `--live` adds CARLA topology/control evidence. |
| `pcd` | Capture from the shared OpenDRIVE road model; supports `--resume`, `--export single`. |
| `refit --source AUTHORED.osm --opendrive MAP.xodr` | Preserve the authored-map refit workflow and its IDs/memberships. |
| `validate --output-dir RUN` | Recheck artifacts and regenerate the report/preview. |

All commands accept `--output-dir`. Generation also accepts `--config`,
`--corrections`, server selection, and optional bounds. See `map.py COMMAND
--help` for applicable options.

A build contains:

```text
run/
  source.xodr                     source snapshot
  config.json                     effective settings
  corrections.yaml                supplied corrections, if any
  network.json                    expected edges, components, controls, diagnostics
  runtime_source.json              live topology, landmarks, light boxes, stop waypoints
  id_mapping.json                 stable lane/boundary/control → OSM IDs
  lanelet2_map.osm
  map_projector_info.yaml          projector_type: Local
  stations.json / survey_poses.csv
  capture/capture.sqlite3          transactional voxels and completed stations
  capture.json                    provenance, progress, export hashes, cleanup status
  pointcloud_map.pcd/              directory of tile_X_Y.pcd files
  pointcloud_map_metadata.yaml
  validation.json / validation.png
```

`--export single` writes a single `pointcloud_map.pcd` instead of a directory.
Each file is uncompressed binary float32 XYZI. Tiles are nonoverlapping 20 m
cells by default. Tile size must be an integer number of meters for the
installed loader; negative tile origins use floor division. Metadata follows
[Autoware's map-loader format](https://autowarefoundation.github.io/autoware_core/main/map/autoware_map_loader/).
Configure its `pcd_paths_or_directory` with the PCD directory and
`pcd_metadata_path` with the metadata file. Keep the projector paired with the
map; do not independently recenter either output.

## Geometry and traffic rules

The shared model evaluates lines, arcs, spirals, `poly3`, `paramPoly3`, lane
width polynomials, lane offsets, elevation, and superelevation. Adaptive samples
have a maximum 1 m spacing and 5 cm midpoint/quarter-point chord error. Lane
sections, markings, speeds, and signal positions split segments. Section ends
use one-sided geometry so simultaneous offset/width changes are handled.

Connections come from road/lane links and junction lane links. IDs are
hash-derived from stable source identifiers. Boundaries are shared within
sections; connected endpoint nodes are shared only for source-linked lanes
whose 3D boundaries agree within the configured tolerance. No connection is
created from XY proximity. Left-hand traffic reverses the appropriate lane
travel directions. Markings provide lane-change permissions; source speeds
are converted from m/s, km/h, or mph. Junction turn direction comes from the
source movement geometry.

Controls combine source signals and validity ranges with recorded live
landmarks, affected lanes, stop waypoints, and light boxes. Source rectangular
crosswalk geometry and sign dimensions are retained where available. Lane and
control IDs are exported for bridge integration. Unambiguous complete controls
can generate traffic-light, traffic-sign, speed-limit, right-of-way, and
crosswalk regulatory elements. Autoware conventions follow its
[Lanelet format extensions](https://github.com/autowarefoundation/autoware_common/blob/main/tmp/lanelet2_extension/docs/lanelet2_format_extension.md).

**Missing bulb positions/colors, stop lines, lane associations, speeds, or
priority rules are not invented.** Light boxes alone do not locate colored
bulbs. Multiple stop waypoints, ambiguous signal IDs, general crosswalk
outlines/directions, and junction priorities may require corrections. Inspect
`network.json`, `runtime_source.json`, and unresolved entries in
`id_mapping.json`.

Current limits are explicit: nonzero crossfall/shape/CRG surfaces, lane borders,
raised driving-lane heights, level lanes on banked roads, lane direction
extensions, access rules, and direct/virtual junctions require review or further
conversion support. Zero lateral profiles are accepted. Source geometry
discontinuities, tiny/inverted segments, or inconsistent source links can
prevent native routing. These findings block readiness rather than silently
producing an approved map. A cropped run still reports source-wide defects
encountered while reading its OpenDRIVE.

## Configuration and corrections

[examples/config.yaml](examples/config.yaml) lists the main settings. Defaults
include 3 m station spacing, 10 cm voxels, 90 m range, 128 channels, two sweeps,
3.1 m sensor height, and a 2 GiB collector budget. The default vertical field of
view is **−89° to +30°** to cover road surfaces near isolated survey endpoints.
Each sweep has a small angular phase offset. Sensor pitch, yaw, and roll follow
the sampled road surface; point transformation always uses the measurement's
own pose. Intensity is explicitly **synthetic `exp(-0.004 * range_m)`**, not
material reflectance. CARLA 0.9.16 dynamic semantic labels are removed.

[examples/corrections.yaml](examples/corrections.yaml) illustrates version 1 of
the correction schema. Replace its placeholder fingerprint and source IDs with
values from your inspection run. An example Lanelet key is
`road/1/section/0/lane/-1/segment/0.000000000`; signal keys are
`signal/ROAD_ID/SIGNAL_ID` and crosswalk keys are `object/ROAD_ID/OBJECT_ID`.

Corrections support:

- `exclude`: lane keys to omit.
- `connections`: `from`, `to`, and `action: add|remove`.
- `speed_limits`: lane keys mapped to `{value: 25, unit: mph}`.
- `controls`: classification, measured XYZ geometry, stop lines, bulb positions,
  height, lane associations, speed, yield/priority lane lists, or explicit exclusion.

Crosswalk correction geometry has four corners ordered along one pedestrian
boundary and back along the other. Traffic-light geometry runs from its bottom
left to bottom right as seen by approaching traffic; `height` is the box height.
Bulbs require measured XYZ and `red`, `yellow`, or `green`; optional arrows are
preserved. Unknown keys, stale source fingerprints, and absent lane/control
references are rejected. Rebuild in a **new run** after changing corrections.
A connection correction does not authorize joining geometrically incompatible
road endpoints.

## Recovery and resources

Voxels are stored in disk-backed SQLite partitions with a bounded cache.
Each station's sweeps and completion record commit in one durable transaction.
A failed transaction, full disk, or process termination cannot mark a partial
station complete. Export streams bounded chunks; each PCD is atomically
replaced and its hashes are published after export. Keep enough disk for the
voxel database, transaction journal, final PCDs, and one temporary exported file.
The collector budget governs its cache and scan buffers; large source-network
models and native validation have additional memory costs.

After interruption or a streaming timeout, restore the same dedicated map and
resume the run:

```bash
python Map-Reconstruction/map.py build \
  --host 127.0.0.1 --port 2100 --output-dir "$RUN" --resume
```

The saved configuration and corrections are reused. Source, configuration,
corrections, and station-plan mismatches reject resume. Completed stations are
skipped; incomplete stations are retried. `capture.sqlite3` is authoritative
when disk exhaustion prevented updating the JSON manifest. Do not remove it
before export and review are complete. If storage fills during export, free
space and resume to re-export committed voxels.

Callback queues and retries are bounded. Stale scans are discarded; future or
nonconsecutive frames identify conflicting tickers. The spectator follows the
survey, streaming distances are configured, and a downward collision ray checks
that the road surface near each station is loaded at the expected elevation.
Persistent scene/OpenDRIVE disagreement stops capture with the station ID.

## Validation and tested compatibility

`validation.json` separates **structural**, **coverage**, **regulatory**, and
**runtime** results. Native routing edges are compared against source links.
Coverage measures 3D distance from planned road-surface stations to exported
points, with no global z=0 assumption or arbitrary minimum point count. The
preview shows XY and elevation. Missing checks stay untested, and `ready` stays
false until every required category and runtime scenario passes.

Implementation checks on this installation (2026-09-18):

| Environment | Offline structural/routing | Live capture / Autoware loaders |
| --- | --- | --- |
| Town01, Town02, Town04, Town07, Town10HD; also their `_Opt` files | Passed | Only Town10HD_Opt tested live. |
| Town03 / `_Opt` | Failed: source-linked lane boundary mismatch | Untested. |
| Town05 / `_Opt` | Failed: routing through a sub-millimeter split | Untested. |
| Town06 / `_Opt` | Failed: discontinuous geometry and unresolved connection | Untested. |
| UB | Review required: source geometry/routing defects | Regional PCD and Local Lanelet/PCD loader tests passed; full routing remains unresolved. |

All **17 installed OpenDRIVE files** were converted and checked. The recorded
results and source fingerprints are in [tests/compatibility.json](tests/compatibility.json). Stock-map
regulatory readiness remains unresolved where source data is incomplete.
Town10HD's full generated Lanelet passed the installed Autoware-extended
routing check with **1,224 expected edges**. Live coverage checks used an
11-station Town10HD region and a 3-station UB region; they do not establish
full-town PCD coverage. The UB repeat used the final downward field of view.
The Town10HD loader/routing test paired its full Lanelet with a regional PCD;
that combination is a loader test, not a complete mapping release.

**Controlled NDT, traffic-light planning, and stop-line planning were not
executed.** No corresponding ground-truth driving scenario was supplied to the
isolated map-loader test. Their statuses are recorded as untested. There is no
claim of universal driving validation or a ready full UB replacement.

Run the automated tests and installed-source matrix:

```bash
python -m unittest discover -s Map-Reconstruction/tests -v
python Map-Reconstruction/tests/offline_matrix.py \
  CARLA/Builds/v1.1.0/CarlaUE4/Content/Carla/Maps/OpenDrive \
  --report Map-Reconstruction/output/offline-matrix.json
```

Tests cover curved/polynomial roads, tapers, sections, merges/junction cycles,
left-hand traffic, slopes, banking, stacked/disconnected roads, absent
georeferences, malformed input, deterministic IDs, routing, controls, coordinate
transforms, dynamic filtering, late/future scans, transaction rollback, actual
SQLite disk limits, resume mismatch, tile seams, and single/tiled equivalence.

For actual loader validation, expose a **copy** of the run and this folder to
the sourced Autoware environment, then run:

```bash
python Map-Reconstruction/tests/runtime_probe.py /path/to/copied/run --domain 187
```

It launches temporary loaders in an isolated ROS domain, checks published
Lanelet/Local-projector/PCD messages and point counts, checks routing with the
installed extensions, and writes `runtime_validation.json` plus logs. Copy that
report back to the corresponding run before `map.py validate`. Artifact hashes
bind runtime evidence to the tested files. Use a dedicated unused ROS domain.
The script terminates the processes it starts.

## Existing entry points

The four original paths remain available:

- `lanelet/refit_lanelet.py`: authored-map refit, preserving relation IDs and
  regulatory memberships; now reports ambiguous geometric correspondences.
  This legacy fitter explicitly rejects nonplanar sources. Its synthesized
  turns always need review. Use new generation for 3D roads.
- `lanelet/validate_lanelet.py`: historical authored-map comparison validator.
- `pointcloud/remap_carla.py`: compatible survey flags, now backed by the
  transactional collector. It defaults to **single-file** PCD. `--lanelet` is
  optional; without it the full source network is surveyed. Existing
  `--road-bounds`, `--east-approach-x`, and `--limit` are retained; explicit
  `--map` selects a server map. Existing helper imports remain compatible.
- `pointcloud/validate_pcd.py`: new capture manifests use the general 3D
  validator without requiring a previous map. Old manifests retain their
  original flat-UB comparison workflow.

Do not use the historical flat-ground validators to certify a new hilly map.
Published earlier UB results remain under `Autoware/maps/`; installed maps
remain under `Autoware/host_data/maps/`. Installation is a separate reviewed
operation after mapping and runtime acceptance.
