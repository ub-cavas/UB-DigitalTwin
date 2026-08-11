"""Figures: dual-bound width profile chart and the corrected-roads map.

Styling follows the validated reference palette (light mode): categorical slots for
series identity, status colors with shape+label for QC state, recessive chrome.
"""
from __future__ import annotations

import csv
import logging

import numpy as np

log = logging.getLogger("lanefit")

SURFACE, PAGE = "#fcfcfb", "#f9f9f7"
INK, INK2, MUTED, BASE = "#0b0b0b", "#52514e", "#898781", "#c3c2b7"
GRID = "#e1e0d9"
S1, S2 = "#2a78d6", "#1baf7a"          # categorical slots 1/2
CRIT = "#d03b3b"                        # status: critical
SEQ = ["#86b6ef", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#104281"]


def width_profile_chart(widths_csv: str, out_png: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s, wi, wo, ci = [], [], [], []
    for r in csv.DictReader(open(widths_csv)):
        s.append(float(r["s_m"]))
        wi.append(float(r["width_in"]))
        wo.append(float(r["width_out"]) if r["width_out"] else np.nan)
        ci.append(int(r["conf_in"]))
    s, wi, wo, ci = map(np.array, (s, wi, wo, ci))
    o = np.argsort(s)
    s, wi, wo, ci = s[o], wi[o], wo[o], ci[o]

    fig, ax = plt.subplots(figsize=(12, 4.2), dpi=150)
    fig.patch.set_facecolor(PAGE)
    ax.set_facecolor(SURFACE)
    ax.fill_between(s, wi, wo, where=np.isfinite(wo), color=S2, alpha=0.10, lw=0)
    ax.plot(s, wo, color=S2, lw=2.0, label="outer — pavement extent")
    ax.plot(s, wi, color=S1, lw=2.0, label="inner — traveled band")
    m0 = ci == 0
    ax.scatter(s[m0], wi[m0], s=18, c=CRIT, marker="x", linewidths=1.2,
               label="inner conf 0 — carried, no local evidence", zorder=4)
    med_i, med_o = np.nanmedian(wi), np.nanmedian(wo)
    ax.set_xlabel("station s along driven path [m]", color=INK2, fontsize=10)
    ax.set_ylabel("carriageway width [m]", color=INK2, fontsize=10)
    ax.set_title(f"Carriageway width vs station — inner median {med_i:.1f} m, "
                 f"outer median {med_o:.1f} m", color=INK, fontsize=12, loc="left", pad=12)
    ax.set_ylim(0, max(np.nanmax(wo[np.isfinite(wo)]) if np.isfinite(wo).any() else 12,
                       12) + 2)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(BASE)
    ax.tick_params(colors=MUTED, labelsize=9)
    leg = ax.legend(loc="upper left", frameon=False, fontsize=9)
    for t in leg.get_texts():
        t.set_color(INK2)
    fig.tight_layout()
    fig.savefig(out_png, facecolor=fig.get_facecolor())
    plt.close(fig)
    log.info("wrote %s", out_png)


def corrected_roads_map(xodr: str, road_matches_csv: str, ground_npz: str,
                        gnss_csv: str, out_png: str,
                        updates_csv: str = "", skipped_csv: str = "") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import LinearSegmentedColormap, Normalize

    from .xodr_io import parse_xodr

    import json as _json
    import os as _os
    cmap = LinearSegmentedColormap.from_list("blues", SEQ)
    corrected = {r["road_id"]: r for r in csv.DictReader(open(road_matches_csv))}
    knots_by_road: dict[str, list] = {}
    if updates_csv and _os.path.exists(updates_csv):
        for u in csv.DictReader(open(updates_csv)):
            knots_by_road[u["road_id"]] = [(float(a), float(b))
                                           for a, b in _json.loads(u["knots"])]
    skipped_ids = set()
    if skipped_csv and _os.path.exists(skipped_csv):
        skipped_ids = {r["road_id"] for r in csv.DictReader(open(skipped_csv))}
    per_lane = [float(r["per_lane_median"]) for r in corrected.values()]
    norm = Normalize(vmin=min(per_lane) - 0.2, vmax=max(per_lane) + 0.2)

    d = np.load(ground_npz)
    gnd, gi = d["xyz"], d["intensity"]
    traj = np.array([[float(r["x_xodr"]), float(r["y_xodr"])]
                     for r in csv.DictReader(open(gnss_csv))])
    _, roads = parse_xodr(xodr)
    bbox = (gnd[:, 0].min() - 5, gnd[:, 0].max() + 5, gnd[:, 1].min() - 5, gnd[:, 1].max() + 5)

    fig, ax = plt.subplots(figsize=(15, 8), dpi=200)
    fig.patch.set_facecolor(PAGE)
    ax.set_facecolor(SURFACE)

    res = 0.25
    px = ((gnd[:, 0] - bbox[0]) / res).astype(int)
    py = ((gnd[:, 1] - bbox[2]) / res).astype(int)
    W = int((bbox[1] - bbox[0]) / res) + 2
    H = int((bbox[3] - bbox[2]) / res) + 2
    img = np.zeros((H, W), np.float32)
    np.maximum.at(img, (py, px), np.clip(gi / 60, 0.25, 1.0))
    backdrop = np.ones((H, W, 3)) - (0.22 * img)[..., None]
    ax.imshow(backdrop, extent=[bbox[0], bbox[1], bbox[2], bbox[3]], origin="lower",
              interpolation="bilinear", zorder=0)

    label_side = 1
    for rid, rd in sorted(roads.items(), key=lambda q: int(q[0])):
        P = rd.sample(1.0)
        if len(P) == 0:
            continue
        inside = ((P[:, 0] > bbox[0]) & (P[:, 0] < bbox[1]) &
                  (P[:, 1] > bbox[2]) & (P[:, 1] < bbox[3]))
        if not inside.any():
            continue
        if rid not in corrected:
            if rid in skipped_ids:
                ax.plot(P[inside, 0], P[inside, 1], color="#fab219", lw=1.6,
                        ls=(0, (4, 3)), zorder=2)
            else:
                ax.plot(P[inside, 0], P[inside, 1], color=BASE, lw=0.6, zorder=1)
            continue
        r = corrected[rid]
        nl = int(r["n_driving_lanes"])
        kn = knots_by_road.get(rid)
        if kn:
            from .profiles import eval_knots
            wsum_arr = np.array([eval_knots(kn, sv) * nl for sv in P[:, 3]])
        else:
            wsum_arr = np.full(len(P), float(r["per_lane_median"]) * nl)
        nx, ny = -np.sin(P[:, 2]), np.cos(P[:, 2])
        c_off = float(r.get("center_measured", 0) or 0)   # measured centerline vs refline
        cxs = P[:, 0] + nx * c_off
        cys = P[:, 1] + ny * c_off
        up = np.column_stack([cxs + nx * wsum_arr / 2, cys + ny * wsum_arr / 2])
        lo = np.column_stack([cxs - nx * wsum_arr / 2, cys - ny * wsum_arr / 2])
        poly = np.vstack([up, lo[::-1]])
        ax.fill(poly[:, 0], poly[:, 1],
                color=cmap(norm(float(r["per_lane_median"]))), alpha=0.85, lw=0, zorder=3)
        mid = len(P) // 2
        ox, oy = nx[mid] * 14 * label_side, ny[mid] * 14 * label_side
        label_side *= -1
        ax.annotate(f"{rid}: {nl}×{float(r['per_lane_min']):.2f}–{float(r['per_lane_max']):.2f} m",
                    (P[mid, 0], P[mid, 1]),
                    xytext=(P[mid, 0] + ox, P[mid, 1] + oy),
                    fontsize=9, color=INK, ha="center", va="center",
                    bbox=dict(boxstyle="round,pad=0.28", fc="white", ec=BASE, lw=0.7),
                    arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.7), zorder=6)

    # junction connectors adjacent to corrected roads: draw their blended ribbons
    from .profiles import eval_knots as _ek
    _, jroads = parse_xodr(xodr, junction_roads=True)

    def _endw(el_id, contact):
        kn = knots_by_road.get(el_id)
        if not kn:
            return None
        return _ek(kn, 0.0 if contact == "start" else max(k[0] for k in kn))

    for rid, rd in jroads.items():
        if rd.junction == "-1" or not (rd.pred and rd.succ):
            continue
        if rd.pred[0] != "road" or rd.succ[0] != "road":
            continue
        w_in = _endw(rd.pred[1], "end")
        w_out = _endw(rd.succ[1], "start")
        if w_in is None and w_out is None:
            continue
        w_in = w_in if w_in is not None else 3.5
        w_out = w_out if w_out is not None else 3.5
        P = rd.sample(1.0)
        if len(P) < 2 or rd.length < 0.5:
            continue
        t = P[:, 3] / rd.length
        nl = max(1, int(np.median([len(sec.driving) for sec in rd.sections
                                   if sec.driving]) if any(
                                       sec.driving for sec in rd.sections) else 1))
        wv = (w_in + (3 * t ** 2 - 2 * t ** 3) * (w_out - w_in)) * nl
        nx, ny = -np.sin(P[:, 2]), np.cos(P[:, 2])
        up = np.column_stack([P[:, 0] + nx * wv / 2, P[:, 1] + ny * wv / 2])
        lo = np.column_stack([P[:, 0] - nx * wv / 2, P[:, 1] - ny * wv / 2])
        ax.fill(np.concatenate([up[:, 0], lo[::-1, 0]]),
                np.concatenate([up[:, 1], lo[::-1, 1]]),
                color=S2, alpha=0.55, lw=0, zorder=2)
    ax.fill([], [], color=S2, alpha=0.55, label="junction connectors (blended widths)")

    ax.plot(traj[:, 0], traj[:, 1], color=MUTED, lw=0.9, ls=(0, (1, 2)), zorder=2)
    ax.set_xlim(bbox[0], bbox[1])
    ax.set_ylim(bbox[2], bbox[3])
    ax.set_aspect("equal")
    ax.set_xlabel("x [m, xodr frame]", color=INK2, fontsize=10)
    ax.set_ylabel("y [m]", color=INK2, fontsize=10)
    ax.tick_params(colors=MUTED, labelsize=8)
    for sp in ax.spines.values():
        sp.set_color(BASE)
    ax.set_title("Corrected lane widths — ribbons follow the measured width PROFILE\n"
                 "label = road: lanes × per-lane range · amber dashed = kept original "
                 "(weak evidence, see report)", color=INK, fontsize=11, loc="left", pad=12)
    sm = ScalarMappable(norm=norm, cmap=cmap)
    cb = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.01)
    cb.set_label("per-lane width [m]", color=INK2, fontsize=9)
    cb.ax.tick_params(colors=MUTED, labelsize=8)
    cb.outline.set_edgecolor(BASE)
    ax.plot([], [], color=BASE, lw=0.8, label="other xodr roads (defaults kept)")
    ax.plot([], [], color="#fab219", lw=1.6, ls=(0, (4, 3)),
            label="matched but kept original (weak evidence)")
    ax.plot([], [], color=MUTED, lw=0.9, ls=(0, (1, 2)), label="driven RTK path")
    leg = ax.legend(loc="lower left", frameon=False, fontsize=8)
    for t in leg.get_texts():
        t.set_color(INK2)
    fig.tight_layout()
    fig.savefig(out_png, facecolor=fig.get_facecolor())
    plt.close(fig)
    log.info("wrote %s", out_png)


