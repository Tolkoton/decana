#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Stop hook: auto-trigger an overseer 12-check audit on unit completion.

Redesign of the abandoned bash `overseer-on-stop.sh`. The bash hook reconstructed
the last assistant message by parsing the transcript JSONL named in the Stop
envelope — but the transcript is flushed asynchronously, so the hook raced the
writer and read a stale or empty turn (anthropics/claude-code#15813).

Claude Code now ships the finished turn's text directly on the Stop envelope as
`last_assistant_message` (field probe PASS, 2026-05-22 — see
.claude/artifacts/spikes/auto-overseer-redesign-2026-05-22.md). This hook reads that
field for the *completion text* and consults the transcript only for the
*structural tool-use signal*, which is a stable historical record by the time
Stop fires.

TRIGGER — both signals required:
  1. text sentinel: `=== UNIT N COMPLETE ===` on its own line in the message.
  2. tool signal:   in the current turn, an Edit/Write/MultiEdit on a code
                    path (configured via SOURCE_DIRS / CODE_EXTENSIONS in
                    .claude/project.env) AND a Bash verification command
                    (configured via CHECK_CMDS, or built-in broad default).

RECURSION GUARDS — per-branch, by design:
  - Audit-request branch    — `.claude/overseer/.last_audit_sha` SHA of last message
                              that requested an audit; same-message re-fire
                              is silent.
  - PASS / CONTINUE branch  — `.claude/overseer/.last_continue_sha` SHA of last
                              OVERSEER_PASS message that produced a CONTINUE
                              injection; same-message re-fire is silent.
  - Halt markers (BLOCK / ESCALATE / ADR_REQUIRED / SLICE_AWAITING_OWNER /
    SLICE_COMPLETE) silent-pass — owner takes over.

  An earlier `stop_hook_active`-based "Guard 1" was removed because it
  short-circuited BEFORE the per-branch SHA guards on hook-initiated turns
  (audit-PASS turns and CONTINUE-driven UNIT turns both arrive with
  `stop_hook_active=true`), making both injection branches unreachable in
  the autonomous loop. The per-branch SHAs handle recursion safety for the
  branches they cover.

PHASE GUARD: `.claude/overseer/state` containing `plan` suppresses the audit — the
developer is designing, not completing units of work.

Output: `{"decision":"block","reason":...}` on stdout (exit 0) injects the audit
request and continues the turn; empty stdout (exit 0) passes the turn through.

Invoked by Claude Code as `python3 .claude/hooks/overseer_stop.py` (see
.claude/settings.json Stop hooks). The `uv run` shebang only applies when the
file is executed directly; either way it needs no third-party dependency.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

# `=== UNIT 7 COMPLETE ===` on its own line; surrounding horizontal space is
# tolerated so the sentinel survives minor formatting.
UNIT_DONE_RE = re.compile(r"^[ \t]*=== UNIT \d+ COMPLETE ===[ \t]*$", re.MULTILINE)
# An overseer verdict already emitted this turn — recursion guard 3.
#
# ANCHORED TO LINE START, deliberately, exactly as UNIT_DONE_RE above is.
# Before this, `re.compile(r"OVERSEER_PASS\b")` matched the token ANYWHERE in
# the message, including inside prose and code spans. Any turn that documented,
# reviewed, or taught the protocol therefore entered the autonomous continue
# loop — and this repo is the protocol's own template, so those turns are
# routine here. Observed 2026-08-27: a turn that only *described* the markers
# consumed .last_continue_sha and injected a continue instruction against a
# slice that did not exist.
#
# SKILL.md's "Verdict format" section already requires a marker to be "on its
# own line", so this makes the hook enforce what the contract always stated.
# Leading horizontal space is tolerated, matching UNIT_DONE_RE.
_MARKER_PREFIX = r"^[ \t]*OVERSEER_"

# Halt markers — owner takes over, hook silent-passes
HALT_MARKER_RE = re.compile(
    _MARKER_PREFIX + r"(?:BLOCK|ESCALATE|ADR_REQUIRED|SLICE_AWAITING_OWNER|SLICE_COMPLETE)\b",
    re.MULTILINE,
)
# Pass marker — hook re-injects "continue to next unit" (taskmaster pattern)
PASS_MARKER_RE = re.compile(_MARKER_PREFIX + r"PASS\b", re.MULTILINE)
# Legacy alias for backward compat — any verdict marker
OVERSEER_MARKER_RE = re.compile(
    _MARKER_PREFIX
    + r"(?:PASS|BLOCK|ESCALATE|ADR_REQUIRED|SLICE_AWAITING_OWNER|SLICE_COMPLETE)\b",
    re.MULTILINE,
)
# File-mutating tools — the other half of the tool signal.
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})

