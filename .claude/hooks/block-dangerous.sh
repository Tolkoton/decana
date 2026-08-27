#!/usr/bin/env bash
# PreToolUse hook for Bash. Blocks destructive commands and git commit.
# Exit 2 = block + show reason to Claude via stderr.
# Exit 0 = allow.
set -euo pipefail

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null || echo "")

if [ -z "$CMD" ]; then
  exit 0
fi

# NOTE on false positives — decided deliberately (S7).
# These patterns match anywhere in the command text, INCLUDING inside quoted
# string literals and heredoc bodies. So merely *describing* a dangerous command
# in documentation is blocked as if it were being run. This was hit twice for
# real while filing and fixing node S7.
# It is NOT fixed here, and that is a choice: telling a real command from a
# quoted mention needs shell parsing, and the obvious shortcut — strip heredoc
# bodies before matching — opens a genuine hole, because a heredoc fed to a
# shell executes its body. For a deny control a false positive is a nuisance
# and a false negative is a breach, so the bias stays where it is.
# Workaround when a write is blocked by its own documentation text: split the
# literal across a concatenation, or write the file with the Edit/Write tool
# instead of a shell heredoc.
#
# Command-position prefix used below is (^|[;&|(`])[[:space:]]* — start of the
# command OR just after a separator. A bare ^ let a compound command walk past
# the check, and a leading tab defeated both anchored forms.

# Truly destructive patterns. Order: most specific first.
DANGEROUS_PATTERNS=(
  'rm -rf /[^a-zA-Z0-9_.]'
  'rm -rf /$'
  'rm -rf ~'
  'rm[[:space:]]+-[a-z]*[rf][a-z]*[[:space:]]+["'"'"']?\$\{?HOME\}?'
  'rm -rf \*'
  'rm -rf \.\s*$'
  'rm -rf \./\*'
  'rm -rf \$\('
  'rm -fr \$\('
  'rm -r \$\('
# NOTE: the git-commit pattern is deliberately NOT in this unconditional list.
# It lives in the branch-aware commit policy near the end of the file, because
# after 2026-08-27 a commit is legal on an unattended/<date> branch and illegal
# everywhere else. Putting it here would block it on every branch, including the
# one where it is now the point.
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
  '(^|[;&|(`])[[:space:]]*sudo[[:space:]]'
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
    if echo "$CMD" | grep -qE '(^|[;&|(`])[[:space:]]*git[[:space:]]+(-[^[:space:]]+[[:space:]]+([^-][^[:space:]]*[[:space:]]+)?)*(commit|push)([[:space:]]|$)'; then
      echo "BLOCKED: direct git $(echo "$CMD" | awk '{print $2}') on protected branch '$BRANCH'." >&2
      echo "Create a feature branch first: git checkout -b feat/<slug>" >&2
      exit 2
    fi
  fi
done

# Commit policy — owner-ratified 2026-08-27.
#
# Commits are allowed on an `unattended/<date>` branch and NOWHERE else. The
# checkpoint is preserved in the only place it does work: nothing reaches `main`
# without a human reading the diff. What it buys is that each session in a long
# run builds on a committed, verified base instead of on top of an unreviewed
# index it inherited from the session before it -- where one bad change is
# silently inherited by everything after.
#
# The pattern is the command-position form from S7: a bare `^` let `cd x && git
# commit` walk straight past the old check, and `git -C dir commit` hid the
# subcommand behind a global option. Both are covered here.
if echo "$CMD" | grep -qE '(^|[;&|(`])[[:space:]]*git[[:space:]]+(-[^[:space:]]+[[:space:]]+([^-][^[:space:]]*[[:space:]]+)?)*commit([[:space:]]|$)'; then
  case "$BRANCH" in
    unattended/*)
      : # allowed — an unattended run's own branch
      ;;
    *)
      echo "BLOCKED: commits are allowed only on an 'unattended/<date>' branch." >&2
      echo "Current branch: '${BRANCH:-unknown}'." >&2
      echo "On any other branch a commit is a human review checkpoint: stage with 'git add <files>'," >&2
      echo "summarise the change, suggest a message, and let the user run the commit themselves." >&2
      echo "For an unattended run, switch first: git switch -c unattended/\$(date -u +%Y-%m-%d)" >&2
      exit 2
      ;;
  esac
fi

exit 0
