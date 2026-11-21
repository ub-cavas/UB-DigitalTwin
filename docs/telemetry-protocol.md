# UB Digital Twin telemetry protocol

Every participant in a shared session — the authoritative server, each driving
simulator client, and the mixed-reality clients — exchanges state over a single
Redis pub/sub channel. This document defines what that channel carries.

It is the contract between `ub-cavas/UB-DigitalTwin` (server roles and bridges)
and `CHELabUB/carla_app` (driving simulator clients). Change it by agreement
between both, not by editing one side.

The reference implementation lives in `CARLA/UB-API/ub-telemetry/`.

## Transport

A single Redis channel carries every message type. Publishers and subscribers
resolve connection settings in this order: environment variable, then
`telemetry.conf`, then the built-in default.

`telemetry.conf` is searched for beside the running script, then in the working
directory, then beside the implementation. Set `UB_TELEMETRY_CONFIG` to an
explicit path to override the search.

| Setting  | Environment variable | Default          |
| -------- | -------------------- | ---------------- |
| Host     | `UB_REDIS_HOST`      | `localhost`      |
| Port     | `UB_REDIS_PORT`      | `6390`           |
| Password | `UB_REDIS_PASSWORD`  | *(must be set)*  |
| Channel  | `UB_REDIS_CHANNEL`   | `carla:telemetry`|

All participants in one session must agree on host, port and channel. A client
pointed at a different channel fails silently — it connects, subscribes, and
receives nothing.

Redis carries no transport security. Treat the channel as private
infrastructure: reachable over a private overlay network, never exposed to the
public internet, and never with a default password.

## Envelope

Every message is a JSON object with three envelope fields merged into a
type-specific payload at the top level:

```json
{
  "id": "6f1b2c3e-...",
  "type": 0,
  "timestamp": 1758200000.123,
  "...": "payload fields for this type"
}
```

| Field       | Type   | Meaning                                                      |
| ----------- | ------ | ------------------------------------------------------------ |
| `id`        | string | Identity of the **publishing process**, stable for its lifetime |
| `type`      | int    | Message type from the registry below                          |
| `timestamp` | float  | Unix epoch seconds at publish time                            |

`id` must be unique per process. Publishers ignore messages carrying their own
`id` and use them to estimate round-trip latency, so a duplicated `id` corrupts
another participant's latency measurement and suppresses its own traffic.

Note that `id` identifies the *publisher*, which is not always the subject. For
type 0 the publisher is the agent, so `id` is the agent identity. For types 2
and 3 the publisher is a relay, and the subject identity lives inside the
payload (`vehicles[].id`, `ego.id`).

## Message type registry

| Type | Name        | Published by                          | Payload                          |
| ---- | ----------- | ------------------------------------- | -------------------------------- |
| 0    | `telemetry` | Each participant's own vehicle        | One agent pose                   |
| 1    | `destroy`   | A participant leaving the session     | Empty                            |
| 2    | `traffic`   | The authoritative traffic publisher   | A batch of traffic vehicle poses |
| 3    | `ego`       | The UDP bridge, relaying a UB-MR ego  | One ego pose                     |

Types 4 and above are unassigned. Claim one by adding it to this table in the
same change that implements it.

## Payloads

### Type 0 — `telemetry`

One participant's own vehicle. Merged into the envelope at the top level.

```json
{
  "location": { "x": 12.5, "y": -3.0, "z": 0.4 },
  "yaw": 91.2,
  "blueprint": "vehicle.dodge.charger_2020",
  "color": "0,0,255"
}
```

The subject's identity is the envelope `id`.

### Type 1 — `destroy`

No payload. The envelope `id` names the participant that is leaving; consumers
remove its vehicle. Consumers must also expire participants that simply go
silent, since a process that crashes never sends this.

### Type 2 — `traffic`

A batch of every traffic vehicle the authoritative server owns. Vehicles with
`role_name` of `hero` or `external_ego` are excluded, because those are other
participants' vehicles arriving over types 0 and 3.