# Built-in broad default: covers Python, JS/TS, Go, Rust, Swift stacks.
_DEFAULT_CHECK_CMDS = "pytest ruff mypy npm jest vitest go cargo swift"


def _get_project_dir() -> Path:
    """Resolve the project root: CLAUDE_PROJECT_DIR → git → CWD.
    Never returns a relative path — always .resolve()d."""
    env_val = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if env_val:
        return Path(env_val).resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).resolve()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path(".").resolve()


def _load_project_env(project_dir: Path) -> dict[str, str]:
    """Parse .claude/project.env as KEY="value" or KEY=value lines.
    Prints a stderr warning when the file is absent; returns {} on any error."""
    env_path = project_dir / ".claude" / "project.env"
    result: dict[str, str] = {}
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        print(
            f"⚠ overseer_stop: .claude/project.env not found at {env_path} — "
            "using built-in defaults. See docs/TEMPLATE-SETUP.md.",
            file=sys.stderr,
        )
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, raw = line.partition("=")
        key = key.strip()
        # Strip surrounding quotes (single or double).
        value = raw.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def _split_list(raw: str) -> list[str]:
    """Split a config list value on commas and/or whitespace, so ".ts,.tsx",
    "ts tsx", and ".ts .tsx" all yield the same tokens. Empty tokens dropped."""
    return [tok for tok in re.split(r"[,\s]+", raw.strip()) if tok]


def _build_check_cmd_re(cfg: dict[str, str]) -> re.Pattern[str]:
    """Build the check-command regex from project config.
    Falls back to the built-in broad default when CHECK_CMDS is empty or
    does not parse into any usable name."""
    raw = cfg.get("CHECK_CMDS", "").strip()
    names = _split_list(raw) if raw else []
    if raw and not names:
        print(
            f"⚠ overseer_stop: CHECK_CMDS='{raw}' did not parse into any usable "
            "command name — falling back to built-in defaults.",
            file=sys.stderr,
        )
    if not names:
        names = _DEFAULT_CHECK_CMDS.split()
    pattern = "|".join(re.escape(n) for n in names)
    return re.compile(rf"\b(?:{pattern})\b")


def _build_source_dirs(cfg: dict[str, str]) -> list[str]:
    """Return the configured source dirs, normalized with trailing slash.
    Empty list means "match any directory" (use CODE_EXTENSIONS fallback)."""
    raw = cfg.get("SOURCE_DIRS", "").strip()
    if not raw:
        return []
    dirs = [tok.rstrip("/") + "/" for tok in _split_list(raw) if tok.rstrip("/")]
    if not dirs:
        print(
            f"⚠ overseer_stop: SOURCE_DIRS='{raw}' did not parse into any usable "
            "directory. Treating as unset — any code-extension match counts.",
            file=sys.stderr,
        )
    return dirs


def _build_code_extensions(cfg: dict[str, str]) -> frozenset[str]:
    """Return the set of code file extensions (without dot).
    Empty set means "match all files"."""
    raw = cfg.get("CODE_EXTENSIONS", "").strip()
    if not raw:
        return frozenset()
    exts = frozenset(
        tok.lstrip(".").lower() for tok in _split_list(raw) if tok.lstrip(".")
    )
    if not exts:
        print(
            f"⚠ overseer_stop: CODE_EXTENSIONS='{raw}' did not parse into any "
            "usable extension. Treating as unset — all edited files count.",
            file=sys.stderr,
        )
    return exts


