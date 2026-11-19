# Shared client experiment logging

UB-MR and CARLA clients use the same CSV schema and the same Python plotting
package, `ub_experiment`. Its source is in `UB-MR/Scripts/ub_experiment`; it has
no Unity, ROS, CARLA, Redis, pygame, or input-device dependency. The C# recorder
is an adapter for that schema. Old UB-MR CSV files remain readable.

## Shared client log folder

Client output defaults to `Client-Logs/` at the root of UB-DigitalTwin:

```text
Client-Logs/
  ub-mr/
    ub-mr-player.log
    unity-editor.log
    experiments/run-*/
  manual-control/
    manual-control.log
    telemetry.log
    experiments/run-*/
```

The player and editor write their respective Unity logs; the manual Docker
launchers append terminal output to `manual-control.log`. Redis lifecycle and
optional payload logging writes `telemetry.log` when that transport is used.
Experiment folders contain CSV, metadata, status, summaries, and graphs.
The root folder is ignored by Git. `UB-MR/Docker/Logs` and `CARLA/Logs` are
legacy locations; compatibility links can preserve them when migrating logs.

`UB_CLIENT_LOG_ROOT=/absolute/path` changes the shared root for both clients.
The existing per-client overrides still work: `UB_MR_LOG_DIR` for UB-MR Docker
logs, `UB_CLIENT_LOG_HOST_DIR` for manual Docker logs, and `UB_CLIENT_LOG_DIR`
for native client logs. `UB_EXPERIMENT_HOST_DIR` or Docker `--log-dir` changes
only experiment output; native clients use `UB_EXPERIMENT_DIR` or `--log-dir`.
Restart clients to apply changed log settings. Unity editor experiment recording
still uses its existing menu toggle.

## Run the existing clients

The normal UB-MR Docker launcher continues to record automatically. Editor
recording remains controlled by **UB-MR → Telemetry → Record Editor experiments**.

The CARLA manual-client launchers enable experiment recording by default:

```bash
# Enable explicitly, including the managed GCP/IAP tunnel:
bash scripts/launch_carla_redis_manual_client.sh --iap 'your-shared-password' --log-network
# Direct server connection:
bash scripts/launch_carla_redis_manual_client.sh --log-network <server-ip>
# Or, with the CARLA world already running:
bash CARLA/start_manual_client.sh --log-network
# Disable CSV recording, probes, and graph generation for a session:
bash scripts/launch_carla_redis_manual_client.sh --iap 'your-shared-password' --no-log-network
```

Both launchers accept `--log-dir DIRECTORY` for the host output parent and
`--network-interface INTERFACE` to select host byte counters (`auto` or `none`
are also accepted). Relative CLI output paths are resolved from the directory
where you invoke the launcher. Flags override environment values. Without a
logging flag, the existing `UB_EXPERIMENT_ENABLED` setting is preserved, or
recording defaults to enabled for these Docker launchers.

CARLA Compose rebuilds the networking image with the recorder and Matplotlib.
It mounts host `Client-Logs/manual-control` at `/app/Logs`; UB-MR mounts
`Client-Logs/ub-mr` there. Experiments use the `experiments/` subfolder. Logs and graphs survive container
removal. `UB_EXPERIMENT_HOST_DIR=/absolute/path` selects another host experiment
directory for either launcher. Existing containers must be recreated to pick up
new Python packages, environment variables, and mounts.

For native clients, install the two local packages in the **same Python
environment as the client** (from the repository root):

```bash
python3 -m pip install -e './UB-MR/Scripts[plots]' -e ./CARLA/UB-API/ub-telemetry
```

The following entry points have recording hooks:

| Client | Entry point |
| --- | --- |
| Docker keyboard | `CARLA/UB-API/redis-networking/manual_control.py` |
| Native keyboard | `carla_app/PythonAPI/examples/manual_control.py` |
| Wheel/joystick | `carla_app/PythonAPI/examples/manual_control_steeringwheel.py` |
| Logitech wheel/drive sim | `CARLA/UB-API/logitech-driving-wheel/manual_control_steeringwheel.py` |
| Mustang keyboard/physical controls and UDP | `carla_app/PythonAPI/examples/machine_specific_scripts/Mustang/UB_Mustang.py` |
| Redis clients/renderers using `Telemetry` | `CARLA/UB-API/ub-telemetry` |

Enable a native session before invoking its usual command:

```bash
# Native keyboard, wheel/joystick, Logitech and Mustang clients accept the same flags:
python3 carla_app/PythonAPI/examples/manual_control.py \
  --host 127.0.0.1 --port 2000 --log-network

# Environment-only configuration is also supported:
export UB_EXPERIMENT_ENABLED=1
export UB_EXPERIMENT_DIR="$PWD/Client-Logs/manual-control/experiments"
export UB_EXPERIMENT_CONTROLLER=joystick  # e.g. keyboard, wheel, drive-sim, mustang
# Run the client using its normal arguments, including --host and --port.
```

