"""dtnet: shared state-plane library, used by both server and station.

Nothing in this package may import CARLA, pygame, or anything display-related.
It exists so the same clock/interpolation/wire code can run inside a CARLA
process (server, station) and outside one (harness, tests, and eventually
the vehicle ingest process).
"""