def road_profiles_figure(road_matches_csv: str, updates_csv: str, out_png: str,
                         default_lane_w: float = 3.5) -> None:
    """Per-road panels: written width profile (knot spline) vs the original width."""
    import json as _json

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from .profiles import eval_knots

    rows = list(csv.DictReader(open(road_matches_csv)))
    knots_by_road = {}
    for u in csv.DictReader(open(updates_csv)):
        knots_by_road[u["road_id"]] = [(float(a), float(b))
                                       for a, b in _json.loads(u["knots"])]
    rows = [r for r in rows if r["road_id"] in knots_by_road]
    if not rows:
        return
    ncols = 3
    nrows = int(np.ceil(len(rows) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 2.9 * nrows), dpi=150,
                             squeeze=False)
    fig.patch.set_facecolor(PAGE)
    for i, r in enumerate(sorted(rows, key=lambda q: -int(q["n_stations"]))):
        ax = axes[i // ncols][i % ncols]
        ax.set_facecolor(SURFACE)
        kn = knots_by_road[r["road_id"]]
        nl = int(r["n_driving_lanes"])
        smax = max(k[0] for k in kn)
        ss = np.linspace(0, smax, 120)
        ww = [eval_knots(kn, sv) for sv in ss]
        ax.plot(ss, ww, color=S1, lw=2.0)
        ax.scatter([k[0] for k in kn], [k[1] for k in kn], s=12, color=S1, zorder=4)
        ax.axhline(default_lane_w, color=INK2, lw=1.2, ls=(0, (5, 3)))
        src = r.get("source_run", "")
        ax.set_title(f"road {r['road_id']} — {nl} lanes · {r['n_stations']} st · "
                     f"cov {r['coverage']}{' · ' + src if src else ''}",
                     color=INK, fontsize=9, loc="left")
        ax.set_ylim(0, 7)
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            ax.spines[sp].set_color(BASE)
        ax.tick_params(colors=MUTED, labelsize=7)
        ax.set_xlabel("s along road [m]", color=INK2, fontsize=7)
        ax.set_ylabel("per-lane width [m]", color=INK2, fontsize=7)
    for j in range(len(rows), nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")
    import matplotlib.lines as mlines
    fig.legend(handles=[
        mlines.Line2D([], [], color=S1, lw=2, marker="o", ms=4,
                      label="written width profile (knots)"),
        mlines.Line2D([], [], color=INK2, lw=1.2, ls=(0, (5, 3)),
                      label=f"original ({default_lane_w:.1f} m/lane)")],
        loc="upper right", frameon=False, fontsize=9)
    fig.suptitle("Applied per-lane width profiles vs original map",
                 color=INK, fontsize=12, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out_png, facecolor=fig.get_facecolor())
    plt.close(fig)
    log.info("wrote %s", out_png)


def width_ladder_figure(widths_csv: str, ground_npz: str, gnss_csv: str,
                        out_png: str) -> None:
    """Spatial 'ladder': measured-width crossbars drawn at their true positions."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    from matplotlib.collections import LineCollection
    from matplotlib.colors import LinearSegmentedColormap, Normalize

    st = []
    for r in csv.DictReader(open(widths_csv)):
        st.append((float(r["x"]), float(r["y"]), float(r["heading_rad"]),
                   float(r["t_left_in"]), float(r["t_right_in"]),
                   float(r["width_in"]), int(r["conf_in"])))
    st = np.array(st)
    d = np.load(ground_npz)
    gnd, gi = d["xyz"], d["intensity"]
    traj = np.array([[float(r["x_xodr"]), float(r["y_xodr"])]
                     for r in csv.DictReader(open(gnss_csv))])

    cmap = LinearSegmentedColormap.from_list("blues", SEQ)
    ok = st[:, 6] >= 1
    norm = Normalize(vmin=np.percentile(st[ok, 5], 5) - 0.5,
                     vmax=np.percentile(st[ok, 5], 95) + 0.5)
    fig, ax = plt.subplots(figsize=(16, 9), dpi=180)
    fig.patch.set_facecolor(PAGE)
    ax.set_facecolor(SURFACE)
    bbox = (gnd[:, 0].min() - 5, gnd[:, 0].max() + 5,
            gnd[:, 1].min() - 5, gnd[:, 1].max() + 5)
    res = 0.25
    px = ((gnd[:, 0] - bbox[0]) / res).astype(int)
    py = ((gnd[:, 1] - bbox[2]) / res).astype(int)
    W, H = int((bbox[1] - bbox[0]) / res) + 2, int((bbox[3] - bbox[2]) / res) + 2
    img = np.zeros((H, W), np.float32)
    np.maximum.at(img, (py, px), np.clip(gi / 60, 0.25, 1.0))
    ax.imshow(np.ones((H, W, 3)) - (0.16 * img)[..., None],
              extent=[bbox[0], bbox[1], bbox[2], bbox[3]], origin="lower",
              interpolation="bilinear", zorder=0)
    segs, cols = [], []
    for x, y, h, tl, tr, w, conf in st:
        if conf < 1:
            continue
        nx, ny = -np.sin(h), np.cos(h)
        segs.append([(x + nx * tr, y + ny * tr), (x + nx * tl, y + ny * tl)])
        cols.append(cmap(norm(w)))
    ax.add_collection(LineCollection(segs, colors=cols, linewidths=2.8,
                                     capstyle="round", zorder=3))
    ax.plot(traj[:, 0], traj[:, 1], color=INK, lw=0.9, ls=(0, (3, 3)), zorder=4,
            label="ego trajectory (RTK)")
    ax.set_xlim(bbox[0], bbox[1])
    ax.set_ylim(bbox[2], bbox[3])
    ax.set_aspect("equal")
    ax.tick_params(colors=MUTED, labelsize=8)
    for sp in ax.spines.values():
        sp.set_color(BASE)
    ax.set_title("Measured carriageway width at every station (crossbars at true "
                 "positions and extents)", color=INK, fontsize=12, loc="left", pad=10)
    sm = ScalarMappable(norm=norm, cmap=cmap)
    cb = fig.colorbar(sm, ax=ax, fraction=0.028, pad=0.01)
    cb.set_label("measured carriageway width [m]", color=INK2, fontsize=9)
    cb.ax.tick_params(colors=MUTED, labelsize=8)
    cb.outline.set_edgecolor(BASE)
    leg = ax.legend(loc="lower right", frameon=False, fontsize=9)
    for t in leg.get_texts():
        t.set_color(INK2)
    fig.tight_layout()
    fig.savefig(out_png, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    log.info("wrote %s", out_png)
