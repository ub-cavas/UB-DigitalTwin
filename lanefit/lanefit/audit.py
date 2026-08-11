"""Audit stage: environment, rosbag, and xodr initial measurements.

Runs first and fails fast. Everything the pipeline later assumes is checked here:
tool availability, topic presence/rates/health (incl. NaN-axis IMU decoys and
per-point time-field semantics), RTK quality, stationary/parked periods, tf_static
extrinsics (T_lidar_imu derived, not hardcoded), and the map's initial width state.
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
from collections import Counter

import numpy as np
import yaml

from .config import Config
from .runctx import RunContext
from .util import TfTree, iter_messages, open_bag_reader
from .xodr_io import parse_xodr, xodr_statistics

log = logging.getLogger("lanefit")


# ---------------- environment ----------------
def audit_environment() -> dict:
    checks: dict[str, dict] = {}

    def rec(name, ok, detail=""):
        checks[name] = {"ok": bool(ok), "detail": detail}
        (log.info if ok else log.error)("env %-22s %s %s", name, "OK" if ok else "MISSING", detail)

    rec("ros2", shutil.which("ros2") is not None, shutil.which("ros2") or "")
    for mod in ("numpy", "scipy", "yaml", "PIL", "matplotlib", "open3d"):
        try:
            __import__(mod)
            rec(f"python:{mod}", True)
        except Exception as e:
            rec(f"python:{mod}", False, str(e))
    try:
        import carla  # noqa: F401
        rec("python:carla", True, "(validate stage will use the map API)")
    except Exception:
        rec("python:carla", False, "validate stage will skip the CARLA readback")
    for pkg, exe in (("glim_ros", "glim_rosbag"), ("flexcloud", "georeferencing")):
        try:
            out = subprocess.run(["ros2", "pkg", "executables", pkg],
                                 capture_output=True, text=True, timeout=60)
            rec(f"ros:{pkg}/{exe}", exe in out.stdout,
                "" if exe in out.stdout else "see deps/install_deps.sh")
        except Exception as e:
            rec(f"ros:{pkg}/{exe}", False, str(e))
    try:
        import rosbag2_py  # noqa: F401
        rec("python:rosbag2_py", True)
    except Exception as e:
        rec("python:rosbag2_py", False, str(e))
    hard = [k for k, v in checks.items() if not v["ok"] and k != "python:carla"]
    if hard:
        raise RuntimeError(f"environment incomplete: {hard} — run deps/install_deps.sh "
                           "inside the container (see docs/SETUP.md)")
    return checks


# ---------------- rosbag ----------------
def audit_bag(bag: str, cfg: Config) -> dict:
    lidar_t, imu_t, gnss_t = (cfg("topics.lidar"), cfg("topics.imu"), cfg("topics.gnss"))
    meta = yaml.safe_load(open(os.path.join(bag, "metadata.yaml")))
    info = meta["rosbag2_bagfile_information"]
    counts_meta = {t["topic_metadata"]["name"]: t["message_count"]
                   for t in info["topics_with_message_count"]}
    types = {t["topic_metadata"]["name"]: t["topic_metadata"]["type"]
             for t in info["topics_with_message_count"]}
    out: dict = {
        "duration_s": info["duration"]["nanoseconds"] / 1e9,
        "message_count_meta": info["message_count"],
        "topics": {},
    }
    for name, label in ((lidar_t, "lidar"), (imu_t, "imu"), (gnss_t, "gnss")):
        if name not in counts_meta:
            raise RuntimeError(f"required topic missing from bag: {name}")
        out["topics"][label] = {"name": name, "type": types[name],
                                "count_meta": counts_meta[name]}

    # --- LiDAR: field layout + per-point time semantics (first message) ---
    for topic, msg, _ in iter_messages(bag, [lidar_t]):
        fields = {f.name: {"offset": f.offset, "datatype": f.datatype} for f in msg.fields}
        lid = out["topics"]["lidar"]
        lid["frame_id"] = msg.header.frame_id
        lid["point_step"] = msg.point_step
        lid["fields"] = list(fields)
        lid["has_intensity"] = "intensity" in fields
        tfield = next((n for n in ("time_stamp", "t", "time", "timestamp") if n in fields), None)
        lid["time_field"] = tfield
        if tfield:
            f = fields[tfield]
            raw = np.frombuffer(bytes(msg.data), np.uint8).reshape(-1, msg.point_step)
            col = raw[:, f["offset"]:f["offset"] + 4].copy()
            if f["datatype"] == 6:      # UINT32
                tv = col.view(np.uint32).ravel()
                lid["time_semantics"] = (
                    f"uint32, span {tv.max()/1e9:.4f}s if ns — glim divides by 1e9 itself; "
                    "perpoint_time_scale must stay 1.0")
            elif f["datatype"] == 7:    # FLOAT32
                tv = col.view(np.float32).ravel()
                lid["time_semantics"] = f"float32, span {float(tv.max()):.4f}"
        if not lid["has_intensity"]:
            raise RuntimeError(f"{lidar_t} has no intensity field — width measurement "
                               "depends on it")
        break

    # --- IMU: rate, gaps, NaN-axis decoy check ---
    stamps, bad_axes = [], 0
    for i, (_, msg, _) in enumerate(iter_messages(bag, [imu_t])):
        stamps.append(msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9)
        if i < 500:
            vals = (msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z,
                    msg.linear_acceleration.x, msg.linear_acceleration.y,
                    msg.linear_acceleration.z)
            if not all(math.isfinite(v) for v in vals):
                bad_axes += 1
    st = np.sort(np.array(stamps))
    dt = np.diff(st)
    imu = out["topics"]["imu"]
    imu.update(count_read=len(st), rate_hz=round(len(st) / max(st[-1] - st[0], 1e-9), 1),
               gap_p99_ms=round(float(np.percentile(dt, 99)) * 1e3, 1),
               gap_max_ms=round(float(dt.max()) * 1e3, 1),
               gaps_over_100ms=int((dt > 0.1).sum()), nan_samples_in_first_500=bad_axes)
    if bad_axes:
        raise RuntimeError(f"{imu_t} carries non-finite axes ({bad_axes}/500 samples) — "
                           "this is a decoy IMU (e.g. CAN yaw-rate sensor); pick another topic")
    if imu["gaps_over_100ms"]:
        log.warning("IMU has %d gaps >100 ms (max %.0f ms) — SLAM tolerates these but "
                    "expect 'insufficient IMU data' warnings", imu["gaps_over_100ms"],
                    imu["gap_max_ms"])

    # --- GNSS: RTK quality + stationary periods ---
    pos_types, ins_stats = Counter(), Counter()
    epochs = []
    lat0 = None
    for _, msg, t_ns in iter_messages(bag, [gnss_t]):
        pos_types[msg.pos_type.type] += 1
        ins_stats[msg.ins_status.status] += 1
        if lat0 is None:
            lat0 = msg.latitude
        epochs.append((t_ns,
                       math.radians(msg.longitude) * 6378137.0 * math.cos(math.radians(lat0)),
                       math.radians(msg.latitude) * 6356752.0,
                       msg.height, getattr(msg, "undulation", float("nan"))))
    g = out["topics"]["gnss"]
    rtk_type = cfg("extract_trajectory.rtk_pos_type")
    g.update(count_read=len(epochs), pos_type_census=dict(pos_types),
             ins_status_census=dict(ins_stats),
             rtk_fixed_share=round(pos_types.get(rtk_type, 0) / max(len(epochs), 1), 3),
             height_note=f"INSPVAX height is MSL/orthometric; undulation={epochs[0][4]:.1f} m"
                         if epochs and math.isfinite(epochs[0][4]) else "")
    if g["rtk_fixed_share"] < 0.5:
        log.warning("only %.0f%% of GNSS epochs are RTK-fixed — georeferencing accuracy "
                    "will suffer", 100 * g["rtk_fixed_share"])

    move_eps = cfg("trim_bag.move_eps")
    runs, cur, cur_start = [], 0, None
    for i in range(1, len(epochs)):
        d = math.hypot(epochs[i][1] - epochs[i - 1][1], epochs[i][2] - epochs[i - 1][2])
        if d < move_eps:
            if cur == 0:
                cur_start = epochs[i - 1][0]
            cur += 1
        elif cur:
            runs.append({"start_ns": cur_start, "duration_s": round((epochs[i - 1][0] - cur_start) / 1e9, 1)})
            cur = 0
    if cur:
        runs.append({"start_ns": cur_start, "duration_s": round((epochs[-1][0] - cur_start) / 1e9, 1)})
    parked = [r for r in runs if r["duration_s"] >= cfg("trim_bag.min_park")]
    g["stationary_runs_s"] = [r["duration_s"] for r in runs]
    g["parked_intervals"] = parked
    if parked:
        log.warning("bag contains %d parked interval(s) totalling %.0f s — consider "
                    "`lanefit trim-bag` (measure stage dedupes stationary epochs regardless)",
                    len(parked), sum(p["duration_s"] for p in parked))

    # metadata overcount check (unclean recording close)
    over = counts_meta.get(gnss_t, 0) - len(epochs)
    if over > 0:
        log.warning("metadata.yaml overcounts %s by %d msgs vs reader — bag likely closed "
                    "uncleanly; reader counts are authoritative", gnss_t, over)
        out["metadata_overcount_gnss"] = over
    return out


# ---------------- extrinsics from tf_static ----------------
def derive_t_lidar_imu(bag: str, cfg: Config) -> dict:
    """T_lidar_imu in glim semantics (p_lidar = T * p_imu), TUM [x y z qx qy qz qw],
    derived from /tf_static and the frame_ids of the imu/points topics."""
    imu_frame = lidar_frame = None
    for _, msg, _ in iter_messages(bag, [cfg("topics.imu")]):
        imu_frame = msg.header.frame_id
        break
    for _, msg, _ in iter_messages(bag, [cfg("topics.lidar")]):
        lidar_frame = msg.header.frame_id
        break
    tree = TfTree()
    n_tf = 0
    reader = open_bag_reader(bag, ["/tf_static"])
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    mt = get_message("tf2_msgs/msg/TFMessage")
    while reader.has_next():
        _, data, _ = reader.read_next()
        msg = deserialize_message(data, mt)
        for tr in msg.transforms:
            t = tr.transform.translation
            q = tr.transform.rotation
            tree.add(tr.header.frame_id, tr.child_frame_id,
                     (t.x, t.y, t.z), (q.x, q.y, q.z, q.w))
            n_tf += 1
    t, q = tree.transform(imu_frame, lidar_frame)   # p_lidar = T_lidar_imu p_imu
    result = {"imu_frame": imu_frame, "lidar_frame": lidar_frame,
              "tf_static_edges": n_tf,
              "t_lidar_imu": [round(v, 6) for v in (*t, *q)]}
    log.info("T_lidar_imu (%s -> %s) = %s", imu_frame, lidar_frame, result["t_lidar_imu"])
    return result


# ---------------- stage entry ----------------
def run(ctx: RunContext, cfg: Config) -> dict:
    out_dir = ctx.dir("audit")
    env = audit_environment()
    bag = audit_bag(ctx.bag, cfg)
    extr = derive_t_lidar_imu(ctx.bag, cfg)
    header, roads = parse_xodr(ctx.xodr)
    stats = xodr_statistics(ctx.xodr)
    xodr = {
        "geo_reference": header["geo_reference"],
        "has_offset_element": header["has_offset"],
        "header": header["attrib"],
        **stats,
    }
    if not header["geo_reference"]:
        raise RuntimeError("xodr has no <geoReference> — cannot georeference the cloud")
    if header["has_offset"]:
        log.warning("xodr header has an <offset> element — the pipeline currently assumes "
                    "none; verify before trusting the output")
    if stats["elevation_nonzero"] == 0:
        log.info("xodr elevations are all zero -> matching will be XY-only (cloud z ignored)")
    dominant = stats["width_top_values"][0] if stats["width_top_values"] else None
    if dominant and dominant["share"] > 0.8:
        log.info("initial width state: %.1f%% of all lane-width records are a=%.2f m "
                 "(the flat default this pipeline corrects)",
                 100 * dominant["share"], dominant["a_m"])

    report = {"environment": env, "rosbag": bag, "extrinsics": extr, "xodr": xodr}
    with open(os.path.join(out_dir, "audit_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    _write_md(os.path.join(out_dir, "audit_report.md"), ctx, report)
    return {
        "bag_duration_s": bag["duration_s"],
        "rtk_fixed_share": bag["topics"]["gnss"]["rtk_fixed_share"],
        "parked_intervals": len(bag["topics"]["gnss"]["parked_intervals"]),
        "xodr_roads": xodr["roads_total"],
        "xodr_dominant_width": dominant,
        "t_lidar_imu": extr["t_lidar_imu"],
    }


def _write_md(path: str, ctx: RunContext, r: dict) -> None:
    g = r["rosbag"]["topics"]["gnss"]
    lid = r["rosbag"]["topics"]["lidar"]
    imu = r["rosbag"]["topics"]["imu"]
    x = r["xodr"]
    lines = [
        "# lanefit audit report", "",
        f"- bag: `{ctx.bag}`", f"- xodr: `{ctx.xodr}`", "",
        "## rosbag",
        f"- duration {r['rosbag']['duration_s']:.1f} s",
        f"- lidar `{lid['name']}`: frame `{lid.get('frame_id')}`, fields {lid.get('fields')}, "
        f"time field `{lid.get('time_field')}` ({lid.get('time_semantics', '-')})",
        f"- imu `{imu['name']}`: {imu.get('rate_hz')} Hz, gaps>100ms: "
        f"{imu.get('gaps_over_100ms')} (max {imu.get('gap_max_ms')} ms)",
        f"- gnss `{g['name']}`: {g.get('count_read')} epochs, RTK-fixed share "
        f"{g.get('rtk_fixed_share')}, stationary runs (s): {g.get('stationary_runs_s')}",
        f"- {g.get('height_note', '')}",
        f"- derived T_lidar_imu: {r['extrinsics']['t_lidar_imu']} "
        f"({r['extrinsics']['imu_frame']} -> {r['extrinsics']['lidar_frame']})", "",
        "## xodr (initial measurements)",
        f"- geoReference: `{x['geo_reference']}`",
        f"- roads: {x['roads_total']} ({x['roads_normal']} normal / {x['roads_junction']} junction)",
        f"- geometry census: {x['geometry_census']}",
        f"- lane types: {x['lane_type_census']}",
        f"- width records: {x['width_records_total']}; top values: {x['width_top_values']}",
        f"- elevation records: {x['elevation_records']} ({x['elevation_nonzero']} non-zero)",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