def _is_code_path(
    file_path: str,
    source_dirs: list[str],
    code_extensions: frozenset[str],
) -> bool:
    """True if the path counts as a code edit for the overseer trigger.

    Decision tree:
    1. If source_dirs is configured: path must start with one of them.
    2. If source_dirs is empty: path must match code_extensions (if configured).
    3. If both are empty: any edit counts.
    """
    normalized = file_path.replace("\\", "/")
    # Ensure it doesn't start with / for relative comparison
    rel = normalized.lstrip("/")

    if source_dirs:
        # Check both absolute (/home/.../src/foo.py) and relative (src/foo.py)
        for d in source_dirs:
            if rel.startswith(d) or ("/" + d) in ("/" + normalized):
                # Match relative form or embedded form (/src/)
                if rel.startswith(d):
                    return True
                # Also match absolute paths containing the dir segment
                parts = normalized.split("/")
                dir_name = d.rstrip("/")
                if dir_name in parts:
                    idx = len(parts) - 1 - list(reversed(parts)).index(dir_name)
                    # Ensure it's a directory, not just a substring
                    if idx < len(parts) - 1:
                        return True
        return False

    if code_extensions:
        suffix = Path(normalized).suffix.lstrip(".").lower()
        return suffix in code_extensions

    # No constraints configured — any edit counts.
    return True


CONTINUE_REASON = (
    "OVERSEER_PASS recorded. Proceed with the next unit per the active slice plan in .claude/overseer/slice/. "
    "Do the next pending UNIT's work (code edits + verification commands), then emit `=== UNIT N COMPLETE ===` on its own line. "
    "If the slice has no more code units (only smoke / G4 owner-driven steps remain), or if you are uncertain what UNIT N is, "
    "emit `OVERSEER_SLICE_AWAITING_OWNER: <reason>` on its own line to halt and request owner input. "
    "If the slice's last code unit is complete and smoke / G4 are next, emit `OVERSEER_SLICE_AWAITING_OWNER: smoke and G4 are owner-driven; awaiting owner walkthrough.`"
)

AUDIT_REASON = (
    "OVERSEER_REQUEST (auto-triggered by the Stop hook on a unit-completion "
    "claim). Before yielding control to the owner:\n"
    "1. Read .claude/skills/overseer/SKILL.md and apply the full 12-check "
    "checklist to the work since your last audit.\n"
    "2. Append the prescribed entry to .claude/overseer/ledger.md before replying.\n"
    "3. Output a verdict on its own line, exactly one of: OVERSEER_PASS | "
    "OVERSEER_BLOCK: #N <reason> | OVERSEER_ESCALATE: <JSON> | "
    "OVERSEER_ADR_REQUIRED: <ADR>. Emitting any OVERSEER_ verdict marker is "
    "what stops this hook re-firing on the next turn."
)
MAX_UNATTENDED_CONTINUES = 25

UNATTENDED_CONTINUE_REASON = (
    "UNATTENDED_CONTINUE. The run is still live ({detail}), so ending the turn "
    "is not one of the three legitimate stops (human-only input; falsified "
    "premise; empty unblocked queue).\n"
    "Do NOT stop to wait for a background task, to report progress, or to let "
    "the owner redirect — unattended, a checkpoint redirects nobody and costs "
    "the whole run.\n"
    "Continue now: take the next unblocked item. If the only thing in flight is "
    "a supervisor session editing the repo, do work that does not race it — "
    "verify a hook's negative case, extend hook-checks/, re-check "
    ".claude/overseer/parked.md, or update PROGRESS.md.\n"
    "To stop for real, emit an OVERSEER_ halt marker naming which of the three "
    "reasons applies."
)

DRY_RUN_REASON = (
    "DRY-RUN: would have blocked — the overseer Stop hook is wired and live. "
    "No real unit-completion was evaluated; this is a smoke-test injection."
)


