#!/usr/bin/env python3
"""Per-road width diagram: LiDAR-measured profile vs original-xodr width, same area.

Top panel: map with ego trajectory + matched roads (colored, labeled).
Grid: one panel per corrected road; x = arclength along the road's reference line;
  - LiDAR inner..outer measured band (per 3 m station, continuous, conf-marked)
  - ORIGINAL xodr carriageway width evaluated continuously from the width
    polynomials of every driving lane (w = a + b ds + c ds^2 + d ds^3 per record,
    summed over lanes of the active laneSection) — NOT assumed constant
  - corrected (applied) constant width

Usage (in container, PYTHONPATH=/host_data/lanefit):
  python3 road_width_profiles.py <run_dir> <xodr> <out_png>
"""
import csv
import sys
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, "/host_data/lanefit")
from lanefit.xodr_io import parse_xodr  # noqa: E402

RUN, XODR, OUT = sys.argv[1], sys.argv[2], sys.argv[3]

# palette
SURFACE, PAGE = "#fcfcfb", "#f9f9f7"
INK, INK2, MUTED, BASE, GRID = "#0b0b0b", "#52514e", "#898781", "#c3c2b7", "#e1e0d9"
S1, S2, CRIT = "#2a78d6", "#1baf7a", "#d03b3b"
ROAD_COLORS = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7",
               "#e34948", "#e87ba4", "#eb6834", "#256abf"]

# ---------------- original xodr width polynomials per road ----------------
def parse_width_polys(xodr_path, road_ids):
    """road -> list of sections; each: (s_sec, [ per driving lane: [(sOffset,a,b,c,d)...] ])"""
    root = ET.parse(xodr_path).getroot()
    out = {}
    for road in root.findall("road"):
        rid = road.get("id")
        if rid not in road_ids:
            continue
        secs = []
        for ls in road.find("lanes").findall(".//laneSection"):
            lanes = []
            for side in ("left", "right"):
                se = ls.find(side)
                if se is None:
                    continue
                for lane in se.findall("lane"):
                    if lane.get("type") != "driving":
                        continue
                    recs = sorted(
                        (float(w.get("sOffset")), float(w.get("a")), float(w.get("b")),
                         float(w.get("c")), float(w.get("d")))
                        for w in lane.findall("width"))
                    if recs:
                        lanes.append(recs)
            secs.append((float(ls.get("s")), lanes))
        secs.sort(key=lambda q: q[0])
        out[rid] = secs
    return out


def orig_width_at(secs, s):
    """Total driving carriageway width of the ORIGINAL map at road arclength s."""
    sec = None
    for s0, lanes in secs:
        if s0 <= s:
            sec = (s0, lanes)
        else:
            break
    if sec is None or not sec[1]:
        return np.nan
    ds_sec = s - sec[0]
    total = 0.0
    for recs in sec[1]:
        rec = None
        for so, a, b, c, dd in recs:
            if so <= ds_sec:
                rec = (so, a, b, c, dd)
            else:
                break
        if rec is None:
            rec = recs[0]
        so, a, b, c, dd = rec
        u = ds_sec - so
        total += a + b * u + c * u * u + dd * u ** 3
    return total


# ---------------- load run data ----------------
matches = {r["road_id"]: r for r in
           csv.DictReader(open(f"{RUN}/conflate/road_matches.csv"))}
stations = []
for r in csv.DictReader(open(f"{RUN}/measure_widths/widths.csv")):
    stations.append((float(r["x"]), float(r["y"]), float(r["heading_rad"]),
                     float(r["width_in"]),
                     float(r["width_out"]) if r["width_out"] else np.nan,
                     int(r["conf_in"])))
stations = np.array(stations)
traj = np.array([[float(r["x_xodr"]), float(r["y_xodr"])] for r in
                 csv.DictReader(open(f"{RUN}/extract_trajectory/gnss_trajectory.csv"))])

_, roads = parse_xodr(XODR)
width_polys = parse_width_polys(XODR, set(matches))

# per-station road assignment (same rule as conflate: nearest + heading-parallel)
from scipy.spatial import cKDTree  # noqa: E402
samples, rid_list = [], []
for rid in matches:
    P = roads[rid].sample(2.0)
    ridx = len(rid_list)
    rid_list.append(rid)
    for x, y, h, s_road in P:
        samples.append((x, y, h, ridx, s_road))
samples = np.array(samples)
tree = cKDTree(samples[:, :2])

assign = {rid: [] for rid in matches}   # rid -> (s_road, w_in, w_out, conf)
for st in stations:
    if st[5] < 1:
        continue
    d, j = tree.query(st[:2])
    if d > 10.0 or abs(np.cos(st[2] - samples[j, 2])) < 0.85:
        continue
    rid = rid_list[int(samples[j, 3])]
    assign[rid].append((samples[j, 4], st[3], st[4], st[5]))

# ---------------- original width summary (printed) ----------------
print(f"{'road':>5} {'lanes':>5} {'orig carriageway over matched range':>38} "
      f"{'lidar inner med':>15} {'corrected':>9}")
