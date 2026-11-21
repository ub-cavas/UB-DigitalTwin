# Inject a modified topic into Autoware

Connect your modification script between the original publisher and Autoware:

```text
Original topic
      ↓
Modification script
      ↓
Modified topic
      ↓
Autoware
```

**Keep your script subscribed to the original topic.** Change only the downstream
Autoware input to the modified topic. Use different input and output names, and
preserve the expected message type, frame, timestamp, and required fields.

## 1. Open the container

From the project's Docker directory, run:

```bash
./dc_bash.sh
```

## 2. Choose what to inject

| Data | Modified topic | Message type |
| --- | --- | --- |
| LiDAR | `/injection/lidar/points` | `sensor_msgs/msg/PointCloud2` |
| Bounding boxes | `/injection/perception/objects` | `autoware_perception_msgs/msg/DetectedObjects` |

Follow the matching configuration below.

### LiDAR · Virtual sensor kit

**Edit this file:**

```text
/autoware/install/awsim_sensor_kit_launch/share/awsim_sensor_kit_launch/config/concatenate_and_time_sync_node.param.yaml
```

**In `input_topics`, replace only the top LiDAR entry:**

| Before | After |
| --- | --- |
| `/sensing/lidar/top/pointcloud_before_sync` | `/injection/lidar/points` |

Your script continues reading `/sensing/lidar/top/pointcloud_before_sync`.

### LiDAR · Physical Lincoln sensor kit

**Edit this file:**

```text
/autoware/src/launcher/autoware_launch/sensor_kit/ub_lincoln_sensor_kit_launch/ub_lincoln_sensor_common_launch/launch/nebula_node_container.launch.py
```

**In the `ring_outlier_filter` component, use:**

```python
remappings=[
    ("input", "/injection/lidar/points"),
    ("output", "/sensing/lidar/concatenated/pointcloud"),
],
```

Your script reads the original upstream cloud. In this pipeline, the normal
filter input is `rectified/pointcloud_ex` within the sensor namespace. Preserve
the fields needed by the ring filter, including channel information.

### Bounding boxes · Both sensor kits

| Connection | Topic |
| --- | --- |
| Script input — original detections | `/perception/object_recognition/detection/objects` |
| Script output — modified detections | `/injection/perception/objects` |

**Edit this file:**

```text
/autoware/install/autoware_launch/share/autoware_launch/config/perception/object_recognition/tracking/multi_object_tracker/input_channels.param.yaml
```

**Under `input_channels → detected_objects`, change only:**

```yaml
topic: "/injection/perception/objects"
```

Confirm that the tracker uses this channel:

```bash
ros2 param get   /perception/object_recognition/tracking/multi_object_tracker   selected_input_channels
```

If another channel is active, change that channel's topic instead and use its
original topic as your script's input.

> **Bounding boxes only?** Keep normal LiDAR routing and run only the
> bounding-box modification script.

## 3. Start and check

1. **Start your script.** It should wait for original messages.
2. **Restart the Autoware launch.** This applies the new subscription.
3. **Check the modified topic** using the relevant command below.

**LiDAR:**

```bash
ros2 topic hz /injection/lidar/points
```

**Bounding boxes:**

```bash
ros2 topic hz /injection/perception/objects
```

In RViz, select the modified topic in a **PointCloud2** or **Autoware
DetectedObjects** display. Use a Fixed Frame connected to the message frame by TF.

**Rebuild?** Not in the inspected setup: the installed configuration is symlinked
to the source. On other installations, update the installed files or rebuild the
relevant launch package if source changes are not reflected there.

## 4. Restore normal operation

1. Restore Autoware's original input topic.
2. Restart the Autoware launch.
3. Stop the modification script.
