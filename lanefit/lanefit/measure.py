"""measure_widths stage: ground extraction, marking detection, dual-bound edge widths.

Method (validated on the ServiceCenterLoop dataset; see the map_conflation notes):
  1. Station frame along the driven RTK path. Stationary epochs are deduplicated
     FIRST — duplicated positions produce zero-length tangents with noise-random
     directions that scramble the (s, t) frame near stops.
  2. Ground = points within a band around the trajectory-anchored road level
     (RTK z + data-estimated antenna offset). Robust against low outliers.
  3. Painted-line tracks from adaptive intensity peaks that are narrow (rejects
     bright-but-wide grass) and z-smooth (rejects vegetation), chained across
     sections with dash tolerance.
  4. Dual-bound carriageway edges by dynamic programming per side:
       INNER = traveled band (weak-bright transition, inward bias)
       OUTER = pavement extent (strong-bright transition = asphalt+add, plus
               strong curb steps, outward bias)
     DP cost = candidate base + bias*|t| + jump_w*|dt|; evidence-free sections
     carry the previous lateral position at gap_cost and are flagged conf 0.

  NOTE vs the legacy scripts: the OUTER intensity threshold here is asphalt+add
  (the legacy bright_factor=99 made max(99*asphalt, ...) unreachable, so legacy
  OUTER was z-step-driven only; final picks were unaffected because selection
  prefers the inner end, but the outer bound is now what it claims to be).
"""
from __future__ import annotations

import csv
import json
import logging
import os

import numpy as np

from .config import Config
from .runctx import RunContext

log = logging.getLogger("lanefit")


# ---------------- station frame + ground ----------------
def build_ground(ctx: RunContext, cfg: Config) -> dict:
    import open3d as o3d
    from scipy.spatial import cKDTree

    pcd_path = ctx.summary("georeference").get("pcd") or ctx.path("georeference",
                                                                  "georef_map_slam.pcd")
    pcd = o3d.t.io.read_point_cloud(pcd_path)
    xyz = pcd.point["positions"].numpy().astype(np.float64)
    inten = pcd.point["intensity"].numpy().ravel().astype(np.float32)

    rows = list(csv.DictReader(open(ctx.path("extract_trajectory", "gnss_trajectory.csv"))))
    txy = np.array([[float(r["x_xodr"]), float(r["y_xodr"])] for r in rows])
    tz = np.array([float(r["height_msl"]) for r in rows])

    # stationary dedupe (the audit-found bug fix)
    eps = float(cfg("ground.stationary_dedupe"))
    keep = [0]
    for i in range(1, len(txy)):
        if np.linalg.norm(txy[i] - txy[keep[-1]]) >= eps:
            keep.append(i)
    txy, tz = txy[keep], tz[keep]
    log.info("trajectory epochs after stationary dedupe: %d/%d", len(keep), len(rows))

    # densify to ~1 m stations
    seg = np.diff(txy, axis=0)
    seglen = np.linalg.norm(seg, axis=1)
    sx, sz = [txy[0]], [tz[0]]
    for p0, z0, s, dz, l in zip(txy[:-1], tz[:-1], seg, np.diff(tz), seglen):
        n = max(1, int(np.ceil(l)))
        for k in range(1, n + 1):
            sx.append(p0 + s * k / n)
            sz.append(z0 + dz * k / n)
    stations, st_z = np.array(sx), np.array(sz)

    tree = cKDTree(stations)
    d, idx = tree.query(xyz[:, :2], workers=-1)
    m = d <= float(cfg("ground.corridor"))
    xyz, inten, d, idx = xyz[m], inten[m], d[m], idx[m]

    near = d <= float(cfg("ground.near_path"))
    dz_near = xyz[near, 2] - st_z[idx[near]]
    hist, edges = np.histogram(dz_near, bins=200, range=(-5, 1))
    mode_dz = edges[np.argmax(hist)] + (edges[1] - edges[0]) / 2
    band = float(cfg("ground.band"))
    g = np.abs(xyz[:, 2] - (st_z[idx] + mode_dz)) <= band
    log.info("corridor %s pts; road level = traj_z %+0.2f m; ground band ±%.2f -> %s pts",
             f"{len(xyz):,}", mode_dz, band, f"{g.sum():,}")
    if g.sum() < 50_000:
        raise RuntimeError("too few ground points — check georeferencing / corridor settings")

    out = ctx.path("measure_widths", "ground.npz")
    np.savez_compressed(out, xyz=xyz[g].astype(np.float32), intensity=inten[g],
                        stations=stations.astype(np.float32),
                        station_z=st_z.astype(np.float32),
                        station_idx=idx[g].astype(np.int32),
                        mode_dz=np.float32(mode_dz))
    return {"ground_points": int(g.sum()), "stations": len(stations),
            "antenna_offset_m": round(float(mode_dz), 2)}


