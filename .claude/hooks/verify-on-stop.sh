#!/usr/bin/env bash
# Stop hook: run lint + typecheck + tests after Claude finishes a turn.
# Reports status. Does NOT commit (commits are a human checkpoint).
# Emits JSON with decision: "block" if any check fails, so Claude continues fixing.
#
# Configuration: .claude/project.env (sourced if present).
# See docs/TEMPLATE-SETUP.md for all variables.
set -euo pipefail

INPUT=$(cat)

# Prevent infinite loop on cascading stop hooks
if echo "$INPUT" | jq -e '.stop_hook_active == true' >/dev/null 2>&1; then
  exit 0
fi

# ---------------------------------------------------------------------------
# TDD RED gate
# ---------------------------------------------------------------------------
# In strict TDD a RED turn ENDS on a deliberately failing test — that failure is
# the checkpoint, not a defect. Without this gate the hook blocks every RED and
# forces RED and GREEN into a single turn, which destroys the review point
# between "here is the test" and "here is the implementation" — the one moment
# where redirecting is still cheap.
#
# Skips the TEST step ONLY. Lint and typecheck still run and still block: a
# deliberately failing test must still be well-formed, correctly typed code.
# This is what keeps the sentinel from becoming a general-purpose bypass.
#
# Read from the envelope's `last_assistant_message` rather than the transcript
# JSONL: the transcript is flushed asynchronously, so a hook parsing it races
# the writer and reads a stale or empty turn (anthropics/claude-code#15813).
# overseer_stop.py hit exactly this and made the same choice — see its module
# docstring. Keep the two hooks agreeing on where turn text comes from.
#
# KNOWN LIMIT — the sentinel is a bypass with no counterparty. Nothing here
# verifies that a turn claiming RED actually produced a FAILING TEST. A turn
# that wrote no test at all, or wrote a passing one, or broke something
# unrelated, gets the identical skip just by emitting the line. The two-signal
# trigger overseer_stop.py uses (sentinel AND structural tool evidence) is the
# obvious shape for closing this, and it is deliberately NOT built yet.
#
# So this gate rests on the developer's honesty about what kind of turn it is.
# That is an acceptable trade for ONE skipped step and no others. It stops being
# acceptable the moment the skip is widened. If you are here to make the
# sentinel also skip lint, typecheck, or a subset of tests: build the
# counterparty first. Widening an unverified bypass is how a verification hook
# quietly becomes decorative.
SKIP_TESTS=false
LAST_MSG=$(echo "$INPUT" | jq -r '.last_assistant_message // ""' 2>/dev/null || echo "")
if printf '%s\n' "$LAST_MSG" | grep -qE '^[[:space:]]*=== TDD RED ===[[:space:]]*$'; then
  SKIP_TESTS=true
  # stderr, NOT stdout: the block path below writes JSON to stdout, and any
  # stray stdout line would corrupt it into an unparseable hook response.
  echo "⚠ verify-on-stop: '=== TDD RED ===' sentinel present — TEST step skipped." >&2
  echo "  Lint and typecheck still ran. Tests must be green by the GREEN turn." >&2
fi

# ---------------------------------------------------------------------------
# Resolve project root: CLAUDE_PROJECT_DIR → git → CWD
# ---------------------------------------------------------------------------
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$PROJECT_ROOT" ]; then
  PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
fi
if [ -z "$PROJECT_ROOT" ]; then
  PROJECT_ROOT="$(pwd)"
fi
cd "$PROJECT_ROOT"

# ---------------------------------------------------------------------------
# Load project configuration
# ---------------------------------------------------------------------------
CODE_EXTENSIONS=""
PROJECT_MARKER=""
LINT_CMD=""
TYPECHECK_CMD=""
TEST_CMD=""

ENV_FILE="${PROJECT_ROOT}/.claude/project.env"
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1091
  source "$ENV_FILE"
else
  echo "⚠ verify-on-stop: .claude/project.env not found at ${ENV_FILE}" >&2
  echo "  Using built-in Python auto-detect defaults. See docs/TEMPLATE-SETUP.md." >&2
fi

# ---------------------------------------------------------------------------
# Normalize CODE_EXTENSIONS: tolerate commas, extra whitespace, leading dots.
# ".ts,.tsx" / "ts tsx" / ".ts .tsx" must all normalize the same way.
# ---------------------------------------------------------------------------
CODE_EXTENSIONS_RAW="$CODE_EXTENSIONS"
if [ -n "$CODE_EXTENSIONS_RAW" ]; then
  NORMALIZED=""
  for tok in $(echo "$CODE_EXTENSIONS_RAW" | tr ',' ' '); do
    tok="${tok#.}"
    tok=$(echo "$tok" | tr '[:upper:]' '[:lower:]')
    [ -n "$tok" ] && NORMALIZED="$NORMALIZED $tok"
  done
  CODE_EXTENSIONS="${NORMALIZED# }"
  if [ -z "$CODE_EXTENSIONS" ]; then
    echo "⚠ verify-on-stop: CODE_EXTENSIONS='$CODE_EXTENSIONS_RAW' did not parse into" >&2
    echo "  any usable extension. Use space- or comma-separated values, e.g. \"ts tsx\" or \"ts,tsx\"." >&2
    echo "  Treating as unset — all changed files will be checked." >&2
  fi
fi

# ---------------------------------------------------------------------------
# Detect which files changed
# ---------------------------------------------------------------------------
CHANGED=""
if [ -d .git ]; then
  CHANGED=$( { git diff --name-only HEAD 2>/dev/null; git diff --name-only --cached 2>/dev/null; } | sort -u )
