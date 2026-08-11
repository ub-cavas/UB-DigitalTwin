"""georeference stage: intensity-preserving submap merge + FlexCloud alignment.

FlexCloud input units (verified against FlexCloud source, and easy to get wrong):
  positions file : stamp in SECONDS  ("stamp x y z x_std y_std z_std")
  poses file     : stamp in SECONDS  (PoseStamped ctor multiplies by 1e9; feeding
                   nanoseconds overflows int64 -> bogus 'timestamp -9.2e9' errors)
  keyframe OUTPUT poses are nanoseconds and feed `georeferencing` as-is.
SLAM poses must sit strictly inside the GNSS time span (spline needs >=2 GNSS
frames before and >=3 after every keyframe) -> trim margins.
"""
from __future__ import annotations

import csv
import glob
import logging
import os
import re
import shutil
import subprocess

import numpy as np

from .config import Config
from .runctx import RunContext

log = logging.getLogger("lanefit")


# ---------------- submap merge (glim dump -> PCD with intensity) ----------------
def _read_t_world_origin(data_txt: str) -> np.ndarray:
    lines = open(data_txt).read().splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith("T_world_origin"):
            return np.array([list(map(float, lines[i + 1 + k].split())) for k in range(4)])
    raise ValueError(f"T_world_origin not found in {data_txt}")


def merge_submaps(dump: str, out_pcd: str, voxel: float) -> dict:
    subs = sorted(d for d in glob.glob(os.path.join(dump, "[0-9]" * 6)) if os.path.isdir(d))
    if not subs:
        raise RuntimeError(f"no submaps under {dump}")
    all_xyz, all_i = [], []
    for s in subs:
        pts = np.fromfile(os.path.join(s, "points_compact.bin"), np.float32).reshape(-1, 3)
        inten = np.fromfile(os.path.join(s, "intensities_compact.bin"), np.float32)
        if len(inten) != len(pts):
            log.warning("submap %s: %d pts vs %d intensities — skipped",
                        os.path.basename(s), len(pts), len(inten))
            continue
        T = _read_t_world_origin(os.path.join(s, "data.txt"))
        all_xyz.append(((T[:3, :3] @ pts.T).T + T[:3, 3]).astype(np.float32))
        all_i.append(inten)
    xyz = np.concatenate(all_xyz)
    inten = np.concatenate(all_i)
    raw_n = len(xyz)
    if voxel > 0:
        keys = np.floor(xyz / voxel).astype(np.int64)
        _, idx, inv = np.unique(keys, axis=0, return_index=True, return_inverse=True)
        acc = np.zeros((len(idx), 4), np.float64)
        cnt = np.zeros(len(idx), np.int64)
        np.add.at(acc[:, :3], inv, xyz)
        np.add.at(acc[:, 3], inv, inten)
        np.add.at(cnt, inv, 1)
        xyz = (acc[:, :3] / cnt[:, None]).astype(np.float32)
        inten = (acc[:, 3] / cnt).astype(np.float32)
    n = len(xyz)
    data = np.column_stack([xyz, inten]).astype(np.float32)
    header = ("# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\n"
              "FIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 1\n"
              f"WIDTH {n}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {n}\nDATA binary\n")
    with open(out_pcd, "wb") as f:
        f.write(header.encode())
        f.write(data.tobytes())
    log.info("merged %d submaps: %s pts raw -> %s voxelized (%.2f m), intensity "
             "[%.0f, %.0f]", len(subs), f"{raw_n:,}", f"{n:,}", voxel,
             float(inten.min()), float(inten.max()))
    return {"submaps": len(subs), "points_raw": raw_n, "points": n}