def _run_has_work(project_dir: Path) -> str | None:
    """Describe live unattended work, or None if there is none.

    Returns None for a session SPAWNED BY the supervisor. Those must be allowed
    to end: a session that finishes a node writes 'unit-done' and exits so the
    supervisor can spawn a fresh one, and a session that dies must leave
    'working' behind so the supervisor detects the death and restarts it.
    Blocking their Stop would break both mechanisms. This branch exists for the
    ORCHESTRATING session only.
    """
    if os.environ.get("CLAUDE_UNATTENDED_SESSION"):
        return None
    try:
        mode = (project_dir / ".claude" / "overseer" / "mode").read_text(
            encoding="utf-8"
        )
    except OSError:
        return None
    if "unattended" not in mode.lower():
        return None

    state_path = project_dir / ".claude" / "unattended" / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        status = str(state.get("status", ""))
        if status in ("working", "unit-done"):
            node = state.get("node") or "?"
            return f"supervisor state is {status!r} on node {node}"
    except (OSError, json.JSONDecodeError, ValueError, AttributeError):
        pass

    dag_path = project_dir / ".claude" / "architecture" / "feature-dag.json"
    try:
        nodes = json.loads(dag_path.read_text(encoding="utf-8")).get("nodes", [])
        done = {n["id"] for n in nodes if n.get("status") == "done"}
        for node in nodes:
            if node.get("status") in ("done", "parked"):
                continue
            if all(dep in done for dep in node.get("deps", [])):
                return f"DAG node {node.get('id')!r} is ready and unblocked"
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError):
        pass
    return None


def _continue_count_file(project_dir: Path) -> Path:
    return project_dir / ".claude" / "overseer" / ".continue_count"