Native logging defaults to off; the two Docker manual-client launchers default
to on. Other Compose services default to off unless `UB_EXPERIMENT_ENABLED=1`
is supplied. `UB_EXPERIMENT_ENABLED=0` disables the new Python hooks without
changing the control calls. The transport package can still be used without
installing `ub_experiment` when recording is off.

Native `--no-log-network` overrides an enabled environment setting. Use the
client's `--help` for all logging flags. Existing recorder hooks collect CARLA
RPC RTT, controller callback-to-control-call timing, and host-interface byte
counts/rates; Redis transports additionally collect Redis RTT, payload bytes,
and handler/publish timing. These use the same recorder, CSV schema, and plotter
as UB-MR, with no separate network-logging implementation.

The instrumented controller scripts import `ub_experiment` directly and need that
package installed even when their recording toggle is off. Pure wheel/joystick
clients do not acquire a Redis dependency from the logging adapter; install the
transport package as well only when using Redis renderers.

## Measurements and scope

| Metric | Meaning |
| --- | --- |
| `receive_to_publish`, source `control/<controller>` | Input polling/callback entry to successful return of the local `apply_control` call. Includes input decoding and computation. Excludes the frame limiter. A failed control call produces no sample. It does not measure simulator response, actuation, display latency, or physical input arrival before the callback. |
| UB-MR `receive_to_publish` | Existing LiDAR callback-to-successful-local-ROS-publish timing, including queue delay and bypass. |
| `carla_rpc_rtt` | An independent connection calls CARLA `get_server_version` about once per second. Includes request/response transport and server processing; it does not measure a control acknowledgement or pure network propagation time. |
| `redis_rtt` | Independent bounded Redis PING/PONG probes, including for subscriber-only roles. Failed probes generate connection events but no RTT values. Reconnection starts a new timing series. |
| `fetch_to_publish` | Redis telemetry payload fetch through successful publish return. No causal association with a received message is assumed. |
| `receive_to_handler` | Redis message receipt through successful return of the receiver callback. This ends at handler completion, rather than at a downstream publish. |
| `redis_payload` throughput | UTF-8 JSON bytes successfully published or delivered to this client, including its own echoed messages. Excludes Redis framing and transport overhead. UB-MR's existing `redis [...]` scope continues counting RESP bytes and is labeled separately. |
| `udp/*` throughput | Actual successful socket send/receive data bytes for Mustang telemetry and motion-base sockets. Excludes protocol headers and retransmissions. |
| `interface/<name>` throughput | Linux interface RX/TX counters. Includes other processes and transport overhead. **This is host-interface traffic, not process-specific CARLA bandwidth.** |

CARLA's native extension hides its internal RPC/streaming byte counts. The CARLA
adapter therefore asks `ip -j route get` which Linux interface reaches the CARLA
host and samples that interface, explicitly labeled with this broader scope.
The Docker image includes `iproute2`; native Linux clients need that command
for automatic selection. Set `UB_EXPERIMENT_INTERFACE=<interface>` to select an
interface, or `none` to disable interface collection. Missing/reset counters are
unavailable rather than invented zeros. On other operating systems, application
payload counters and RTT/control timings still work; supply your own byte counters
through the generic API if you need additional throughput scopes.

For the manual launcher's managed IAP tunnel, interface detection follows the
route to gcloud's IAP gateway (`tunnel.cloudproxy.app`) rather than the local
forward at `127.0.0.1`. This captures host-interface traffic carrying the
encrypted tunnel. RPC RTT is still measured through the forwarded CARLA API.
Set `UB_EXPERIMENT_NETWORK_HOST` to override the route-selection host, or use
`--network-interface` for a specific NIC/VPN. For an externally managed tunnel,
set one of these explicitly; a loopback endpoint otherwise selects loopback.
Interface totals still include other host processes; they are not per-client
CARLA bandwidth.

Do not sum payload, RESP, and interface series: they overlap and measure different
parts of the data path. RTTs and durations use local monotonic clocks and require
no clock synchronization. Control hooks wrap the existing calls and do not change
the control values, polling frequency, or simulator settings.