```json
{
  "vehicles": [
    {
      "id": "1423",
      "role_name": "",
      "blueprint": "vehicle.audi.a2",
      "color": "255,0,0",
      "location": { "x": 40.1, "y": 12.0, "z": 0.3 },
      "yaw": 180.0,
      "server_timestamp": 1043.55,
      "server_frame": 20871
    }
  ],
  "server_timestamp": 1043.55,
  "server_frame": 20871
}
```

`server_timestamp` is CARLA simulation time on the authoritative server, not
wall clock. It is the correct basis for interpolating between batches; the
envelope `timestamp` is not, because it includes network delay.

Vehicle `id` is unique only within one publisher's session. It is reused after
the server restarts.

### Type 3 — `ego`

One mixed-reality ego vehicle, relayed from Unity over UDP by the bridge.

```json
{
  "ego": {
    "id": "ub-mr-ego",
    "location": { "x": -330.0, "y": -76.0, "z": 1.0 },
    "yaw": 0.0,
    "blueprint": "vehicle.lincoln.mkz_2017",
    "color": "0,0,0"
  }
}
```

The envelope `id` is the bridge, not the ego. Use `ego.id` to distinguish
multiple mixed-reality clients.

## Conventions

Positions and rotations are in **CARLA world coordinates**, in metres, with
`yaw` in **degrees**. Unity clients convert on their side; nothing on the
channel is ever in Unity coordinates.

`blueprint` is a CARLA 0.9.16 blueprint id. Consumers must fall back to a
default when the id is unknown rather than dropping the vehicle, so that a
client running a different CARLA build still renders something.

`color` is `"R,G,B"` with components 0–255.

## Rules for consumers

These exist because breaking them has already caused outages on this channel.

**Check `type` before reading anything else.** The channel is shared. A
consumer that assumes every message carries its payload shape will fail on
every message meant for someone else.

**Ignore unknown types silently.** A consumer must not log an error or drop
its subscription when it sees a type it does not handle, otherwise no type can
ever be added without a synchronised upgrade of every client.

**Validate required fields before use.** Do not assume a well-formed payload
just because the type matched.

**Never let one bad message kill the subscriber.** Handle failures per message
and keep the loop running.

**Do not publish if you have nothing to say.** Subscriber-only roles must not
start a publisher thread; an empty payload published at the default interval
adds 100 messages per second per client of pure noise.

## Rules for publishers

Publish at a fixed, declared rate rather than as fast as the loop turns. The
channel is shared with participants on the far end of a WAN link.

Add fields freely; consumers ignore unknown ones. Never repurpose or remove an
existing field, and never change the meaning of a type. Both are silent
breakages for anyone who has not upgraded.

## Known divergences

As of this writing the protocol has three implementations, which is the reason
this document exists:

- `CARLA/UB-API/ub-telemetry/` — the reference. Environment-variable configuration,
  the full type registry, and consumer type-guards.
- `carla_app/PythonAPI/examples/modules/` — an older fork. No environment
  variable support, so it is configured only by editing `telemetry.conf`; its
  default channel is `DEFAULT_CHANNEL`; its type registry stops at 1; and its
  `MultiAgentRenderer` has no type guard, so it fails on every type 2 and 3
  message on the channel.
- `carla_app/PythonAPI/examples/modules/p2p_telemetry.py` — a variant using
  Redis for peer discovery and direct UDP for transport. It shares the envelope
  but not the transport.

The intended end state is that both repositories depend on `ub-telemetry` and
these forks are deleted.

### Multiple participants and replica ownership

Type 3 uses the nested `ego.id` as the participant identity. The envelope `id`
may remain `ub-mr` for every client. Unity generates a process session UUID once,
keeps it across reconnects and scene changes, and uses it for both Redis and UDP.
The serialized EgoPublisher `egoId` field overrides this default; give each
participant a different value. Unity renders peers under internal `ego:<id>`
keys, leaving raw numeric CARLA traffic IDs unchanged, and filters its exact
published ID. Traffic snapshots reconcile traffic only. Peer poses expire two
seconds after the last valid arrival, including during complete network silence.
Disconnect/session replacement clears both sources and their pending state.

