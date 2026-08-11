"""lanefit CLI.

  lanefit run       --bag B --xodr X --out RUN     # the whole pipeline
  lanefit stage <name> --out RUN [--bag/--xodr on first use]
  lanefit audit     --bag B --xodr X --out RUN     # audit only
  lanefit trim-bag  --bag B --out-bag B2           # remove parked periods
  lanefit stages                                    # list stage names

Run inside the tooling container with ROS sourced (the bin/lanefit wrapper does
both). All paths must be container-visible (e.g. under /host_data).
"""
from __future__ import annotations

import argparse
import sys

from . import audit as audit_mod
from . import conflate as conflate_mod
from . import georef as georef_mod
from . import gnss as gnss_mod
from . import measure as measure_mod
from . import slam as slam_mod
from . import validate as validate_mod
from .config import load_config
from .runctx import STAGES, RunContext, setup_logging

STAGE_FN = {
    "audit": audit_mod.run,
    "extract_trajectory": gnss_mod.run,
    "slam": slam_mod.run,
    "georeference": georef_mod.run,
    "measure_widths": measure_mod.run,
    "conflate": conflate_mod.run,
    "apply": validate_mod.run_apply,
    "validate": validate_mod.run_validate,
}


def _common(p: argparse.ArgumentParser, needs_out: bool = True) -> None:
    if needs_out:
        p.add_argument("--out", required=True, help="run directory")
    p.add_argument("--bag", help="input rosbag directory")
    p.add_argument("--xodr", help="input OpenDRIVE file")
    p.add_argument("--config", help="user config YAML (deep-merged over defaults)")
    p.add_argument("--set", action="append", default=[], metavar="KEY.PATH=VALUE",
                   help="config override, repeatable")
    p.add_argument("--force", action="store_true", help="re-run stages already done")
    p.add_argument("-v", "--verbose", action="store_true")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lanefit",
                                 description="LiDAR-measured lane widths into OpenDRIVE")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run the full pipeline")
    _common(p_run)
    p_run.add_argument("--from-stage", choices=STAGES, help="start at this stage")
    p_run.add_argument("--until-stage", choices=STAGES, help="stop after this stage")

    p_stage = sub.add_parser("stage", help="run one stage")
    p_stage.add_argument("name", choices=STAGES)
    _common(p_stage)

    p_audit = sub.add_parser("audit", help="audit inputs only (alias of `stage audit`)")
    _common(p_audit)

    p_merge = sub.add_parser("merge-runs",
                             help="combine roads from multiple runs (winner by evidence)")
    p_merge.add_argument("--runs", required=True,
                         help="comma-separated run dirs (each with conflate done)")
    p_merge.add_argument("--out", required=True, help="merged run directory")
    p_merge.add_argument("--xodr", required=True)
    p_merge.add_argument("--config")
    p_merge.add_argument("--set", action="append", default=[])
    p_merge.add_argument("-v", "--verbose", action="store_true")

    p_trim = sub.add_parser("trim-bag", help="copy a bag without parked periods")
    p_trim.add_argument("--bag", required=True)
    p_trim.add_argument("--out-bag", required=True)
    p_trim.add_argument("--config")
    p_trim.add_argument("--set", action="append", default=[])
    p_trim.add_argument("-v", "--verbose", action="store_true")

    sub.add_parser("stages", help="list pipeline stages in order")

    args = ap.parse_args(argv)
    if args.cmd == "stages":
        print("\n".join(STAGES))
        return 0

    setup_logging(getattr(args, "verbose", False))
    cfg = load_config(getattr(args, "config", None), getattr(args, "set", []))

    if args.cmd == "merge-runs":
        from .merge import merge_runs
        merge_runs([r.strip() for r in args.runs.split(",")], args.out, args.xodr, cfg)
        return 0

    if args.cmd == "trim-bag":
        from .bagtools import trim_parked
        trim_parked(args.bag, args.out_bag, cfg)
        return 0

    ctx = RunContext(args.out, bag=args.bag, xodr=args.xodr)

    if args.cmd == "audit":
        ctx.run_stage("audit", STAGE_FN["audit"], ctx, cfg, force=True)
        return 0
    if args.cmd == "stage":
        ctx.run_stage(args.name, STAGE_FN[args.name], ctx, cfg, force=args.force)
        return 0

    # full run
    stages = list(STAGES)
    if args.from_stage:
        stages = stages[stages.index(args.from_stage):]
        # stages before from-stage must already be done
        for s in STAGES[:STAGES.index(args.from_stage)]:
            if not ctx.stage_done(s):
                print(f"error: --from-stage {args.from_stage} but prerequisite "
                      f"'{s}' is not done in {ctx.run_dir}", file=sys.stderr)
                return 2
    if args.until_stage:
        stages = stages[:stages.index(args.until_stage) + 1]
    for s in stages:
        ctx.run_stage(s, STAGE_FN[s], ctx, cfg, force=args.force)
    print(f"\npipeline complete — see {ctx.run_dir}/report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
