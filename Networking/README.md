# UB Digital Twin — Sept 15 demo scaffold

Four packages, each with one job. Fill in the `NotImplementedError`s.

- `dtnet/` — shared library (wire format, clock, interpolation, metrics).
  No CARLA, no pygame, no display. Used by both `server/` and `station/`.
- `server/` — the world master. Headless. Owns `world.tick()`.
- `station/` — the wheel station. Permanently a desktop app.
- `harness/` — CARLA-free test tools: synthetic publisher, impairment
  injector, standalone visualizer. This is what proves `dtnet/` works
  before anything else exists, and what week 3 swaps out for `server/`.

Build order matches the sprint board: `dtnet/` and `harness/` (week 1) →
`station/` against the harness (week 2) → `server/` (week 3), at which
point `station.puppets` points at `server.relay` instead of
`harness.publisher`. Both speak `dtnet.wire`, so that swap should be a
one-line change — if it isn't, that's the signal to fall back rather than
debug through feature freeze.

See `ub-digitaltwin-implementation-plan.md` for the full post-demo plan
and `sept15-demo-sprint.md` for this scoped slice.
