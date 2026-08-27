#!/usr/bin/env python3
"""Commits are legal on unattended/<date> and nowhere else.

Owner-ratified 2026-08-27. The checkpoint is kept where it does work -- nothing
reaches main without a human -- while a long run gets a committed base to build
on, instead of each session working on top of an unreviewed index inherited from
the one before it.

Every case runs against a REAL throwaway git repo with a real branch checked
out, because the hook reads the branch with `git branch --show-current`; faking
it would test the test.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / ".claude/hooks/block-dangerous.sh"


def repo_on(branch: str) -> str:
    root = Path(tempfile.mkdtemp())
    run = lambda *a: subprocess.run(a, cwd=root, capture_output=True, text=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "t")
    (root / "f.txt").write_text("x")
    run("git", "add", "f.txt")
    run("git", "commit", "-qm", "init")
    if branch != "main":
        run("git", "switch", "-qc", branch)
    else:
        run("git", "branch", "-M", "main")
    return str(root)


def blocked(cmd: str, project_dir: str) -> bool:
    r = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"tool_input": {"command": cmd}}),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "CLAUDE_PROJECT_DIR": project_dir},
    )
    return r.returncode == 2


UNATT = repo_on("unattended/2026-08-27")
MAIN = repo_on("main")
FEAT = repo_on("feat/something")

CASES = [
    # (name, command, project_dir, must_block)
    ("commit on unattended/<date>",          "git commit -m x",            UNATT, False),
    ("compound commit on unattended",        "cd . && git commit -m x",    UNATT, False),
    ("commit -C form on unattended",         "git -C . commit -m x",       UNATT, False),
    ("commit on main",                       "git commit -m x",            MAIN,  True),
    ("compound commit on main",              "cd . && git commit -m x",    MAIN,  True),
    ("commit -C form on main",               "git -C . commit -m x",       MAIN,  True),
    ("commit on an ordinary feature branch", "git commit -m x",            FEAT,  True),
    ("push still blocked on main",           "git push origin main",       MAIN,  True),
    ("force-push blocked on unattended too", "git push --force",           UNATT, True),
    ("ordinary staging on main",             "git add .",                  MAIN,  False),
    ("status on unattended",                 "git status",                 UNATT, False),
]

fails = []
for name, cmd, root, must_block in CASES:
    got = blocked(cmd, root)
    ok = got == must_block
    verdict = "BLOCK" if got else "allow"
    print(f"  {'ok  ' if ok else 'FAIL'} {name:40} -> {verdict}")
    if not ok:
        fails.append(f"{name}: expected {'BLOCK' if must_block else 'allow'}, got {verdict}")

print()
if fails:
    print(f"FAIL ({len(fails)}):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print(f"PASS {len(CASES)}/{len(CASES)} commit-policy cases")