def _station_frame(d: dict) -> tuple:
    stations = d["stations"].astype(np.float64)
    xyz = d["xyz"].astype(np.float64)
    inten = d["intensity"].astype(np.float64)
    sidx = d["station_idx"]
    seg = np.diff(stations, axis=0)
    arclen = np.concatenate([[0], np.cumsum(np.linalg.norm(seg, axis=1))])
    tang = np.vstack([seg[0], seg])
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    normal = np.column_stack([-tang[:, 1], tang[:, 0]])
    rel = xyz[:, :2] - stations[sidx]
    s = arclen[sidx] + np.einsum("ij,ij->i", rel, tang[sidx])
    t = np.einsum("ij,ij->i", rel, normal[sidx])
    return stations, arclen, tang, normal, xyz, inten, s, t


# ---------------- markings ----------------
def detect_markings(ground_npz: str, out_csv: str, cfg: Config) -> dict:
    p = cfg.section("markings")
    d = np.load(ground_npz)
    stations, arclen, tang, normal, xyz, inten, s, t = _station_frame(d)
    ct = float(p["carriage_t"])
    m = np.abs(t) <= ct + 2
    xyz, inten, s, t = xyz[m], inten[m], s[m], t[m]

    sec_len = float(p["section_len"])
    nsec = int(np.ceil(max(s.max(), 1) / sec_len))
    sec = np.clip((s / sec_len).astype(np.int64), 0, nsec - 1)
    order = np.argsort(sec, kind="stable")
    bounds = np.searchsorted(sec[order], np.arange(nsec + 1))
    tbin = 0.05
    tgrid = np.arange(-ct, ct + tbin, tbin)
    kernel = np.array([1, 4, 6, 4, 1], float)
    kernel /= kernel.sum()

    sec_peaks: list[list] = [[] for _ in range(nsec)]
    for k in range(nsec):
        a, b = bounds[k], bounds[k + 1]
        if b - a < 50:
            continue
        ii = order[a:b]
        tt, zz, vv = t[ii], xyz[ii, 2], inten[ii]
        cw = np.abs(tt) <= ct
        if cw.sum() < 50:
            continue
        med = np.median(vv[cw])
        mad = np.median(np.abs(vv[cw] - med))
        thr = max(med + float(p["k_mad"]) * 1.4826 * mad, float(p["abs_min"]))
        cand = cw & (vv >= thr)
        if cand.sum() < int(p["peak_min_pts"]):
            continue
        h, _ = np.histogram(tt[cand], bins=tgrid)
        hs = np.convolve(h, kernel, mode="same")
        for j in range(1, len(hs) - 1):
            if not (hs[j] > hs[j - 1] and hs[j] >= hs[j + 1]):
                continue
            tc = tgrid[j] + tbin / 2
            sel = cand & (np.abs(tt - tc) <= 0.30)
            if sel.sum() < int(p["peak_min_pts"]):
                continue
            t_med = np.median(tt[sel])
            fine = cand & (np.abs(tt - t_med) <= 0.25)
            if fine.sum() < int(p["peak_min_pts"]):
                continue
            if tt[fine].std() > float(p["peak_max_std_t"]) or \
               zz[fine].std() > float(p["peak_max_std_z"]):
                continue
            sec_peaks[k].append((float(np.median(tt[fine])), int(fine.sum())))

    # section-by-section tracker (dash tolerant)
    tracks, active = [], []
    for k in range(nsec):
        evs = sorted(sec_peaks[k])
        used = [False] * len(evs)
        for a in active:
            best, bd = -1, float(p["track_dt"])
            for j, e in enumerate(evs):
                if not used[j] and abs(e[0] - a["t"]) <= bd:
                    best, bd = j, abs(e[0] - a["t"])
            if best >= 0:
                used[best] = True
                a.update(t=evs[best][0], last=k)
                a["rows"].append((k, *evs[best]))
        for j, e in enumerate(evs):
            if not used[j]:
                active.append({"t": e[0], "last": k, "rows": [(k, *e)]})
        still = []
        for a in active:
            if k - a["last"] > int(p["track_gap"]):
                r = a["rows"]
                if len(r) >= int(p["min_hits"]) and \
                   r[-1][0] - r[0][0] >= int(p["min_span_sections"]):
                    tracks.append(r)
            else:
                still.append(a)
        active = still
    for a in active:
        r = a["rows"]
        if len(r) >= int(p["min_hits"]) and r[-1][0] - r[0][0] >= int(p["min_span_sections"]):
            tracks.append(r)

    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["track_id", "s_m", "t_m", "npts"])
        for tid, tr in enumerate(tracks):
            for k, tv, n in tr:
                w.writerow([tid, f"{(k + 0.5) * sec_len:.1f}", f"{tv:.3f}", n])
    n_peaks = sum(len(v) for v in sec_peaks)
    log.info("markings: %d narrow peaks -> %d persistent tracks", n_peaks, len(tracks))
    return {"peaks": n_peaks, "tracks": len(tracks)}


