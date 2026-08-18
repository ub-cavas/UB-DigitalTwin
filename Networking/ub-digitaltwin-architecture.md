# UB Digital Twin: Multi-Agent Shared-World Architecture

## 1. Use case

A single authoritative CARLA world, hosted on a remote GPU server, shared in real time by three kinds of participant:

1. **Human drivers** at wheel stations distributed over a **WAN**, each rendering their own view in CARLA.
2. **Autoware agents** — either simulated on the server, or a **real vehicle** on the physical test track that perceives virtual actors through UB-MR.
3. **UB-MR occupants** in the real vehicle, seeing a simplified render of the virtual world overlaid on the physical one.

The virtual map is a georeferenced digital twin of the physical test area. All actors remain within its bounds. Real–virtual collisions are logged; handling semantics are deferred.

**Network assumption: WAN by default.** No participant is assumed to share an L2 segment with the server. Where stations happen to be colocated on a LAN, they run the same code path with better numbers — colocation is an optimization, never a requirement.

## 2. Design principle

**One authority per object; state replication everywhere else.**

Every dynamic object has exactly one machine that simulates it. Every other machine holds a physics-disabled puppet posed from a shared state feed. This is the DIS/HLA pattern; it is chosen over lockstep because CARLA cannot guarantee bit-exact determinism across machines, and over camera streaming because uncompressed CARLA frames cost roughly 880 Mbps per 720p station.

| Object | Authority | Everywhere else |
|---|---|---|
| Wheel station N ego | Station N (local CARLA, physics on) | Puppet |
| Simulated Autoware ego | Server | Puppet |
| **Real vehicle** | **The vehicle itself** (GNSS + localization) | Puppet |
| Background traffic, pedestrians, signals, weather | Server (Traffic Manager / SUMO) | Puppet |

Consequences:

- **A participant's own vehicle has zero network latency between input and view.** Physics runs where the wheel is plugged in. This property is what makes WAN operation viable at all, and it is the thing to protect in every subsequent trade-off.
- The server holds puppets of every human and real ego, so the Traffic Manager and simulated Autoware perceive and react to them.
- The real vehicle is not a special case; it is a self-authoritative ego whose simulator is reality.

## 3. Components

### 3.1 Server (single host, one workstation-class GPU)

**World master.** CARLA server in synchronous mode. Sole owner of `world.tick()`, `apply_settings()`, and Traffic Manager sync. Ticks at a fixed 60 Hz (`fixed_delta_seconds = 1/60`, substepping enabled) paced against wall clock, stamping each tick with a monotonic frame sequence number.

**The master never waits for a client.** If a station's ego uplink is late, the master dead-reckons that station's puppet from its last known velocity. One bad link must not add jitter to every other participant's world.

**State relay.** Reads all actor transforms and velocities each tick and unicasts them to every registered participant (Section 4). Per-destination radius filtering. Replaces the LAN-era multicast publisher; extends the existing `udp-bridge` / `traffic-publisher` sidecars.

**Puppet applier.** Receives ego-state uplinks from wheel stations and the real vehicle; applies them via `set_transform()` to physics-disabled puppets in the master world.

**Redis.** Control plane only (Section 5). Reachable only through the tunnel.

Optional: one or more **simulated Autoware egos** with sensor rendering. For more than one full-fidelity Autoware ego, use CARLA multi-GPU (`-nullrhi` primary, one secondary per GPU) and prototype it before it is on the critical path.

GPU choice: RTX PRO 6000 or equivalent workstation card. Not H100/A100 — no RT cores, no NVENC, and Vulkan headless on datacenter cards is fragile. The server GPU is sized by *sensor* workload for simulated Autoware, not by number of human drivers.

### 3.2 Wheel stations (one per human driver, WAN-attached)

Each station is a full CARLA workstation (approx. RTX 4070 / 8 GB VRAM for 1080p60 at medium quality), connected to the server over a WireGuard tunnel. It runs:

- A local CARLA instance in synchronous mode, byte-identical packaged map, ticking on **its own wall clock** at the fixed timestep. Local physics is never gated on the network.
- Its own ego spawned with physics **enabled**; every other actor spawned as a puppet with physics **disabled**.
- A wheel-input thread (100 Hz+, forked from `manual_control_steeringwheel.py`) writing to a latest-value slot; the sim loop reads the slot and calls `apply_control()` locally.
- A pygame camera window on the local ego.
- A **remote clock estimator** and **interpolating puppet applier** (Section 4.3). This is the component that makes WAN operation feel correct and is the primary thing to get right.
- An ego-state uplink at 60 Hz.
- A health reporter publishing RTT, jitter, loss, and clock-error estimates to Redis at 1 Hz.

