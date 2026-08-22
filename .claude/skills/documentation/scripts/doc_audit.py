#!/usr/bin/env python3
"""doc_audit.py - check documentation health for a repository.

Stdlib only. Requires Python 3.9+. Run from anywhere inside the repo,
or pass --root <path>.

Checks performed:
  1. AGENTS.md / CLAUDE.md presence and line-count caps.
  2. docs/ Diataxis quadrant coverage (tutorials, how-to, reference, explanation).
  3. Relative Markdown links that point to missing files.
  4. ADR inventory and status.
  5. `make <target>` references in docs whose target does not exist in the Makefile.

Exit code: 0 = no errors, 1 = at least one error. Warnings never fail the run.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ENTRY_LINE_CAP = 200
MANDATORY_QUADRANT = "reference"
NARRATIVE_QUADRANTS = ("tutorials", "how-to", "explanation")
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", ".tox", "__pycache__",
             "build", "dist", ".mypy_cache", ".ruff_cache", "site"}
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
MAKE_RE = re.compile(r"\bmake\s+([a-zA-Z0-9][a-zA-Z0-9_.-]*)")
MAKE_TARGET_RE = re.compile(r"^([a-zA-Z0-9][a-zA-Z0-9_.-]*)\s*:(?!=)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "ftp://", "//")

errors: list[str] = []
warnings: list[str] = []
notes: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def note(msg: str) -> None:
    notes.append(msg)


def find_repo_root(start: Path) -> Path:
    """Walk up from `start` until a .git dir or pyproject.toml is found."""
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").is_file():
            return candidate
    return cur


def iter_markdown(root: Path):
    """Yield every .md file under root, skipping vendored and build dirs."""
    for path in root.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def check_entry_files(root: Path) -> None:
    agents = root / "AGENTS.md"
    claude = root / "CLAUDE.md"

    if not agents.is_file():
        err("AGENTS.md is missing at the repo root.")
    else:
        lines = agents.read_text(encoding="utf-8", errors="replace").splitlines()
        n = len(lines)
        if n > ENTRY_LINE_CAP:
            err(f"AGENTS.md is {n} lines (cap is {ENTRY_LINE_CAP}). "
                "Trim it or split path-scoped rules into nested AGENTS.md files.")
        else:
            note(f"AGENTS.md: {n}/{ENTRY_LINE_CAP} lines.")

    if not claude.is_file():
        warn("CLAUDE.md is missing. Recommended: a one-line file importing "
             "AGENTS.md (`@AGENTS.md`).")
    else:
        text = claude.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        n = len(lines)
        if n > ENTRY_LINE_CAP:
            err(f"CLAUDE.md is {n} lines (cap is {ENTRY_LINE_CAP}).")
        if "@AGENTS.md" not in text:
            warn("CLAUDE.md does not import AGENTS.md. To avoid drift, make it "
                 "`@AGENTS.md` plus any Claude-only overrides.")
        else:
            note(f"CLAUDE.md: {n} lines, imports AGENTS.md.")


def check_diataxis(root: Path) -> None:
    docs = root / "docs"
    if not docs.is_dir():
        warn("No docs/ directory found. Run the bootstrap workflow to create "
             "at minimum docs/reference/ and docs/adr/.")
        return
    if (docs / "index.md").is_file():
        note("docs/index.md present.")
    else:
        note("docs/index.md missing (optional; useful as a map of docs/).")

    ref = docs / MANDATORY_QUADRANT
    if not ref.is_dir():
        warn(f"docs/{MANDATORY_QUADRANT}/ is missing. Reference docs capture "
             "the public surface an agent needs to look up; this is the one "
             "narrative-style folder you want.")
    else:
        n = sum(1 for _ in ref.glob("*.md"))
        note(f"docs/{MANDATORY_QUADRANT}/: {n} page(s).")

    # Narrative quadrants are optional in agent-first mode: inventory only.
    for q in NARRATIVE_QUADRANTS:
        d = docs / q
        if d.is_dir():
            n = sum(1 for _ in d.glob("*.md"))
            suffix = " (empty — consider removing)" if n == 0 else ""
            note(f"docs/{q}/: {n} page(s){suffix}.")


def check_links(root: Path) -> None:
    broken = 0
    for md in iter_markdown(root):
        for lineno, line in enumerate(
                md.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for raw in LINK_RE.findall(line):
                target = raw.strip()
                if " \"" in target:
                    target = target.split(" \"", 1)[0].strip()
                if (not target
                        or target.startswith("#")
                        or target.lower().startswith(EXTERNAL_PREFIXES)):
                    continue
                file_part = target.split("#", 1)[0]
                if not file_part:
                    continue
                resolved = (md.parent / file_part).resolve()
                if not resolved.exists():
                    err(f"{rel(root, md)}:{lineno} - broken link to "
                        f"'{file_part}'.")
                    broken += 1
    if broken == 0:
        note("Relative Markdown links: all resolve.")


def parse_adr_status(text: str) -> str:
    m = re.search(r"(?im)^\s*[-*]?\s*\*{0,2}status\*{0,2}\s*:?\s*(.+)$", text)
    if m:
        return m.group(1).strip().strip("*").strip()
    m = re.search(r"(?im)^#{1,6}\s*status\s*$\n+\s*(.+)$", text)
    if m:
        return m.group(1).strip()
    return "unknown"


def check_adrs(root: Path) -> None:
    adr_dir = None
    for candidate in ("docs/adr", "docs/adrs", "docs/decisions", "adr"):
        d = root / candidate
        if d.is_dir():
            adr_dir = d
            break
    if adr_dir is None:
        warn("No ADR directory found (looked for docs/adr/). Architectural "
             "decisions are not being recorded.")
        return
    adrs = sorted(p for p in adr_dir.glob("*.md") if p.name.lower() != "readme.md")
    if not adrs:
        warn(f"{rel(root, adr_dir)}/ exists but contains no ADRs.")
        return
    note(f"ADRs found in {rel(root, adr_dir)}/: {len(adrs)}")
    for p in adrs:
        status = parse_adr_status(p.read_text(encoding="utf-8", errors="replace"))
        note(f"  {p.name}: {status}")
        if status.lower() == "unknown":
            warn(f"{rel(root, p)} - ADR has no parseable Status line.")


def check_make_targets(root: Path) -> None:
    makefile = root / "Makefile"
    if not makefile.is_file():
        return
    targets = set()
    for line in makefile.read_text(encoding="utf-8", errors="replace").splitlines():
        m = MAKE_TARGET_RE.match(line)
        if m and m.group(1) not in (".PHONY", ".DEFAULT"):
            targets.add(m.group(1))
    for md in iter_markdown(root):
        for lineno, line in enumerate(
                md.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for tgt in MAKE_RE.findall(line):
                if tgt not in targets and tgt not in ("install", "build"):
                    warn(f"{rel(root, md)}:{lineno} - docs reference "
                         f"`make {tgt}` but Makefile has no such target.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit repository documentation.")
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="Repo root (default: detected from cwd).")
    args = parser.parse_args()

    root = find_repo_root(args.root)
    print(f"doc_audit: auditing {root}\n")

    check_entry_files(root)
    check_diataxis(root)
    check_links(root)
    check_adrs(root)
    check_make_targets(root)

    if notes:
        print("INFO")
        for m in notes:
            print(f"  {m}")
        print()
    if warnings:
        print(f"WARNINGS ({len(warnings)})")
        for m in warnings:
            print(f"  WARN  {m}")
        print()
    if errors:
        print(f"ERRORS ({len(errors)})")
        for m in errors:
            print(f"  ERROR {m}")
        print()
        print(f"FAIL - {len(errors)} error(s), {len(warnings)} warning(s).")
        return 1

    print(f"PASS - 0 errors, {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
