#!/usr/bin/env bash
# Supervisor for unattended Claude Code operation.
#
# Restarts a session when it DIES. Does not restart when it FINISHES. Caps
# restarts so a crash loop cannot run all night, and caps spend so a working
# loop cannot either.
#
# The decision it exists to make, on every session exit:
#
#     state.json status is terminal   -> stop, leave alone      (finished/parked/halted)
#     state.json status is working    -> the session died       -> restart
#     no state file at all            -> the session died early -> restart
#
# The exit code is corroborating only. A crashed CLI, an OOM kill and a clean
# finish can all return 0, so the file is authoritative (D-3). The bias is
# deliberate: restarting a finished run costs one cheap no-op session that
# immediately re-reports 'finished'; failing to restart a died run costs the
# whole night.
#
# Usage:
#   .claude/unattended/supervisor.sh            # run until terminal
#   .claude/unattended/supervisor.sh --status   # print state and exit
#   .claude/unattended/supervisor.sh --reset    # clear state for a fresh run
#
# Reads .claude/unattended/config.sh. See README.md for the session contract.

set -uo pipefail   # NOT -e: this loop must survive a failing child, that is its job

# ---------------------------------------------------------------------------
# Locate the project and load config
# ---------------------------------------------------------------------------
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$HERE/../.." && pwd)}"
cd "$PROJECT_ROOT" || exit 1

# shellcheck disable=SC1091
[ -f "$HERE/config.sh" ] && source "$HERE/config.sh"

RUNSTATE="python3 $HERE/runstate.py"
LOG_DIR="$HERE/logs"
SUP_LOG="$LOG_DIR/supervisor.log"
RESTART_LOG="$HERE/restarts.log"
HEARTBEAT="$HERE/heartbeat"
PROGRESS="$PROJECT_ROOT/PROGRESS.md"
mkdir -p "$LOG_DIR" "$HERE/archive"

log() {
  local line
  line="$(date -u +'%Y-%m-%dT%H:%M:%SZ') [supervisor] $*"
  # stderr, NOT stdout. run_session() returns the child's exit code via command
  # substitution, so anything a helper prints to stdout is captured as part of
  # that value. Logging to stdout corrupted rc= on first run.
  printf '%s\n' "$line" >> "$SUP_LOG"
  printf '%s\n' "$line" >&2
}

now() { date +%s; }

# ---------------------------------------------------------------------------
# Liveness (D-4): newest of PROGRESS.md and the heartbeat.
# A stall is declared only when BOTH are stale, so a long unit that does not
# touch PROGRESS.md is not mistaken for a hang.
# ---------------------------------------------------------------------------
mtime() {
  [ -e "$1" ] || { echo 0; return; }
  if stat -f %m "$1" >/dev/null 2>&1; then stat -f %m "$1"   # BSD / macOS
  else stat -c %Y "$1"; fi                                    # GNU / Linux
}

last_life() {
  local a b
  a=$(mtime "$PROGRESS")
  b=$(mtime "$HEARTBEAT")
  [ "$a" -gt "$b" ] && echo "$a" || echo "$b"
}

# ---------------------------------------------------------------------------
# Restart budget (D-6): rolling 60-minute window over a timestamp file.
# ---------------------------------------------------------------------------
record_restart() { now >> "$RESTART_LOG"; }

restarts_last_hour() {
  local cutoff count=0 ts
  cutoff=$(( $(now) - 3600 ))
  [ -f "$RESTART_LOG" ] || { echo 0; return; }
  while read -r ts; do
    [ -n "$ts" ] && [ "$ts" -ge "$cutoff" ] 2>/dev/null && count=$((count + 1))
  done < "$RESTART_LOG"
  echo "$count"
}

prune_restart_log() {
  local cutoff tmp
  cutoff=$(( $(now) - 3600 ))
  tmp="$RESTART_LOG.tmp"
  [ -f "$RESTART_LOG" ] || return 0
  awk -v c="$cutoff" '$1 >= c' "$RESTART_LOG" > "$tmp" 2>/dev/null && mv "$tmp" "$RESTART_LOG"
}

