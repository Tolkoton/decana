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

# Truly destructive patterns. Order: most specific first.
DANGEROUS_PATTERNS=(
  'rm -rf /[^a-zA-Z0-9_.]'
  'rm -rf /$'
  'rm -rf ~'
  'rm -rf \$HOME'
  'rm -rf \*'
  'rm -rf \.\s*$'
  'rm -rf \./\*'
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

# Block `git commit` entirely — commits are a human review checkpoint by policy.
if echo "$CMD" | grep -qE '^[[:space:]]*git[[:space:]]+commit($|\s)'; then
  echo "BLOCKED: this project treats commits as a human review checkpoint." >&2
  echo "Stage with 'git add <files>' if helpful, then let the user review the diff and run 'git commit' themselves." >&2
  echo "If the user explicitly asked you to commit, explain this hook is blocking and ask them to run the commit manually." >&2
  exit 2
fi

exit 0
