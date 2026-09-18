# CARLA map reconstruction

Build a Lanelet map and static point-cloud map for a new UB CARLA release.
Refit the existing Lanelet routes to the new OpenDRIVE road widths, validate
the result, then capture a fresh LiDAR survey aligned with that Lanelet map.

The Lanelet tool **updates an existing local-coordinate map**. It preserves
its routes and traffic rules; it does not create a complete Lanelet map from
arbitrary OpenDRIVE input. The PCD tool captures the actual CARLA scene using
stationary sensor poses, so no manual driving is needed.

## Contents

| Path | Purpose |
| --- | --- |
| `lanelet/refit_lanelet.py` | Fit straight lane boundaries to OpenDRIVE and rebuild connecting turns. |
| `lanelet/validate_lanelet.py` | Check Lanelet geometry, routing, stop lines, and generate a comparison image. |
| `pointcloud/remap_carla.py` | Capture and merge static semantic-LiDAR scans into a binary XYZI PCD. |
| `pointcloud/validate_pcd.py` | Check PCD integrity and ground coverage; generate a comparison image. |
| `tests/` | Coordinate, filtering, voxel, survey-pose, and PCD-format tests. |
| `output/` | Local generation runs; ignored by Git. |

Installed maps live in `Autoware/host_data/maps/ub_autonomous_proving_grounds/`.
Existing [v1.1.0 Lanelet results](../Autoware/maps/ub_autonomous_proving_grounds/v1.1.0/README.md)
and [PCD results](../Autoware/maps/ub_autonomous_proving_grounds/v1.1.0/pcd-remapping/README.md)
include previews, validation reports, and backup details. RoadRunner scene
assets remain in the separate `Road-Runner/` submodule.

## 1. Set up dependencies and inputs

**Run all commands below from the repository root**, in Bash. The example uses
the installed v1.0.0 Lanelet as the baseline and the v1.1.0 CARLA build as the
new geometry source. Both versions must already be downloaded.

Use Python 3.10 with the matching CARLA wheel and ROS Humble Lanelet2 bindings.
The PCD collector needs CARLA and NumPy; full validation also needs SciPy,
pyproj, Shapely, Matplotlib, and Lanelet2. A local environment can reuse the
system/ROS packages:

```bash
source /opt/ros/humble/setup.bash
/usr/bin/python3 -m venv --system-site-packages Map-Reconstruction/.venv
source Map-Reconstruction/.venv/bin/activate
python -m pip install -r Map-Reconstruction/requirements.txt
python -m pip install CARLA/Builds/v1.1.0/PythonAPI/carla/dist/carla-0.9.16-cp310-cp310-linux_x86_64.whl
python -c 'import carla, lanelet2, numpy, scipy, pyproj, shapely, matplotlib'
```

If the ROS installation does not supply `lanelet2`, install its Python bindings
for the same interpreter before running Lanelet validation. Use a fresh run
folder to keep previous outputs available:

```bash
MAP_BASE=Autoware/host_data/maps/ub_autonomous_proving_grounds
BASELINE="$MAP_BASE/v1.0.0/lanelet2_map.osm"
TARGET_MAP="$MAP_BASE/v1.1.0"
XODR=CARLA/Builds/v1.1.0/CarlaUE4/Content/Carla/Maps/OpenDrive/UBAutonomousProvingGrounds.xodr
RUN="Map-Reconstruction/output/v1.1.0-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN"
export MPLCONFIGDIR=/tmp/ub-map-matplotlib
```

The workflow uses the existing Autoware `projector_type: Local` configuration.
CARLA coordinates become local map coordinates with **x unchanged, y negated,
z unchanged**. Do not recenter the PCD or change the projector independently.

## 2. Build and validate the Lanelet

This step runs offline; a CARLA server is not required.

```bash
python Map-Reconstruction/lanelet/refit_lanelet.py \
  --source "$BASELINE" \
  --opendrive "$XODR" \
  --output "$RUN/lanelet2_map.osm"

python Map-Reconstruction/lanelet/validate_lanelet.py \
  --source "$BASELINE" \
  --candidate "$RUN/lanelet2_map.osm" \
  --opendrive "$XODR" \
  --report "$RUN/lanelet-validation.json"
```

Review `lanelet-validation.json` and `lanelet-validation.png`.
`lanelet2_map.refit.json` records source hashes, matched OpenDRIVE lanes,
widths, and intersection adjustments. A validation failure exits nonzero.
The validator checks the default maximum boundary spacing of 1 m.

The refitter preserves relation IDs, route connections, speed limits, and
traffic-sign memberships. Straight boundaries follow same-direction driving
lanes; tangent cubic curves connect them through intersections. Inspect these
synthesized turns against the scene/point cloud. The retained v1.1.0 report
documents a northwest-corner discrepancy that still needs simulator review.
The upstream Lanelet2 linter can also report Autoware-specific tags and nearby
points; the local validation report is not a claim that every upstream lint
check is warning-free.

