#!/usr/bin/env python3
"""Spatial width diagram ("ladder" view): measured width drawn at its real location.

One map panel:
  - at every measured station, a crossbar spanning the ACTUAL measured edges
    (t_right..t_left of the LiDAR traveled band), colored by width -> you see the
    continuous width variation directly on the road
  - the ORIGINAL xodr carriageway as a dashed envelope (refline +- orig_width/2)
  - the ego RTK trajectory
  - one label per corrected road: original -> applied width (* = clamped)

Usage (in container, PYTHONPATH=/host_data/lanefit):
  python3 road_width_ladder.py <run_dir> <xodr> <out_png>
"""
import csv
import sys
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, "/host_data/lanefit")
from lanefit.xodr_io import parse_xodr  # noqa: E402

RUN, XODR, OUT = sys.argv[1], sys.argv[2], sys.argv[3]

SURFACE, PAGE = "#fcfcfb", "#f9f9f7"
INK, INK2, MUTED, BASE = "#0b0b0b", "#52514e", "#898781", "#c3c2b7"
SEQ = ["#86b6ef", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#104281"]

# ---------- original xodr width (evaluated, not assumed) ----------
def orig_widths(xodr_path, road_ids):
    root = ET.parse(xodr_path).getroot()
    out = {}
    for road in root.findall("road"):
        rid = road.get("id")
        if rid not in road_ids:
            continue
        tot = 0.0
        ls = road.find("lanes").find(".//laneSection")
        for side in ("left", "right"):
            se = ls.find(side)
            if se is None:
                continue
            for lane in se.findall("lane"):
                if lane.get("type") == "driving":
                    w = lane.find("width")
                    tot += float(w.get("a"))
        out[rid] = tot
    return out


matches = {r["road_id"]: r for r in csv.DictReader(open(f"{RUN}/conflate/road_matches.csv"))}
orig = orig_widths(XODR, set(matches))

st = []
for r in csv.DictReader(open(f"{RUN}/measure_widths/widths.csv")):
    st.append((float(r["x"]), float(r["y"]), float(r["heading_rad"]),
               float(r["t_left_in"]), float(r["t_right_in"]),
               float(r["width_in"]), int(r["conf_in"])))
st = np.array(st)
traj = np.array([[float(r["x_xodr"]), float(r["y_xodr"])] for r in
                 csv.DictReader(open(f"{RUN}/extract_trajectory/gnss_trajectory.csv"))])
d = np.load(f"{RUN}/measure_widths/ground.npz")
gnd, gi = d["xyz"], d["intensity"]

_, roads = parse_xodr(XODR)

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.cm import ScalarMappable  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402

cmap = LinearSegmentedColormap.from_list("blues", SEQ)
wvals = st[st[:, 6] >= 1, 5]
norm = Normalize(vmin=np.percentile(wvals, 5) - 0.5, vmax=np.percentile(wvals, 95) + 0.5)

fig, ax = plt.subplots(figsize=(16, 9), dpi=200)
fig.patch.set_facecolor(PAGE)
ax.set_facecolor(SURFACE)

# cloud backdrop
bbox = (gnd[:, 0].min() - 5, gnd[:, 0].max() + 5, gnd[:, 1].min() - 5, gnd[:, 1].max() + 5)
res = 0.25
px = ((gnd[:, 0] - bbox[0]) / res).astype(int)
py = ((gnd[:, 1] - bbox[2]) / res).astype(int)
W, H = int((bbox[1] - bbox[0]) / res) + 2, int((bbox[3] - bbox[2]) / res) + 2
img = np.zeros((H, W), np.float32)
np.maximum.at(img, (py, px), np.clip(gi / 60, 0.25, 1.0))
ax.imshow(np.ones((H, W, 3)) - (0.16 * img)[..., None],
          extent=[bbox[0], bbox[1], bbox[2], bbox[3]], origin="lower",
          interpolation="bilinear", zorder=0)

# ORIGINAL xodr envelope per corrected road (dashed)
for rid, r in matches.items():
    P = roads[rid].sample(1.5)
    hw = orig[rid] / 2
    nx, ny = -np.sin(P[:, 2]), np.cos(P[:, 2])
    for sgn in (+1, -1):
        ax.plot(P[:, 0] + sgn * nx * hw, P[:, 1] + sgn * ny * hw,
                color=INK2, lw=1.0, ls=(0, (5, 4)), zorder=2)

# measured-width rungs at their true positions
segs, cols = [], []
for x, y, h, tl, tr, w, conf in st:
    if conf < 1:
        continue
    nx, ny = -np.sin(h), np.cos(h)
    segs.append([(x + nx * tr, y + ny * tr), (x + nx * tl, y + ny * tl)])
    cols.append(cmap(norm(w)))
ax.add_collection(LineCollection(segs, colors=cols, linewidths=3.2,
                                 capstyle="round", zorder=3))

# ego trajectory
ax.plot(traj[:, 0], traj[:, 1], color=INK, lw=1.0, ls=(0, (3, 3)), zorder=4,
        label="ego trajectory (RTK)")

# per-road labels: original -> applied
label_side = 1
for rid, r in sorted(matches.items(), key=lambda q: int(q[0])):
    P = roads[rid].sample(2.0)
    mid = P[len(P) // 2]
    nx, ny = -np.sin(mid[2]), np.cos(mid[2])
    off = 16 * label_side
    label_side *= -1
    star = "*" if r["clamped"] == "1" else ""
    ax.annotate(f"{rid}:  {orig[rid]:.1f} → {float(r['carriageway_pick']):.1f} m{star}",
                (mid[0], mid[1]), xytext=(mid[0] + nx * off, mid[1] + ny * off),
                fontsize=10, color=INK, ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=BASE, lw=0.8),
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.7), zorder=6)

ax.set_xlim(bbox[0], bbox[1])
ax.set_ylim(bbox[2] - 8, bbox[3] + 4)
ax.set_aspect("equal")
ax.set_xlabel("x [m, xodr frame]", color=INK2, fontsize=10)
ax.set_ylabel("y [m]", color=INK2, fontsize=10)
ax.tick_params(colors=MUTED, labelsize=8)
for sp in ax.spines.values():
    sp.set_color(BASE)
ax.set_title("Measured road width at every station (colored crossbars) vs the original map "
             "(dashed envelope)\nlabel: road id, original carriageway → applied correction "
             "(* = plausibility-clamped)", color=INK, fontsize=12, loc="left", pad=12)

sm = ScalarMappable(norm=norm, cmap=cmap)
cb = fig.colorbar(sm, ax=ax, fraction=0.028, pad=0.01)
cb.set_label("measured carriageway width (traveled band) [m]", color=INK2, fontsize=9)
cb.ax.tick_params(colors=MUTED, labelsize=8)
cb.outline.set_edgecolor(BASE)

ax.plot([], [], color=INK2, lw=1.0, ls=(0, (5, 4)), label="original xodr envelope (flat)")
leg = ax.legend(loc="lower right", frameon=False, fontsize=9)
for t in leg.get_texts():
    t.set_color(INK2)

fig.tight_layout()
fig.savefig(OUT, facecolor=fig.get_facecolor(), bbox_inches="tight")
print("wrote", OUT)
