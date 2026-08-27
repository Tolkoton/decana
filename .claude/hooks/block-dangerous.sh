#!/usr/bin/env bash
# PreToolUse hook for Bash. Blocks destructive commands, and blocks commits and
# publishes on protected branches. Plain commits on a feature branch are allowed.
# Exit 2 = block + show reason to Claude via stderr.
# Exit 0 = allow.
set -euo pipefail

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null || echo "")

if [ -z "$CMD" ]; then
  exit 0
fi

# Truly destructive patterns. Order: most specific first.
DANGEROUS_PATTERNS=(
  'rm -rf /[^a-zA-Z0-9_.]'
  'rm -rf /$'
  'rm -rf ~'
  'rm -rf \$HOME'
  'rm -rf \*'
  'rm -rf \.\s*$'
  'rm -rf \./\*'
  'rm -rf \$\('
  'rm -fr \$\('
  'rm -r \$\('
  'git push --force'
  'git push -f '
  'git push --force-with-lease'
  'git reset --hard origin'
  'git reset --hard HEAD~'
  'git filter-branch'
  'git clean -fdx'
  'git clean -fX'
  'git update-ref -d'
  'chmod -R 777'
  'chmod 777 '
  ':\(\)\{ :\|:& \};:'
  'curl [^|]+\| (sh|bash|zsh|fish)'
  'wget [^|]+\| (sh|bash|zsh|fish)'
  '^sudo '
  ' sudo '
  'mkfs\.'
  'dd if=.*of=/dev/(sd|disk|nvme|hd)'
  '> /dev/(sda|sdb|disk|nvme|hd)'
  'shred '
  'wipefs '
  'twine upload'
  'uv publish'
  'poetry publish'
  'python -m twine upload'
  'npm publish'
)

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
  if echo "$CMD" | grep -qE "$pattern"; then
    echo "BLOCKED by claude-autonomy safety hook." >&2
    echo "Pattern matched: $pattern" >&2
    echo "Command: $CMD" >&2
    echo "" >&2
    echo "If this is genuinely needed, ask the user to run it manually outside Claude Code." >&2
    exit 2
  fi
done

# Block direct git commit/push on protected branches (defense-in-depth)
BRANCH=""
if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -d "$CLAUDE_PROJECT_DIR/.git" ]; then
  BRANCH=$(git -C "$CLAUDE_PROJECT_DIR" branch --show-current 2>/dev/null || echo "")
fi

PROTECTED_BRANCHES=("main" "master" "production" "prod" "release")
for protected in "${PROTECTED_BRANCHES[@]}"; do
  if [ "$BRANCH" = "$protected" ]; then
    if echo "$CMD" | grep -qE '^[[:space:]]*git[[:space:]]+(commit|push)\s'; then
      echo "BLOCKED: direct git $(echo "$CMD" | awk '{print $2}') on protected branch '$BRANCH'." >&2
      echo "Create a feature branch first: git checkout -b feat/<slug>" >&2
      exit 2
    fi
  fi
done

# `git commit` is ALLOWED as of 2026-08-27 (owner-ratified; see
# .claude/overseer/audit.md). Commits are the cheapest thing in git to undo, and under
# continuous unattended operation a human-only commit step produced the opposite of a
# review checkpoint: one undifferentiated multi-thousand-line diff nobody could read.
#
# The guard that matters is still above this line: the protected-branch check refuses
# commits on main/master/production/prod/release, so work happens on a feature branch
# and nothing reaches main without the owner merging. Publishing to a remote remains
# ask-listed, and the forced-history patterns remain hard-denied.
#
# If you are re-introducing a blanket commit block, put it here — but read the audit
# entry first, because the reason it was removed is not that it was inconvenient.

exit 0
