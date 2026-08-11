"""Width profiles: per-road knot sequences and piecewise-cubic coefficient generation.

A corrected road's lane width is represented as knots (s_road, w_per_lane) built from
confident stations: rolling-median smoothed, decimated to ~knot_spacing, with in-road
gaps bridged by monotone (PCHIP) interpolation between measured neighbours and the
boundary values held constant to the road ends. Knots are converted to OpenDRIVE
<width sOffset a b c d> records as C1 cubic Hermite segments.
"""
from __future__ import annotations

import numpy as np


def build_knots(s: np.ndarray, w: np.ndarray, road_len: float,
                knot_spacing: float = 9.0, smooth_win: int = 3,
                w_floor: float = 0.0, w_cap: float = 1e9) -> list[tuple[float, float]]:
    """Confident station widths -> knot list [(s, w)], covering [0, road_len].

    Knots are clipped to [w_floor, w_cap]: local excursions (intersection throats,
    pavement flares) must not write sim-breaking lane widths, while the road-level
    trust decision stays with the caller."""
    order = np.argsort(s)
    s, w = s[order], w[order]
    w = np.clip(w, w_floor, w_cap)
    # rolling median smoothing
    ws = np.copy(w)
    h = smooth_win // 2
    for i in range(len(w)):
        ws[i] = np.median(w[max(0, i - h):i + h + 1])
    # decimate to knot spacing (median of stations in each bin)
    knots: list[tuple[float, float]] = []
    lo = s[0]
    while lo < s[-1] + 1e-6:
        m = (s >= lo) & (s < lo + knot_spacing)
        if m.any():
            knots.append((float(np.median(s[m])), float(np.median(ws[m]))))
        lo += knot_spacing
    if len(knots) == 1:
        knots = [(max(0.0, knots[0][0] - 1), knots[0][1]),
                 (min(road_len, knots[0][0] + 1), knots[0][1])]
    # hold boundary values to the physical road ends (junction taper picks these up)
    if knots[0][0] > 0.0:
        knots.insert(0, (0.0, knots[0][1]))
    if knots[-1][0] < road_len:
        knots.append((road_len, knots[-1][1]))
    return knots


def _pchip_slopes(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Monotone cubic (Fritsch–Carlson) slopes: no overshoot across gaps."""
    h = np.diff(xs)
    d = np.diff(ys) / h
    m = np.zeros(len(xs))
    for i in range(1, len(xs) - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0
        else:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    m[0] = 0.0    # flat ends: C1 hand-off into junction tapers
    m[-1] = 0.0
    return m


def knots_to_records(knots: list[tuple[float, float]],
                     sec_s: float, sec_end: float) -> list[dict]:
    """Hermite segments of the knot spline clipped to one laneSection.

    Returns [{sOffset, a, b, c, d}, ...] with sOffset relative to the section start.
    """
    xs = np.array([k[0] for k in knots], float)
    ys = np.array([k[1] for k in knots], float)
    m = _pchip_slopes(xs, ys)
    recs = []
    for i in range(len(xs) - 1):
        s0, s1 = xs[i], xs[i + 1]
        if s1 <= sec_s + 1e-9 or s0 >= sec_end - 1e-9:
            continue
        h = s1 - s0
        w0, w1, m0, m1 = ys[i], ys[i + 1], m[i], m[i + 1]
        a = w0
        b = m0
        c = (3 * (w1 - w0) / h - 2 * m0 - m1) / h
        d = (2 * (w0 - w1) / h + m0 + m1) / (h * h)
        # segment polynomial is in ds from s0; shift to section-relative offset
        off = s0 - sec_s
        if off < 0:  # segment starts before the section: re-expand around section start
            u = -off
            a = a + b * u + c * u * u + d * u ** 3
            b = b + 2 * c * u + 3 * d * u * u
            c = c + 3 * d * u
            off = 0.0
        recs.append({"sOffset": off, "a": a, "b": b, "c": c, "d": d})
    if not recs:
        w = float(np.interp(sec_s, xs, ys))
        recs = [{"sOffset": 0.0, "a": w, "b": 0.0, "c": 0.0, "d": 0.0}]
    return recs


def eval_knots(knots: list[tuple[float, float]], s: float) -> float:
    """Evaluate the knot spline (piecewise Hermite) at road arclength s."""
    xs = np.array([k[0] for k in knots], float)
    ys = np.array([k[1] for k in knots], float)
    m = _pchip_slopes(xs, ys)
    s = float(np.clip(s, xs[0], xs[-1]))
    i = int(np.clip(np.searchsorted(xs, s) - 1, 0, len(xs) - 2))
    h = xs[i + 1] - xs[i]
    t = (s - xs[i]) / h
    h00 = 2 * t ** 3 - 3 * t ** 2 + 1
    h10 = t ** 3 - 2 * t ** 2 + t
    h01 = -2 * t ** 3 + 3 * t ** 2
    h11 = t ** 3 - t ** 2
    return float(h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1])


def smoothstep_taper(w_in: float, w_out: float, length: float) -> dict:
    """One cubic record blending w_in -> w_out over `length` with zero end slopes."""
    d = w_out - w_in
    return {"sOffset": 0.0, "a": w_in, "b": 0.0,
            "c": 3 * d / length ** 2, "d": -2 * d / length ** 3}
