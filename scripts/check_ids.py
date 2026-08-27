"""Diff each slice's ratified behavior ids against its tests, both directions.

WHY a script rather than a snippet pasted into PROGRESS.md: the snippet had to be
escaped for a shell heredoc, a markdown code fence and a regex at once, and it drifted
twice. This is the exit criterion's own property, so the thing that checks it should be
runnable rather than transcribable.

Both directions matter. Missing ids mean a ratified behavior has no test; unratified
ids mean a test drifted in that nobody agreed to. Exits non-zero if either is dirty.

Usage:  uv run python scripts/check_ids.py
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# slice slug -> (test file, id pattern)
SLICES = {
    "twilio-server": ("tests/test_twilio_server.py", r"S\d+\.\w"),
    "analysis": ("tests/test_analysis.py", r"A\d+\.\w"),
}


def main() -> int:
    dirty = False
    for slug, (test_path, pattern) in SLICES.items():
        artifact = REPO_ROOT / ".claude/overseer/slice" / f"{slug}.md"
        tests = REPO_ROOT / test_path
        if not artifact.exists() or not tests.exists():
            print(f"{slug:16} SKIP (artifact or tests missing)")
            continue

        ids = set(re.findall(rf"^\| `({pattern})` \|", artifact.read_text(), re.MULTILINE))
        covered = set(re.findall(rf'"""({pattern})', tests.read_text()))
        missing = sorted(ids - covered)
        unratified = sorted(covered - ids)

        status = "OK  " if not (missing or unratified) else "DIRTY"
        print(f"{slug:16} {status} {len(ids)} ids, {len(covered & ids)} covered")
        if missing:
            print(f"                 MISSING (ratified, no test): {missing}")
        if unratified:
            print(f"                 UNRATIFIED (test, no id):    {unratified}")
        dirty = dirty or bool(missing or unratified)

    return 1 if dirty else 0


if __name__ == "__main__":
    raise SystemExit(main())