Stations never call `world.tick()` on the server and never spawn a Traffic Manager locally.

### 3.3 Real vehicle

Onboard, three separable pieces behind one shared ingest:

**Ingest.** A small native process that receives the unicast state feed, checks sequence numbers, runs the same clock estimation and interpolation as a wheel station, and republishes locally. The only network-facing component.

**Occupant renderer (UB-MR / Unity).** Soft real-time. Subscribes to the ingest for virtual actors; takes the vehicle's own pose from onboard localization at 50–100 Hz **with no network in the loop**, so the virtual world never swims relative to the physical one. Free to drop frames.

**Object injection (ROS 2 node).** Safety-critical. Converts ingested actors to `autoware_perception_msgs::TrackedObjects` and publishes downstream of real perception. Non-negotiable rules:

- Virtual objects are additive only. Nothing may suppress, filter, or outvote a real detection.
- Staleness watchdog (start at ~200 ms) with a defined fail-safe: drop all virtual objects, alert the safety driver.
- Geofenced to the test area.
- Injection may consult CARLA line-of-sight (raycast in the digital twin) so occluded virtual actors are not handed to Autoware as visible detections.

Separating render from injection is mandatory: a Unity frame hitch must never become a control-path delay.

### 3.4 Edge relay / tunnel termination

One WireGuard endpoint on the server terminates every participant tunnel. WireGuard is UDP-native, adds ~1 ms, and solves NAT traversal — clients dial out, the tunnel is bidirectional. DTLS is an acceptable substitute if you prefer to keep transport security in-app.

The vehicle's wireless link is treated as one more WAN path, not a special case.

### 3.5 Simulated Autoware egos (optional)

Two fidelity tiers, chosen per agent by what is under study:

| Tier | Perception | Localization | Cost |
|---|---|---|---|
| Hero | Full sensors → Autoware perception | NDT | ~1 GPU + ~12 cores per ego |
| Reduced | Ground-truth `TrackedObjects` injected | Ground-truth pose | ~2 cores, no GPU |

Reduced tier bypasses the sensor and perception pipeline but retains real Autoware planning and control. Correct choice for background AVs and any study where AV perception is not the dependent variable.

Each instance: separate `ROS_DOMAIN_ID`, distinct `role_name` on its ego, containerized, `use_sim_time` driven from the master's tick sequence. Hero-tier instances co-locate with the GPU rendering their sensors. Autoware never blocks the world tick — the master applies the latest control command (zero-order hold) and Autoware runs asynchronously.

## 4. State plane

### 4.1 Transport

Unicast UDP inside a per-participant WireGuard tunnel, 60 Hz, sequence-numbered, unreliable by design. No multicast anywhere — it does not cross routers or WiFi reliably.

**Payload per actor** (~60–80 bytes): actor ID, master frame sequence, position, rotation, linear velocity, angular velocity, optionally steering angle and light state.

**Budget per station:** 50 actors × 80 B × 60 Hz ≈ 2 Mbps down, ~5 KB/s up. Server egress scales linearly with participant count — 8 participants is ~16 Mbps, still trivial. Radius filtering (~150 m) trims packet count on lossy paths.

### 4.2 Remote clock estimation

Frame sequence numbers are authoritative for ordering; wall time is used only for coarse alignment and drift detection. Each client maintains a smoothed estimate of the master's current frame index as an offset from local time, updated from incoming packets and filtered against measured RTT.

The LAN heuristic ("more than 2–3 frames behind, skip ahead") is **removed**. Under WAN jitter it thrashes.

### 4.3 Interpolation, not extrapolation

Clients buffer 2–3 packets and render puppets at *(estimated master time − render delay)*, where render delay ≈ 1.5× measured jitter. Puppets are therefore shown slightly in the past, but **smoothly**, interpolating between two known poses.

Extrapolation is the fallback for genuinely late packets only, and the primary mechanism only on the **server** (which has no future data for a late client uplink). Extrapolating a braking vehicle over 100 ms of WAN latency puts the puppet metres from truth; the correction becomes the visible artifact.

Cost: a fixed ~50 ms of additional puppet latency. Benefit: remote vehicles that move like vehicles.

## 5. Control plane (Redis)