for rid, r in sorted(matches.items(), key=lambda q: -int(q[1]["n_stations"])):
    pts = np.array(sorted(assign[rid]))
    if not len(pts):
        continue
    ss = np.linspace(pts[0, 0], pts[-1, 0], 50)
    ow = np.array([orig_width_at(width_polys[rid], s) for s in ss])
    print(f"{rid:>5} {r['n_driving_lanes']:>5} "
          f"min {np.nanmin(ow):5.2f} / med {np.nanmedian(ow):5.2f} / max {np.nanmax(ow):5.2f} m"
          f"{float(r['med_width_in']):>12.2f} m {float(r['carriageway_pick']):>8.2f} m")

# ---------------- figure ----------------
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.gridspec import GridSpec  # noqa: E402

order = sorted(matches, key=lambda q: -int(matches[q]["n_stations"]))
ncols = 3
nrows = int(np.ceil(len(order) / ncols))
fig = plt.figure(figsize=(15, 5.2 + 3.1 * nrows), dpi=150)
fig.patch.set_facecolor(PAGE)
gs = GridSpec(nrows + 2, ncols, figure=fig, height_ratios=[2.6, 0.001] + [1] * nrows,
              hspace=0.55, wspace=0.25)

# --- map panel ---
axm = fig.add_subplot(gs[0, :])
axm.set_facecolor(SURFACE)
col_of = {}
for i, rid in enumerate(order):
    c = ROAD_COLORS[i % len(ROAD_COLORS)]
    col_of[rid] = c
    P = roads[rid].sample(1.0)
    axm.plot(P[:, 0], P[:, 1], color=c, lw=3.0, solid_capstyle="round", zorder=3)
    mid = P[len(P) // 2]
    axm.annotate(rid, (mid[0], mid[1]), xytext=(mid[0], mid[1] + 8), fontsize=9,
                 color=INK, ha="center",
                 bbox=dict(boxstyle="round,pad=0.22", fc="white", ec=c, lw=1.0), zorder=6)
axm.plot(traj[:, 0], traj[:, 1], color=INK2, lw=1.1, ls=(0, (4, 3)), zorder=4,
         label="ego trajectory (RTK)")
axm.set_aspect("equal")
axm.set_title("Corrected roads and the ego trajectory (xodr frame)",
              color=INK, fontsize=12, loc="left", pad=10)
axm.tick_params(colors=MUTED, labelsize=8)
for sp in axm.spines.values():
    sp.set_color(BASE)
axm.set_ylim(axm.get_ylim()[0] - 18, axm.get_ylim()[1] + 6)
leg = axm.legend(loc="lower right", frameon=False, fontsize=9)
for t in leg.get_texts():
    t.set_color(INK2)

# --- per-road profile panels ---
for i, rid in enumerate(order):
    ax = fig.add_subplot(gs[2 + i // ncols, i % ncols])
    ax.set_facecolor(SURFACE)
    r = matches[rid]
    pts = np.array(sorted(assign[rid]))
    ss, win, wout, conf = pts[:, 0], pts[:, 1], pts[:, 2], pts[:, 3]

    sgrid = np.linspace(ss.min(), ss.max(), 100)
    ow = np.array([orig_width_at(width_polys[rid], s) for s in sgrid])

    ax.fill_between(ss, win, np.where(np.isfinite(wout), wout, win),
                    color=S2, alpha=0.12, lw=0)
    ax.plot(ss, wout, color=S2, lw=1.4)
    ax.plot(ss, win, color=S1, lw=1.8, marker="o", ms=2.5)
    ax.plot(sgrid, ow, color=INK2, lw=1.4, ls=(0, (5, 3)))
    corr = float(r["carriageway_pick"])
    ax.plot([ss.min(), ss.max()], [corr, corr], color=CRIT, lw=1.4, ls=(0, (1, 2)))
    m0 = conf < 1
    if m0.any():
        ax.scatter(ss[m0], win[m0], s=14, c=CRIT, marker="x", zorder=5)

    clamped = " · clamped" if r["clamped"] == "1" else ""
    ax.set_title(f"road {rid} — {r['n_driving_lanes']} lanes · {len(ss)} stations"
                 f"{clamped}", color=col_of[rid], fontsize=10, loc="left")
    ax.set_xlabel("s along road [m]", color=INK2, fontsize=8)
    ax.set_ylabel("carriageway [m]", color=INK2, fontsize=8)
    ax.set_ylim(0, 18)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(BASE)
    ax.tick_params(colors=MUTED, labelsize=7)

# figure-level legend
import matplotlib.lines as mlines  # noqa: E402
handles = [
    mlines.Line2D([], [], color=S1, lw=1.8, marker="o", ms=3, label="LiDAR inner (traveled band)"),
    mlines.Line2D([], [], color=S2, lw=1.4, label="LiDAR outer (pavement extent)"),
    mlines.Line2D([], [], color=INK2, lw=1.4, ls=(0, (5, 3)),
                  label="ORIGINAL xodr carriageway (Σ driving-lane width polys)"),
    mlines.Line2D([], [], color=CRIT, lw=1.4, ls=(0, (1, 2)), label="corrected (applied) width"),
]
fig.legend(handles=handles, loc="upper right", frameon=False, fontsize=9,
           bbox_to_anchor=(0.99, 0.985))
fig.suptitle("Road width measurements — LiDAR vs original OpenDRIVE, per road",
             color=INK, fontsize=13, x=0.01, ha="left")
fig.savefig(OUT, facecolor=fig.get_facecolor(), bbox_inches="tight")
print("wrote", OUT)
