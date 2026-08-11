"""slam stage: generate a glim run-config from the base CPU config and run glim_rosbag.

Config edits are done on parsed JSON (comments stripped), not string surgery.
T_lidar_imu comes from the audit stage (tf_static-derived) unless overridden.
A short smoke run precedes the full pass; SLAM output is QC'd against the GNSS
trajectory (path length, start/end gap) before the stage is declared done.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import subprocess

import numpy as np

from .config import Config
from .runctx import RunContext
from .util import load_jsonc

log = logging.getLogger("lanefit")


def _write_glim_config(base_dir: str, out_dir: str, cfg: Config, t_lidar_imu: list) -> None:
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    shutil.copytree(base_dir, out_dir)

    ros_p = os.path.join(out_dir, "config_ros.json")
    d = load_jsonc(ros_p)
    d["glim_ros"]["points_topic"] = cfg("topics.lidar")
    d["glim_ros"]["imu_topic"] = cfg("topics.imu")
    d["glim_ros"]["extension_modules"] = ["libmemory_monitor.so"]  # headless
    json.dump(d, open(ros_p, "w"), indent=2)

    sen_p = os.path.join(out_dir, "config_sensors.json")
    d = load_jsonc(sen_p)
    s = d["sensors"]
    s["T_lidar_imu"] = [float(v) for v in t_lidar_imu]
    s["ring_field"] = cfg("slam.ring_field")
    s["autoconf_perpoint_times"] = False
    s["perpoint_relative_time"] = True
    # glim's PointCloud2 converter divides UINT32 'time_stamp' ns by 1e9 itself;
    # a 1e-9 here would double-scale and silently break deskewing.
    s["perpoint_time_scale"] = float(cfg("slam.perpoint_time_scale"))
    json.dump(d, open(sen_p, "w"), indent=2)

    main_p = os.path.join(out_dir, "config.json")
    d = load_jsonc(main_p)
    root_key = next(iter(d))            # glim uses a single root ("global")
    for k, v in d[root_key].items():
        if isinstance(v, str) and v.endswith("_gpu.json"):
            d[root_key][k] = v.replace("_gpu.json", "_cpu.json")
    json.dump(d, open(main_p, "w"), indent=2)


def _run_glim(bag: str, config_path: str, dump_path: str, duration: float | None,
              log_file: str) -> None:
    cmd = ["ros2", "run", "glim_ros", "glim_rosbag", bag, "--ros-args",
           "-p", f"config_path:={config_path}",
           "-p", "auto_quit:=true",
           "-p", f"dump_path:={dump_path}"]
    if duration:
        cmd += ["-p", f"playback_duration:={duration}"]
    if os.path.isdir(dump_path):
        shutil.rmtree(dump_path)
    log.info("glim: %s", " ".join(cmd))
    with open(log_file, "w") as lf:
        res = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if res.returncode != 0:
        raise RuntimeError(f"glim_rosbag exited {res.returncode} — see {log_file}")
    traj = os.path.join(dump_path, "traj_lidar.txt")
    if not os.path.exists(traj) or os.path.getsize(traj) == 0:
        raise RuntimeError(f"glim produced no trajectory — see {log_file}")


def _traj_qc(dump_path: str, gnss_csv: str) -> dict:
    T = np.loadtxt(os.path.join(dump_path, "traj_lidar.txt"))
    xyz = T[:, 1:4]
    slam_len = float(np.linalg.norm(np.diff(xyz, axis=0), axis=1).sum())
    slam_gap = float(np.linalg.norm(xyz[0] - xyz[-1]))
    g = np.array([[float(r["x_xodr"]), float(r["y_xodr"])]
                  for r in csv.DictReader(open(gnss_csv))])
    gnss_len = float(np.linalg.norm(np.diff(g, axis=0), axis=1).sum())
    gnss_gap = float(np.linalg.norm(g[0] - g[-1]))
    len_err = abs(slam_len - gnss_len) / max(gnss_len, 1e-6)
    qc = {"poses": len(T), "slam_path_m": round(slam_len, 1), "gnss_path_m": round(gnss_len, 1),
          "path_length_error": round(len_err, 4),
          "slam_endgap_m": round(slam_gap, 1), "gnss_endgap_m": round(gnss_gap, 1),
          "slam_z_extent_m": round(float(xyz[:, 2].ptp()), 1)}
    if len_err > 0.05:
        raise RuntimeError(f"SLAM path length differs from GNSS by {100*len_err:.1f}% — "
                           "check IMU/extrinsics/time config before georeferencing")
    if qc["slam_z_extent_m"] > 5:
        log.warning("SLAM z drift %.1f m (site GNSS z extent is usually ~1 m) — "
                    "rubber-sheeting will correct it, but expect a large Umeyama residual",
                    qc["slam_z_extent_m"])
    return qc


def run(ctx: RunContext, cfg: Config) -> dict:
    if cfg("georeference.method", "flexcloud") == "ins_direct":
        log.info("georeference.method=ins_direct -> SLAM not needed, skipping")
        return {"skipped": "ins_direct georeferencing does not use SLAM"}
    t_li = cfg("slam.t_lidar_imu", None) or ctx.summary("audit").get("t_lidar_imu")
    if not t_li:
        raise RuntimeError("no T_lidar_imu (audit stage not run and no override in config)")
    config_path = ctx.path("slam", "glim_config")
    _write_glim_config(cfg("slam.base_config"), config_path, cfg, t_li)

    smoke = float(cfg("slam.smoke_duration"))
    if smoke > 0:
        log.info("smoke run (%.0f s of bag) ...", smoke)
        _run_glim(ctx.bag, config_path, ctx.path("slam", "dump_smoke"), smoke,
                  ctx.path("slam", "glim_smoke.log"))
        log.info("smoke run OK")

    log.info("full SLAM pass ...")
    dump = ctx.path("slam", "dump")
    _run_glim(ctx.bag, config_path, dump, None, ctx.path("slam", "glim_full.log"))

    gnss_csv = ctx.path("extract_trajectory", "gnss_trajectory.csv")
    qc = _traj_qc(dump, gnss_csv)
    log.info("SLAM QC: %s", qc)
    return {"dump": dump, "config": config_path, **qc}
