#!/usr/bin/env python3
"""Re-check parked items whose unblocker may have changed (D-12).

Runs before each spawn. A parked item is not dead — it is waiting on a named
condition, and conditions change: a credential appears in .env, a premise is
verified, a dependency slice finishes, the session becomes attended. Without
this, an item parked at 02:00 stays parked even after the thing it needed
arrives at 02:05, and the run reports "nothing can move" while work is sitting
right there.

What it does NOT do: guess. It only re-opens an item when a machine-checkable
condition in its `Unblocks when:` line is now true. Anything requiring judgment
stays parked, because re-opening on a guess is how a run starts thrashing.

Checkable conditions, matched from the entry text:
    env:VAR            -> that variable is now set in the environment
    file:PATH          -> that path now exists
    node:ID            -> that DAG node is now status 'done'
    mode:attended      -> .claude/overseer/mode no longer says unattended
    premise:ID         -> that premise row is now 'verified' in the premise log

Anything else -> left parked, counted, and reported.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PARKED = ROOT / ".claude" / "overseer" / "parked.md"
MODE = ROOT / ".claude" / "overseer" / "mode"
PREMISES = ROOT / ".claude" / "premises" / "premise-log.md"

ENTRY_RE = re.compile(r"^## (\S+) — (.+?) — (PARKED|RESUMED|SURFACED)\s*$", re.M)
COND_RE = re.compile(r"\b(env|file|node|mode|premise):([^\s,;]+)")


def dag_path() -> Path:
    cfg = HERE / "config.sh"
    default = ROOT / ".claude" / "architecture" / "feature-dag.json"
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DAG_FILE="):
                raw = line.split("=", 1)[1].strip().strip('"')
                if ":-" in raw:
                    raw = raw.split(":-", 1)[1].rstrip("}\"")
                return (ROOT / raw).resolve()
    except OSError:
        pass
    return default


def node_is_done(node_id: str) -> bool:
    import json
    try:
        dag = json.loads(dag_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(n.get("id") == node_id and n.get("status") == "done"
               for n in dag.get("nodes", []))


def premise_verified(pid: str) -> bool:
    try:
        for line in PREMISES.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"| {pid} ") and "`verified`" in line:
                return True
    except OSError:
        pass
    return False


def condition_met(kind: str, value: str) -> bool:
    if kind == "env":
        return bool(os.environ.get(value, "").strip())
    if kind == "file":
        return (ROOT / value).exists()
    if kind == "node":
        return node_is_done(value)
    if kind == "mode":
        if value != "attended":
            return False
        try:
            return "unattended" not in MODE.read_text(encoding="utf-8").lower()
        except OSError:
            return True          # no mode file at all == attended
    if kind == "premise":
        return premise_verified(value)
    return False


def main() -> int:
    try:
        text = PARKED.read_text(encoding="utf-8")
    except OSError:
        print("[recheck-parked] no parked.md — nothing to re-check")
        return 0

    entries = list(ENTRY_RE.finditer(text))
    if not entries:
        print("[recheck-parked] queue empty")
        return 0

    resumable, judgment, already = [], [], 0
    for i, m in enumerate(entries):
        if m.group(3) != "PARKED":
            already += 1
            continue
        body = text[m.end(): entries[i + 1].start() if i + 1 < len(entries) else len(text)]
        conds = COND_RE.findall(body)
        if not conds:
            judgment.append(m.group(2))
            continue
        if all(condition_met(k, v) for k, v in conds):
            resumable.append((m.group(2), conds))
        else:
            judgment.append(m.group(2))

    for item, conds in resumable:
        pretty = ", ".join(f"{k}:{v}" for k, v in conds)
        print(f"[recheck-parked] RESUMABLE: {item} — all conditions now met ({pretty})")
        text = text.replace(f"— {item} — PARKED", f"— {item} — RESUMED", 1)

    if resumable:
        PARKED.write_text(text, encoding="utf-8")

    print(f"[recheck-parked] {len(resumable)} resumed, "
          f"{len(judgment)} still parked (need judgment or unmet conditions), "
          f"{already} already closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
