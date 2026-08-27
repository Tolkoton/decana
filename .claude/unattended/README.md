# Unattended operation

Runs the agent 24/7 with nobody watching. A supervisor outside the agent
restarts a session that dies, leaves alone one that finishes, and caps both
restarts and spend so a bad night cannot run to morning.

Every design call is in [`unattended-decisions.md`](unattended-decisions.md)
with its reasoning and cost-to-reverse.

## Start it

**Prerequisite — grant the launch permission on this machine.** The agent cannot
grant it to itself: launching a self-restarting loop of agent processes is
refused, correctly, by the permission layer. Add to
`.claude/settings.local.json` (machine-local and gitignored, *not*
`settings.json`, which ships with the template):

```json
{ "permissions": { "allow": [
    "Bash(bash .claude/unattended/supervisor.sh:*)",
    "Bash(.claude/unattended/supervisor.sh:*)"
] } }
```

**Then restart Claude Code.** Settings are read at session start, so a rule
added mid-session does not apply until the next one.

```bash
command -v jq                                # REQUIRED: four hooks silently
                                             # enforce nothing without it
echo unattended > .claude/overseer/mode      # only when the guardrails verify green
nohup .claude/unattended/supervisor.sh >> .claude/unattended/logs/nohup.log 2>&1 &
```

On the Linux server, prefer the unit: `sudo cp claude-unattended.service
/etc/systemd/system/ && sudo systemctl enable --now claude-unattended`.

```bash
.claude/unattended/supervisor.sh --status    # state, restarts this hour, spend
.claude/unattended/supervisor.sh --reset     # clear state for a fresh run (keeps cost)
```

## The decision the supervisor makes

On every session exit, read `state.json`:

| status | meaning | supervisor |
|---|---|---|
| `working` | a session is in flight | process gone + this status = **it died** → restart |
| `unit-done` | unit finished, work remains | restart, self-feeding the next DAG node |
| `finished` | DAG exhausted | **stop.** Legitimate interrupt 3 |
| `parked` | work remains, all of it blocked | **stop.** Legitimate interrupt 1 or 2 |
| `halted` | a cap fired | **stop.** A human must look |
| *(no file)* | died before writing anything | restart |

The exit code is corroborating only. A crashed CLI, an OOM kill, and a clean
finish all return 0, so the file decides (D-3). The bias is deliberate:
restarting a finished run costs one no-op session; failing to restart a died run
costs the night.

## Session contract

Anything used as `SESSION_CMD` must:

1. **Tick the heartbeat** while working —
   `python3 .claude/unattended/runstate.py heartbeat`. Combined with
   `PROGRESS.md` mtime this is the liveness signal; a session that updates
   neither for `STALL_TIMEOUT_SEC` is killed as wedged (D-4, D-5).
2. **Write a terminal status before exiting** —
   `runstate.py set finished|parked|halted "<reason>" "<what unblocks it>"`, or
   `set unit-done` when work remains.
3. **Record its cost** — `runstate.py add-cost <usd>`.
4. **Never invent `finished`.** If the agent stops without a status, leave
   `working`: the supervisor reads that as a death and retries, which is
   recoverable. A false `finished` is a silent overnight halt, which is not.

## Files

| File | Role | Tracked |
|---|---|---|
| `supervisor.sh` | the loop: spawn, watch, classify, cap, restart | yes |
| `runstate.py` | state / cost / DAG operations, shared by shell and agent | yes |
| `session-claude.sh` | real runner: one headless `claude -p` per node | yes |
| `session-sim.sh` | scripted runner for the proof harness (D-15) | yes |
| `recheck_parked.py` | re-opens parked items whose condition is now met (D-12) | yes |
| `rotate.sh` | size-triggered log/ledger rotation (D-13) | yes |
| `config.sh` | all tunables. Named `.sh` because `protect-paths.sh` denies `*.env` | yes |
| `state.json` | the authoritative status | no |
| `cost.json` | cumulative spend, survives restarts (D-9) | no |
| `restarts.log` | timestamps for the rolling-hour cap (D-6) | no |
| `logs/`, `archive/` | session logs and rotated generations | no |

## Making a parked item auto-resume

`recheck_parked.py` runs before every spawn and re-opens an item only when a
machine-checkable condition in its `Unblocks when:` line is satisfied. Write one
of these tokens into the line and the queue heals itself:

| Token | True when |
|---|---|
| `env:VAR` | that variable is set |
| `file:PATH` | that path exists |
| `node:ID` | that DAG node is `done` |
| `mode:attended` | `.claude/overseer/mode` no longer says unattended |
| `premise:ID` | that premise row is `verified` in the premise log |

An item with no token stays parked until a human moves it. That is deliberate —
re-opening on a guess is how a run starts thrashing.

## The feature DAG

```json
{"feature": "slug",
 "nodes": [{"id": "S1", "deps": [], "status": "pending"},
           {"id": "S2", "deps": ["S1"], "status": "pending"}]}
```

`status` is `pending`, `done`, or `parked`. The next node is the first whose
deps are all `done` (D-10). A parked node blocks its dependents but not the rest
of the graph — the run routes around it.

`.claude/architecture/feature-dag.json` currently holds a **tracer-bullet DAG**
built to prove the harness. Replace it with a real one from
`/feature-architect`.

## What was proven, and what was not

Proven end to end, repeatedly, on this machine: a session killed with SIGKILL
mid-unit is detected and restarted; the run self-feeds across a slice boundary
with no human turn; a clean finish is not restarted; a crash loop halts at the
restart cap; the cost cap parks; a wedged session is killed and recovered;
rotation triggers, prunes, and no-ops correctly.

Not proven: multi-day operation, and the quality of the agent's work inside a
session. The proof used the simulated runner (D-15) — the supervisor code path
is identical either way, but what happens *inside* a session is out of its
scope by construction.
