# Lincoln localization rosbag collection

`Data-Collection/scripts/record_localization_bag.py` prepares a ROS 2 Humble recording in the physical Lincoln's running Autoware container. It checks publisher endpoints for the 22 topics below, refuses missing essential publishers by default, and then records the entire requested list. It adds no Python dependencies beyond the ROS-provided `rclpy`; `--help` works without ROS.

This tool has been checked with mocked publishers, not a physical Lincoln capture. The previously observed incomplete local graph is not evidence that the vehicle is ready. Run preflight in the vehicle's actual Autoware environment before collecting data.

## Container preparation and preflight

From the repository root on the host, copy the standalone helper into the running container:

```bash
docker cp Data-Collection/scripts/record_localization_bag.py autoware_c:/host_data/record_localization_bag.py
docker exec -it autoware_c bash
```

Inside that shell, source the container overlays in build order:

```bash
source /opt/ros/humble/setup.bash
source /ros_ws/install/local_setup.bash
source /autoware/install/setup.bash
mkdir -p /host_data/bags
df -h /host_data/bags
bag_dir="/host_data/bags/lincoln_localization_$(date +%Y%m%d_%H%M%S)"
python3 /host_data/record_localization_bag.py --output "$bag_dir" --check-only
```

These overlay paths come from `Autoware/ub-lincoln-docker/docker/ros2.dockerfile` (Humble and `/ros_ws`) and `autoware.dockerfile` (`/autoware/install`). If the vehicle uses a different build, adjust to its installed setup files and source any additional workspace that provides its custom messages. In particular the recorder must resolve Autoware, NovAtel, and UB-MR types actually advertised by the publishers. A visible publisher does not establish that the recorder can load its message type. Do not ignore missing setup files or recorder type-support errors.

`Autoware/ub-lincoln-docker/docker/docker-compose.yml` mounts `$HOST_DATA_PATH` at `/host_data` and `$AUTOWARE_DATA_PATH` at `/root/autoware_data`. The repository itself need not be mounted. Bags under `/host_data/bags` persist on the host; confirm the running container uses that bind mount. Pointclouds and maps can consume substantial disk and write bandwidth, so check available storage and monitor it during collection. The helper does not choose compression or storage settings for you.

Preflight prints each requested name, its effective name, publisher count, and discovered message types. Subscriber-only entries do not count as available. Essential absences return a nonzero status; optional absences warn. `--check-only` never starts a recorder or creates a bag. A fresh output path is required even for preflight. To allow more time for DDS discovery, add `--discovery-timeout 15` (positive finite seconds, maximum 300; default 5).

If expected publishers are missing, check the vehicle launch state, `ROS_DOMAIN_ID`, RMW configuration, and container networking. From the same sourced shell, inspect:

```bash
ros2 topic list
ros2 topic info --verbose /tf_static
ros2 topic info --verbose /sensing/lidar/top/aw_points
```

Do not infer vehicle aliases from matching message types. Ensure these names and types describe the intended data streams.

## Record and inspect

After successful preflight, in the same sourced container shell:

```bash
python3 /host_data/record_localization_bag.py --output "$bag_dir"
```

The helper repeats preflight and prints the absolute destination and exact shell-readable command. It refuses an existing output directory. Every effective topic is passed explicitly to `ros2 bag record`; discovery stays enabled so currently absent topics can be recorded if they appear later. No `/clock`, `--all`, sim-time behavior, compression, or global sensor QoS override is added.

Stop with **Ctrl-C once**, then wait for rosbag to finalize metadata and for the helper to exit before closing the shell or stopping the container. The helper forwards the interrupt to the recorder and keeps its temporary QoS file until the child exits. An interrupted collection returns status 130; other recorder failures propagate a nonzero status. Inspect the bag afterward:

```bash
ros2 bag info "$bag_dir"
ls -lh "$bag_dir"
```

For the first hardware session, collect a short authorized smoke capture. Confirm the persisted bag has the requested effective names, expected message types, sensible message counts and time span, and retained map/TF/initialization/description messages. Check the host's `$HOST_DATA_PATH/bags` too. Publisher discovery and even a listed bag topic do not prove messages were captured. `/initialpose` may have zero messages unless an operator publishes an initial pose during recording. Missing or zero-count topics require investigation against the live publishers and recorder logs before treating the collection as complete.

`--allow-missing-essential` explicitly permits an incomplete essential set. It prints the missing names and preserves them in discovery, but cannot recover data that was never published or captured. Use it only when intentionally accepting those gaps; a successful exit or later publisher appearance does not repair earlier omissions. It also applies to the readiness result of `--check-only`.

## Topic list and explicit mappings

| Classification | Requested topic |
| --- | --- |
| Essential | `/tf` |
| Essential | `/tf_static` |
| Essential | `/sensing/lidar/top/aw_points` |
| Essential | `/sensing/gnss/novatel/oem7/odom` |
| Essential | `/localization/kinematic_state` |
| Essential | `/api/localization/initialization_state` |
| Essential | `/map/pointcloud_map` |
| Essential | `/ub_mr/localization` |
| Optional | `/initialpose` |
| Optional | `/sensing/lidar/top/pointcloud_raw_ex` |
| Optional | `/sensing/lidar/top/aw_points_ex` |
| Optional | `/localization/pose_estimator/pose_with_covariance` |
| Optional | `/sensing/gnss/pose_with_covariance` |
| Optional | `/vehicle/status/velocity_status` |
| Optional | `/sensing/imu/imu_data` |
| Optional | `/diagnostics` |
| Optional | `/robot_description` |
| Optional | `/sensing/gnss/novatel/oem7/fix` |
| Optional | `/sensing/gnss/novatel/oem7/inspva` |
| Optional | `/autoware_orientation` |
| Optional | `/sensing/gnss/novatel/oem7/imu/data_raw` |
| Optional | `/parameter_events` |

For a verified vehicle-specific equivalent, repeat `--topic-map REQUESTED=ACTUAL`. This syntax illustration does **not** assert a Lincoln alias:

```bash
python3 /host_data/record_localization_bag.py --output "$bag_dir" --check-only \
  --topic-map /ub_mr/localization=/verified_vehicle/localization
```

Use the same mapping arguments on the recording invocation. The helper shows the substitution, preserves the requested topic's essential/optional classification, and applies any retained-topic QoS to the mapped name. Mapping sources must be in the table, targets must be absolute ROS topic names, and all 22 effective names must remain distinct. Duplicate sources are rejected. There are no automatic aliases or type-based substitutions; raw and processed lidar streams are not interchangeable by inference.

## Retained context and QoS limits

For currently published `/tf_static`, `/map/pointcloud_map`, `/api/localization/initialization_state`, and `/robot_description` (or their explicit mappings), the helper inspects each publisher's offered QoS. It requests `transient_local` only when **all** current publishers offer it; otherwise it requests `volatile` and warns that historical context may be unavailable. Reliability is `reliable` only when all offers are known reliable, otherwise `best_effort`. Unknown/system-default policies trigger conservative fallback and warnings. History is `keep_last`, depth 100 for static TF and 1 for the other three. Other topics use rosbag's normal QoS adaptation.

This is a startup snapshot. Absent retained-topic candidates receive no override, allowing rosbag to adapt when they appear. Publishers appearing later may have different QoS, and an existing override will not be recomputed during recording. Volatile publishers cannot provide historical messages to a late subscriber; mixed publishers cannot guarantee all retained context through one subscription. Verify actual counts and QoS during the smoke capture. Restart preparation after a publisher/configuration change if the snapshot is no longer representative.
