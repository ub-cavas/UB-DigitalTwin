# lanefit

**Measure real lane widths from a drive, and write them into your OpenDRIVE map.**

Maps imported from OSM, via RoadRunner or similar, carry a guessed lane width. Usually a flat
3.5 m on every lane of every road. lanefit replaces that guess with a measurement: drive the
road once with a LiDAR + RTK-INS rig, and it turns the rosbag into a per-road, per-lane width
profile written back into the `.xodr`.

```
  rosbag2                                   existing .xodr
  LiDAR · IMU · RTK                         guessed lane widths
           │                                        │
           ▼                                        ▼
 ┌──────────────────┐  ┌────────────────┐  ┌────────────────┐  ┌─────────────────┐
 │   georeference   │─>│ measure_widths │─>│    conflate    │─>│      apply      │─┐
 └─────────┬────────┘  └────────┬───────┘  └────────┬───────┘  └────────┬────────┘ │
           │                    │                   │                   │          │
 ┌─────────▼────────┐  ┌────────▼───────┐  ┌────────▼───────┐  ┌────────▼────────┐ │
 │ rosbag2_py       │  │ open3d         │  │ scipy cKDTree  │  │ ElementTree     │ │
 │ pyproj           │  │ scipy cKDTree  │  │ scipy fresnel  │  │ PCHIP + Hermite │ │
 │ glim + FlexCloud │  │ MAD peaks + DP │  │ rolling median │  │ carla.Map       │ │
 └──────────────────┘  └────────────────┘  └────────────────┘  └─────────────────┘ │
                                                                                   ▼
                                                                <map>_corrected.xodr
```

Those four blocks are eight stages underneath: `audit` vets the inputs before anything
runs, `extract_trajectory` and `slam` feed `georeference`, and `validate` reads back what
`apply` wrote. Each records its status, so a re-run skips finished work and picks up where
you left off.

Roads that cannot be measured confidently are **left exactly as they were** and listed
with a reason. lanefit never guesses.

> [!NOTE]
> **This README covers installing and running lanefit. Nothing else.** The rest is here:
>
> - **[docs/PIPELINE.md](docs/PIPELINE.md)** covers **how the pipeline works and why**.
>   Every stage, what it produces, how to inspect it, which knob to turn when it
>   misbehaves, and the design notes behind each decision.
> - **[docs/SETUP.md](docs/SETUP.md)** covers **what you need before running**. What your
>   bag and map must contain, what goes in the container, and how to rebuild it.
> - **[config/default.yaml](config/default.yaml)** documents **every tunable**, inline.

---

## Install

On the host you need `docker`, `rsync` and `bash`. That is the whole list. Everything the
pipeline drives (ROS 2 humble, glim, FlexCloud, open3d, and the pinned SLAM stack) gets built
inside a container by `deps/install_deps.sh`.

> [!NOTE]
> **Read [`docs/SETUP.md`](docs/SETUP.md) before you start.** It lists every component
> with its version and pinned commit, the apt packages and the Python modules, plus what
> your rosbag and `.xodr` have to provide, which `audit` will otherwise reject them for.

```bash
# 1 · host · get the code
git clone https://github.com/<your-user>/lanefit.git ~/lanefit

# 2 · host · start a ROS 2 humble container with a /host_data bind mount
docker run -d --name autoware_c \
    -v ~/ub-lincoln-docker/docker_data/host_data:/host_data \
    ubcavas/autoware-lincoln:latest sleep infinity

# 3 · host · seed the package into the mount so the installer is visible inside
rsync -a --exclude .git ~/lanefit/ ~/ub-lincoln-docker/docker_data/host_data/lanefit/

# 4 · container · build the toolchain (15-25 min, mostly compiles)
docker exec -it autoware_c bash /host_data/lanefit/deps/install_deps.sh

# 5 · host · verify
~/lanefit/bin/lanefit stages
```

Any ROS 2 humble container will do, as long as `/host_data` is mounted and
`novatel_oem7_msgs` is available. The reference image is `ubcavas/autoware-lincoln`. If you
use the `ub-lincoln-docker` compose setup, `cd ~/ub-lincoln-docker/docker && ./dc_up.sh`
replaces step 2 and `./dc_bash.sh` gets you a shell.

Step 3 is a one-time bootstrap. The installer has to exist inside the container before it can
run; after that, `bin/lanefit` rsyncs the package on every invocation.

For a real check, run `audit` on a bag. It verifies every tool, ROS package and Python module
the pipeline needs, and tells you what is missing.

| variable | default | meaning |
|---|---|---|
| `LANEFIT_CONTAINER` | `autoware_c` | container to `docker exec` into |
| `LANEFIT_HOST_DATA` | `~/ub-lincoln-docker/docker_data/host_data` | host side of the `/host_data` mount |

> [!IMPORTANT]
> Every path you pass gets resolved **inside the container**. Keep bags, maps and run
> directories under `/host_data/...`, not under your home directory.

---

## Run

```bash
~/lanefit/bin/lanefit run \
    --bag  /host_data/rosbags/rosbag2_2026_02_25-15_02_42_driving \
    --xodr /host_data/ServiceCenterLoopMR.xodr \
    --out  /host_data/lanefit_runs/loop01
```

`audit` finishes in seconds and stops you early if the inputs cannot support the rest.
`georeference` and `measure_widths` take most of the runtime.

```
loop01/
├── report.md                    start here: rollup of every stage
├── manifest.json                stage status, which is also the resume state
├── audit/  extract_trajectory/  georeference/  measure_widths/
├── conflate/                    road_matches · lane_width_updates · skipped_roads
├── apply/<map>_corrected.xodr   the deliverable
└── validate/                    corrected_roads_map · road_profiles · width_ladder
```

Read `report.md` first. Then `validate/corrected_roads_map.png`, which draws the corrected
widths on the driven map. Then `conflate/skipped_roads.csv` for every road left untouched and
the reason why.

### Everyday variants

```bash
# health-check the inputs only, before committing CPU to a full run
bin/lanefit audit --bag $BAG --xodr $XODR --out $RUN

# stop early, or resume after tuning config (finished stages are skipped for free)
bin/lanefit run --bag $BAG --xodr $XODR --out $RUN --until-stage measure_widths
bin/lanefit run --out $RUN --from-stage conflate

# re-run one stage with an override
bin/lanefit stage conflate --out $RUN --force --set conflate.min_stations=6

# drop parked periods from a bag first (optional, makes SLAM faster)
bin/lanefit trim-bag --bag $BAG --out-bag ${BAG}_driving

# combine several drives. Per road, the run with the strongest evidence wins
bin/lanefit merge-runs --runs $RUN1,$RUN2 --xodr $XODR --out /host_data/lanefit_runs/merged
```

The first stage invocation records `--bag` and `--xodr` into `manifest.json`, and later
stages on the same run directory reuse them. `--force` re-runs a completed stage.

---

## Documentation

**Everything this README skipped is in one of these.**

| file | what's in it |
|---|---|
| **[docs/PIPELINE.md](docs/PIPELINE.md)** | **How the pipeline works, and why.** Every stage, what it produces, how to inspect it, the tuning cheat-sheet, and the design notes |
| **[docs/SETUP.md](docs/SETUP.md)** | **What you need before running.** Required bag topics and xodr constraints, container components and pinned commits, rebuild runbook |
| **[config/default.yaml](config/default.yaml)** | **Every tunable**, documented inline |