# ---------------------------------------------------------------------------
# Pre-spawn gates. Each returns non-zero to stop the run, having written the
# terminal state that says why.
# ---------------------------------------------------------------------------
check_cost_cap() {
  local spent remaining
  spent=$($RUNSTATE get-cost 2>/dev/null || echo 0)
  remaining=$(python3 -c "print(round(${COST_CAP_USD:-25} - ${spent:-0}, 4))")
  if python3 -c "import sys; sys.exit(0 if ${spent:-0} >= ${COST_CAP_USD:-25} else 1)"; then
    log "COST CAP reached: \$${spent} of \$${COST_CAP_USD}. Parking (D-7)."
    $RUNSTATE set parked \
      "cost cap reached: \$${spent} spent of \$${COST_CAP_USD} allowed" \
      "the owner raises COST_CAP_USD in .claude/unattended/config.sh, or resets cost.json"
    return 1
  fi
  if python3 -c "import sys; sys.exit(0 if ${remaining} < ${MAX_SESSION_USD:-3} else 1)"; then
    log "WARN: \$${remaining} left, under MAX_SESSION_USD (\$${MAX_SESSION_USD}). One more session may overshoot (D-8)."
  fi
  return 0
}

check_restart_cap() {
  local n
  n=$(restarts_last_hour)
  if [ "$n" -ge "${MAX_RESTARTS_PER_HOUR:-6}" ]; then
    log "RESTART CAP reached: $n restarts in the last hour (max ${MAX_RESTARTS_PER_HOUR}). Halting (D-7)."
    $RUNSTATE set halted \
      "restart cap: $n restarts within one hour — this is a crash loop, not progress" \
      "a human reads $SUP_LOG and the session logs, fixes the cause, then deletes $RESTART_LOG"
    return 1
  fi
  return 0
}

check_session_cap() {
  local s
  s=$(python3 -c "import json;print(json.load(open('$HERE/state.json')).get('sessions',0))" 2>/dev/null || echo 0)
  if [ "$s" -ge "${MAX_SESSIONS:-200}" ]; then
    log "SESSION CAP reached: $s sessions (max ${MAX_SESSIONS}). Halting."
    $RUNSTATE set halted \
      "session cap: $s sessions in this run" \
      "a human confirms the run is genuinely making progress, then raises MAX_SESSIONS"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Run one session under a stall watchdog. Echoes the child's exit code.
# ---------------------------------------------------------------------------
run_session() {
  local node="$1" prompt slog pid waited rc
  prompt="${SESSION_PROMPT//\{NODE\}/$node}"

  # D-19. The session must know WHICH node it is building. If the placeholder
  # survived substitution the prompt is malformed, and a session handed the
  # literal "{NODE" works blind while every log line still says node=$node --
  # progress that is indistinguishable from the real thing. This is a config
  # defect affecting every node, so nothing unblocked can move: halt for a human
  # rather than park and continue.
  case "$prompt" in
    *"{NODE"*)
      log "MALFORMED PROMPT: '{NODE' survived substitution for node '$node' (D-19). Refusing to spawn."
      log "        Likely cause: SESSION_PROMPT assigned via \${SESSION_PROMPT:-...} with a literal {NODE} in the default. Bash closes the expansion on that placeholder's own brace. Assign it in two steps instead."
      # >/dev/null: run_session's stdout IS the return value (see the header
      # note). runstate 'set' echoes the status, which corrupted rc= to "halted".
      $RUNSTATE set halted \
        "malformed SESSION_PROMPT: the {NODE} placeholder was not substituted, so sessions do not know their node" \
        "the owner fixes the SESSION_PROMPT assignment in .claude/unattended/config.sh" >/dev/null
      echo 125
      return
      ;;
  esac
  slog="$LOG_DIR/session-$(date -u +%Y%m%dT%H%M%SZ)-${node}.log"

  $RUNSTATE heartbeat
  $RUNSTATE set working "session running for node $node" "" "$node" >/dev/null

  log "spawn: node=$node cmd=[$SESSION_CMD] log=$(basename "$slog")"
  # shellcheck disable=SC2086
  $SESSION_CMD "$node" "$prompt" >"$slog" 2>&1 &
  pid=$!

  while kill -0 "$pid" 2>/dev/null; do
    sleep "${POLL_INTERVAL_SEC:-15}"
    waited=$(( $(now) - $(last_life) ))
    if [ "$waited" -ge "${STALL_TIMEOUT_SEC:-900}" ]; then
      log "STALL: no PROGRESS.md or heartbeat movement for ${waited}s (limit ${STALL_TIMEOUT_SEC}s). Killing pid $pid (D-5)."
      kill -TERM "$pid" 2>/dev/null
      local g=0
      while kill -0 "$pid" 2>/dev/null && [ "$g" -lt "${KILL_GRACE_SEC:-20}" ]; do
        sleep 1; g=$((g + 1))
      done
      kill -KILL "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      echo 124   # conventional timeout code
      return
    fi
  done

  wait "$pid"; rc=$?
  echo "$rc"
}

