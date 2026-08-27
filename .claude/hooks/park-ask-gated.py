#!/usr/bin/env python3
"""PreToolUse hook for Bash. Turns an ask-gated command into a PARK when
nobody is in the loop.

WHY THIS EXISTS
---------------
settings.json's `permissions.ask` list is correct policy: a push, a publish, a
dependency change, a `gh` state change genuinely needs a human, because it
spends money or changes shared state. But its MECHANISM is an interactive
permission prompt. Unattended that prompt is answered by nobody, so the whole
run hangs on one command instead of parking one item and continuing.

PreToolUse runs BEFORE permission evaluation, so denying here preempts the
prompt and hands the reason back to the agent, which parks the item and moves
on. Attended, this hook does nothing and the normal prompt fires as designed.

THIS DOES NOT WEAKEN THE ASK LIST. The command still does not run. The
difference is that the agent gets a reason it can act on instead of a dialog
nobody will close.

WHY PYTHON AND NOT BASH
-----------------------
`jq` is NOT installed on every machine that runs this template — verified
absent on the authoring machine 2026-08-27. Every hook that parses its stdin
with `jq` degrades to a silent no-op there, because the idiom in use is
`jq ... 2>/dev/null || echo ""` followed by an empty-value early exit. A
security hook that silently does nothing is worse than no hook, so this one
uses the standard library only. See the note in CLAUDE.md's hook table.

Exit codes: 0 with JSON on stdout = decision; 0 with no stdout = allow.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Mirrored from .claude/settings.json permissions.ask. Keep in sync: an entry
# here that is NOT in the ask list would block work that should merely prompt.
ASK_GATED = [
    r"^\s*git\s+push(\s|$)",
    r"^\s*git\s+rebase(\s|$)",
    r"^\s*git\s+merge(\s|$)",
    r"^\s*git\s+cherry-pick(\s|$)",
    r"^\s*git\s+revert(\s|$)",
    r"(^|\s)uv\s+(add|remove)(\s|$)",
    r"(^|\s)poetry\s+(add|remove)(\s|$)",
    r"(^|\s)pip\s+(install|uninstall)(\s|$)",
    r"(^|\s)pipx\s+(install|uninstall)(\s|$)",
    r"(^|\s)npm\s+(install|uninstall)(\s|$)",
    r"(^|\s)yarn\s+(add|remove)(\s|$)",
    r"(^|\s)pnpm\s+(add|remove)(\s|$)",
    r"(^|\s)docker\s+push(\s|$)",
    r"(^|\s)gh\s+pr\s+(create|merge)(\s|$)",
    r"(^|\s)gh\s+release(\s|$)",
    r"(^|\s)gh\s+repo\s+(create|delete)(\s|$)",
    r"(^|\s)cargo\s+(add|remove)(\s|$)",
    r"(^|\s)go\s+get(\s|$)",
    r"(^|\s)go\s+mod\s+tidy(\s|$)",
    r"(^|\s)gem\s+install(\s|$)",
    r"(^|\s)bundle\s+(add|remove)(\s|$)",
]
ASK_GATED_RE = [re.compile(p) for p in ASK_GATED]

REASON_TEMPLATE = (
    "Ask-gated command in an unattended run: {cmd!r}. This needs a human — it "
    "spends money or changes shared state — and no human is in the loop "
    "(.claude/overseer/mode says unattended). Do NOT retry and do NOT work "
    "around it. Append a PARKED entry to .claude/overseer/parked.md with "
    "Class: ask-gated, the exact command above under 'Blocked on', and "
    "'Unblocks when: a human runs it or the session becomes attended', then "
    "continue with the next unblocked item. Blocked by "
    ".claude/hooks/park-ask-gated.py; attended, this same command would simply "
    "prompt."
)


def project_dir() -> Path:
    env_val = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if env_val:
        return Path(env_val).resolve()
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return Path(r.stdout.strip()).resolve()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path(".").resolve()


def is_unattended(root: Path) -> bool:
    """True only when .claude/overseer/mode names the unattended mode.
    Absent or unreadable -> attended, which is the safe default: the normal
    permission prompt fires and a human decides."""
    try:
        return "unattended" in (root / ".claude" / "overseer" / "mode").read_text(
            encoding="utf-8"
        ).lower()
    except OSError:
        return False


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        # Cannot read the call -> do not decide. The ask prompt still fires;
        # this hook only ever converts a prompt into a park, never the reverse.
        sys.exit(0)

    cmd = ""
    tool_input = data.get("tool_input") or {}
    if isinstance(tool_input, dict):
        cmd = tool_input.get("command") or ""
    if not isinstance(cmd, str) or not cmd.strip():
        sys.exit(0)

    if not is_unattended(project_dir()):
        sys.exit(0)

    for rx in ASK_GATED_RE:
        if rx.search(cmd):
            json.dump(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": REASON_TEMPLATE.format(cmd=cmd),
                    }
                },
                sys.stdout,
            )
            sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
