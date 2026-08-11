"""Run context: directory layout, manifest (resume/skip), per-stage logging."""
from __future__ import annotations

import json
import logging
import os
import time
import traceback
from typing import Callable

log = logging.getLogger("lanefit")

STAGES = [
    "audit",
    "extract_trajectory",
    "slam",
    "georeference",
    "measure_widths",
    "conflate",
    "apply",
    "validate",
]


class StageFailed(RuntimeError):
    pass


class RunContext:
    """One pipeline run rooted at run_dir, with inputs bag+xodr and a manifest."""

    def __init__(self, run_dir: str, bag: str | None = None, xodr: str | None = None):
        self.run_dir = os.path.abspath(run_dir)
        os.makedirs(self.run_dir, exist_ok=True)
        os.makedirs(os.path.join(self.run_dir, "logs"), exist_ok=True)
        self._manifest_path = os.path.join(self.run_dir, "manifest.json")
        self.manifest = self._load_manifest()
        inputs = self.manifest.setdefault("inputs", {})
        if bag:
            inputs["bag"] = os.path.abspath(bag)
        if xodr:
            inputs["xodr"] = os.path.abspath(xodr)
        if not inputs.get("bag") or not inputs.get("xodr"):
            raise SystemExit("run dir has no recorded inputs; pass --bag and --xodr")
        self.bag: str = inputs["bag"]
        self.xodr: str = inputs["xodr"]
        self._save_manifest()

    # ---------- paths ----------
    def dir(self, stage: str) -> str:
        d = os.path.join(self.run_dir, stage)
        os.makedirs(d, exist_ok=True)
        return d

    def path(self, stage: str, *names: str) -> str:
        return os.path.join(self.dir(stage), *names)

    # ---------- manifest ----------
    def _load_manifest(self) -> dict:
        if os.path.exists(self._manifest_path):
            with open(self._manifest_path) as f:
                return json.load(f)
        return {"stages": {}}

    def _save_manifest(self) -> None:
        tmp = self._manifest_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.manifest, f, indent=2, default=str)
        os.replace(tmp, self._manifest_path)

    def stage_done(self, stage: str) -> bool:
        return self.manifest["stages"].get(stage, {}).get("status") == "done"

    def summary(self, stage: str) -> dict:
        return self.manifest["stages"].get(stage, {}).get("summary", {})

    # ---------- execution ----------
    def run_stage(self, stage: str, fn: Callable[..., dict], *args, force: bool = False) -> dict:
        if self.stage_done(stage) and not force:
            log.info("[%s] already done — skipping (use --force to re-run)", stage)
            return self.summary(stage)

        rec = {"status": "running", "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.manifest["stages"][stage] = rec
        self._save_manifest()

        fh = logging.FileHandler(os.path.join(self.run_dir, "logs", f"{stage}.log"))
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(fh)
        t0 = time.time()
        try:
            log.info("[%s] starting", stage)
            summary = fn(*args) or {}
            rec.update(status="done", ended=time.strftime("%Y-%m-%dT%H:%M:%S"),
                       elapsed_s=round(time.time() - t0, 1), summary=summary)
            log.info("[%s] done in %.1fs", stage, time.time() - t0)
            return summary
        except Exception as e:
            rec.update(status="failed", ended=time.strftime("%Y-%m-%dT%H:%M:%S"),
                       elapsed_s=round(time.time() - t0, 1), error=str(e))
            log.error("[%s] FAILED: %s\n%s", stage, e, traceback.format_exc())
            raise StageFailed(f"stage {stage} failed: {e}") from e
        finally:
            self._save_manifest()
            logging.getLogger().removeHandler(fh)
            fh.close()


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
