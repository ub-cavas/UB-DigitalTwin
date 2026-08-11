"""conflate stage: match measured stations to xodr roads, decide per road, build profiles.

Evidence policy (user decision 2026-07-09): TRUST OR DON'T TOUCH.
  - A road is corrected only when its evidence is strong: enough stations, enough
    coverage, consistent widths (IQR), enough multi-signal stations, and a per-lane
    value inside physical sanity bounds. Corrected roads get a full piecewise WIDTH
    PROFILE (knots from confident stations; in-road gaps bridged by monotone
    interpolation between measured neighbours — never by the map default).
  - Anything weaker keeps its ORIGINAL width and is reported in skipped_roads.csv
    (reasoned), the log, and the run report. No clamped/fabricated values.
Junction connectors are handled downstream (apply stage) by cubic blending between
their endpoint roads' profile values.
"""
from __future__ import annotations

import csv
import json
import logging

import numpy as np

from .config import Config
from .profiles import build_knots
from .runctx import RunContext
from .xodr_io import parse_xodr

log = logging.getLogger("lanefit")


def run(ctx: RunContext, cfg: Config) -> dict:
    from scipy.spatial import cKDTree
    c = cfg.section("conflate")
    _, roads = parse_xodr(ctx.xodr)

    st = []
    for r in csv.DictReader(open(ctx.path("measure_widths", "widths.csv"))):
        st.append((float(r["x"]), float(r["y"]), float(r["heading_rad"]),
                   float(r["width_in"]),
                   float(r["width_out"]) if r["width_out"] else np.nan,
                   int(r["conf_in"]),
                   float(r["t_left_in"]), float(r["t_right_in"])))
    st = np.array(st)
    use = st[:, 5] >= 1
    st_tree = cKDTree(st[:, :2])
    log.info("stations: %d (conf>=1: %d), normal roads: %d", len(st), int(use.sum()),
             len(roads))

    samples, rid_list = [], []
    for rid, rd in roads.items():
        coarse = rd.sample(10.0)
        if len(coarse) == 0:
            continue
        d, _ = st_tree.query(coarse[:, :2], distance_upper_bound=float(c["corridor_pad"]))
        if not np.isfinite(d).any():
            continue
        ridx = len(rid_list)
        rid_list.append(rid)
        for x, y, h, s_road in rd.sample(float(c["sample_step"])):
            samples.append((x, y, h, ridx, s_road))
    samples = np.array(samples)
    log.info("corridor roads: %d, refline samples: %d", len(rid_list), len(samples))
    if not len(samples):
        raise RuntimeError("no xodr roads near the measured corridor — frame mismatch?")

    ref_tree = cKDTree(samples[:, :2])
    matches: dict[str, list] = {}
    n_matched = 0
    for i in np.nonzero(use)[0]:
        d, j = ref_tree.query(st[i, :2])
        if d > float(c["match_dist"]):
            continue
        if abs(np.cos(st[i, 2] - samples[j, 2])) < float(c["head_cos"]):
            continue
        rid = rid_list[int(samples[j, 3])]
        hr = samples[j, 2]
        align = 1.0 if np.cos(st[i, 2] - hr) >= 0 else -1.0
        dxy = st[i, :2] - samples[j, :2]
        d_lat = -np.sin(hr) * dxy[0] + np.cos(hr) * dxy[1]
        c_ref = d_lat + align * (st[i, 6] + st[i, 7]) / 2.0
        matches.setdefault(rid, []).append((samples[j, 4], st[i, 3], st[i, 4],
                                            st[i, 5], c_ref))
        n_matched += 1
    log.info("matched %d stations onto %d roads", n_matched, len(matches))

    lane_min = float(c["lane_min"])
    lane_max = float(c["lane_sane_max"])
    road_rows, skipped, updates = [], [], []
    profiles: dict[str, list] = {}

    for rid, mm in sorted(matches.items(), key=lambda q: -len(q[1])):
        mm = np.array(mm)          # columns: s_road, w_in, w_out, conf
        rd = roads[rid]
        n_st = len(mm)
        med_in = float(np.nanmedian(mm[:, 1]))
        iqr = float(np.percentile(mm[:, 1], 75) - np.percentile(mm[:, 1], 25))
        # local consistency: deviation from the rolling-median profile (along-road
        # variation is real signal; only local scatter counts as ambiguity)
        order_s = np.argsort(mm[:, 0])
        ws = mm[order_s, 1]
        roll = np.array([np.median(ws[max(0, i - 2):i + 3]) for i in range(len(ws))])
        local_resid = float(np.median(np.abs(ws - roll)))
        coverage = float((mm[:, 0].max() - mm[:, 0].min()) / max(rd.length, 1e-6))
        conf2 = float((mm[:, 3] >= 2).mean())
        secs = [s for s in rd.sections if s.driving]
        n_lanes = int(np.median([len(s.driving) for s in secs])) if secs else 0
        per_lane = med_in / n_lanes if n_lanes else np.nan

        reason = None
        if n_lanes == 0:
            reason = "no driving lanes in xodr"
        elif n_st < int(c["min_stations"]):
            reason = f"sparse: {n_st} stations < {c['min_stations']}"
        elif coverage < float(c["min_coverage"]):
            reason = f"sparse: coverage {coverage:.2f} < {c['min_coverage']}"
        elif local_resid > float(c["max_local_resid"]):
            reason = (f"ambiguous: local width scatter {local_resid:.2f} m > "
                      f"{c['max_local_resid']}")
        elif conf2 < float(c["min_conf2_share"]):
            reason = f"weak: {100*conf2:.0f}% multi-signal stations < {100*float(c['min_conf2_share']):.0f}%"
        elif per_lane < lane_min:
            reason = f"implausible: {per_lane:.2f} m/lane < {lane_min}"
        elif per_lane > lane_max:
            reason = f"gross: {per_lane:.2f} m/lane > {lane_max}"

        base = dict(road_id=rid, n_stations=n_st, coverage=round(coverage, 2),
                    med_width_in=round(med_in, 2), iqr_in=round(iqr, 2),
                    local_resid=round(local_resid, 2),
                    conf2_share=round(conf2, 2), n_driving_lanes=n_lanes)
        if reason:
            skipped.append({**base, "reason": reason})
            log.warning("road %-5s KEPT ORIGINAL — %s", rid, reason)
            continue

        # drop junction-throat stations near the road ends (contaminated evidence);
        # keep all if the road is too short for the margin
        em = float(c.get("end_margin", 12.0))
        core = mm[(mm[:, 0] > em) & (mm[:, 0] < rd.length - em)]
        use_mm = core if len(core) >= max(4, len(mm) // 3) else mm
        if c.get("profile_mode", "constant") == "piecewise":
            knots = build_knots(use_mm[:, 0], use_mm[:, 1] / n_lanes, rd.length,
                                knot_spacing=float(c.get("knot_spacing", 9.0)),
                                w_floor=lane_min, w_cap=lane_max)
        else:
            w_const = float(np.clip(np.median(use_mm[:, 1]) / n_lanes,
                                    lane_min, lane_max))
            # measured width carried full-length; gaps and junction connectors
            # inherit the nearest known width (user directive 2026-07-09)
            knots = [(0.0, w_const), (rd.length, w_const)]
        # lateral registration: shift the lane stack so the modeled carriageway
        # centers on the MEASURED centerline (OSM reflines are laterally biased)
        c_med = float(np.median(use_mm[:, 4]))
        sec0 = next(sec for sec in rd.sections if sec.driving)
        w_ref = knots[len(knots) // 2][1]
        lo_now = rd.lane_offset_at(rd.length / 2)
        stack_center = lo_now + (sec0.n_left - sec0.n_right) * w_ref / 2.0
        center_delta = float(np.clip(c_med - stack_center, -3.0, 3.0))
        profiles[rid] = knots
        road_rows.append({**base, "action": "corrected",
                          "per_lane_median": round(per_lane, 2),
                          "per_lane_min": round(min(k[1] for k in knots), 2),
                          "per_lane_max": round(max(k[1] for k in knots), 2),
                          "center_delta": round(center_delta, 2),
                          "center_measured": round(c_med, 2)})
        for sec_i, sec in enumerate(rd.sections):
            if not sec.driving:
                continue
            sec_end = rd.sections[sec_i + 1].s if sec_i + 1 < len(rd.sections) else rd.length
            for lane_id in sorted(sec.driving):
                updates.append(dict(road_id=rid, lane_section_s=f"{sec.s:.3f}",
                                    lane_section_end=f"{sec_end:.3f}", lane_id=lane_id,
                                    center_delta=f"{center_delta:.3f}",
                                    knots=json.dumps([[round(a, 2), round(b, 3)]
                                                      for a, b in knots])))
        log.info("road %-5s CORRECTED  n=%-3d cov=%.2f resid=%.2f m  per-lane %.2f m "
                 "(profile %.2f–%.2f)  center shift %+0.2f m", rid, n_st, coverage,
                 local_resid, w_ref, min(k[1] for k in knots),
                 max(k[1] for k in knots), center_delta)

    if not road_rows:
        raise RuntimeError("no road passed the evidence policy — nothing to correct")

    def _write(name, rows):
        p = ctx.path("conflate", name)
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        return p

    rm_path = _write("road_matches.csv", road_rows)
    up_path = _write("lane_width_updates.csv", updates)
    sk_path = _write("skipped_roads.csv", skipped) if skipped else ""
    if skipped:
        log.warning("NOTIFY: %d matched roads kept their ORIGINAL widths (weak evidence) "
                    "— see %s", len(skipped), sk_path)
    return {"roads_corrected": len(road_rows), "roads_kept_original": len(skipped),
            "lane_updates": len(updates), "stations_matched": n_matched,
            "road_matches_csv": rm_path, "updates_csv": up_path,
            "skipped_csv": sk_path}
