"""ins_direct georeferencing: project raw scans with the high-rate RTK-INS pose.

No SLAM, no spatial warp — each point is placed with the interpolated INS pose at
its own scan time, so there is no drift to correct and multi-pass surfaces align
(validated: 4 cm ground thickness vs ~66 cm for the SLAM+rubber-sheet path on the
same data). Requires continuous RTK-fixed INS (audit reports the fixed share).

Handled here (each was a real failure mode found on the reference dataset):
  - boresight: the LiDAR mount rotation vs tf_static's claim (often identity in
    URDFs while the physical mount is tilted). Config: boresight_pitch/roll_deg.
  - INSPVA height is ELLIPSOIDAL; INSPVAX is MSL. Output is shifted to MSL using
    the undulation from the INSPVAX stream (consistent with extract_trajectory).
  - mirror reflections (ghost roads metres below grade): range_max cap +
    below-trajectory gate.
  - motion deskew: per-point timestamps, pose interpolated in blocks per scan.
"""
from __future__ import annotations

import logging
import math
import os

import numpy as np

from .config import Config
from .runctx import RunContext
from .util import TfTree, iter_messages
from .xodr_io import parse_xodr

log = logging.getLogger("lanefit")


def _rz(c):
    return np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])


def _rx(c):
    return np.array([[1, 0, 0], [0, np.cos(c), -np.sin(c)], [0, np.sin(c), np.cos(c)]])


def _ry(c):
    return np.array([[np.cos(c), 0, np.sin(c)], [0, 1, 0], [-np.sin(c), 0, np.cos(c)]])


def _r_enu_base(roll, pitch, az):
    """NovAtel SPAN roll/pitch/azimuth -> ENU rotation of base_link (x fwd, y left, z up)."""
    return _rz(np.pi / 2 - az) @ _ry(-pitch) @ _rx(roll)


def _tf_translations(bag: str, cfg: Config) -> tuple[np.ndarray, np.ndarray, str, str]:
    """(base->lidar translation, base->antenna lever arm) from /tf_static."""
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    imu_frame = lidar_frame = None
    for _, m, _ in iter_messages(bag, [cfg("topics.imu")]):
        imu_frame = m.header.frame_id
        break
    for _, m, _ in iter_messages(bag, [cfg("topics.lidar")]):
        lidar_frame = m.header.frame_id
        break
    tree = TfTree()
    from .util import open_bag_reader
    r = open_bag_reader(bag, ["/tf_static"])
    mt = get_message("tf2_msgs/msg/TFMessage")
    gnss_frame = None
    frames = set()
    while r.has_next():
        _, data, _ = r.read_next()
        for tr in deserialize_message(data, mt).transforms:
            t, q = tr.transform.translation, tr.transform.rotation
            tree.add(tr.header.frame_id, tr.child_frame_id,
                     (t.x, t.y, t.z), (q.x, q.y, q.z, q.w))
            frames.add(tr.child_frame_id)
    gnss_frame = next((f for f in frames if "gnss" in f), imu_frame)
    # p_lidar_in_base: invert T_lidar_base
    # transform(src, dst) returns T_dst_src (p_dst = R p_src + t): t is the SRC
    # origin expressed in DST coordinates — use directly, no extra negation.
    t_li, _ = tree.transform(lidar_frame, imu_frame)       # lidar origin in base frame
    t_bl_velo = np.array(t_li)                             # base -> lidar translation
    t_lever, _ = tree.transform(gnss_frame, imu_frame)     # antenna origin in base frame
    lever = np.array(t_lever)
    return t_bl_velo, lever, imu_frame, lidar_frame