# ---------------- dual-bound widths ----------------
def _candidates(profiles, marks, nsec, side_cfg: dict, wcfg: dict, use_marks: bool):
    tbin, tmax = wcfg["tbin"], wcfg["tmax"]
    nbin = int(2 * tmax / tbin)
    c0 = nbin // 2
    sustain = int(wcfg["sustain"])
    emin, emax = wcfg["edge_min_t"], wcfg["edge_max_t"]
    factor = float(side_cfg["bright_factor"])
    add = float(side_cfg["bright_add"])
    curb = float(side_cfg["curb"])
    cost = side_cfg["cost"]

    candL: list[list] = [[] for _ in range(nsec)]
    candR: list[list] = [[] for _ in range(nsec)]
    for k in range(nsec):
        if profiles[k] is None:
            continue
        medv, medz, asphalt = profiles[k]
        thr = asphalt + add if factor <= 0 else max(asphalt * factor, asphalt + add)
        for side, cand in ((+1, candL), (-1, candR)):
            rng = range(c0, nbin - sustain) if side > 0 else range(c0, sustain, -1)
            for j in rng:
                tv = (j + 0.5) * tbin - tmax
                if abs(tv) < emin or abs(tv) > emax:
                    continue
                nxt = medv[j:j + sustain] if side > 0 else medv[j - sustain + 1:j + 1]
                prv = medv[j - side]
                if np.isfinite(nxt).all() and (nxt >= thr).all() and \
                   np.isfinite(prv) and prv < thr:
                    cand[k].append((tv, "int", float(cost["int"])))
                z_in = medz[j - side] if 0 <= j - side < nbin else np.nan
                z_out = medz[j + side] if 0 <= j + side < nbin else np.nan
                if np.isfinite(z_in) and np.isfinite(z_out) and abs(z_out - z_in) >= curb:
                    zo = medz[j + side:j + 3 * side:side]
                    zo = zo[np.isfinite(zo)]
                    if len(zo) and (np.abs(zo - z_in) >= curb * 0.7).all():
                        cand[k].append((tv, "z", float(cost["z"])))
        if use_marks:
            for mv in marks.get(k, []):
                if emin <= abs(mv) <= emax:
                    (candL if mv > 0 else candR)[k].append((mv, "mark", float(cost["mark"])))
    merge_t = float(wcfg["merge_t"])
    for cands in (candL, candR):
        for k in range(nsec):
            out = []
            for c in sorted(cands[k]):
                if out and abs(c[0] - out[-1][0]) <= merge_t:
                    out[-1] = ((c[0] + out[-1][0]) / 2, out[-1][1] + "+" + c[1],
                               min(out[-1][2], c[2]) - 0.5)
                else:
                    out.append(c)
            cands[k] = out
    return candL, candR