# ---------------------------------------------------------------------------
# Housekeeping before each spawn (D-12, D-13)
# ---------------------------------------------------------------------------
pre_spawn_maintenance() {
  bash "$HERE/rotate.sh" >>"$SUP_LOG" 2>&1 || log "WARN: rotation failed (non-fatal)"
  python3 "$HERE/recheck_parked.py" >>"$SUP_LOG" 2>&1 || log "WARN: parked re-check failed (non-fatal)"
  prune_restart_log
}

# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
case "${1:-}" in
  --status)
    $RUNSTATE get-state
    echo "restarts in last hour: $(restarts_last_hour)"
    echo "spend: \$$($RUNSTATE get-cost)"
    exit 0
    ;;
  --reset)
    rm -f "$HERE/state.json" "$RESTART_LOG" "$HEARTBEAT"
    log "state reset (cost.json deliberately preserved — spend is cumulative)"
    exit 0
    ;;
esac

# ---------------------------------------------------------------------------
# Fixture retirement (D-17). The proof harness runs with a SIMULATED session
# runner so the state machine can be exercised without spending money. That
# fixture must never drive a real run: it would report clean node completions
# for work nobody did, which reads identically to progress. Opt in explicitly
# or it is refused.
# ---------------------------------------------------------------------------
case "$SESSION_CMD" in
  *session-sim.sh*|*sim*|*fixture*|*mock*|*stub*)
    if [ "${ALLOW_SIM_SESSIONS:-0}" != "1" ]; then
      log "REFUSED: SESSION_CMD='$SESSION_CMD' is a simulated runner and this is a real run (D-17)."
      log "        A fixture reports node completions for work nobody did. Set ALLOW_SIM_SESSIONS=1 to run the proof harness deliberately."
      exit 1
    fi
    log "WARN: running with SIMULATED sessions ($SESSION_CMD) — ALLOW_SIM_SESSIONS=1 was set. No real work is being done."
    ;;
esac

# ---------------------------------------------------------------------------
# S6. One supervisor per repository. Two live supervisors both select the first
# ready node and spawn a session for it, and the two sessions then edit the same
# files with no knowledge of each other. Observed for real on node S3.
# The lock holds the owning PID; a lock whose PID is gone is stale and reclaimed,
# so a crashed supervisor does not wedge the repo forever.
# ---------------------------------------------------------------------------
LOCKFILE="$HERE/supervisor.lock"
if [ -f "$LOCKFILE" ]; then
  HOLDER=$(cat "$LOCKFILE" 2>/dev/null)
  if [ -n "$HOLDER" ] && kill -0 "$HOLDER" 2>/dev/null; then
    log "REFUSED: supervisor pid $HOLDER already owns this repo (S6). Not starting a second one."
    exit 1
  fi
  log "reclaiming stale lock from dead pid ${HOLDER:-unknown}"
