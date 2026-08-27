#!/usr/bin/env python3
"""The guardrails stay unwritable even after the write grant was widened.

On 2026-08-27 the owner ratified letting supervisor-spawned sessions write under
.claude/hooks, .claude/unattended and .claude/architecture, so an overnight run
can repair the harness instead of only diagnosing it. That widening is exactly
when the files defining the agent's limits need a second mechanism: a permission
list can be re-widened by editing settings.local.json, and an agent that may edit
its own permissions has no limits at all.

So this asserts BOTH halves:
  - the three guardrail files are refused by protect-paths.sh
  - the three newly-granted directories are NOT refused by it (the grant is real,
    not cancelled by the hook it sits next to)
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".claude/hooks/protect-paths.sh"


def refused(path: str) -> bool:
    """protect-paths.sh signals a denial by PRINTING a decision and exiting 0 --
    not by a non-zero exit. Checking the exit code instead reports every file as
    writable, including .env; that mistake was made while writing this test and
    is exactly why the .env case below is kept as a control."""
    r = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"tool_name": "Edit", "tool_input": {"file_path": path}}),
        capture_output=True,
        text=True,
    )
    return '"permissionDecision"' in r.stdout and '"deny"' in r.stdout


MUST_REFUSE = [
    "the constitution",              str(ROOT / ".claude/constitution.md"),
    "shipped settings",              str(ROOT / ".claude/settings.json"),
    "machine-local settings",        str(ROOT / ".claude/settings.local.json"),
    "constitution via relative path", ".claude/constitution.md",
    "a dotenv file",                 str(ROOT / ".env"),
]

MUST_ALLOW = [
    "a hook (newly granted)",        str(ROOT / ".claude/hooks/overseer_stop.py"),
    "the supervisor (newly granted)", str(ROOT / ".claude/unattended/supervisor.sh"),
    "the DAG (newly granted)",       str(ROOT / ".claude/architecture/feature-dag.json"),
    "the overseer ledger",           str(ROOT / ".claude/overseer/ledger.md"),
    "an ordinary doc",               str(ROOT / "PROGRESS.md"),
]

fails = []
print("must REFUSE:")
for i in range(0, len(MUST_REFUSE), 2):
    name, path = MUST_REFUSE[i], MUST_REFUSE[i + 1]
    ok = refused(path)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    if not ok:
        fails.append(f"{name} was WRITABLE: {path}")

print("\nmust ALLOW:")
for i in range(0, len(MUST_ALLOW), 2):
    name, path = MUST_ALLOW[i], MUST_ALLOW[i + 1]
    ok = not refused(path)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    if not ok:
        fails.append(f"{name} was REFUSED: {path}")

print()
if fails:
    print(f"FAIL ({len(fails)}):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("PASS: guardrails locked, granted directories writable")