def _dp_track(cands, nsec, bias, jump_w, gap_cost):
    INF = 1e18
    dp_c, dp_p, dp_t, dp_s = [], [], [], []
    prev = None
    for k in range(nsec):
        if cands[k]:
            cur = cands[k]
            cost = np.full(len(cur), INF)
            prv = np.full(len(cur), -1, int)
            for i, (tv, src, base) in enumerate(cur):
                base = base + bias * abs(tv)
                if prev is None:
                    cost[i] = base
                else:
                    trans = dp_c[prev] + jump_w * np.abs(dp_t[prev] - tv)
                    jb = int(np.argmin(trans))
                    cost[i] = trans[jb] + base
                    prv[i] = jb
            dp_c.append(cost)
            dp_p.append(prv)
            dp_t.append(np.array([c[0] for c in cur]))
            dp_s.append([c[1] for c in cur])
            prev = k
        elif prev is None:
            dp_c.append(None); dp_p.append(None); dp_t.append(None); dp_s.append(None)
        else:
            dp_c.append(dp_c[prev] + gap_cost)
            dp_p.append(np.arange(len(dp_c[prev])))
            dp_t.append(dp_t[prev])
            dp_s.append(["carry"] * len(dp_t[prev]))
            prev = k
    res_t = np.full(nsec, np.nan)
    res_s = [""] * nsec
    last = next((k for k in range(nsec - 1, -1, -1) if dp_c[k] is not None), None)
    if last is None:
        return res_t, res_s
    i, k = int(np.argmin(dp_c[last])), last
    while k >= 0 and dp_c[k] is not None:
        res_t[k] = dp_t[k][i]
        res_s[k] = dp_s[k][i]
        pi = dp_p[k][i]
        if pi < 0:
            break
        kk = k - 1
        while kk >= 0 and dp_c[kk] is None:
            kk -= 1
        if kk < 0:
            break
        i, k = int(pi), kk
    return res_t, res_s


def _conf(src: str) -> int:
    if src in ("", "carry"):
        return 0
    return 2 if ("+" in src or src == "mark") else 1


