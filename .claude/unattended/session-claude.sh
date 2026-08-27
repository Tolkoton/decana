#!/usr/bin/env bash
# The real session runner: one headless Claude Code session for one DAG node.
#
# The supervisor calls this as:  session-claude.sh <NODE_ID> <PROMPT>
#
# Its whole job is to satisfy the session contract (README "Session contract"):
#   - tick the heartbeat while the session runs, so the stall watchdog can tell
#     working from wedged
#   - run the agent
#   - record what the session cost
#   - make sure a terminal-or-continuing status lands in state.json
#
# The last point is load-bearing. If the agent exits without writing a status,
# this wrapper does NOT invent one — it leaves state.json saying 'working', which
# the supervisor correctly reads as "died" and restarts. Inventing 'finished'
# here would be the single worst bug in the harness: a silent overnight halt.

set -uo pipefail

NODE="${1:-}"
PROMPT="${2:-}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$HERE/../.." && pwd)}"
cd "$PROJECT_ROOT" || exit 1
RUNSTATE="python3 $HERE/runstate.py"

# Heartbeat ticker: the fast half of the liveness signal (D-4). PROGRESS.md is
# the slow half and only moves at unit boundaries.
( while true; do $RUNSTATE heartbeat; sleep 30; done ) &
TICKER=$!

# S6. The old trap killed ONLY the ticker, so a SIGTERM to this wrapper left the
# headless `claude` grandchild running. It kept editing the repo, orphaned, while
# the supervisor believed the node was free -- which is how two sessions ended up
# on node S3 at once. The child now goes down with the wrapper.
cleanup() {
  kill "$TICKER" 2>/dev/null
  if [ -n "${CLAUDE_PID:-}" ]; then
    kill -TERM "$CLAUDE_PID" 2>/dev/null
    for _ in 1 2 3 4 5; do
      kill -0 "$CLAUDE_PID" 2>/dev/null || break
      sleep 1
    done
    kill -KILL "$CLAUDE_PID" 2>/dev/null
  fi
}
trap cleanup EXIT
trap 'cleanup; exit 143' TERM INT

# Run the agent. --dangerously-skip-permissions is NOT used: the deny list,
# ask list, and the PreToolUse hooks are the guardrails that make unattended
# running safe, and park-ask-gated.py converts an ask-gated command into a park
# rather than a hang. Bypassing them would defeat the entire design.
# Marks this process tree as a SUPERVISOR-SPAWNED session. The Stop hook's
# unattended-continue branch keys off it and stays out of the way here: a
# session must be free to end so the supervisor can spawn the next node, or so
# a death leaves 'working' behind for the restart logic to see. The branch is
# for the orchestrating session, not for these.
export CLAUDE_UNATTENDED_SESSION=1

claude -p "$PROMPT" \
  --output-format json \
  > "$HERE/logs/last-session.json" 2> "$HERE/logs/last-session.err" &
CLAUDE_PID=$!
wait "$CLAUDE_PID"
RC=$?

# Record cost from the run's own report; fall back to 0 rather than guessing.
COST=$(python3 -c "
import json,sys
try:
    d=json.load(open('$HERE/logs/last-session.json'))
    print(d.get('total_cost_usd') or d.get('cost_usd') or 0)
except Exception:
    print(0)
" 2>/dev/null || echo 0)
$RUNSTATE add-cost "$COST" >/dev/null 2>&1

echo "[session] node=$NODE rc=$RC cost=\$$COST status=$($RUNSTATE get-status)"
exit "$RC"