def run(ctx: RunContext, cfg: Config) -> dict:
    g = cfg.section("georeference")
    header, _ = parse_xodr(ctx.xodr)
    from pyproj import Transformer
    tfm = Transformer.from_crs("EPSG:4326", header["geo_reference"], always_xy=True)

    t_bl_velo, lever, imu_frame, lidar_frame = _tf_translations(ctx.bag, cfg)
    log.info("tf: base->%s %s, antenna lever %s", lidar_frame,
             np.round(t_bl_velo, 4).tolist(), np.round(lever, 4).tolist())
    br = _ry(math.radians(float(g["boresight_pitch_deg"]))) @ \
         _rx(math.radians(float(g["boresight_roll_deg"])))

    # undulation (MSL = ellipsoidal - undulation) from the INSPVAX stream
    undulation = None
    for _, m, _ in iter_messages(ctx.bag, [cfg("topics.gnss")]):
        undulation = float(m.undulation)
        break
    if undulation is None:
        raise RuntimeError("no INSPVAX message for undulation")

    # ---- INS pose stream ----
    ts, px, py, pz, rr, pp, aa = [], [], [], [], [], [], []
    for _, m, _ in iter_messages(ctx.bag, [g["ins_topic"]]):
        t = m.header.stamp.sec + m.header.stamp.nanosec * 1e-9
        x, y = tfm.transform(m.longitude, m.latitude)
        ts.append(t); px.append(x); py.append(y)
        pz.append(m.height - undulation)                  # ellipsoidal -> MSL
        rr.append(math.radians(m.roll)); pp.append(math.radians(m.pitch))
        aa.append(math.radians(m.azimuth))
    ts = np.array(ts)
    pos = np.column_stack([px, py, pz])
    rr, pp = np.array(rr), np.array(pp)
    aa_un = np.unwrap(np.array(aa))
    if len(ts) < 100:
        raise RuntimeError(f"too few INS epochs on {g['ins_topic']}")
    log.info("INS: %d epochs @ %.0f Hz, undulation %.2f m", len(ts),
             len(ts) / (ts[-1] - ts[0]), undulation)

    # ---- project scans ----
    rng_min, rng_max = float(g["range_min"]), float(g["range_max"])
    below_max = float(g["below_traj_max"])
    nblk = int(g["deskew_blocks"])
    out_xyz, out_i = [], []
    n_scans = n_dropped_grade = 0
    for _, m, _ in iter_messages(ctx.bag, [cfg("topics.lidar")]):
        n_scans += 1
        hdr = m.header.stamp.sec + m.header.stamp.nanosec * 1e-9
        raw = np.frombuffer(bytes(m.data), np.uint8).reshape(-1, m.point_step)
        p = raw[:, 0:12].copy().view(np.float32).reshape(-1, 3).astype(np.float64)
        inten = raw[:, 12].astype(np.float32)
        t_abs = hdr + raw[:, 28:32].copy().view(np.uint32).ravel() / 1e9
        rng = np.linalg.norm(p, axis=1)
        keep = (rng > rng_min) & (rng < rng_max) & (t_abs >= ts[0]) & (t_abs <= ts[-1])
        p, inten, t_abs = p[keep], inten[keep], t_abs[keep]
        if not len(p):
            continue
        o = np.argsort(t_abs)
        p, inten, t_abs = p[o], inten[o], t_abs[o]
        edges = np.linspace(0, len(p), nblk + 1).astype(int)
        for a, b in zip(edges[:-1], edges[1:]):
            if b <= a:
                continue
            tm = t_abs[(a + b) // 2]
            R = _r_enu_base(np.interp(tm, ts, rr), np.interp(tm, ts, pp),
                            np.interp(tm, ts, aa_un))
            org = np.array([np.interp(tm, ts, pos[:, i]) for i in range(3)])
            base = (br @ p[a:b].T).T + t_bl_velo
            world = (R @ base.T).T + (org - R @ lever)
            grade_ok = world[:, 2] > org[2] - below_max
            n_dropped_grade += int((~grade_ok).sum())
            out_xyz.append(world[grade_ok].astype(np.float32))
            out_i.append(inten[a:b][grade_ok])
    xyz = np.concatenate(out_xyz)
    inten = np.concatenate(out_i)
    log.info("projected %d scans -> %s pts (%s dropped below grade)",
             n_scans, f"{len(xyz):,}", f"{n_dropped_grade:,}")

    # ---- voxelize + write ----
    voxel = float(g["merge_voxel"])
    keys = np.floor(xyz / voxel).astype(np.int64)
    _, idx, inv = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    acc = np.zeros((len(idx), 4))
    cnt = np.zeros(len(idx), np.int64)
    np.add.at(acc[:, :3], inv, xyz)
    np.add.at(acc[:, 3], inv, inten)
    np.add.at(cnt, inv, 1)
    xyz = (acc[:, :3] / cnt[:, None]).astype(np.float32)
    inten = (acc[:, 3] / cnt).astype(np.float32)
    n = len(xyz)
    out = ctx.path("georeference", "georef_map_ins.pcd")
    hdr_txt = ("# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\n"
               "FIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 1\n"
               f"WIDTH {n}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {n}\nDATA binary\n")
    with open(out, "wb") as f:
        f.write(hdr_txt.encode())
        f.write(np.column_stack([xyz, inten]).astype(np.float32).tobytes())

    # ---- QC: multi-pass ground thickness near the trajectory ----
    from scipy.spatial import cKDTree
    tree = cKDTree(pos[::25, :2])
    samp = xyz[:: max(1, n // 2_000_000)]
    d, _ = tree.query(samp[:, :2], workers=-1)
    sub = samp[d < 8.0]
    key = (np.floor(sub[:, 0]).astype(np.int64) << 20) + np.floor(sub[:, 1]).astype(np.int64)
    o = np.argsort(key)
    ks, zz = key[o], sub[o, 2]
    uq = np.unique(ks)
    st = np.searchsorted(ks, uq)
    en = np.append(st[1:], len(ks))
    spr = []
    for a, b in zip(st, en):
        if b - a >= 8:
            seg = np.sort(zz[a:b])
            k60 = max(3, int(0.6 * len(seg)))
            spr.append(np.percentile(seg[:k60], 95) - np.percentile(seg[:k60], 5))
    thick = float(np.median(spr)) if spr else float("nan")
    log.info("ins_direct: %s pts, ground thickness %.0f cm -> %s", f"{n:,}", thick * 100, out)
    if thick > 0.25:
        log.warning("ground thickness %.0f cm is high — check boresight calibration "
                    "(georeference.boresight_*_deg) and INS quality", thick * 100)
    return {"pcd": out, "points": n, "scans": n_scans,
            "ground_thickness_cm": round(thick * 100, 1),
            "dropped_below_grade": n_dropped_grade, "method": "ins_direct"}
