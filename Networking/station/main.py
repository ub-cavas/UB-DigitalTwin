"""station.main — the sim loop, pygame view, and telemetry overlay.

One job: tie together the local CARLA ego (physics on, driven by
station.wheel), the puppets (physics off, driven by station.puppets), and
render both plus a telemetry overlay from dtnet.metrics.

Local CARLA runs synchronous, on ITS OWN wall clock, at the fixed
timestep — never gated on network arrival. Pulling the network mid-drive
must not visibly affect this loop; that's the core guarantee to demo.

Data source for puppets is configurable: harness.publisher (weeks 1-2) or
server.relay (week 3+). Swapping should be a one-line change.
"""


def main():
    raise NotImplementedError


if __name__ == "__main__":
    main()
