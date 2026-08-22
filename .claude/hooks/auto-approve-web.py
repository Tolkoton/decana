#!/usr/bin/env python3
"""
Claude Code hook to auto-approve WebFetch and WebSearch for ANY domain.

Why this exists:
  Claude Code's settings.json permissions for WebFetch are buggy in current versions.
  - "WebFetch" (bulk) in allow → still prompts for each domain (issue #11972)
  - "WebFetch(domain:*)" wildcard → ignored
  - Even "Yes, allow domain X for all projects" prompt → doesn't always persist (#27582)

  Hooks run BEFORE permission evaluation and return explicit allow/deny.
  This works reliably in CLI, VSCode extension, sub-agents, and planning mode.

Optional restriction:
  Set ALLOWED_FETCH_DOMAINS to a set of hostnames to restrict.
  Leave as None to allow ALL domains.

Exit codes:
  0 = Hook decided (JSON printed to stdout)
  1 = Hook did not decide; falls back to normal permission flow

Source: adapted from https://dev.to/alexisfranorge (Dec 2025)
"""
from __future__ import annotations

import json
import sys
from urllib.parse import urlparse

# Restrict WebFetch to a domain allowlist (set of lowercase hostnames).
# Leave as None to allow ALL domains (recommended for autonomy).
ALLOWED_FETCH_DOMAINS: set[str] | None = None
# Example to restrict: {"docs.python.org", "github.com", "stackoverflow.com"}

# Force WebSearch results to specific domains.
# Leave as None to not force any filtering.
FORCE_SEARCH_ALLOWED_DOMAINS: list[str] | None = None


def log(msg: str) -> None:
    print(f"[auto-approve-web] {msg}", file=sys.stderr)


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def emit(result: dict) -> None:
    try:
        print(json.dumps(result))
        sys.exit(0)
    except (TypeError, ValueError) as e:
        log(f"failed to serialize: {e}")
        sys.exit(1)


def handle_pre_tool_use(tool: str, tool_input: dict) -> None:
    updated_input = None

    if tool == "WebFetch" and ALLOWED_FETCH_DOMAINS is not None:
        host = host_of(tool_input.get("url", ""))
        if host not in ALLOWED_FETCH_DOMAINS:
            emit({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"WebFetch blocked by hook: '{host}' not in ALLOWED_FETCH_DOMAINS",
                }
            })

    if tool == "WebSearch" and FORCE_SEARCH_ALLOWED_DOMAINS is not None:
        updated_input = dict(tool_input)
        updated_input["allowed_domains"] = list(FORCE_SEARCH_ALLOWED_DOMAINS)

    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": f"Auto-approved {tool} via hook",
        }
    }
    if updated_input is not None:
        result["hookSpecificOutput"]["updatedInput"] = updated_input

    emit(result)


def handle_permission_request() -> None:
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"},
        }
    })


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        log(f"invalid JSON input: {e}")
        sys.exit(1)
    except Exception as e:
        log(f"failed to read stdin: {e}")
        sys.exit(1)

    event = data.get("hook_event_name", "")
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}

    # SECURITY: handle ONLY WebFetch and WebSearch
    if tool not in ("WebFetch", "WebSearch"):
        sys.exit(1)

    if event == "PreToolUse":
        handle_pre_tool_use(tool, tool_input)
    elif event == "PermissionRequest":
        handle_permission_request()
    else:
        log(f"unknown event: {event}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log(f"unexpected error: {e}")
        sys.exit(1)