fi
printf '%s\n' "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

log "=== supervisor starting: cap ${MAX_RESTARTS_PER_HOUR}/hr, \$${COST_CAP_USD} budget, stall ${STALL_TIMEOUT_SEC}s ==="

FIRST=1
while true; do
  # 1. Already finished? Never restart a terminal run.
  if $RUNSTATE is-terminal; then
    st=$($RUNSTATE get-status)
    log "terminal state '$st' — not restarting. This is a clean stop."
    $RUNSTATE get-state | tee -a "$SUP_LOG"
    exit 0
  fi

  # 2. A non-first iteration means the previous session died. Count it.
  if [ "$FIRST" -eq 0 ]; then
    record_restart
    log "restart #$(restarts_last_hour) in the current hour"
  fi
  FIRST=0

  # 3. Gates.
  check_restart_cap || exit 0
  check_cost_cap    || exit 0
  check_session_cap || exit 0

  pre_spawn_maintenance

  # 4. What to work on (D-10), refusing any self-referential node (D-16).
  #
  # A node whose task is "run the supervisor" must never be spawned BY the
  # supervisor: the session would launch a supervisor, which spawns a session,
  # and the caps that bound THIS run do not bound the tree of runs beneath it.
  # runstate.next_node already declines to select one; this is the spawn-time
  # half, for a node that reached here by any other route (hand-set id, resumed
  # state, a future caller). Refusing parks the node and picks another — it does
  # not end the run, and it deliberately does not consume the restart budget.
  verdict=""; node=""; guard_tries=0
  while [ "$guard_tries" -lt 20 ]; do
    guard_tries=$((guard_tries + 1))
    read -r verdict node <<<"$(python3 "$HERE/runstate.py" next-node "$DAG_FILE" 2>/dev/null || echo 'error')"
    [ "$verdict" = "ready" ] || break

    offender=$(python3 "$HERE/runstate.py" guard-node "$DAG_FILE" "$node" 2>/dev/null)
    if [ $? -eq 0 ]; then
      break
    fi
    log "SELF-REFERENTIAL node '$node' refused at spawn time (D-16): matched \"$offender\". Parking it and selecting another."
    python3 "$HERE/runstate.py" set-node "$DAG_FILE" "$node" parked >/dev/null 2>&1
  done

  case "$verdict" in
    ready) ;;
    finished)
      log "DAG exhausted — every node done. Finishing cleanly (legitimate stop 3)."
      $RUNSTATE set finished "all DAG nodes complete" "nothing — the feature is built"
      continue
      ;;
    parked)
      log "every remaining node is blocked. Parking (legitimate stop 1 or 2)."
      $RUNSTATE set parked "nodes remain but all are blocked or parked" \
        "the owner resolves an item in .claude/overseer/parked.md"
      continue
      ;;
    *)
      log "cannot read DAG at '$DAG_FILE' — halting rather than guessing."
      $RUNSTATE set halted "DAG unreadable at $DAG_FILE" \
        "the owner supplies a valid feature DAG"
      continue
      ;;
  esac

  # 5. Go.
  rc=$(run_session "$node")
  st=$($RUNSTATE get-status)
  log "session exited rc=$rc, state='$st'"

  # 6. Classify (D-3) — the file decides, not rc.
  case "$st" in
    finished|parked|halted)
      log "clean stop: '$st'. Not restarting."
      ;;
    unit-done)
      log "unit complete, more work exists — self-feeding to the next node."
      ;;
    working|unknown|*)
      log "DIED: process gone but state is still '$st' (rc=$rc). Restarting."
      ;;
  esac

  sleep "${RESPAWN_DELAY_SEC:-10}"
done
