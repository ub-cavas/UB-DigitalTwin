# Traffic Spawner (Fixed Points)

This script (`test_traffic1.py`) spawns random vehicles only at designated spawn points, keeps a maximum count, enables waypoint following via CARLA Traffic Manager, and respawns if vehicles are destroyed.

## Requirements
- CARLA 0.9.x server running (same version as Python API)
- `carla` Python egg installed in your environment

If the editor flags `Import "carla" could not be resolved`, ensure your Python interpreter includes CARLA's egg, e.g.:

```bash
# Example for CARLA_0.9.16 Python 3.8
export CARLA_ROOT=~/CARLA_0.9.16
export PYTHONPATH="$CARLA_ROOT/PythonAPI/carla/dist/carla-0.9.16-py3.8-linux-x86_64.egg:$PYTHONPATH"
```

Adjust the version and Python minor version to match your setup.

## Run examples

Use first N map spawn points and keep up to 30 vehicles:

```bash
python3 test_traffic1.py --max-vehicles 30 --points-from-map 10 --sync
```

Use custom points from JSON file and cap total environment vehicles to 100:

```bash
python3 test_traffic1.py --spawn-file spawns.example.json --limit-total --max-env-vehicles 100 --max-vehicles 40 --sync
```

Inline JSON points:

```bash
python3 test_traffic1.py --spawn-json '[{"x":0,"y":0,"z":0.5,"yaw":0}]' --max-vehicles 10 --sync
```

## Notes
- Vehicles use Traffic Manager autopilot for waypoint following. You can set speed with `--tm-perc-speed` and inter-vehicle distance with `--tm-global-distance`.
- If a spawn location is blocked, the script will try others in subsequent loops.
- Only vehicles created by this script are destroyed on exit (Ctrl+C).
