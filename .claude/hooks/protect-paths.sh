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

# Patterns to deny absolutely. Match against the full path.
PROTECTED_PATTERNS=(
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
    cat <<EOF
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Path '$FILE_PATH' matches protected pattern '$pattern'. This is enforced by .claude/hooks/protect-paths.sh as defense-in-depth. If you genuinely need to edit this file, ask the user to do it manually outside Claude Code, or rename/move the file if the protection is wrong for your project."}}
EOF
    exit 0
  fi
done

exit 0
