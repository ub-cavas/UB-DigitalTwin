# CARLA server and client setup

Use the multi-agent server launcher to host a shared CARLA world and Redis
traffic/ego communication for remote clients. Run the commands below from the
repository root.

## Prerequisites

- Linux with Docker Compose and the NVIDIA container runtime configured.
- An NVIDIA GPU on the server, including when running without a graphics window.
- The matching UB-CARLA build on the server and on manual-driving client machines.

Install the default build if needed:

```bash
bash scripts/install_ub_carla.sh v1.1.0
```

The launchers build their Docker images automatically. They use
`CARLA/Builds/v1.1.0` by default; set `BUILD_FOLDER` to select another installed
build.

## Start the server

Replace `192.168.1.50` with the server's own LAN or VPN IP, reachable by clients,
and choose a shared Redis password:

```bash
UB_REDIS_HOST=192.168.1.50 \
UB_REDIS_PASSWORD='your-shared-password' \
bash scripts/launch_carla_redis_server.sh
```

This starts CARLA without a graphics window, loads `UBAutonomousProvingGrounds`,
and starts Redis, the traffic publisher, and the ego renderer. Keep the terminal
open; press Ctrl+C to stop the services.

**Set `UB_REDIS_HOST` for remote access.** Its default, `127.0.0.1`, only allows
connections from the server itself. This setting controls both Redis's bind
address and the address used by the server's Redis clients.

To show the server's graphics window, run from a graphical desktop session:

```bash
UB_REDIS_HOST=192.168.1.50 \
UB_REDIS_PASSWORD='your-shared-password' \
CARLA_ARGS="-prefernvidia -quality-level=Epic -nosound" \
UB_TRAFFIC_NO_RENDERING=0 \
bash scripts/launch_carla_redis_server.sh
```

## Network ports

Allow client machines to reach these TCP ports on the server:

| Port | Purpose |
| --- | --- |
| `2000` | CARLA API |
| `2001` | CARLA streaming |
| `6390` | Redis traffic/ego communication |

The Compose services use host networking, so no Docker port mappings are needed.
CARLA's default ports are described in the
[CARLA quick-start documentation](https://carla.readthedocs.io/en/0.9.15/start_quickstart/).

## Connect clients

### Manual-driving client

On a client machine with the repository, matching build, NVIDIA container runtime,
and a graphical desktop session:

```bash
UB_REDIS_PASSWORD='your-shared-password' \
bash scripts/launch_carla_redis_manual_client.sh 192.168.1.50
```

Use the same server IP and password as above. This launches a local rendered CARLA
instance on port `2100`, mirrors server traffic, and connects manual control to
the authoritative server on port `2000`.

### UB-MR client

In UB-MR's Main Menu, connect using the server IP, Redis port `6390`, and the same
Redis password. See the [UB-MR documentation](../UB-MR/README.md) for its setup.

### Python API client

With a Python CARLA package matching the server build:

```python
import carla

client = carla.Client("192.168.1.50", 2000)
client.set_timeout(10.0)
print(client.get_world().get_map().name)
```

If you only need direct CARLA API clients, start the server with
`bash scripts/launch_carla.sh` instead of the multi-agent launcher. This starts
CARLA and the map loader without Redis or the traffic/ego services.

## Check a connection problem

- Confirm the map loader has finished successfully in the server terminal.
- Use the server's reachable IP on remote clients, not `127.0.0.1`.
- Check that Redis is bound to the server IP and that passwords match.
- Check that firewalls permit the required TCP ports between the machines.
- Confirm the client Python API matches the server build.

Inspect the server containers from the repository root:

```bash
docker compose -f CARLA/docker-compose.yml ps
docker compose -f CARLA/docker-compose.yml logs --tail=100 carla map-loader redis traffic-publisher ego-renderer
```
