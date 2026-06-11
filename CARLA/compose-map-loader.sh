#!/usr/bin/env bash
set -euo pipefail

CARLA_MAP_PATH="${CARLA_MAP_PATH-/Game/Carla/Maps/UBAutonomousProvingGrounds}"

if [[ -z "${CARLA_MAP_PATH}" ]]; then
  echo "CARLA_MAP_PATH is empty; skipping CARLA map load."
  exit 0
fi

CARLA_MAP_NAME="${CARLA_MAP_PATH##*/}"
CARLA_PYTHON_TARGET="${CARLA_PYTHON_TARGET:-/tmp/ub-carla-python}"

CARLA_WHEEL="$(find /carla/PythonAPI/carla/dist -maxdepth 1 -type f -name 'carla-*-cp310-*.whl' 2>/dev/null | head -n 1 || true)"

if [[ -z "${CARLA_WHEEL}" ]]; then
  echo "Error: CARLA Python wheel not found under /carla/PythonAPI/carla/dist." >&2
  exit 1
fi

python3 - <<'PY'
import sys

if sys.version_info[:2] != (3, 10):
    raise SystemExit(
        f"Error: container python3 must be 3.10 for the CARLA cp310 wheel, got {sys.version.split()[0]}"
    )
PY

if [[ ! -d "${CARLA_PYTHON_TARGET}/carla" ]]; then
  python3 -m pip install --no-index --target "${CARLA_PYTHON_TARGET}" "${CARLA_WHEEL}" >/dev/null
fi

PYTHONPATH="${CARLA_PYTHON_TARGET}" python3 - <<'PY'
import os
import socket
import sys
import time

import carla

host = os.environ.get("UB_CARLA_HOST", "127.0.0.1")
port = int(os.environ.get("UB_CARLA_PORT", "2000"))
map_name = os.environ["CARLA_MAP_PATH"].split("/")[-1]

for _ in range(120):
    try:
        with socket.create_connection((host, port), timeout=1.0):
            break
    except OSError:
        time.sleep(1.0)
else:
    print(f"Error: timed out waiting for CARLA server at {host}:{port}", file=sys.stderr)
    sys.exit(1)

client = carla.Client(host, port)
client.set_timeout(2.0)

last_error = None
for _ in range(90):
    try:
        world = client.get_world()
        if world.get_map().name.endswith(map_name):
            print(f"CARLA map already loaded: {world.get_map().name}")
            sys.exit(0)

        print(f"Loading CARLA map: {map_name}")
        sys.stdout.flush()
        client.set_timeout(120.0)
        world = client.load_world(map_name)
        print(f"CARLA map loaded: {world.get_map().name}")
        sys.exit(0)
    except RuntimeError as exc:
        last_error = exc
        time.sleep(1.0)

print(f"Error: timed out loading CARLA map '{map_name}': {last_error}", file=sys.stderr)
sys.exit(1)
PY
