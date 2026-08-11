"""merge-runs: combine per-road results from multiple runs into one corrected map.

Policy: per-road winner-takes-all by evidence — for every road corrected in at
least one run, take the profile from the run with the most matched stations
(tiebreak: coverage). Roads that no run could correct stay original and are
reported with the best-available reason. Apply + validate then run in the merged
run directory (junction tapering sees the union, so connectors blend between the
best-known endpoint widths).

Rationale for winner-takes-all over station pooling: drives may disagree
systematically (e.g. seasonal snowbank narrowing); mixing them widens IQR and
would reject roads that a single good drive measured confidently. The newest/
densest drive usually wins per road, and every decision is traceable to one run.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import shutil

import numpy as np

from .config import Config
from .runctx import RunContext

log = logging.getLogger("lanefit")


def _read(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    return list(csv.DictReader(open(path)))


def merge_runs(run_dirs: list[str], out_dir: str, xodr: str, cfg: Config) -> None:
    if len(run_dirs) < 2:
        raise SystemExit("merge-runs needs at least two --runs")
    for rd in run_dirs:
        if not os.path.exists(os.path.join(rd, "conflate", "road_matches.csv")):
            raise SystemExit(f"{rd} has no completed conflate stage (run it first)")

    # nominal bag from the first run's manifest (for RunContext bookkeeping)
    first = json.load(open(os.path.join(run_dirs[0], "manifest.json")))
    ctx = RunContext(out_dir, bag=first["inputs"]["bag"], xodr=xodr)

    best: dict[str, tuple] = {}       # road_id -> (score, run_dir, row)
    skipped_best: dict[str, tuple] = {}
    for rd in run_dirs:
        for row in _read(os.path.join(rd, "conflate", "road_matches.csv")):
            score = (int(row["n_stations"]), float(row["coverage"]))
            if row["road_id"] not in best or score > best[row["road_id"]][0]:
                best[row["road_id"]] = (score, rd, row)
        for row in _read(os.path.join(rd, "conflate", "skipped_roads.csv")):
            score = (int(row["n_stations"]), float(row["coverage"]))
            if row["road_id"] not in skipped_best or score > skipped_best[row["road_id"]][0]:
                skipped_best[row["road_id"]] = (score, rd, row)
    # a road corrected anywhere is corrected; drop it from skipped
    for rid in best:
        skipped_best.pop(rid, None)

    road_rows, updates = [], []
    for rid, (score, src_run, row) in sorted(best.items(), key=lambda q: -q[1][0][0]):
        row = dict(row)
        row["source_run"] = os.path.basename(src_run)
        road_rows.append(row)
        for u in _read(os.path.join(src_run, "conflate", "lane_width_updates.csv")):
            if u["road_id"] == rid:
                updates.append(u)
        log.info("road %-5s <- %s (n=%s, cov=%s)", rid, os.path.basename(src_run),
                 row["n_stations"], row["coverage"])
    skipped = []
    for rid, (score, src_run, row) in sorted(skipped_best.items()):
        row = dict(row)
        row["source_run"] = os.path.basename(src_run)
        skipped.append(row)
        log.warning("road %-5s KEPT ORIGINAL in all runs — best: %s (%s)",
                    rid, row["reason"], os.path.basename(src_run))

    def _write(name, rows):
        if not rows:
            return ""
        p = ctx.path("conflate", name)
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        return p

    _write("road_matches.csv", road_rows)
    _write("lane_width_updates.csv", updates)
    _write("skipped_roads.csv", skipped)

    # figure/backdrop inputs: concatenate ground clouds + trajectories from all runs
    try:
        xs, gs = [], []
        for rd in run_dirs:
            d = np.load(os.path.join(rd, "measure_widths", "ground.npz"))
            xs.append(d["xyz"])
            gs.append(d["intensity"])
        np.savez_compressed(ctx.path("measure_widths", "ground.npz"),
                            xyz=np.concatenate(xs), intensity=np.concatenate(gs))
        with open(ctx.path("measure_widths", "widths.csv"), "w") as out:
            done = False
            for rd in run_dirs:
                wp = os.path.join(rd, "measure_widths", "widths.csv")
                if not os.path.exists(wp):
                    continue
                lines = open(wp).readlines()
                out.writelines(lines[1:] if done else lines)
                done = True
        with open(ctx.path("extract_trajectory", "gnss_trajectory.csv"), "w") as out:
            hdr_done = False
            for rd in run_dirs:
                with open(os.path.join(rd, "extract_trajectory",
                                       "gnss_trajectory.csv")) as f:
                    lines = f.readlines()
                    if hdr_done:
                        ncol = len(lines[0].split(","))
                        out.write(",".join(["nan"] * ncol) + "\n")   # break plot line
                        out.writelines(lines[1:])
                    else:
                        out.writelines(lines)
                    hdr_done = True
    except Exception as e:
        log.warning("merged figure inputs unavailable: %s", e)

    # audit summary (default width) from the first run, for reporting
    ctx.manifest["stages"]["audit"] = {
        "status": "done", "summary": first["stages"].get("audit", {}).get("summary", {})}
    for st in ("extract_trajectory", "slam", "georeference", "measure_widths"):
        ctx.manifest["stages"][st] = {
            "status": "done", "summary": {"merged_from": [os.path.basename(r)
                                                          for r in run_dirs]}}
    ctx.manifest["stages"]["conflate"] = {
        "status": "done",
        "summary": {"roads_corrected": len(road_rows),
                    "roads_kept_original": len(skipped),
                    "lane_updates": len(updates),
                    "merged_from": [os.path.basename(r) for r in run_dirs]}}
    ctx._save_manifest()
    log.info("merged %d runs: %d roads corrected, %d kept original — now run "
             "apply + validate", len(run_dirs), len(road_rows), len(skipped))

    from . import validate as validate_mod
    ctx.run_stage("apply", validate_mod.run_apply, ctx, cfg, force=True)
    ctx.run_stage("validate", validate_mod.run_validate, ctx, cfg, force=True)
