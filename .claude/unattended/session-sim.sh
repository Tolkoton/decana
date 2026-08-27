#!/usr/bin/env bash
# Simulated session runner — the proof harness only (D-15).
#
# Substitutes for session-claude.sh so the supervisor's behaviour can be
# exercised deterministically, for free, in seconds. It honours exactly the
# same session contract, so what it proves about the supervisor holds for real
# sessions too: the code path under test is identical, only the work inside a
# session is faked.
#
#   session-sim.sh <NODE_ID> <PROMPT>
#
# Behaviour per node is read from sim-plan.txt, one line per invocation:
#   work    <node>   do the unit properly: PROGRESS.md, node done, unit-done
#   crash   <node>   die mid-unit WITHOUT writing terminal state (the supervisor
#                    must notice and restart)
#   last    <node>   do the unit and mark the DAG finished
# Consumed lines are struck through so a re-run advances the plan.

set -uo pipefail

NODE="${1:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$HERE/../.." && pwd)}"
cd "$PROJECT_ROOT" || exit 1
RUNSTATE="python3 $HERE/runstate.py"
PLAN="$HERE/sim-plan.txt"
DAG="${DAG_FILE:-.claude/architecture/feature-dag.json}"

# Next unconsumed plan line.
ACTION=$(grep -vE '^(#|x )' "$PLAN" 2>/dev/null | head -1 | awk '{print $1}')
ACTION="${ACTION:-work}"

# Consume it.
python3 - "$PLAN" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
if p.exists():
    out, done = [], False
    for line in p.read_text().splitlines():
        if not done and line.strip() and not line.startswith(("#", "x ")):
            out.append("x " + line); done = True
        else:
            out.append(line)
    p.write_text("\n".join(out) + "\n")
PY

$RUNSTATE heartbeat
echo "[sim] node=$NODE action=$ACTION"

case "$ACTION" in
  crash)
    # Do a little work, then die hard. state.json is left saying 'working',
    # which is precisely what the supervisor must interpret as a death.
    echo "[sim] simulating mid-unit crash for $NODE (no terminal state written)"
    sleep 1
    kill -9 $$
    ;;

  hang)
    # Wedge: alive but producing no liveness signal. Neither PROGRESS.md nor
    # the heartbeat moves, so the watchdog must SIGTERM/SIGKILL this (D-5).
    echo "[sim] simulating a wedged session for $NODE (no heartbeat, no PROGRESS)"
    sleep 600
    ;;

  work|last)
    sleep 1
    printf '\n## %s — simulated unit (%s)\n- Result: unit completed by the sim runner\n- Tests: n/a (harness proof)\n' \
      "$NODE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$PROJECT_ROOT/PROGRESS.md"
    $RUNSTATE set-node "$DAG" "$NODE" done >/dev/null
    $RUNSTATE add-cost 0.10 >/dev/null

    if [ "$ACTION" = "last" ]; then
      $RUNSTATE set finished "all DAG nodes complete (sim)" "nothing — the feature is built" "$NODE" >/dev/null
      echo "[sim] $NODE done; DAG finished"
    else
      $RUNSTATE set unit-done "unit $NODE complete, more work exists" "" "$NODE" >/dev/null
      echo "[sim] $NODE done; more work remains"
    fi
    exit 0
    ;;
esac
