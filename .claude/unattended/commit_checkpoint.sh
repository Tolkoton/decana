#!/usr/bin/env bash
# Commit a unit of work onto the run's own branch. Owner-ratified 2026-08-27.
#
# WHY THIS EXISTS
# ---------------
# Before this, an unattended run staged everything and committed nothing. Over a
# night that means every session builds on top of an unreviewed index it
# inherited from the session before it, so one bad change is silently inherited
# by all the work that follows and there is no point to roll back to.
#
# The fix is not "let the agent commit". It is "let the agent commit somewhere a
# human still has to approve before it counts". Nothing reaches `main` without a
# person reading the diff -- the checkpoint is preserved exactly where it does
# work, and removed exactly where it only caused work to pile up.
#
# block-dangerous.sh enforces the same rule independently: a commit outside an
# `unattended/*` branch is refused regardless of what this script does. See
# hook-checks/test_commit_policy.py, 11 cases.
#
# Usage:  commit_checkpoint.sh <node-id> [message]
# Exit 0 when it committed AND when there was nothing to commit -- both are
# normal. Non-zero only on a real failure.

set -uo pipefail

NODE="${1:-unknown}"
MESSAGE="${2:-}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$HERE/../.." && pwd)}"
cd "$PROJECT_ROOT" || exit 1

BRANCH_NAME="unattended/$(date -u +%Y-%m-%d)"
CURRENT=$(git branch --show-current 2>/dev/null || echo "")

# Never commit on a branch a human is using. If we are not already on the run's
# branch, create or switch to it -- the working tree carries over unchanged.
if [ "$CURRENT" != "$BRANCH_NAME" ]; then
  if git show-ref --verify --quiet "refs/heads/$BRANCH_NAME"; then
    git switch -q "$BRANCH_NAME" || { echo "[checkpoint] cannot switch to $BRANCH_NAME" >&2; exit 1; }
  else
    git switch -qc "$BRANCH_NAME" || { echo "[checkpoint] cannot create $BRANCH_NAME" >&2; exit 1; }
  fi
  echo "[checkpoint] on $BRANCH_NAME (was ${CURRENT:-detached})"
fi

# Stage tracked modifications only. Deliberately NOT `git add -A`: an unattended
# run generates logs, patches and scratch files, and sweeping them in wholesale
# is how a review surface becomes unreadable.
git add -u

if git diff --cached --quiet; then
  echo "[checkpoint] nothing staged for $NODE — nothing to commit"
  exit 0
fi

if [ -z "$MESSAGE" ]; then
  MESSAGE="checkpoint($NODE): unattended unit complete"
fi

# LAST LINE OF DEFENCE, and on this path the ONLY one.
#
# PreToolUse hooks and the permission deny-list evaluate the Bash tool call the
# agent issues. They do NOT see commands run from inside a script: verified
# 2026-08-27 with `git commit --dry-run`, which the harness refuses at top level
# and which executed untouched from a two-line script. So block-dangerous.sh
# does NOT protect this file, whatever the policy says -- the branch rule holds
# here only because these lines hold it.
#
# Re-check rather than trust the switch above: a `git switch` that fails leaves
# us on the previous branch, and committing there is precisely the outcome the
# whole policy exists to prevent.
FINAL_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
case "$FINAL_BRANCH" in
  unattended/*)
    ;;
  *)
    echo "[checkpoint] REFUSING to commit on branch '${FINAL_BRANCH:-unknown}'." >&2
    echo "[checkpoint] Commits are legal only on unattended/<date>. Nothing was committed." >&2
    exit 1
    ;;
esac

if git commit -q -m "$MESSAGE"; then
  echo "[checkpoint] committed $(git rev-parse --short HEAD) on $BRANCH_NAME"
  exit 0
fi

echo "[checkpoint] commit failed for $NODE" >&2
exit 1
