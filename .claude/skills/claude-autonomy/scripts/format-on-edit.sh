#!/usr/bin/env bash
# PostToolUse hook for Edit|Write|MultiEdit.
# Auto-formats Python (and adjacent) files. Silent on success; never blocks.
set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null || echo "")

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

case "$FILE_PATH" in
  *.py)
    if [ -f uv.lock ] && command -v uv >/dev/null 2>&1; then
      uv run ruff format "$FILE_PATH" 2>/dev/null || true
      uv run ruff check --fix --select I "$FILE_PATH" 2>/dev/null || true
    elif [ -f poetry.lock ] && command -v poetry >/dev/null 2>&1; then
      poetry run ruff format "$FILE_PATH" 2>/dev/null || true
      poetry run ruff check --fix --select I "$FILE_PATH" 2>/dev/null || true
    elif command -v ruff >/dev/null 2>&1; then
      ruff format "$FILE_PATH" 2>/dev/null || true
      ruff check --fix --select I "$FILE_PATH" 2>/dev/null || true
    elif command -v black >/dev/null 2>&1; then
      black --quiet "$FILE_PATH" 2>/dev/null || true
    fi
    ;;
  *.json)
    if command -v jq >/dev/null 2>&1; then
      tmp=$(mktemp)
      if jq . "$FILE_PATH" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$FILE_PATH"
      else
        rm -f "$tmp"
      fi
    fi
    ;;
  *.md|*.yml|*.yaml|*.toml)
    if command -v prettier >/dev/null 2>&1; then
      prettier --write --log-level silent "$FILE_PATH" 2>/dev/null || true
    fi
    ;;
esac

exit 0
