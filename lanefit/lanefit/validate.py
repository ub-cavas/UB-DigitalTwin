"""apply + validate stages (profile semantics).

apply    — writes piecewise width profiles onto corrected driving lanes and blends
           junction connecting-roads between their endpoints (xodr_io.apply_lane_profiles).
validate — CARLA client-side parse + lane_width readback SAMPLED along each corrected
           road against the knot spline; before/after summary vs the original width;
           corrected-roads map figure; final report incl. kept-original notifications.
"""
from __future__ import annotations

import csv
import json
import logging
import os

import numpy as np

from .config import Config
from .profiles import eval_knots
from .runctx import RunContext
from .xodr_io import apply_lane_profiles

log = logging.getLogger("lanefit")


def run_apply(ctx: RunContext, cfg: Config) -> dict:
    updates = list(csv.DictReader(open(ctx.path("conflate", "lane_width_updates.csv"))))
    out_name = os.path.splitext(os.path.basename(ctx.xodr))[0] + "_corrected.xodr"
    out_path = ctx.path("apply", out_name)
    res = apply_lane_profiles(ctx.xodr, updates, out_path,
                              taper_junctions=bool(cfg("apply.taper_junctions", True)))
    return {"corrected_xodr": out_path, **res}


def _carla_readback(xodr_path: str, updates: list[dict], tol: float) -> dict:
    try:
        import carla
    except Exception:
        log.warning("carla python package not available — skipping CARLA readback")
        return {"carla": "unavailable"}
    m = carla.Map("lanefit_corrected", open(xodr_path).read())

    ok = bad = 0
    worst = 0.0
    for u in updates:
        rid = int(u["road_id"])
        lid = int(u["lane_id"])
        knots = [(float(a), float(b)) for a, b in json.loads(u["knots"])]
        s0, s1 = float(u["lane_section_s"]), float(u["lane_section_end"])
        for s in np.linspace(s0 + 0.5, s1 - 0.5, 5):
            if s <= s0 or s >= s1:
                continue
            wp = m.get_waypoint_xodr(rid, lid, float(s))
            if wp is None:
                continue
            want = eval_knots(knots, float(s))
            if not (np.isfinite(wp.lane_width) and np.isfinite(want)):
                continue          # section-boundary artifacts in CARLA's sampling
            err = abs(wp.lane_width - want)
            worst = max(worst, err)
            if err <= max(tol, 0.05):
                ok += 1
            else:
                bad += 1
                if bad <= 5:
                    log.warning("readback mismatch road %s lane %s s=%.1f: carla %.3f "
                                "vs profile %.3f", rid, lid, s, wp.lane_width, want)
    if bad:
        raise RuntimeError(f"CARLA profile readback failed on {bad} samples "
                           f"(worst {worst:.3f} m)")
    log.info("CARLA: map parses; %d sampled widths verified (worst err %.3f m)", ok, worst)

    # NPC drivability: walk the waypoint chain across every corrected road's seams
    # and measure lane-center jumps (a planner follows exactly this chain)
    max_jump = 0.0
    n_seams = 0
    seen_roads = set()
    for u in updates:
        rid, lid = int(u["road_id"]), int(u["lane_id"])
        if (rid, lid) in seen_roads:
            continue
        seen_roads.add((rid, lid))
        s1 = float(u["lane_section_end"])
        for s_probe, fn in ((s1 - 1.0, "next"), (float(u["lane_section_s"]) + 1.0,
                                                 "previous")):
            wp = m.get_waypoint_xodr(rid, lid, float(s_probe))
            if wp is None:
                continue
            try:
                nxts = wp.next(2.0) if fn == "next" else wp.previous(2.0)
            except Exception:
                continue
            for nxt in nxts or []:
                dist = wp.transform.location.distance(nxt.transform.location)
                lat = max(0.0, (dist ** 2 - 4.0)) ** 0.5   # lateral component vs 2 m step
                max_jump = max(max_jump, lat)
                n_seams += 1
    log.info("NPC continuity: %d seam transitions checked, max lane-center jump %.2f m",
             n_seams, max_jump)
    if max_jump > 0.6:
        log.warning("lane-center jump %.2f m > 0.6 m at a seam — NPC vehicles may swerve",
                    max_jump)
    return {"carla": "ok", "samples_verified": ok, "worst_err_m": round(worst, 4),
            "seams_checked": n_seams, "max_lane_center_jump_m": round(max_jump, 2)}


