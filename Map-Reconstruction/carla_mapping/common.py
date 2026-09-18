"""Shared configuration, provenance, and durable artifact writes."""
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

import yaml

DEFAULTS = {
    'max_spacing': 1.0, 'chord_error': 0.05, 'join_tolerance': 0.10,
    'station_spacing': 3.0, 'voxel': 0.10, 'range': 90.0, 'channels': 128,
    'sweeps': 2, 'height': 3.1, 'horizontal_samples': 1024,
    'upper_fov': 30.0, 'lower_fov': -89.0, 'delta': 0.1,
    'memory_mib': 2048, 'tile_size': 20.0, 'export': 'tiled',
    'streaming_distance': 200.0, 'retries': 5, 'scan_timeout': 15.0,
    'surface_tolerance': 0.50, 'coverage_fraction': 0.99,
    'bounds': None,
}


def canonical_source(source):
    return ET.canonicalize(source, strip_text=True)


def fingerprint(source):
    return hashlib.sha256(canonical_source(source).encode()).hexdigest()


def stable_id(key):
    # Positive, signed-int64-safe and exactly representable by common JSON clients.
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:6], 'big') + 1


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data.encode() if isinstance(data, str) else data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path, value):
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def configuration(path=None, overrides=None):
    result = DEFAULTS.copy()
    if path:
        data = yaml.safe_load(Path(path).read_text())
        if not isinstance(data, dict):
            raise ValueError('Configuration must be a YAML mapping')
        unknown = set(data) - set(result)
        if unknown:
            raise ValueError(f'Unknown configuration keys: {sorted(unknown)}')
        result.update(data)
    result.update({k: v for k, v in (overrides or {}).items() if v is not None})
    for key, value in result.items():
        if key not in ('bounds', 'export', 'lower_fov', 'upper_fov'):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{key} must be finite and positive')
    for key in ('channels', 'sweeps', 'horizontal_samples', 'retries', 'tile_size'):
        if int(result[key]) != result[key]:
            raise ValueError(f'{key} must be an integer')
        result[key] = int(result[key])
    if result['export'] not in ('single', 'tiled'):
        raise ValueError('export must be single or tiled')
    if result['memory_mib'] < 64:
        raise ValueError('memory_mib must be at least 64')
    if not -90 <= result['lower_fov'] < result['upper_fov'] <= 90:
        raise ValueError('Require -90 <= lower_fov < upper_fov <= 90')
    if result['delta'] > 0.1 or result['coverage_fraction'] > 1:
        raise ValueError('delta must be <= 0.1; coverage_fraction must be <= 1')
    if result['streaming_distance'] < result['range'] + result['height']:
        raise ValueError('streaming_distance must exceed sensor range + height')
    if result['bounds'] is not None:
        b = result['bounds']
        if len(b) != 4 or not all(math.isfinite(x) for x in b) or b[0] >= b[2] or b[1] >= b[3]:
            raise ValueError('bounds must be finite xmin ymin xmax ymax in Local coordinates')
    return result


class Diagnostics:
    def __init__(self):
        self.items = []
        self._seen = set()

    def add(self, code, source, message, category='structural', severity='error'):
        item = dict(code=code, source=source, message=message, category=category, severity=severity)
        key = (code, source, message)
        if key not in self._seen:
            self._seen.add(key)
            self.items.append(item)

    def errors(self, category=None):
        return [x for x in self.items if x['severity'] == 'error' and (category is None or x['category'] == category)]
