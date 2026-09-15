# September 7, 2026 demo feature-freeze runbook

This file is the tracked operational record for DT-17. It defines the exact
baseline cut and the blocker-only policy through the September 15 demo. Do
not record WireGuard private keys, tokens, passwords, or Xauthority cookies
here.

## Verified candidate

- Prepared on: 2026-08-25
- Candidate branch: `multi-agent-architecture`
- Candidate commit: `836f99b7e31dbb43bb1437b4337506a859774b4f`
- Candidate subject: `Handle occupied station puppet spawn positions`
- CARLA map: `Carla/Maps/UBAutonomousProvingGrounds`
- Network ports: relay `5005`, station uplink `5006`, probe `5007`

The September 7 baseline must be cut from the then-current, fully validated
tip of `multi-agent-architecture`; the candidate above is evidence only, not
the frozen release ref.

## Preflight

Run from the repository root before cutting the freeze:

```bash
git status --short --branch
git fetch origin
git status --short --branch
PYTHONPATH=Networking python3 -m unittest discover -s Networking/tests -q
cd CARLA
docker compose config >/dev/null
DISPLAY=:0 XAUTHORITY=/tmp/.Xauthority docker compose -f docker-compose.yml -f docker-compose.gui.yml config >/dev/null
```

Require a clean worktree, an up-to-date `multi-agent-architecture` branch,
and successful checks. On the server and station, verify an active WireGuard
handshake and matching checked-out commit before the live acceptance run.

## Live acceptance

Use the approved server and station launch commands from the current DT-22
manual-validation record. Confirm all of the following:

1. Server master starts with the approved CARLA map and background traffic.
2. Station receives and renders remote Traffic Manager puppets.
3. Station HUD reports RTT, jitter, loss, and interpolation buffer depth.
4. The station has no duplicate ego puppet.
5. The server GUI mirrors station-ego motion and Traffic Manager reacts to
   the server-side station puppet.

Record the date, the two machine commit SHA, and pass/fail result in DT-17.

## September 7 cut

After preflight and live acceptance pass, from the validated tip of
`multi-agent-architecture`:

```bash
git switch multi-agent-architecture
git pull --ff-only origin multi-agent-architecture
git tag -a demo-freeze-2026-09-07 -m "September 7, 2026 demo feature freeze"
git branch demo-freeze/2026-09-07 demo-freeze-2026-09-07
git push origin demo-freeze-2026-09-07 demo-freeze/2026-09-07
git rev-parse demo-freeze-2026-09-07
```

Replace the candidate metadata above with the resulting frozen SHA and record
the tag, branch, SHA, and validation evidence in DT-17 before marking it Done.

## Post-freeze policy

Only demonstrable demo blockers may be committed directly to
`demo-freeze/2026-09-07`. Do not add features, refactor, upgrade dependencies,
or perform unrelated cleanup on that branch. Each permitted fix must pass the
full Networking suite and the affected live acceptance checks.

Immediately before the demo, tag the exact branch commit that will run:

```bash
git switch demo-freeze/2026-09-07
git pull --ff-only origin demo-freeze/2026-09-07
git tag -a demo-final-2026-09-15 -m "September 15, 2026 demo baseline"
git push origin demo-final-2026-09-15
```
