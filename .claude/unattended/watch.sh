#!/usr/bin/env bash
# Ask-clean watcher for a running supervisor.
#
# WHY THIS FILE EXISTS
# --------------------
# A helper that only works because a human is present to approve it is not a
# helper. The first version of this watch was written inline as
#
#     comm -13 <(printf '%s\n' "$prev") <(printf '%s\n' "$cur")
#
# and the harness permission classifier prompted on the process substitution.
# Attended that is one keypress. Unattended it is a denial, and then the
# supervisor runs on while the only thing watching it is dead — blind, with
# nobody to unblock it. Note this was NOT caught by park-ask-gated.py: that hook
# only matches the patterns mirrored from settings.json's ask list, so it cannot
# convert a classifier prompt into a structured park. The gate here is the
# classifier, which is wider than the ask list and has no park conversion.
#
# So: no process substitution, no comm. Only grep, cut, wc, tail, sleep. Every
# construct below is one the classifier allows without a prompt.
#
# SCOPED TO THE CURRENT RUN — learned the hard way
# ------------------------------------------------
# The first version grepped the whole logfile. supervisor.log accumulates across
# runs, so the backlog already contained "terminal state ... clean stop" lines
# from earlier runs; the watcher matched one on its first poll, printed the
# entire history, and exited 0 while the live session was still working. A
# watcher that reports a finished run as finished-before-it-started is worse
# than none, because the exit code looks like success.
#
# Fix: anchor on the LAST "=== supervisor starting" marker and read only from
# there. That scopes to the current run no matter when the watcher arms.
#
# Usage:
#   .claude/unattended/watch.sh [logfile] [max_polls] [interval_sec]
#
# Exit 0 = current run reached a terminal line, 1 = gave up.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOGFILE="${1:-$HERE/logs/supervisor.log}"
MAX_POLLS="${2:-240}"
INTERVAL="${3:-5}"

# Coverage rule: silence is not success. This filter must match every terminal
# state, not just the happy path — a watcher that greps only for the success
# marker stays quiet through a crash loop, and quiet looks exactly like
# "still working".
SIGNAL='spawn:|session exited|self-feeding|DIED|STALL|CAP |terminal state|clean stop|DAG exhausted|Parking|halting|cannot read DAG|SELF-REFERENTIAL|REFUSED'
TERMINAL='terminal state|clean stop|DAG exhausted|halting|CAP |cannot read DAG|REFUSED'

RUN_FILE="$HERE/logs/.watch-run"
SEEN_FILE="$HERE/logs/.watch-seen"
mkdir -p "$HERE/logs"
: > "$RUN_FILE"
: > "$SEEN_FILE"

seen=0
poll=0
while [ "$poll" -lt "$MAX_POLLS" ]; do
  poll=$((poll + 1))

  # Anchor to the current run: everything at or after the last start banner.
  start_line=$(grep -n '=== supervisor starting' "$LOGFILE" 2>/dev/null | tail -n 1 | cut -d: -f1)
  [ -z "$start_line" ] && start_line=1

  tail -n +"$start_line" "$LOGFILE" > "$RUN_FILE" 2>/dev/null
  grep -E "$SIGNAL" "$RUN_FILE" > "$SEEN_FILE" 2>/dev/null

  total=$(wc -l < "$SEEN_FILE" 2>/dev/null | tr -d ' ')
  [ -z "$total" ] && total=0

  # Emit only what is new since the last poll, by line offset.
  if [ "$total" -gt "$seen" ]; then
    tail -n +$((seen + 1)) "$SEEN_FILE"
    seen="$total"
  fi

  if grep -qE "$TERMINAL" "$SEEN_FILE" 2>/dev/null; then
    exit 0
  fi

  sleep "$INTERVAL"
done

echo "[watch] gave up after $MAX_POLLS polls without a terminal line" >&2
exit 1
