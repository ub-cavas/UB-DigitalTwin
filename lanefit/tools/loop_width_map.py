#!/usr/bin/env python3
"""Simple, manually-tunable road-width map: long CONSTANT-width segments,
continuous through gaps/turns/intersections, both drives combined.

Outputs: <out_png> and <out>_segments.csv (segment table for hand-tuning).

Usage: loop_width_map.py <out_png> <run_newest> [<run_older> ...]
"""
import csv
import sys

import numpy as np

OUT = sys.argv[1]
RUNS = sys.argv[2:]

SURFACE, PAGE = "#fcfcfb", "#f9f9f7"
INK, INK2, MUTED, BASE = "#0b0b0b", "#52514e", "#898781", "#c3c2b7"
SEQ = ["#86b6ef", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#104281"]

SEG_TOL = 1.5      # m; width change that starts a new segment (coarse = few segments)
SEG_MIN = 12       # stations (~36 m); shorter segments merge into neighbours
OVERLAP_D = 12.0   # m; hide older-run stations near newer coverage
SELF_D = 8.0       # m; hide same-run repeat passes (keep first pass)
SMOOTH = 7         # stations; centerline rolling-mean window


def load_run(run):
    rows = []
    for r in csv.DictReader(open(f"{run}/measure_widths/widths.csv")):
        rows.append((float(r["s_m"]), float(r["x"]), float(r["y"]),
                     float(r["heading_rad"]), float(r["t_left_in"]),
                     float(r["t_right_in"]), float(r["width_in"])))
    rows.sort(key=lambda q: q[0])
    return np.array(rows)


def segment(widths):
    segs, i0 = [], 0
    for i in range(1, len(widths) + 1):
        if i == len(widths) or abs(widths[i] - np.median(widths[i0:i])) > SEG_TOL:
            segs.append([i0, i, float(np.median(widths[i0:i]))])
            i0 = i
    merged = True
    while merged and len(segs) > 1:
        merged = False
        for k, sgm in enumerate(segs):
            if sgm[1] - sgm[0] >= SEG_MIN:
                continue
            if 0 < k < len(segs) - 1:
                nb = min(segs[k - 1], segs[k + 1], key=lambda q: abs(q[2] - sgm[2]))
            else:
                nb = segs[k - 1] if k > 0 else segs[k + 1]
            nb[0], nb[1] = min(nb[0], sgm[0]), max(nb[1], sgm[1])
            segs.pop(k)
            merged = True
            break
    return segs


def smooth(v, win):
    out = np.copy(v)
    h = win // 2
    for i in range(len(v)):
        out[i] = np.mean(v[max(0, i - h):i + h + 1])
    return out


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from scipy.spatial import cKDTree

    runs = [load_run(r) for r in RUNS]
    gnd = gi = None
    for r in RUNS:
        try:
            d = np.load(f"{r}/measure_widths/ground.npz")
            gnd, gi = d["xyz"], d["intensity"]
            break
        except Exception:
            pass

    cmap = LinearSegmentedColormap.from_list("blues", SEQ)
    allw = np.concatenate([rr[:, 6] for rr in runs])
    norm = Normalize(vmin=np.percentile(allw, 5) - 0.5,
                     vmax=np.percentile(allw, 95) + 0.5)

    fig, ax = plt.subplots(figsize=(17, 9), dpi=180)
    fig.patch.set_facecolor(PAGE)
    ax.set_facecolor(SURFACE)
    if gnd is not None:
        bbox = (gnd[:, 0].min() - 5, gnd[:, 0].max() + 5,
                gnd[:, 1].min() - 5, gnd[:, 1].max() + 5)
        res = 0.25
        px = ((gnd[:, 0] - bbox[0]) / res).astype(int)
        py = ((gnd[:, 1] - bbox[2]) / res).astype(int)
        W = int((bbox[1] - bbox[0]) / res) + 2
        H = int((bbox[3] - bbox[2]) / res) + 2
        img = np.zeros((H, W), np.float32)
        np.maximum.at(img, (py, px), np.clip(gi / 60, 0.25, 1.0))
        ax.imshow(np.ones((H, W, 3)) - (0.14 * img)[..., None],
                  extent=[bbox[0], bbox[1], bbox[2], bbox[3]], origin="lower",
                  interpolation="bilinear", zorder=0)

    newest_pts = None
    seg_table = []
    label_boxes = []
    for run_i, rr in enumerate(runs):
        s, x, y, h, tl, tr, w = rr.T
        keep = np.ones(len(rr), bool)
        if newest_pts is not None:
            d, _ = cKDTree(newest_pts).query(rr[:, 1:3])
            keep &= d > OVERLAP_D
        # same-run repeat-pass dedup: drop stations near a much-earlier kept one
        kept_xy, kept_s = [], []
        for i in range(len(rr)):
            if not keep[i]:
                continue
            if kept_xy:
                arr = np.array(kept_xy)
                dd = np.hypot(arr[:, 0] - x[i], arr[:, 1] - y[i])
                near = dd < SELF_D
                if near.any() and (s[i] - np.array(kept_s)[near].min()) > 40:
                    keep[i] = False
                    continue
            kept_xy.append((x[i], y[i]))
            kept_s.append(s[i])
        idx = np.nonzero(keep)[0]
        if len(idx) < 4:
            continue
        # split ONLY on true position jumps (stay continuous through turns)
        gaps = np.hypot(np.diff(x[idx]), np.diff(y[idx])) > 12.0
        chunks = np.split(idx, np.nonzero(gaps)[0] + 1)
        for ch in chunks:
            if len(ch) < 4:
                continue
            ctr = (tl[ch] + tr[ch]) / 2
            cx = smooth(x[ch] + (-np.sin(h[ch])) * ctr, SMOOTH)
            cy = smooth(y[ch] + (np.cos(h[ch])) * ctr, SMOOTH)
            tx, ty = np.gradient(cx), np.gradient(cy)
            tn = np.hypot(tx, ty)
            tn[tn < 1e-9] = 1
            nx, ny = -ty / tn, tx / tn
            segs = segment(w[ch])
            for k, (i0, i1, val) in enumerate(segs):
                j1 = min(i1 + 1, len(ch))
                sl = slice(i0, j1)
                up = np.column_stack([cx[sl] + nx[sl] * val / 2,
                                      cy[sl] + ny[sl] * val / 2])
                lo = np.column_stack([cx[sl] - nx[sl] * val / 2,
                                      cy[sl] - ny[sl] * val / 2])
                ax.fill(np.concatenate([up[:, 0], lo[::-1, 0]]),
                        np.concatenate([up[:, 1], lo[::-1, 1]]),
                        color=cmap(norm(val)), alpha=0.92, lw=0, zorder=3)
                mid = (i0 + min(i1, len(ch) - 1)) // 2
                seg_table.append({
                    "run": RUNS[run_i].rstrip("/").split("/")[-1],
                    "segment": len(seg_table) + 1,
                    "mid_x": round(float(cx[mid]), 1),
                    "mid_y": round(float(cy[mid]), 1),
                    "length_m": round(3.0 * (i1 - i0), 0),
                    "width_m": round(val, 1)})
                lx = cx[mid] + nx[mid] * 15
                ly = cy[mid] + ny[mid] * 15
                if all((lx - a) ** 2 + (ly - b) ** 2 > 22 ** 2 for a, b in label_boxes):
                    label_boxes.append((lx, ly))
                    ax.annotate(f"#{len(seg_table)}: {val:.1f} m",
                                (cx[mid], cy[mid]), xytext=(lx, ly),
                                fontsize=9, color=INK, ha="center", va="center",
                                bbox=dict(boxstyle="round,pad=0.25", fc="white",
                                          ec=BASE, lw=0.7),
                                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.7),
                                zorder=6)
        newest_pts = rr[keep][:, 1:3] if newest_pts is None else \
            np.vstack([newest_pts, rr[keep][:, 1:3]])

    ax.set_aspect("equal")
    ax.tick_params(colors=MUTED, labelsize=8)
    for sp in ax.spines.values():
        sp.set_color(BASE)
    ax.set_title("LiDAR road widths — CONSTANT per segment, continuous through "
                 "gaps/turns\nsegment ids reference the tuning table "
                 "(*_segments.csv)", color=INK, fontsize=13, loc="left", pad=12)
    sm = ScalarMappable(norm=norm, cmap=cmap)
    cb = fig.colorbar(sm, ax=ax, fraction=0.028, pad=0.01)
    cb.set_label("carriageway width [m]", color=INK2, fontsize=10)
    cb.ax.tick_params(colors=MUTED, labelsize=8)
    cb.outline.set_edgecolor(BASE)
    fig.tight_layout()
    fig.savefig(OUT, facecolor=fig.get_facecolor(), bbox_inches="tight")
    print("wrote", OUT)

    csv_path = OUT.rsplit(".", 1)[0] + "_segments.csv"
    with open(csv_path, "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=list(seg_table[0]))
        wtr.writeheader()
        wtr.writerows(seg_table)
    print("wrote", csv_path, f"({len(seg_table)} segments)")


if __name__ == "__main__":
    main()