def _read_continue_count(project_dir: Path) -> int:
    try:
        return int(_continue_count_file(project_dir).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _write_continue_count(project_dir: Path, value: int) -> None:
    path = _continue_count_file(project_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{value}\n", encoding="utf-8")
    except OSError:
        pass


def _stop_or_continue(project_dir: Path) -> NoReturn:
    """The former plain `_passthrough()` for turns with nothing to audit.

    Unattended with work still live, ending the turn is not a legitimate stop,
    so block and re-inject. Bounded by MAX_UNATTENDED_CONTINUES so a genuinely
    wedged loop cannot spin forever.
    """
    detail = _run_has_work(project_dir)
    if detail is None:
        _write_continue_count(project_dir, 0)
        _passthrough()
    count = _read_continue_count(project_dir)
    if count >= MAX_UNATTENDED_CONTINUES:
        _write_continue_count(project_dir, 0)
        _passthrough()
    _write_continue_count(project_dir, count + 1)
    _emit_block(UNATTENDED_CONTINUE_REASON.format(detail=detail))


def _emit_block(reason: str) -> NoReturn:
    """Print the block decision and exit 0 — Claude injects `reason` and
    continues the turn."""
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.exit(0)


def _passthrough() -> NoReturn:
    """Exit silently with no decision — the turn ends normally."""
    sys.exit(0)


def _read_envelope() -> dict[str, object]:
    """Parse the Stop envelope from stdin. A malformed or non-object payload
    degrades to an empty envelope, never a crash — a hook must not break a
    turn over bad input."""
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items()}


def _str_field(envelope: dict[str, object], key: str) -> str:
    """Read a string field from the envelope, or `""` if absent / wrong type."""
    value = envelope.get(key)
    return value if isinstance(value, str) else ""


def _is_turn_boundary(record: dict[str, object]) -> bool:
    """True if `record` is a genuine user message — `message.content` is a bare
    string. Tool-result records are `type:user` too but carry a list body, so
    they return False and the reverse scan treats them as transparent."""
    message = record.get("message")
    if not isinstance(message, dict):
        return False
    return isinstance(message.get("content"), str)


def _has_tool_signal(
    transcript_path: str,
    source_dirs: list[str],
    code_extensions: frozenset[str],
    check_cmd_re: re.Pattern[str],
) -> bool:
    """True if the current turn contains BOTH a code-file Edit/Write/MultiEdit
    AND a Bash verification command, as configured in .claude/project.env.

    The transcript is walked in reverse; the current turn is the run of records
    after the most recent genuine user message. Claude Code writes one content
    block per JSONL record, so a turn spans several assistant records.
    """
    if not transcript_path:
        return False
    path = Path(transcript_path)
    if not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False

    saw_code_edit = False
    saw_check_cmd = False
    for raw_line in reversed(lines):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        record_type = record.get("type")
        if record_type == "user":
            if _is_turn_boundary(record):
                break  # start of the current turn — stop scanning.
            continue  # tool-result record — transparent.
        if record_type != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            tool_input = block.get("input")
            if not isinstance(tool_input, dict):
                continue
            if name in EDIT_TOOLS:
                file_path = tool_input.get("file_path")
                if isinstance(file_path, str) and _is_code_path(
                    file_path, source_dirs, code_extensions
                ):
                    saw_code_edit = True
            elif name == "Bash":
                command = tool_input.get("command")
                if isinstance(command, str) and check_cmd_re.search(command):
                    saw_check_cmd = True
        if saw_code_edit and saw_check_cmd:
            return True
    return saw_code_edit and saw_check_cmd


def _phase_is_plan(project_dir: Path) -> bool:
    """True if `.claude/overseer/state` exists and names the planning phase."""
    try:
        content = (project_dir / ".claude" / "overseer" / "state").read_text(
            encoding="utf-8"
        )
    except OSError:
        return False
    return "plan" in content.lower()


def _audit_sha_file(project_dir: Path) -> Path:
    return project_dir / ".claude" / "overseer" / ".last_audit_sha"


def _message_digest(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def _already_audited(project_dir: Path, message: str) -> bool:
    """True if an audit was already requested for this exact message text."""
    try:
        recorded = _audit_sha_file(project_dir).read_text(encoding="utf-8")
    except OSError:
        return False
    return recorded.strip() == _message_digest(message)


def _record_audit(project_dir: Path, message: str) -> None:
    """Persist this message's digest so the SHA guard suppresses a re-fire."""
    sha_file = _audit_sha_file(project_dir)
    sha_file.parent.mkdir(parents=True, exist_ok=True)
    sha_file.write_text(_message_digest(message) + "\n", encoding="utf-8")


def main() -> NoReturn:
    # NOTE — `stop_hook_active`-based Guard 1 was removed (see module
    # docstring "RECURSION GUARDS"). It preempted the per-branch SHA
    # idempotency on every hook-initiated turn — making both injection
    # branches (audit-request, PASS→CONTINUE) unreachable in the
    # autonomous loop. Per-branch SHAs at `.claude/overseer/.last_audit_sha`
    # and `.claude/overseer/.last_continue_sha` are the design's intended
    # recursion guards and are sufficient.
    dry_run = "--dry-run" in sys.argv[1:]
    envelope = _read_envelope()

    if dry_run:
        _emit_block(DRY_RUN_REASON)

    message = _str_field(envelope, "last_assistant_message")

    # Halt markers — owner takes over, hook silent-passes.
    if HALT_MARKER_RE.search(message):
        _passthrough()

    # PASS marker — re-inject "continue to next unit" (taskmaster pattern: keep blocking until slice done)
    if PASS_MARKER_RE.search(message):
        sha_file = (
            _get_project_dir() / ".claude" / "overseer" / ".last_continue_sha"
        )
        digest = _message_digest(message)
        try:
            if sha_file.read_text(encoding="utf-8").strip() == digest:
                _passthrough()
        except OSError:
            pass
        sha_file.parent.mkdir(parents=True, exist_ok=True)
        sha_file.write_text(digest + "\n", encoding="utf-8")
        print(json.dumps({"decision": "block", "reason": CONTINUE_REASON}))
        sys.exit(0)

    project_dir = _get_project_dir()

    # Phase guard: the developer is planning, not completing units of work.
    if _phase_is_plan(project_dir):
        _passthrough()

    # Guard 2: this exact message already requested an audit.
    if _already_audited(project_dir, message):
        _stop_or_continue(project_dir)

    # Sentinel pre-check — short-circuit before loading config (avoids noisy
    # project.env warning on every turn that has no unit-completion claim).
    if not UNIT_DONE_RE.search(message):
        _stop_or_continue(project_dir)

    # Load project config — only reached when the sentinel is present.
    # Prints a stderr warning if project.env is absent.
    cfg = _load_project_env(project_dir)
    source_dirs = _build_source_dirs(cfg)
    code_extensions = _build_code_extensions(cfg)
    check_cmd_re = _build_check_cmd_re(cfg)

    # Two-signal trigger — sentinel already confirmed above; check tool signal.
    tool_signal = _has_tool_signal(
        _str_field(envelope, "transcript_path"),
        source_dirs,
        code_extensions,
        check_cmd_re,
    )
    if not tool_signal:
        _stop_or_continue(project_dir)

    _record_audit(project_dir, message)
    _emit_block(AUDIT_REASON)


if __name__ == "__main__":
    main()
