#!/usr/bin/env python3
"""Every autonomous deviation in the DAG must have a CLOSED decision entry.

The failure this pins down: a two-way-door decision was made, acted on, and
never written to escalations.md. Logging is what closes a decision; an unlogged
one stays open in working memory and gets re-raised with the owner turn after
turn, which is a stop wearing a question mark. It happened on node S3 -- decided
once, re-surfaced three times, recorded nowhere.

The detectable trace of such a deviation is `prior_evidence`: a node only has it
because someone reopened a `done` node and deliberately preserved the old record
instead of overwriting it. So: every node carrying `prior_evidence` must have a
matching `AUTONOMOUS` entry, marked `Status: CLOSED`, in escalations.md.

Usage:
  python3 hook-checks/test_decision_logged.py [dag.json] [escalations.md]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAG = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".claude/architecture/feature-dag.json"
ESC = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / ".claude/overseer/escalations.md"


def closed_autonomous_ids(text: str) -> set[str]:
    """Ids from '## <ts> — AUTONOMOUS — <id>' blocks whose Status is CLOSED."""
    found = set()
    blocks = re.split(r"^## ", text, flags=re.MULTILINE)
    for block in blocks:
        header = block.splitlines()[0] if block.splitlines() else ""
        m = re.match(r".*—\s*AUTONOMOUS\s*—\s*(\S+)", header)
        if not m:
            continue
        if re.search(r"^-\s*Status:\s*CLOSED\s*$", block, flags=re.MULTILINE):
            found.add(m.group(1).strip())
    return found


def main() -> int:
    # A project with no feature DAG has no autonomous deviations to check.
    # That is an ordinary state -- every project built from this template starts
    # there -- so it is a pass, not a crash. Found when the suite was migrated
    # into a real project (decana) and this was the only test that exploded.
    if not DAG.is_file():
        print(f"no DAG at {DAG} — nothing to check")
        return 0
    if not ESC.is_file():
        print(f"no escalations log at {ESC} — nothing to check")
        return 0

    dag = json.loads(DAG.read_text(encoding="utf-8"))
    logged = closed_autonomous_ids(ESC.read_text(encoding="utf-8"))

    deviations = [n["id"] for n in dag.get("nodes", []) if "prior_evidence" in n]
    if not deviations:
        print("no autonomous deviations in the DAG — nothing to check")
        return 0

    fails = []
    for node_id in deviations:
        ok = node_id in logged
        print(f"  {'ok  ' if ok else 'FAIL'} {node_id} deviation has a CLOSED decision entry")
        if not ok:
            fails.append(node_id)

    print()
    if fails:
        print(f"FAIL: {len(fails)} unlogged deviation(s): {', '.join(fails)}")
        print("An unlogged decision is an open decision. Add an AUTONOMOUS entry")
        print("to .claude/overseer/escalations.md with Status: CLOSED.")
        return 1
    print(f"PASS: {len(deviations)}/{len(deviations)} deviations logged and closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