The CARLA probe uses one client worker thread. Its
[`get_server_version` RPC](https://github.com/carla-simulator/carla/blob/0.9.15/LibCarla/source/carla/client/detail/Client.cpp#L131)
waits for a server response; the
[Python binding](https://github.com/carla-simulator/carla/blob/0.9.15/PythonAPI/carla/source/libcarla/Client.cpp#L176)
releases the GIL while waiting. The probe therefore runs off the control loop.

## Files and configuration

Each process creates its own `run-<yyyyMMdd-HHmmss>Z-<host>-<unique suffix>` folder.
Controllers and Redis transports within that process share one recorder. The
folder contains `metrics.csv`, `experiment.json` (client/controller/host identity
and traffic definitions), `recording-status.txt`, the three standard PNG graphs,
`summary.json`, and graphs for any additional timing metrics. Timing graphs show
one-second means and min/max ranges; individual events remain in the CSV.

| Variable | Use |
| --- | --- |
| `UB_CLIENT_LOG_ROOT` | Shared host log root, default `<repo>/Client-Logs`. Clients use `ub-mr/` or `manual-control/` beneath it. |
| `UB_CLIENT_LOG_DIR` | Per-client directory for native logs; Docker sets this to its `/app/Logs` mount. |
| `UB_CLIENT_LOG_HOST_DIR` | Manual Docker client host directory, default `<repo>/Client-Logs/manual-control`. |
| `UB_EXPERIMENT_ENABLED` | `1` enables, `0` disables. In UB-MR it overrides the legacy `UB_MR_METRICS_ENABLED` environment setting; the Editor menu must also be enabled. |
| `UB_EXPERIMENT_CONTROLLER` | Controller label in metadata; defaults to the adapter's controller type. |
| `UB_EXPERIMENT_CLIENT_ID` | Optional participant ID; otherwise generated per process/session. |
| `UB_EXPERIMENT_DIR` | Native output parent. In Docker, use `UB_EXPERIMENT_HOST_DIR` to choose the host bind-mount destination. |
| `UB_EXPERIMENT_HOST_NAME` | Override the host label. Docker launchers forward the real host name. |
| `UB_EXPERIMENT_INTERFACE` | Linux interface name, automatic selection for CARLA by default, or `none`. |
| `UB_EXPERIMENT_NETWORK_HOST` | Optional routing target for automatic CARLA interface selection. Managed IAP manual sessions default to `tunnel.cloudproxy.app`. Does not change the CARLA API endpoint. |
| `UB_EXPERIMENT_PLOTS` | `0` records CSV without automatically rendering graphs; defaults to `1`. Editor graphs still use the manual command. |

The queue is bounded; callbacks enqueue while a worker writes and flushes about
once per second. Successful throughput samples use actual elapsed time, including
the final partial interval. Check `recording-status.txt` for dropped rows or writer
errors. Python session adapters handle Ctrl+C/SIGTERM so normal Docker stops drain
the queue and generate graphs. Forced termination can lose buffered rows and skip
graphs; regenerate from preserved CSV files afterward:

```bash
ub-experiment-plot /path/to/run-or-experiments-parent
# Compatible UB-MR entry point, from repository root:
python3 UB-MR/Scripts/plot_experiment_metrics.py /path/to/run
```

The shared library records no control values, passwords, or complete telemetry
payloads. The transport's separate `UB_TELEMETRY_LOG_PAYLOADS` debugging setting
continues to control full payload logging.

## Add another client

Use a context for the client lifetime. All callbacks can use `current()`; callers
may also retain the returned recorder explicitly across threads. Keep custom probe
timeouts bounded (at most one second is recommended).

```python
from ub_experiment import experiment, current

with experiment(client_type="my-client", controller_type="drive-sim") as log:
    if log:
        log.define_traffic("device_payload", "Device data bytes, no protocol headers")
        log.add_probe("server", ping_with_one_second_timeout)

    # In the receive callback, attach this token to the actual queued message:
    received_at = log.clock() if log else None
    if log:
        log.traffic("device_payload", received=len(message_bytes))
    # Decode/process/queue the message. When that same message is published:
    publish(output_bytes)
    if log:
        log.traffic("device_payload", sent=len(output_bytes))
        log.timing("receive_to_publish", "device", started_at=received_at)
```

For CARLA controls, decorate the client lifetime with
`ub_experiment.carla.carla_session("controller-name")`, decorate the input polling
method with `input_callback("controller-name")`, and submit through
`apply_control(vehicle, control)`. These adapters preserve the underlying call's
return value and exceptions. `measured_socket(sock, "udp/my-device")` wraps explicit
socket operations without changing their data.

For C# clients, `ExperimentLog` and `ResourceTelemetry` have no Unity dependency.
Use `ExperimentLog.RecordTiming(metric, source, startedAt)`, with timestamps from
`MonotonicClock.Instance.Seconds`. `TrafficMeter` exposes public byte counters and
source registration; submit its snapshots with `ExperimentLog.RecordTraffic`.
`ResourceTelemetry.RegisterSensor` and `SensorTelemetry.RecordPublished` provide
the existing queue-aware sensor adapter. The old LiDAR and Redis hooks remain
compatible.

## Validation

```bash
PYTHONPATH=UB-MR/Scripts:CARLA/UB-API/ub-telemetry \
  python3 -m unittest discover -s UB-MR/Scripts -p 'test_*.py' -v
PYTHONPATH=UB-MR/Scripts:CARLA/UB-API/ub-telemetry \
  python3 -m unittest discover -s CARLA/UB-API/ub-telemetry/tests -v
PYTHONPATH=UB-MR/Scripts:CARLA/UB-API/ub-telemetry \
  python3 -m unittest discover -s CARLA/UB-API/redis-networking/tests -v
```

These fixtures verify concurrency, final byte/rate accounting, successful control
timings, probe failures and shutdown, shared recorder ownership, naming, CSV
compatibility and graphs without driving hardware or a CARLA server. Validate
physical controls and real server/network behavior in an experiment before relying
on the timings for a performance comparison.
