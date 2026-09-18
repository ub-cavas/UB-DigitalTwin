# ub-telemetry

Shared telemetry transport for UB Digital Twin participants: the message
envelope, the message type registry, and the Redis pub/sub plumbing.

The wire protocol this implements is specified in
[docs/telemetry-protocol.md](../../docs/telemetry-protocol.md). This package is
the reference implementation of that document.

## Why this exists

The same telemetry code was maintained separately in `ub-cavas/UB-DigitalTwin`
and `CHELabUB/carla_app`, and the copies drifted: different default channels,
one side without environment-variable configuration, and a type guard on only
one side. Both repositories should depend on this package instead of carrying
their own copy.

## Install

```bash
pip install -e packages/ub-telemetry              # from a UB-DigitalTwin checkout
pip install "git+https://github.com/ub-cavas/UB-DigitalTwin.git#subdirectory=packages/ub-telemetry"
```

Pin a version on client machines so simulators can be upgraded one at a time.

The CARLA Python API is **not** a declared dependency. It ships as a wheel
inside a packaged CARLA build, so install it from that local path first if you
need the renderers:

```bash
pip install /path/to/CARLA/PythonAPI/carla/dist/carla-*-cp310-*.whl
```

## Use

```python
from ub_telemetry import Telemetry, MESSAGE_TYPES

# Where CARLA is available:
from ub_telemetry.multi_agent_renderer import MultiAgentRenderer
from ub_telemetry.multi_traffic_renderer import MultiTrafficRenderer

renderer = MultiAgentRenderer()   # peers, type 0/1
traffic = MultiTrafficRenderer()  # server traffic, type 2
renderer.start()
traffic.start()
```

Both renderers also run standalone:

```bash
python -m ub_telemetry.multi_agent_renderer
python -m ub_telemetry.multi_traffic_renderer
```

Configure with `UB_REDIS_HOST`, `UB_REDIS_PORT`, `UB_REDIS_PASSWORD` and
`UB_REDIS_CHANNEL`. `UB_CARLA_HOST` and `UB_CARLA_PORT` point the renderers at
a local CARLA — they default to `localhost:2000` and should stay local, since
rendering happens client-side.

## Extending

Subclass `Telemetry`, override `handle_fetch_telemetry_data` to publish and
`on_receive_telemetry` to consume. Set `PUBLISH_TELEMETRY = False` on
subscriber-only roles so they do not publish empty messages.

Read the "Rules for consumers" section of the protocol document before writing
an `on_receive_telemetry`; the type guard is not optional.
