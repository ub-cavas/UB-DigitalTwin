# DT-27 — CARLA `-nullrhi` viability and sustained-tick check

## Decision

`-nullrhi` is viable for the current build's **headless world-master** path:
the smoke run on the UB proving-grounds map loaded successfully, returned a
`world.cast_ray()` road hit, and kept all 50 synchronous Traffic Manager
vehicles alive and moving at 59.99 Hz for 20 seconds. The required 30-minute
probe is the decision gate for adopting it.

Traffic Manager and `world.cast_ray()` are part of CARLA's simulation API, not
a separate no-render API. Consequently `-nullrhi` may be used only after the
exact CARLA build, map, GPU driver, and 30-minute report pass this probe. The
existing launchers retain `-RenderOffScreen` as their conservative default
until the evidence is recorded.

## Acceptance probe

`CARLA/UB-API/util/headless_spike.py` is the repeatable test. It connects to
a dedicated CARLA server, then:

1. enables synchronous mode, a 1/60 s fixed step, and valid substepping;
2. enables synchronous Traffic Manager with seed 27;
3. casts a ray through the road below a known map spawn point;
4. spawns exactly 50 Traffic Manager autopilot vehicles; and
5. paces `world.tick()` for 1,800 wall-clock seconds, checking that all
   vehicles remain alive and at least one moves.

The JSON report contains the map, ray-hit count, actor count, tick rate, late
ticks, and an error string. The pass threshold is at least 99% of the requested
rate (59.4 Hz at 60 Hz). It is deliberately evidence rather than a log scrape:
a nonzero process exit or `"status": "failed"` is a failed spike. Inspect
the CARLA container log afterwards; any Vulkan validation error also fails the
spike.

Run it inside the CARLA container, after the map loader has completed:

```bash
cd CARLA
CARLA_ARGS='-RenderOffScreen -quality-level=Low -nosound' \
  docker compose up -d carla map-loader
docker cp UB-API/util/headless_spike.py ub-carla-container:/tmp/headless_spike.py
docker exec ub-carla-container bash -lc '
  wheel=$(find /carla/PythonAPI/carla/dist -maxdepth 1 -name "carla-*-cp310-*.whl" | head -n1)
  test -n "$wheel"
  python3 -m pip install --no-index --target /tmp/dt27-carla "$wheel"
  PYTHONPATH=/tmp/dt27-carla python3 /tmp/headless_spike.py \
    --output /tmp/dt27-render-offscreen.json
'
docker cp ub-carla-container:/tmp/dt27-render-offscreen.json ./dt27-render-offscreen.json
```

For the `-nullrhi` run, repeat the exact procedure with only `CARLA_ARGS`
changed to `-nullrhi -nosound`. Do not make it the default merely because the
process opens its RPC port: it must produce a passing JSON report, no Vulkan
validation errors, and comparable tick/ray/actor results. A failure leaves
`-RenderOffScreen` as the supported master configuration.

## Result status

The 20-second smoke run on 2026-08-18 passed under `-nullrhi`:

```json
{"actual_hz": 59.9864, "alive_actor_count": 50, "cast_ray_hit_count": 1,
 "frames": 1200, "map": "Carla/Maps/UBAutonomousProvingGrounds",
 "moved_actor_count": 50, "status": "passed"}
```

The repository now has the 30-minute probe and the initial empirical result.
The subsequent 30-minute run was manually stopped after approximately 15
minutes at the request of the operator. It produced no CARLA or Vulkan error
in the container log before it was stopped, but termination happened before a
JSON report was written. Treat that as supporting observation, **not** a
30-minute pass. Attach a completed 30-minute JSON report and clean CARLA log
before asserting the sustained-tick acceptance criterion.
