#!/usr/bin/env python3
"""Flag hunks that plausibly WEAKEN something, in a patch proposed by a session.

Why this exists
---------------
Session S3 found four real defects, proved them against copies, and staged a
patch. One hunk in that patch was a regression:

    - PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
    + PROJECT_ROOT=$(git rev-parse --show-toplevel >/dev/null 2>&1 || true)

In a command substitution stdout IS the value, so the "fix" silently emptied the
variable and the hook fell back to the wrong directory. It was caught by a human
reading the diff. Unattended it would have been applied blind, and every test in
the suite would still have passed, because no test covered project-root
detection.

That is the shape of the danger: a session's patch is proven against its own
tests, not against intent. This linter does not judge intent. It flags the small
set of textual transformations that are almost always a weakening, so a human --
or a blind critic -- looks at those hunks specifically.

It is a screen, not a proof. Exit 1 means "these hunks need eyes", not "wrong".

Usage:
  python3 hook-checks/lint_patch.py <patch-file> [...]
"""
import re
import sys
from pathlib import Path

# (severity, name, pattern applied to an added line, why it matters)
#
# CRITICAL is reserved for transformations that are wrong essentially always, so
# the gate can fail on them. Everything else is REVIEW: printed for a human, but
# not a blocker, because a formatter legitimately discards its own output and a
# legitimate `|| true` exists on every best-effort line. A gate that fires on
# twenty hunks when one matters trains people to ignore it.
SUSPICIOUS = [
    (
        "CRITICAL",
        "command substitution with stdout discarded",
        re.compile(r"=\s*[\"']?\$\([^)]*>\s*/dev/null"),
        "in $(...) stdout is the VALUE; redirecting it away empties the variable",
    ),
    (
        "REVIEW",
        "stderr-only redirect changed to discard-both",
        re.compile(r">\s*/dev/null\s+2>&1"),
        "2>/dev/null keeps stdout; >/dev/null 2>&1 throws it away - check which was meant",
    ),
    (
        "REVIEW",
        "failure suppressed with || true",
        re.compile(r"\|\|\s*true\s*$"),
        "a check that cannot fail is not a check",
    ),
    (
        "REVIEW",
        "exit code forced to success",
        re.compile(r"\bexit\s+0\b"),
        "verify this is not short-circuiting a guard that should block",
    ),
    (
        "CRITICAL",
        "guard turned into a comment",
        re.compile(r"^\s*#.*\b(exit\s+2|_emit_block|BLOCKED|return\s+1)\b"),
        "a guard commented out still reads like it is there",
    ),
]

# Removed lines that look like a protection being taken away.
REMOVAL_SUSPICIOUS = [
    (
        "CRITICAL",
        "deny pattern removed",
        re.compile(r"^\s*'.*(chmod|push --force|publish|filter-branch).*'\s*$"),
        "a pattern leaving a deny list is a hole unless something replaces it",
    ),
    (
        "CRITICAL",
        "guard clause removed",
        re.compile(r"\b(exit\s+2|_emit_block|BLOCKED)\b"),
        "removing a block path is how a hook silently becomes a no-op",
    ),
]


def lint(path: Path) -> list[tuple[str, str]]:
    """Return (severity, rendered finding) pairs."""
    findings = []
    current_file = "?"
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if raw.startswith("+++ "):
            current_file = raw[4:].strip()
            continue
        if raw.startswith("---") or raw.startswith("@@"):
            continue

        if raw.startswith("+"):
            body, rules, sign = raw[1:], SUSPICIOUS, "+"
        elif raw.startswith("-"):
            body, rules, sign = raw[1:], REMOVAL_SUSPICIOUS, "-"
        else:
            continue

        for severity, name, rx, why in rules:
            if rx.search(body):
                findings.append((
                    severity,
                    f"{path.name}:{lineno} [{current_file}] {name}\n"
                    f"      {sign} {body.strip()[:100]}\n"
                    f"      why: {why}",
                ))
    return findings


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    critical, review = [], []
    for arg in argv[1:]:
        p = Path(arg)
        if not p.is_file():
            print(f"no such patch: {arg}", file=sys.stderr)
            return 2
        for severity, text in lint(p):
            (critical if severity == "CRITICAL" else review).append(text)

    if critical:
        print(f"=== CRITICAL — {len(critical)} hunk(s), do not apply unreviewed ===")
        for f in critical:
            print("  " + f)
        print()
    if review:
        print(f"=== REVIEW — {len(review)} hunk(s), informational ===")
        for f in review:
            print("  " + f)
        print()

    if critical:
        print(f"{len(critical)} CRITICAL, {len(review)} review-level.")
        print("A flagged hunk may still be correct: this is a screen, not a verdict.")
        return 1
    print(f"no critical hunks ({len(review)} review-level note(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
