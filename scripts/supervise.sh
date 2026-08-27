#!/usr/bin/env bash
# Keep the unattended build loop alive across session deaths.
#
# WHY this exists outside the agent: the failure it must survive is the agent's
# own death -- a context limit, a crash, an OOM. Nothing inside the session can
# restart the session. PROGRESS.md's `## NOW` block is what a fresh instance
# resumes from, and this script's only job is to make sure a fresh instance
# happens.
#
# WHY it exits rather than spinning: an agent that restarts forever while making
# no progress burns tokens to accomplish nothing and looks, from outside, exactly
# like one that is working. Liveness is judged by PROGRESS.md's timestamp moving,
# not by the process being up.
#
# Secrets come from the environment, never from .env: the agent is hard-denied
# from reading .env, so THIS is the layer that exports them. Source your own
# secrets file before invoking, or export beforehand.
#
# Usage:
#   export GEMINI_API_KEY=...            # required by the smokes
#   scripts/supervise.sh [max-restarts]  # default 20

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

MAX_RESTARTS="${1:-20}"
PROGRESS="PROGRESS.md"
STALL_LIMIT=3          # consecutive restarts with no PROGRESS.md change
restarts=0
stalled=0

log() { printf '[supervise %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

if ! command -v claude >/dev/null 2>&1; then
  log "EXIT: \`claude\` is not on PATH. Nothing to supervise."
  exit 2
fi

if [[ ! -f "$PROGRESS" ]]; then
  log "EXIT: $PROGRESS does not exist. It is what a fresh session resumes from,"
  log "      and the stall detector compares its hash — without it this script"
  log "      cannot tell a working session from a wedged one."
  exit 2
fi

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  log "WARNING: GEMINI_API_KEY is not exported. The real-environment smokes will"
  log "         park rather than run. Everything else proceeds."
fi

while (( restarts < MAX_RESTARTS )); do
  before=$(sha256sum "$PROGRESS" 2>/dev/null | cut -d' ' -f1)

  log "starting session $((restarts + 1))/$MAX_RESTARTS"
  claude --continue --dangerously-skip-permissions \
         -p "Resume unattended work. Read PROGRESS.md's ## NOW block first — it is
             written for a fresh instance with no memory of the previous session.
             Follow the work loop in .claude/skills/slice-builder/SKILL.md:
             finish the current slice, then take the next unbuilt node in the
             feature DAG, plan it, build it, repeat. Park anything blocked with
             its unblocker named and move on. Update PROGRESS.md at every unit."
  status=$?

  after=$(sha256sum "$PROGRESS" 2>/dev/null | cut -d' ' -f1)
  restarts=$(( restarts + 1 ))

  if [[ "$before" == "$after" ]]; then
    stalled=$(( stalled + 1 ))
    log "PROGRESS.md unchanged (stall $stalled/$STALL_LIMIT), exit status $status"
    if (( stalled >= STALL_LIMIT )); then
      log "EXIT: $STALL_LIMIT consecutive sessions moved nothing. A restart loop that"
      log "      makes no progress is worse than a stopped one -- it hides the stall."
      exit 3
    fi
  else
    stalled=0
    log "PROGRESS.md advanced; exit status $status"
  fi

  sleep 5
done

log "EXIT: reached the $MAX_RESTARTS restart cap."
exit 0