def measure(ground_npz: str, marks_csv: str, out_csv: str, cfg: Config) -> dict:
    w = cfg.section("widths")
    sec_len = float(cfg("markings.section_len"))
    d = np.load(ground_npz)
    stations, arclen, tang, normal, xyz, inten, s, t = _station_frame(d)
    tmax = float(w["tmax"])
    m = np.abs(t) <= tmax
    xyz, inten, s, t = xyz[m], inten[m], s[m], t[m]

    nsec = int(np.ceil(max(s.max(), 1) / sec_len))
    sec = np.clip((s / sec_len).astype(np.int64), 0, nsec - 1)
    order = np.argsort(sec, kind="stable")
    bounds = np.searchsorted(sec[order], np.arange(nsec + 1))
    tbin = float(w["tbin"])
    nbin = int(2 * tmax / tbin)
    c0 = nbin // 2

    profiles: list = [None] * nsec
    for k in range(nsec):
        a, b = bounds[k], bounds[k + 1]
        if b - a < 80:
            continue
        ii = order[a:b]
        tt, zz, vv = t[ii], xyz[ii, 2], inten[ii]
        bi = np.clip(((tt + tmax) / tbin).astype(int), 0, nbin - 1)
        cnt = np.bincount(bi, minlength=nbin)
        medv = np.full(nbin, np.nan)
        medz = np.full(nbin, np.nan)
        for u in np.nonzero(cnt >= int(w["min_bin_pts"]))[0]:
            medv[u] = np.median(vv[bi == u])
            medz[u] = np.median(zz[bi == u])
        ctr = medv[c0 - 4:c0 + 5]
        ctr = ctr[np.isfinite(ctr)]
        if len(ctr) >= 3:
            profiles[k] = (medv, medz, float(np.median(ctr)))

    marks: dict[int, list[float]] = {}
    if os.path.exists(marks_csv):
        for r in csv.DictReader(open(marks_csv)):
            marks.setdefault(int(float(r["s_m"]) / sec_len), []).append(float(r["t_m"]))

    jw, gc = float(w["jump_w"]), float(w["gap_cost"])
    cLi, cRi = _candidates(profiles, marks, nsec, w["inner"], w, use_marks=True)
    cLo, cRo = _candidates(profiles, marks, nsec, w["outer"], w, use_marks=True)
    tLi, sLi = _dp_track(cLi, nsec, float(w["inner"]["bias"]), jw, gc)
    tRi, sRi = _dp_track(cRi, nsec, float(w["inner"]["bias"]), jw, gc)
    tLo, sLo = _dp_track(cLo, nsec, float(w["outer"]["bias"]), jw, gc)
    tRo, sRo = _dp_track(cRo, nsec, float(w["outer"]["bias"]), jw, gc)

    sw = np.isfinite(tLo) & np.isfinite(tLi) & (tLo < tLi)
    tLo[sw] = tLi[sw]
    sw = np.isfinite(tRo) & np.isfinite(tRi) & (tRo > tRi)
    tRo[sw] = tRi[sw]

    with open(out_csv, "w", newline="") as f:
        cw = csv.writer(f)
        cw.writerow(["s_m", "x", "y", "heading_rad",
                     "t_left_in", "t_right_in", "width_in",
                     "t_left_out", "t_right_out", "width_out",
                     "conf_in", "conf_out", "src_left_in", "src_right_in",
                     "src_left_out", "src_right_out", "mark_ts"])
        n_rows = 0
        for k in range(nsec):
            if not (np.isfinite(tLi[k]) and np.isfinite(tRi[k])):
                continue
            sc = (k + 0.5) * sec_len
            j = int(np.clip(np.searchsorted(arclen, sc), 0, len(stations) - 1))
            hd = float(np.arctan2(tang[j, 1], tang[j, 0]))
            ci = min(_conf(sLi[k]), _conf(sRi[k]))
            has_o = np.isfinite(tLo[k]) and np.isfinite(tRo[k])
            co = min(_conf(sLo[k]), _conf(sRo[k])) if has_o else 0
            cw.writerow([f"{sc:.1f}", f"{stations[j][0]:.3f}", f"{stations[j][1]:.3f}",
                         f"{hd:.4f}", f"{tLi[k]:.2f}", f"{tRi[k]:.2f}",
                         f"{tLi[k] - tRi[k]:.2f}",
                         f"{tLo[k]:.2f}" if has_o else "",
                         f"{tRo[k]:.2f}" if has_o else "",
                         f"{tLo[k] - tRo[k]:.2f}" if has_o else "",
                         ci, co, sLi[k], sRi[k], sLo[k], sRo[k],
                         json.dumps([round(v, 2) for v in sorted(marks.get(k, []))])])
            n_rows += 1

    win = tLi - tRi
    q = np.isfinite(win)
    med_in = float(np.nanmedian(win[q])) if q.any() else float("nan")
    wout = tLo - tRo
    qo = np.isfinite(wout)
    med_out = float(np.nanmedian(wout[qo])) if qo.any() else float("nan")
    log.info("widths: %d sections; inner median %.2f m, outer median %.2f m",
             n_rows, med_in, med_out)
    return {"sections": n_rows, "median_width_in": round(med_in, 2),
            "median_width_out": round(med_out, 2)}


def run(ctx: RunContext, cfg: Config) -> dict:
    g = build_ground(ctx, cfg)
    ground_npz = ctx.path("measure_widths", "ground.npz")
    marks_csv = ctx.path("measure_widths", "marking_tracks.csv")
    mk = detect_markings(ground_npz, marks_csv, cfg)
    widths_csv = ctx.path("measure_widths", "widths.csv")
    wd = measure(ground_npz, marks_csv, widths_csv, cfg)
    from .figures import width_profile_chart
    width_profile_chart(widths_csv, ctx.path("measure_widths", "width_profile.png"))
    return {**g, **mk, **wd, "widths_csv": widths_csv}