# ---------------- FlexCloud ----------------
def _write_inputs(gnss_csv: str, traj_txt: str, out_pos: str, out_pose: str,
                  m_start: float, m_end: float) -> tuple[int, int]:
    stamps = []
    with open(out_pos, "w") as f:
        for r in csv.DictReader(open(gnss_csv)):
            sec = int(r["stamp_ns"]) / 1e9
            stamps.append(sec)
            f.write(f"{sec:.9f} {r['x_xodr']} {r['y_xodr']} {r['height_msl']} "
                    f"{r['x_stdev']} {r['y_stdev']} {r['height_stdev']}\n")
    t_lo, t_hi = min(stamps) + m_start, max(stamps) - m_end
    kept = 0
    with open(out_pose, "w") as f:
        for line in open(traj_txt):
            p = line.split()
            if len(p) == 8 and t_lo <= float(p[0]) <= t_hi:
                f.write(line)
                kept += 1
    if kept < 50:
        raise RuntimeError(f"only {kept} SLAM poses inside GNSS coverage — check clocks")
    return len(stamps), kept


def _run(cmd: list[str], log_file: str) -> str:
    log.info("run: %s", " ".join(cmd))
    with open(log_file, "w") as lf:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, text=True)
        lf.write(res.stdout)
    if res.returncode != 0:
        raise RuntimeError(f"{cmd[2]} exited {res.returncode} — see {log_file}")
    return res.stdout


def run(ctx: RunContext, cfg: Config) -> dict:
    if cfg("georeference.method", "flexcloud") == "ins_direct":
        from . import ins_georef
        return ins_georef.run(ctx, cfg)
    d = ctx.dir("georeference")
    dump = ctx.summary("slam").get("dump") or ctx.path("slam", "dump")
    gnss_csv = ctx.path("extract_trajectory", "gnss_trajectory.csv")

    merge = merge_submaps(dump, os.path.join(d, "map_slam.pcd"),
                          float(cfg("georeference.merge_voxel")))

    n_pos, n_pose = _write_inputs(
        gnss_csv, os.path.join(dump, "traj_lidar.txt"),
        os.path.join(d, "positions.txt"), os.path.join(d, "poses.txt"),
        float(cfg("georeference.trim_start_margin")),
        float(cfg("georeference.trim_end_margin")))

    kf = os.path.join(d, "keyframes")
    if os.path.isdir(kf):
        shutil.rmtree(kf)
    os.makedirs(kf)
    _run(["ros2", "run", "flexcloud", "keyframe_interpolation",
          os.path.join(d, "positions.txt"), os.path.join(d, "poses.txt"), kf,
          "--interpolate"], os.path.join(d, "keyframe_interpolation.log"))
    for req in ("poses_keyframes.txt", "positions_interpolated.txt"):
        if not os.path.getsize(os.path.join(kf, req)):
            raise RuntimeError(f"keyframe_interpolation produced empty {req}")

    out = _run(["ros2", "run", "flexcloud", "georeferencing",
                os.path.join(kf, "positions_interpolated.txt"),
                os.path.join(kf, "poses_keyframes.txt"),
                "--pcd", os.path.join(d, "map_slam.pcd"),
                "--control-points", str(int(cfg("georeference.control_points"))),
                "--evaluation"], os.path.join(d, "georeferencing.log"))

    georef_pcd = os.path.join(d, "georef_map_slam.pcd")
    if not os.path.exists(georef_pcd):
        raise RuntimeError("FlexCloud did not write the georeferenced PCD")

    # parse the evaluation table: "RMSE   <aligned>   <rubber>"
    m = re.search(r"RMSE\s+([\d.]+)\s+([\d.]+)", re.sub(r"\x1b\[[0-9;]*m", "", out))
    rmse_rubber = float(m.group(2)) if m else float("nan")
    limit = float(cfg("georeference.max_rubber_rmse"))
    if not (rmse_rubber == rmse_rubber) or rmse_rubber > limit:
        raise RuntimeError(f"rubber-sheet RMSE {rmse_rubber} m exceeds limit {limit} m "
                           "(or missing) — georeferencing unreliable")
    log.info("georeference: rubber-sheet RMSE %.3f m, positions %d, poses %d",
             rmse_rubber, n_pos, n_pose)
    return {"pcd": georef_pcd, "rubber_rmse_m": rmse_rubber, **merge}