## 3. Start a dedicated CARLA server

In a **second terminal**, from the repository root:

```bash
CARLA/Builds/v1.1.0/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping \
  CarlaUE4 -carla-rpc-port=2100 -RenderOffScreen -quality-level=Low -nosound -unattended
```

Keep port 2100 free of driving clients or other tickers. The collector loads
the UB map using its advertised server name and verifies its OpenDRIVE against
`--opendrive`. It refuses a server containing vehicles, walkers, or sensors.
It temporarily enables synchronous operation, then destroys its own sensor
and restores world settings. Stop this dedicated server after collection.

## 4. Capture the PCD

Back in the first terminal, preview the scan stations without connecting to
CARLA:

```bash
python Map-Reconstruction/pointcloud/remap_carla.py \
  --lanelet "$RUN/lanelet2_map.osm" \
  --opendrive "$XODR" \
  --road-bounds -445 -8 12 183 \
  --output-dir "$RUN/pcd" \
  --plan-only
```

Run the same command without `--plan-only` to capture:

```bash
python Map-Reconstruction/pointcloud/remap_carla.py \
  --lanelet "$RUN/lanelet2_map.osm" \
  --opendrive "$XODR" \
  --road-bounds -445 -8 12 183 \
  --output-dir "$RUN/pcd"
```

The bounds are UB-specific local **xmin ymin xmax ymax** values that include
surrounding roads and parking aisles. Omit them to survey only the Lanelet
network, or change them for another area. Useful options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--host`, `--port` | `127.0.0.1`, `2100` | Dedicated CARLA server. |
| `--spacing` | `3.0` m | Distance between scan stations. |
| `--voxel` | `0.1` m | Keep one actual static return per voxel. |
| `--range` | `90` m | LiDAR range. |
| `--height` | `3.1` m | Sensor height above the station's road elevation. |
| `--limit` | `0` | Limit stations for a probe; use a separate output folder. |

Each station gets two 360-degree scans from a 128-channel semantic LiDAR.
Dynamic labels are removed, and each measurement is transformed using its
recorded pose. Intensity is synthetic range attenuation, not calibrated
reflectance. Scans merge incrementally; reserve space for the new PCD,
checkpoints, and the previous map's backup. The v1.1.0 survey produced a roughly
342 MB PCD. An existing output PCD is never overwritten by the collector.

## 5. Validate the PCD

```bash
python Map-Reconstruction/pointcloud/validate_pcd.py \
  --candidate "$RUN/pcd/pointcloud_map.pcd" \
  --previous "$TARGET_MAP/pointcloud_map.pcd" \
  --lanelet "$RUN/lanelet2_map.osm" \
  --capture "$RUN/pcd/capture.json" \
  --report-dir "$RUN/pcd/review"
```

Review `pcd/review/validation.json` and `pcd/review/comparison.png`.
Keep `capture.json` and `survey_poses.csv` together: validation uses both.
The checks cover binary XYZI layout, finite values, intensity range, voxel
uniqueness, hashes, scan completeness, and ground returns near the routes and
scan stations. The coverage checks assume the flat UB proving ground and a
full survey; they are not intended for a limited probe or a hilly map.

## 6. Install reviewed outputs

After both reports pass and the previews have been inspected, back up the
installed files and copy the new pair. Use the same first terminal:

```bash
(
set -e
python - "$RUN/lanelet-validation.json" "$RUN/pcd/review/validation.json" <<'PY'
import json, sys
for path in sys.argv[1:]:
    if not json.load(open(path))["passed"]:
        raise SystemExit(f"Validation failed: {path}")
PY
BACKUP="$TARGET_MAP/.backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
cp -p "$TARGET_MAP/lanelet2_map.osm" "$TARGET_MAP/pointcloud_map.pcd" \
  "$TARGET_MAP/map_projector_info.yaml" "$BACKUP/" && \
cp "$RUN/lanelet2_map.osm" "$TARGET_MAP/lanelet2_map.osm.new" && \
cp "$RUN/pcd/pointcloud_map.pcd" "$TARGET_MAP/pointcloud_map.pcd.new" && \
mv "$TARGET_MAP/lanelet2_map.osm.new" "$TARGET_MAP/lanelet2_map.osm" && \
mv "$TARGET_MAP/pointcloud_map.pcd.new" "$TARGET_MAP/pointcloud_map.pcd"
echo "Previous maps saved in $BACKUP"
)
```

Restart Autoware/map loading to use the new files. Leave
`map_projector_info.yaml` unchanged. Check map alignment in RViz and perform
an NDT localization/route-driving test before treating the maps as a validated
driving release. To restore the previous pair, copy it from the printed backup folder and reload
the maps.

## Tests

```bash
python -m unittest discover -s Map-Reconstruction/tests -v
```

All four tools also accept `--help`. Reorganizing these tools does not require
recapturing or replacing existing installed maps.
