#!/usr/bin/env bash
# PreToolUse hook for Edit|Write|MultiEdit.
# Defense-in-depth for paths that should never be written to from a Claude session.
# Emits JSON with permissionDecision: "deny" so Claude sees the reason.
set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null || echo "")

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Narrow allowlist, checked BEFORE the deny patterns.
#
# `\.env$` below is a secrets heuristic: it cannot tell a config file from a
# credentials file by name. That is the right default and it stays. But this
# template ships .claude/project.env as a COMMITTED, secret-free config file
# and docs/TEMPLATE-SETUP.md Step 2 instructs the operator to edit it — so the
# heuristic was blocking the setup path of the very template it protects.
#
# Scoped as tightly as possible: this exact filename, only directly inside a
# .claude/ directory. Any other *.env, including .claude/anything-else.env and
# project.env outside .claude/, is still denied.
#
# Rejected alternative: renaming to project.sh. It reads better, but every
# project already built from this template has a project.env that three hooks
# read by name, and a rename would silently stop those hooks configuring
# themselves. Silent breakage of downstream projects costs more than one
# audited exception here. If a secret is ever put in this file, that is a
# review failure, not a hook failure — the file is committed and visible.
# ---------------------------------------------------------------------------
ALLOWED_PATTERNS=(
  '(^|/)\.claude/project\.env$'
)

for allowed in "${ALLOWED_PATTERNS[@]}"; do
  if echo "$FILE_PATH" | grep -qE "$allowed"; then
    exit 0
  fi
done

# Patterns to deny absolutely. Match against the full path.
PROTECTED_PATTERNS=(
  # The guardrails themselves. Added 2026-08-27 alongside the owner-ratified
  # grant letting spawned sessions write under .claude/hooks, .claude/unattended
  # and .claude/architecture so an overnight run can repair the harness it runs
  # on. Widening what an agent may edit is exactly when the things that define
  # its limits need a second layer: the permission list is one mechanism, and a
  # settings.local.json edit could quietly re-widen it. These three stay out of
  # reach in both mechanisms. Propose changes in .claude/overseer/audit.md.
  '\.claude/constitution\.md$'
  '\.claude/settings\.json$'
  '\.claude/settings\.local\.json$'
  '\.env$'
  '\.env\.'
  '/secrets/'
  '^secrets/'
  '/\.git/'
  '/\.ssh/'
  '/\.aws/'
  '/\.gnupg/'
  '/\.npmrc$'
  '/\.pypirc$'
  'id_rsa$'
  'id_rsa\.pub$'
  'id_ed25519$'
  'id_ed25519\.pub$'
  '\.pem$'
  '\.key$'
  '\.p12$'
  '\.pfx$'
  'credentials\.json$'
  'service-account.*\.json$'
  'gcloud-key\.json$'
  '/migrations/.*\.py$'
  '^migrations/.*\.py$'
  '/alembic/versions/.*\.py$'
  '^alembic/versions/.*\.py$'
  'alembic\.ini$'
  '/\.github/workflows/'
  '^\.github/workflows/'
)

for pattern in "${PROTECTED_PATTERNS[@]}"; do
  if echo "$FILE_PATH" | grep -qE "$pattern"; then
    # Encode with jq, not a heredoc. 23 of the 27 patterns above contain a
    # backslash (\.env$, \.pem$, /\.ssh/, ...), and interpolating one raw into
    # a JSON string produces an invalid escape — the harness then cannot parse
    # the decision and the deny is silently lost. Verified 2026-08-27: a write
    # to .env emitted 406 bytes of malformed JSON and was NOT denied.
    jq -n --arg path "$FILE_PATH" --arg pattern "$pattern" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:"Path \($path) matches protected pattern \($pattern). This is enforced by .claude/hooks/protect-paths.sh as defense-in-depth. If you genuinely need to edit this file, ask the user to do it manually outside Claude Code, or rename/move the file if the protection is wrong for your project."}}'
    exit 0
  fi
done

exit 0
