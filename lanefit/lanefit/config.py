"""Configuration: default.yaml deep-merged with an optional user file and --set overrides."""
from __future__ import annotations

import copy
import os
from typing import Any

import yaml

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "default.yaml")


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _parse_scalar(s: str) -> Any:
    return yaml.safe_load(s)


class Config:
    """Dot-path access over the merged config dict. cfg('widths.inner.bias')."""

    def __init__(self, data: dict):
        self._d = data

    def __call__(self, path: str, default: Any = KeyError) -> Any:
        cur: Any = self._d
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                if default is KeyError:
                    raise KeyError(f"config key missing: {path}")
                return default
            cur = cur[part]
        return cur

    def section(self, path: str) -> dict:
        v = self(path)
        if not isinstance(v, dict):
            raise TypeError(f"config section expected at {path}")
        return v

    def as_dict(self) -> dict:
        return copy.deepcopy(self._d)


def load_config(user_file: str | None = None, overrides: list[str] | None = None) -> Config:
    with open(_DEFAULT_PATH) as f:
        data = yaml.safe_load(f)
    if user_file:
        with open(user_file) as f:
            data = _deep_merge(data, yaml.safe_load(f) or {})
    for ov in overrides or []:
        if "=" not in ov:
            raise ValueError(f"--set expects key.path=value, got {ov!r}")
        key, val = ov.split("=", 1)
        cur = data
        parts = key.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = _parse_scalar(val)
    return Config(data)