Type 2 optionally includes `world_id`, the authoritative CARLA episode ID as a
string. Existing readers can ignore it; legacy packets without it still work.
A renderer suppresses a replica only when the source world matches its actual
target world and the numeric ID identifies a native actor. It can follow that
physical actor directly. A separate visual world mirrors the controlled vehicle
for its camera; a coincident actor number in another world is not a self match.

Python renderers share atomic Redis leases scoped by channel, actual target
world ID, source kind (`traffic` or `ego`), and canonical vehicle ID. Managed
replicas have deterministic `ub_mirror:` role tags; only the lease owner may
transform or destroy them. A new owner may adopt that tagged actor after lease
expiry. Redis ownership failures stop replica creation/updates. Native actors
are never adopted or destroyed as replicas. The authoritative publisher excludes
managed tags to prevent echo loops and preserves them during startup cleanup.
Use the updated publisher with these renderers; an older publisher may not
recognize the new managed tags.

Manual launchers create one `UB_MANUAL_CLIENT_ID` per invocation and share it
between services. Defaults are `manual_vehicle:<client-id>` and metadata key
`carla:manual_control:actor:<client-id>`. The controller publishes its identity,
actor ID and source world, and removes metadata using an atomic comparison.
`UB_MANUAL_ROLE_NAME` / `--role-name` and `UB_MANUAL_ACTOR_REDIS_KEY` /
`--actor-redis-key` preserve explicit overrides, including intentional legacy
actor reuse. The paired viewer uses `UB_RENDER_MANUAL_ACTOR_REDIS_KEY` and
`UB_RENDER_FOLLOW_ROLE_NAME`; set these when pairing independent processes.
All `manual_vehicle:` roles remain real type-2 traffic. Clients sharing one host
still need distinct Compose container/project names and available CARLA ports
when launching separate visual simulator instances.

The UDP bridge continues forwarding bare `{vehicles,timestamp}` traffic and now
forwards validated type-3 envelopes independently, retaining nested identity.
It polls during idle periods so stale replicas expire without another message.
Scene-only Unity uses ports 12345 (inbound traffic/peers) and 12346 (outbound ego).
Direct Redis Main Menu clients do not require this bridge. The MR launcher keeps
`UB_EGO_BRIDGE=0` by default; explicitly set `UB_EGO_BRIDGE=1` for scene-only ego
publication. UDP retains its existing datagram-size and delivery limitations.


Direct `docker compose` controller/viewer services also share default identity
resolution in `sidecar-entrypoint.sh`. Without an explicit `UB_MANUAL_CLIENT_ID`,
the identity combines the Compose project name and the host machine ID mounted
read-only from `/etc/machine-id`. Thus equal project names on different hosts
still get distinct roles/metadata keys. Both services derive role/key from that
same identity; explicit manual and viewer overrides still win. If running the
entrypoint outside Compose without the host mount, supply `UB_MANUAL_CLIENT_ID`.

Lease maintenance uses one cached world/actor snapshot and one batched Redis
renewal at a half-second cadence on a worker. Lease ownership checks are local
and expire conservatively when maintenance is stalled or fails. Before dispatch,
each rendered frame verifies the actual episode once without scanning actors; pose callbacks
do not wait for maintenance. Redis connect/read timeouts are 0.5 seconds with
automatic command retries disabled. Initial claims, spawn verification and
owner-safe cleanup perform bounded service operations outside the shared render
state lock. A spawn temporarily reserves its claim for up to 60 seconds to cover
bounded CARLA spawn/fallback/world checks, then resumes the ordinary three-second
lease. Every returned spawn is token-verified before mutation; the current owner
reconciles any late duplicate managed actor. A process dying during a spawn
reservation can delay takeover until that reservation expires.

Lease-changing Redis operations use a separate service-operation lock, including
TTL selection and local deadline updates. A delayed ordinary renewal therefore
cannot shorten a newer spawn reservation; local ownership reads and incoming
pose updates do not acquire that lock. Spawn results and direct actor
transform/destruction paths also verify the actual episode and fail closed if
the lookup fails.
