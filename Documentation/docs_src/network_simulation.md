# Network Simulation

## Multi-Agent Server
```bash
# No Graphics
bash scripts/launch_carla_redis_server.sh
# Graphics
CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound" \
UB_TRAFFIC_NO_RENDERING=0 \
./scripts/launch_carla_redis_server.sh
```

## Multi-Agent Manual Client
```bash
# Local Host
./scripts/launch_carla_redis_manual_client.sh 127.0.0.1
# Remote Host (required)
./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
```

## Multi-Agent Mixed Reality (UB-MR)
```bash
# Starts UB-MR, the UB-MR localization bridge, UB-CARLA, and Autoware.
./scripts/launch_ub_mr.sh
# Light graphics
CARLA_ARGS="-prefernvidia -quality-level=low -nosound" bash scripts/launch_ub_mr.sh
```

This wrapper defaults to `UB_MR_BUILD_FOLDER=0.0.7`, `BUILD_FOLDER=v1.0.0`,
`CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound"`, and
`UB_CARLA_EXTRA_SERVICES="udp-bridge"`. It does not start CARLA traffic by
default.

Useful MR overrides:

```bash
UB_MR_BUILD_FOLDER=0.0.7 ./scripts/launch_ub_mr.sh
UB_MR_LOCALIZATION=0 ./scripts/launch_ub_mr.sh
UB_KEEP_MR=1 ./scripts/launch_ub_mr.sh
BUILD_FOLDER=v1.0.0 ./scripts/launch_ub_mr.sh
CARLA_ARGS="-RenderOffScreen -quality-level=Low -nosound" ./scripts/launch_ub_mr.sh
UB_CARLA_EXTRA_SERVICES="traffic-publisher udp-bridge" ./scripts/launch_ub_mr.sh
```

### Authoritative CARLA + manual client

Start the authoritative CARLA server, Redis, map loader, and traffic publisher:

```bash
./scripts/launch_carla_redis_server.sh
```

In a second terminal, start the local rendered CARLA client, Redis traffic renderer, and keyboard-controlled manual CARLA client:

```bash
./scripts/launch_carla_redis_manual_client.sh 127.0.0.1
```

The manual vehicle is controlled through the authoritative CARLA API and is published to Redis by the authoritative CARLA traffic publisher like any other traffic actor. The local client opens a CARLA graphics window and mirrors server-side Redis traffic into it.

Manual controls require keyboard focus on the `CARLA Manual Control` window:
`W/Up` throttle, `S/Down` brake, `A/D` steer, `Space` full brake, `Q` reverse, `F` toggle authoritative-server chase camera, `Esc` quit.

Useful manual-client overrides:

```bash
./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_ROLE_NAME=manual_vehicle ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_BLUEPRINT=vehicle.lincoln.mkz_2020 ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_COLOR=0,0,255 ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_MAX_KMH=60 ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_FOLLOW_SPECTATOR=0 ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
UB_MANUAL_SPAWN_INDEX=0 ./scripts/launch_carla_redis_manual_client.sh <authoritative-carla-host>
```

Useful server overrides:

```bash
CARLA_ARGS="-RenderOffScreen -quality-level=Low -nosound" ./scripts/launch_carla_redis_server.sh
UB_TRAFFIC_NO_RENDERING=1 ./scripts/launch_carla_redis_server.sh
UB_TRAFFIC_MANAGER_PORT=8002 ./scripts/launch_carla_redis_server.sh
UB_TRAFFIC_PUBLISH_HZ=60 ./scripts/launch_carla_redis_server.sh
BUILD_FOLDER=v1.0.0 ./scripts/launch_carla_redis_server.sh
CARLA_MAP_PATH= ./scripts/launch_carla_redis_server.sh
```