fi

# If nothing changed, no need to verify
if [ -z "$CHANGED" ]; then
  exit 0
fi

# Build grep pattern for code file extensions
if [ -n "$CODE_EXTENSIONS" ]; then
  # Convert space-separated extensions to grep -E alternation: "py ts" → "(py|ts)"
  EXT_PATTERN=$(echo "$CODE_EXTENSIONS" | tr ' ' '|')
  EXT_RE="\.(${EXT_PATTERN})$"
  if ! echo "$CHANGED" | grep -qE "$EXT_RE"; then
    # No matching code files changed — skip heavy verification
    exit 0
  fi
  CODE_CHANGED=$(echo "$CHANGED" | grep -E "$EXT_RE" | head -5 | tr '\n' ' ')
else
  # No extension filter configured — treat all changes as code
  CODE_CHANGED=$(echo "$CHANGED" | head -5 | tr '\n' ' ')
fi

# ---------------------------------------------------------------------------
# Honour PROJECT_MARKER guard
# ---------------------------------------------------------------------------
if [ -n "$PROJECT_MARKER" ] && [ ! -f "$PROJECT_MARKER" ]; then
  # Marker file absent → tooling not set up yet; inform and exit cleanly.
  echo ""
  echo "⚠ verify-on-stop: $PROJECT_MARKER not found — verification skipped."
  echo "  Add tooling (or clear PROJECT_MARKER in .claude/project.env) to enable checks."
  exit 0
fi

# ---------------------------------------------------------------------------
# Detect toolchain prefix (Python-specific; used in auto-detect path)
# ---------------------------------------------------------------------------
PREFIX=""
if [ -f uv.lock ] && command -v uv >/dev/null 2>&1; then
  PREFIX="uv run"
elif [ -f poetry.lock ] && command -v poetry >/dev/null 2>&1; then
  PREFIX="poetry run"
fi

# ---------------------------------------------------------------------------
# Decide whether to use configured commands or Python auto-detect
# ---------------------------------------------------------------------------
USE_CONFIGURED=false
if [ -n "$LINT_CMD" ] || [ -n "$TYPECHECK_CMD" ] || [ -n "$TEST_CMD" ]; then
  USE_CONFIGURED=true
fi

ERRORS=""

if [ "$USE_CONFIGURED" = true ]; then
  # --- Configured path: run whatever the project declared ---

  if [ -n "$LINT_CMD" ]; then
    if ! eval "$LINT_CMD" 2>/tmp/claude-lint.log >/tmp/claude-lint.log; then
      ERRORS="${ERRORS}LINT FAILED (${LINT_CMD}):\n$(tail -30 /tmp/claude-lint.log)\n\n"
    fi
  fi

  if [ -n "$TYPECHECK_CMD" ]; then
    if ! eval "$TYPECHECK_CMD" 2>/tmp/claude-typecheck.log >/tmp/claude-typecheck.log; then
      ERRORS="${ERRORS}TYPECHECK FAILED (${TYPECHECK_CMD}):\n$(tail -30 /tmp/claude-typecheck.log)\n\n"
    fi
  fi

  if [ -z "$ERRORS" ] && [ -n "$TEST_CMD" ] && [ "$SKIP_TESTS" = false ]; then
    if ! eval "$TEST_CMD" 2>/tmp/claude-test.log >/tmp/claude-test.log; then
      ERRORS="${ERRORS}TESTS FAILED (${TEST_CMD}):\n$(tail -40 /tmp/claude-test.log)\n\n"
    fi
  fi

else
  # --- Auto-detect path: Python defaults (backward-compatible) ---

  # Warn if code extensions are configured but aren't Python
  if [ -n "$CODE_EXTENSIONS" ] && ! echo "$CODE_EXTENSIONS" | grep -qw "py"; then
    echo ""
    echo "⚠ verify-on-stop: CODE_EXTENSIONS='$CODE_EXTENSIONS' but no check commands"
    echo "  are configured in .claude/project.env (LINT_CMD / TYPECHECK_CMD / TEST_CMD)."
    echo "  Code changes detected in: $CODE_CHANGED"
    echo "  Set the check commands to enable verification for this language."
    exit 0
  fi

  # Only proceed with Python auto-detect if .py files actually changed
  if ! echo "$CHANGED" | grep -qE '\.py$'; then
    exit 0
  fi

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

  # 3. Tests (only if previous checks passed, and not a declared RED turn)
  if [ -z "$ERRORS" ] && [ "$SKIP_TESTS" = false ]; then
    if [ -d tests ] || [ -d test ]; then
      if ! $PREFIX pytest -x --no-header -q 2>/tmp/claude-pytest.log >/tmp/claude-pytest.log; then
        ERRORS="${ERRORS}TESTS FAILED (pytest):\n$(tail -40 /tmp/claude-pytest.log)\n\n"
      fi
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
if [ -n "$ERRORS" ]; then
  REASON=$(printf '%b' "$ERRORS" | jq -Rs .)
  cat <<EOF
{"decision":"block","reason":${REASON}}
EOF
  exit 0
fi

echo ""
if [ "$SKIP_TESTS" = true ]; then
  echo "✓ verify-on-stop: lint + typecheck passed — TESTS SKIPPED (=== TDD RED === turn)"
else
  echo "✓ verify-on-stop: all checks passed"
fi
echo "  Files changed: $CODE_CHANGED"
echo "  Ready for your review. Run:  git diff   then   git add ...   then   git commit"

exit 0