def _summary_vs_original(ctx: RunContext) -> dict:
    rows = list(csv.DictReader(open(ctx.path("conflate", "road_matches.csv"))))
    audit = ctx.summary("audit").get("xodr_dominant_width") or {}
    default_a = float(audit.get("a_m", 3.5))
    deltas = []
    for r in rows:
        n = int(r["n_driving_lanes"])
        deltas.append(abs(float(r["med_width_in"]) - default_a * n) * int(r["n_stations"]))
    total_st = sum(int(r["n_stations"]) for r in rows)
    skipped = 0
    sk_path = ctx.path("conflate", "skipped_roads.csv")
    if os.path.exists(sk_path):
        skipped = sum(1 for _ in csv.DictReader(open(sk_path)))
    return {"roads_corrected": len(rows), "roads_kept_original": skipped,
            "mean_correction_m": round(sum(deltas) / max(total_st, 1), 2),
            "original_default_m_per_lane": default_a}


def run_validate(ctx: RunContext, cfg: Config) -> dict:
    corrected = ctx.summary("apply").get("corrected_xodr")
    if not corrected or not os.path.exists(corrected):
        raise RuntimeError("apply stage output missing")
    updates = list(csv.DictReader(open(ctx.path("conflate", "lane_width_updates.csv"))))

    carla_res = _carla_readback(corrected, updates, float(cfg("validate.width_tol")))
    summary = _summary_vs_original(ctx)

    figs = {}
    from .figures import corrected_roads_map, road_profiles_figure, width_ladder_figure
    default_a = float((ctx.summary("audit").get("xodr_dominant_width") or {}).get("a_m", 3.5))
    try:
        figs["map"] = ctx.path("validate", "corrected_roads_map.png")
        corrected_roads_map(ctx.xodr, ctx.path("conflate", "road_matches.csv"),
                            ctx.path("measure_widths", "ground.npz"),
                            ctx.path("extract_trajectory", "gnss_trajectory.csv"),
                            figs["map"],
                            updates_csv=ctx.path("conflate", "lane_width_updates.csv"),
                            skipped_csv=ctx.path("conflate", "skipped_roads.csv"))
    except Exception as e:
        log.warning("map figure skipped: %s", e)
    try:
        figs["profiles"] = ctx.path("validate", "road_profiles.png")
        road_profiles_figure(ctx.path("conflate", "road_matches.csv"),
                             ctx.path("conflate", "lane_width_updates.csv"),
                             figs["profiles"], default_lane_w=default_a)
    except Exception as e:
        log.warning("profiles figure skipped: %s", e)
    try:
        figs["ladder"] = ctx.path("validate", "width_ladder.png")
        width_ladder_figure(ctx.path("measure_widths", "widths.csv"),
                            ctx.path("measure_widths", "ground.npz"),
                            ctx.path("extract_trajectory", "gnss_trajectory.csv"),
                            figs["ladder"])
    except Exception as e:
        log.warning("ladder figure skipped: %s", e)
    fig_path = figs

    report = {"corrected_xodr": corrected, "carla": carla_res, **summary,
              "figure": fig_path}
    with open(ctx.path("validate", "validation.json"), "w") as f:
        json.dump(report, f, indent=2)

    lines = ["# lanefit run report", ""]
    for stage in ("audit", "extract_trajectory", "slam", "georeference",
                  "measure_widths", "conflate", "apply"):
        lines.append(f"## {stage}")
        for k, v in ctx.summary(stage).items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    lines += ["## validate", f"- carla: {carla_res}", f"- summary: {summary}",
              f"- corrected map: `{corrected}`",
              "- figures: " + ", ".join(f"`{v}`" for v in fig_path.values()), "",
              "## corrected roads", "",
              "| road | lanes | stations | coverage | per-lane profile [m] | source |",
              "|---|---|---|---|---|---|"]
    for r in csv.DictReader(open(ctx.path("conflate", "road_matches.csv"))):
        lines.append(f"| {r['road_id']} | {r['n_driving_lanes']} | {r['n_stations']} | "
                     f"{r['coverage']} | {r['per_lane_min']}–{r['per_lane_max']} | "
                     f"{r.get('source_run', '-')} |")
    sk = ctx.path("conflate", "skipped_roads.csv")
    if os.path.exists(sk):
        lines += ["", "## NOTICE — roads kept at ORIGINAL widths (weak evidence)", ""]
        for r in csv.DictReader(open(sk)):
            lines.append(f"- road {r['road_id']}: {r['reason']} "
                         f"(n={r['n_stations']}, cov={r['coverage']}, "
                         f"med_in={r['med_width_in']} m)")
    with open(os.path.join(ctx.run_dir, "report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    log.info("run report: %s", os.path.join(ctx.run_dir, "report.md"))
    return report
