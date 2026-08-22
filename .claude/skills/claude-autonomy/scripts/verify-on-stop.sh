#!/usr/bin/env bash
# Stop hook: run lint + typecheck + tests after Claude finishes a turn.
# Reports status. Does NOT commit (commits are a human checkpoint).
# Emits JSON with decision: "block" if any check fails, so Claude continues fixing.
set -euo pipefail

INPUT=$(cat)

# Prevent infinite loop on cascading stop hooks
if echo "$INPUT" | jq -e '.stop_hook_active == true' >/dev/null 2>&1; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# Detect toolchain prefix
PREFIX=""
if [ -f uv.lock ] && command -v uv >/dev/null 2>&1; then
  PREFIX="uv run"
elif [ -f poetry.lock ] && command -v poetry >/dev/null 2>&1; then
  PREFIX="poetry run"
fi

# Skip verification if no Python source files have been modified
CHANGED=""
if [ -d .git ]; then
  CHANGED=$( { git diff --name-only HEAD 2>/dev/null; git diff --name-only --cached 2>/dev/null; } | sort -u )
fi
if [ -z "$CHANGED" ]; then
  exit 0
fi
if ! echo "$CHANGED" | grep -qE '\.py$'; then
  # Only non-Python changes — skip heavy verification
  exit 0
fi

ERRORS=""

# 1. Ruff lint (fast)
if [ -f pyproject.toml ] && grep -q '\[tool\.ruff' pyproject.toml 2>/dev/null; then
  if ! $PREFIX ruff check . 2>/tmp/claude-ruff.log >/tmp/claude-ruff.log; then
    ERRORS="${ERRORS}LINT FAILED (ruff check):\n$(tail -30 /tmp/claude-ruff.log)\n\n"
  fi
fi

# 2. Mypy typecheck
if [ -f pyproject.toml ] && grep -q '\[tool\.mypy' pyproject.toml 2>/dev/null; then
  if ! $PREFIX mypy . 2>/tmp/claude-mypy.log >/tmp/claude-mypy.log; then
    ERRORS="${ERRORS}TYPECHECK FAILED (mypy):\n$(tail -30 /tmp/claude-mypy.log)\n\n"
  fi
fi

# 3. Tests (only if previous checks passed)
if [ -z "$ERRORS" ]; then
  if [ -d tests ] || [ -d test ]; then
    if ! $PREFIX pytest -x --no-header -q 2>/tmp/claude-pytest.log >/tmp/claude-pytest.log; then
      ERRORS="${ERRORS}TESTS FAILED (pytest):\n$(tail -40 /tmp/claude-pytest.log)\n\n"
    fi
  fi
fi

if [ -n "$ERRORS" ]; then
  REASON=$(printf '%b' "$ERRORS" | jq -Rs .)
  cat <<EOF
{"decision":"block","reason":${REASON}}
EOF
  exit 0
fi

# All checks passed — print a "ready for review" message and exit cleanly.
# This goes to the transcript; the turn ends normally.
echo ""
echo "✓ verify-on-stop: lint / typecheck / tests passed"
PYTHON_CHANGED=$(echo "$CHANGED" | grep -E '\.py$' | head -5 | tr '\n' ' ')
if [ -n "$PYTHON_CHANGED" ]; then
  echo "  Python files changed: $PYTHON_CHANGED"
fi
echo "  Ready for your review. Run:  git diff   then   git add ...   then   git commit"

exit 0
