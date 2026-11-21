# UB-DigitalTwin Codex team

<!-- codex-team-kit: orchestrator instructions. Appended to AGENTS.md by install.sh. -->

## Commands

Run from the repository root, in this order. These checks use Python's standard library and Bash.

- Script tests: `python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v`
- Launch tests: `python3 -m unittest discover -s launch/tests -p 'test_*.py' -v`
- Python syntax: `python3 -m compileall -q scripts launch Data-Collection/scripts`
- Shell syntax: `for script in scripts/*.sh launch/*.sh; do [ -f "$script" ] || continue; bash -n "$script" || exit; done`

There is no repository-wide lint or type-check command configured. The checks above are the baseline, not full simulator or hardware validation. Plans must also name relevant component checks (for example, the telemetry suites in `docs/experiment-logging.md`) when those components change.

## Working with subagents

You are the orchestrator. You decompose, delegate, synthesize and merge. You do not implement or review yourself when a specialist exists for it.

.codex/config.toml enables the team for this trusted project.

Roles available in `.codex/agents/`: `scout`, `planner`, `implementer`, `reviewer`, `validator`, `docs_researcher` (optional, needs a docs MCP server on this session).

Rules:

1. Spawn specialists with a clean context (`fork_turns: "none"`) and a self-contained task message. Never full-fork a specialist.
2. Standard loop for any non-trivial task: scout -> planner -> implementer -> (reviewer and validator in parallel) -> merge.
   Skip the scout for tasks confined to one file you already understand. Skip the planner only for one-step changes.
3. Only one implementer may run against this working tree at a time. Parallel implementation requires one git worktree per implementer.
4. Every task names the files it may touch (the planner's "Files" list). An edit outside that list is a `NEEDS_CLARIFICATION`, not an edit. Have the planner update the file list when the additional file is within the authorized scope; ask the user only when the scope or design needs their decision.
5. Wait for `IMPLEMENTATION_COMPLETE` before spawning reviewer and validator. Wait for both before deciding.
6. Merge only on `APPROVED` and `VALIDATION_PASSED`. On `CHANGES_REQUESTED` or `VALIDATION_FAILED`, send the specific findings back to the implementer as a new task message. After 3 rounds, stop and ask the user.
7. Read each agent's result (its file in `.codex/out/`, or its final message for agents that return reports directly) and close the thread when the available tools support closing it.
8. This workflow does not authorize commits, pushes, or merges without a user request. Report to the user with: what changed (files), the reviewer's verdict and any remaining NITs, the validator's verdict, and what you did not do.
9. `.codex/out/` is scratch. Never commit it.

Completion tokens, used verbatim by every role:
`PLAN_COMPLETE`, `IMPLEMENTATION_COMPLETE`, `IMPLEMENTATION_BLOCKED`, `NEEDS_CLARIFICATION`, `APPROVED`, `CHANGES_REQUESTED`, `VALIDATION_PASSED`, `VALIDATION_FAILED`.

Kickoff prompt the user may give you: "Implement <task>. Run the standard loop and report the verdicts with file references before merging."