Bursty, must-not-lose, latency-tolerant. Never in the 60 Hz path. Reachable only through the tunnel.

```
dt:session:current          HASH    trial_id, condition, map, seed, state
dt:registry:actors          HASH    actor_id -> {owner, blueprint, role}
dt:station:{id}:heartbeat   STRING  last frame seq, 2 s TTL
dt:station:{id}:ready       STRING  "0" | "1"
dt:station:{id}:map_hash    STRING  checksum of packaged map
dt:station:{id}:link        HASH    rtt_ms, jitter_ms, loss_pct, clock_err_ms
dt:events                   STREAM  collisions, near-misses, trial markers
```

Uses: late-joiner actor registry, readiness barrier before trial start, event log, and operator-visible link health.

**The readiness barrier gains a link-quality gate.** A station is refused if its map hash mismatches *or* its measured RTT/jitter/loss exceeds the study's threshold. Discovering after the fact that a participant's near-miss data came from a 15%-loss link is worse than losing the session.

## 6. Coordinate frames

Two conversions must be exact and are verified once against surveyed points before anything moves:

1. CARLA left-handed Z-up → ROS REP-103 right-handed (`y -> -y`, yaw sign).
2. CARLA world → UTM via the OpenDRIVE header `proj4` georeference.

Verification: park the real vehicle at 3–4 surveyed points; compare UB-MR's computed CARLA-frame position to the survey. Repeat whenever the map is re-exported.

## 7. Timing

| Path | LAN | Metro WAN | Cross-country |
|---|---|---|---|
| Input → own view | 0 network | 0 network | 0 network |
| Remote puppet on a wheel station | ~25 ms | ~60–90 ms | ~120–180 ms |
| Round-trip human ↔ human | ~50 ms | ~150 ms | ~300 ms |
| CARLA → real-vehicle Autoware control | — | ~200–300 ms | — |

Add ~50 ms to puppet rows for the interpolation buffer.

The first row is the design's core guarantee and does not move with distance.

At 200–300 ms, the real vehicle travels 3–4.5 m at 15 m/s before responding to a virtual object. Measure this end to end; do not estimate it.

## 8. Collision logging

Authority is the world master (single log, no reconciliation). CARLA's collision sensor does not fire between puppets; the master runs an OBB overlap test each tick for the real vehicle's puppet against nearby virtual actors and appends to `dt:events` with frame sequence, both poses and velocities, closing speed, and TTC.

Continuous minimum-distance and TTC per real–virtual pair are logged throughout the trial; near-miss distributions are more informative than collision counts. Post-overlap handling of the virtual actor is deferred.

## 9. Known limitations

**WAN-specific**

- At ~150 ms round-trip, two humans in close negotiation each react to a ~75 ms-old version of the other. Acceptable for car-following, lane changes, and most gap-acceptance work; **not** acceptable for tight close-range negotiation, where it biases results toward "the other driver seemed slow to react" — an artifact, not a finding. Constrain scenario design, or colocate close-interaction pairs.
- Puppet latency is a per-station property. Report it alongside results; do not pool across stations with materially different links.
- Human–human collisions across stations produce divergent local outcomes; treat as terminal events arbitrated by the master.

**General**

- Puppet wheels do not spin (physics disabled). Send steering angle in the packet and drive visuals if it matters.
- CARLA multi-GPU is underdocumented and has setup friction; prototype early.
- Every Autoware instance loads its own maps; use partial map loading.
- Object-level injection bypasses Autoware perception for virtual objects. Sensor-level injection is a separate, substantially harder project.

## 10. Build order

1. **Clock estimation + interpolation loop, in isolation.** Two boxes, synthetic jitter and loss injected. This is the piece that determines whether remote vehicles look like vehicles, and it is easy to get subtly wrong in ways that only surface as "something felt off" in participant comments. Build and tune it before anything depends on it.
2. Server: master, relay, Redis, registry, readiness barrier, map-hash and link-quality gates.
3. One wheel station over the tunnel. Validate puppet smoothness and measure the real latency budget.
4. Second wheel station. Validate relay fan-out, per-station degradation isolation, and the barrier.
5. Reduced-tier simulated Autoware ego. Validate tick discipline and clock.
6. Real vehicle: ingest + occupant render on a **stationary** vehicle; survey-point verification.
7. Object injection with watchdog and geofence; low-speed track runs with safety driver.
8. Hero-tier Autoware and multi-GPU only if required by the study.
