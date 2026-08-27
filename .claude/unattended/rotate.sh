#!/usr/bin/env bash
# Size-triggered rotation for everything a long run grows (D-13).
#
# Called before each spawn by supervisor.sh, so a week of running cannot fill
# the disk. Time-based rotation does nothing on a quiet day and too little on a
# loud one; size is the property that actually matters.
#
# Managed: supervisor + session logs, the overseer ledger, the scratchpad.
# Rotated files are gzipped into archive/ with a UTC stamp, ROTATE_KEEP
# generations are retained per basename, and anything older than
# ARCHIVE_MAX_AGE_DAYS is deleted.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$HERE/../.." && pwd)}"
# shellcheck disable=SC1091
[ -f "$HERE/config.sh" ] && source "$HERE/config.sh"

ARCHIVE="$HERE/archive"
LOG_DIR="$HERE/logs"
MAX_KB="${ROTATE_MAX_KB:-2048}"
KEEP="${ROTATE_KEEP:-7}"
MAX_AGE="${ARCHIVE_MAX_AGE_DAYS:-30}"
mkdir -p "$ARCHIVE" "$LOG_DIR"

size_kb() {
  [ -f "$1" ] || { echo 0; return; }
  if stat -f %z "$1" >/dev/null 2>&1; then echo $(( $(stat -f %z "$1") / 1024 ))
  else echo $(( $(stat -c %s "$1") / 1024 )); fi
}

rotate_one() {
  local f="$1" base kb stamp
  [ -f "$f" ] || return 0
  kb=$(size_kb "$f")
  [ "$kb" -lt "$MAX_KB" ] && return 0
  base="$(basename "$f")"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  cp "$f" "$ARCHIVE/${base}.${stamp}" && : > "$f"
  gzip -f "$ARCHIVE/${base}.${stamp}" 2>/dev/null
  echo "rotated $base at ${kb}KB -> archive/${base}.${stamp}.gz"

  # Keep only the newest $KEEP generations of this basename.
  local n=0
  # shellcheck disable=SC2012
  ls -1t "$ARCHIVE/${base}."*.gz 2>/dev/null | while read -r old; do
    n=$((n + 1))
    [ "$n" -gt "$KEEP" ] && rm -f "$old" && echo "pruned $(basename "$old")"
  done
}

# Managed files.
rotate_one "$LOG_DIR/supervisor.log"
rotate_one "$PROJECT_ROOT/.claude/overseer/ledger.md"
for f in "$LOG_DIR"/session-*.log; do rotate_one "$f"; done

# Session logs are per-session, so they accumulate by COUNT, not size.
# Keep the newest 200; a stalled run should not leave 10k files behind.
# shellcheck disable=SC2012
ls -1t "$LOG_DIR"/session-*.log 2>/dev/null | tail -n +201 | while read -r old; do
  rm -f "$old"
done

# Age out the archive.
find "$ARCHIVE" -type f -mtime "+${MAX_AGE}" -delete 2>/dev/null

# Scratchpad: session-local temp files, safe to clear once cold.
SCRATCH="${CLAUDE_SCRATCHPAD:-}"
if [ -n "$SCRATCH" ] && [ -d "$SCRATCH" ]; then
  find "$SCRATCH" -type f -mtime +7 -delete 2>/dev/null
fi

exit 0
