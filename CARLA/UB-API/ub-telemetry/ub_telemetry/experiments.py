"""Optional bridge to the portable experiment package; no dependency when off."""
import os
from contextlib import nullcontext


def _enabled():
    return os.environ.get("UB_EXPERIMENT_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def experiment(client_type="carla", controller_type="unspecified"):
    if not _enabled():
        return nullcontext(None)
    from ub_experiment import experiment as shared
    return shared(client_type, controller_type)
