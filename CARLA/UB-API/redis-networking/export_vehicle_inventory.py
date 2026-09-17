#!/usr/bin/env python3
"""Export available vehicle IDs without ticking or modifying the CARLA world."""

import argparse
import json
from pathlib import Path


def collect_inventory(client):
    return {
        "server_version": client.get_server_version(),
        "blueprints": sorted(
            blueprint.id
            for blueprint in client.get_world().get_blueprint_library().filter("vehicle.*")
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import carla

    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    inventory = collect_inventory(client)
    args.output.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(inventory['blueprints'])} blueprints from CARLA {inventory['server_version']}")


if __name__ == "__main__":
    main()
