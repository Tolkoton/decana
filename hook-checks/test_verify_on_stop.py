#!/usr/bin/env python3
"""Regression harness for .claude/hooks/verify-on-stop.sh  (DAG node S3).

WHY THIS EXISTS
---------------
The prior S3 pass checked that the block path emits *valid JSON*. That is
necessary but not sufficient: valid JSON can carry a corrupted payload. This
harness checks the thing that actually matters downstream — whether the failure
text handed back to the model is INTACT.

It is not. Every one of the six capture sites uses::

    eval "$CMD" 2>/tmp/log >/tmp/log

Two redirections to the same path, neither of them ``2>&1``. The shell opens
the file twice, with two independent descriptors, each carrying its own offset
and each truncating. The two streams then overwrite each other from offset 0
instead of interleaving, so whichever stream writes second clobbers the start of
the other. The first line of a lint/type/test failure — where the header and
the file:line live — is exactly what gets destroyed.

That matters because CLAUDE.md instructs the agent to "read the actual error;
don't guess" when this hook blocks. The hook corrupts the actual error first.

WHY IT LIVES HERE AND NOT UNDER .claude/
    Same reason as test_format_on_edit.py: every write under .claude/ is
    refused by the harness sensitive-path classifier in an unattended session.

WHY THE DIRECTORY IS NOT CALLED tests/
    verify-on-stop.sh runs `pytest -x` whenever a tests/ or test/ directory
    exists and a .py file changed. pytest is absent here, so creating tests/
    would make the Stop hook fail every turn.

Run:   python3 hook-checks/test_verify_on_stop.py
Exit:  0 = all green, 1 = at least one case failed.

EXPECTED STATE AS OF 2026-08-27: 4 PASS, 1 FAIL.
    CAP-1 is a REAL DEFECT in verify-on-stop.sh, red on purpose. The patch is
    in HANDOFF.md and could not be applied in the session that found it.
    Set VOS_HOOK=<path> to run against a patched copy; it must go to 5/0.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    ).stdout.strip()
)
# VOS_HOOK overrides the hook under test, so a proposed patch can be validated
# against a copy before it is applied to the real hook.
HOOK = Path(os.environ.get("VOS_HOOK") or REPO_ROOT / ".claude" / "hooks" / "verify-on-stop.sh")

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  ok   {msg}")


def bad(msg: str, expected: object, actual: object) -> None:
    global FAIL
    FAIL += 1
    FAILURES.append(msg)
    print(f"  FAIL {msg}\n         expected: {expected!r}\n         actual:   {actual!r}")


# Distinctive, length-asymmetric streams. stderr is long and stdout is short,
# which is the real-world shape (diagnostics on one, a one-line summary on the
# other) and the shape that makes the clobber visible: the short stream
# overwrites the head of the long one rather than appending after it.
ERR_HEAD = "E001 first-diagnostic-line-THIS-IS-THE-HEADER"
ERR_TAIL = "E002 second-diagnostic-line-still-present"
OUT_LINE = "SUMMARY-1-error"


def new_repo() -> Path:
    """A git repo with a staged .py change, which is what the hook keys on.

    Staged rather than committed: `git commit` is denied by block-dangerous.sh,
    and the hook reads `git diff --name-only --cached` as well as HEAD, so
    staging alone is enough to make a changed .py file visible.
    """
    root = Path(tempfile.mkdtemp(prefix="vos-"))
    (root / ".claude").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    (root / "mod.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "mod.py"], cwd=root, check=True, capture_output=True)
    return root


def write_env(root: Path, **kv: str) -> None:
    (root / ".claude" / "project.env").write_text("".join(f'{k}="{v}"\n' for k, v in kv.items()))


def noisy_checker(root: Path, name: str, rc: int) -> Path:
    """A stand-in lint/test binary: long stderr, short stdout, exit `rc`."""
    p = root / f"{name}.sh"
    p.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n%s\\n" "{ERR_HEAD}" "{ERR_TAIL}" >&2\n'
        f'printf "%s\\n" "{OUT_LINE}"\n'
        f"exit {rc}\n"
    )
    p.chmod(0o755)
    return p


def run_hook(root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"stop_hook_active": False}),
        capture_output=True,
        text=True,
        cwd=root,
        env=env,
    )


print("verify-on-stop.sh regression")
print(f"  hook: {HOOK}")
print()

# ---------------------------------------------------------------------------
# CAP-1  A failing check's diagnostics must survive into the block reason.
# ---------------------------------------------------------------------------
print("CAP-1  failure output is captured INTACT (2>LOG >LOG clobbers it)")
r = new_repo()
chk = noisy_checker(r, "lint", rc=1)
write_env(r, CODE_EXTENSIONS="py", LINT_CMD=f"bash {chk}")
res = run_hook(r)

try:
    payload = json.loads(res.stdout)
except (json.JSONDecodeError, ValueError):
    payload = None

if payload is None or payload.get("decision") != "block":
    bad("a failing check must emit decision:block", "decision=block", res.stdout[:200])
else:
    ok("emits valid JSON with decision:block")
    reason = payload.get("reason", "")
    # The head of stderr is what the short stdout line overwrites.
    if ERR_HEAD in reason:
        ok("first diagnostic line survived intact")
    else:
        bad(
            "stderr head must not be overwritten by stdout",
            f"...{ERR_HEAD}...",
            reason[:300],
        )
    if ERR_TAIL in reason:
        ok("later diagnostic lines present")
    else:
        bad("stderr tail must be present", f"...{ERR_TAIL}...", reason[:300])

# ---------------------------------------------------------------------------
# CAP-2  A passing check must not block. Guards against a patch that turns the
#        capture fix into an always-block.
# ---------------------------------------------------------------------------
print("CAP-2  a passing check does not block")
r = new_repo()
chk = noisy_checker(r, "lint", rc=0)
write_env(r, CODE_EXTENSIONS="py", LINT_CMD=f"bash {chk}")
res = run_hook(r)
if res.returncode == 0 and '"decision":"block"' not in res.stdout:
    ok("exit 0, no block emitted")
else:
    bad("passing check must not block", "rc=0, no block", f"rc={res.returncode}: {res.stdout[:200]}")

# ---------------------------------------------------------------------------
# CAP-3  stop_hook_active short-circuits. Pins existing behaviour so the patch
#        is seen not to disturb it.
# ---------------------------------------------------------------------------
print("CAP-3  stop_hook_active=true short-circuits immediately")
r = new_repo()
chk = noisy_checker(r, "lint", rc=1)
write_env(r, CODE_EXTENSIONS="py", LINT_CMD=f"bash {chk}")
env = dict(os.environ, CLAUDE_PROJECT_DIR=str(r))
res = subprocess.run(
    ["bash", str(HOOK)],
    input=json.dumps({"stop_hook_active": True}),
    capture_output=True,
    text=True,
    cwd=r,
    env=env,
)
if res.returncode == 0 and res.stdout.strip() == "":
    ok("exit 0, silent")
else:
    bad("stop_hook_active must short-circuit", "rc=0, empty", f"rc={res.returncode}: {res.stdout[:200]}")

print()
print("---------------------------------------------")
print(f"PASS {PASS}   FAIL {FAIL}")
if FAILURES:
    print("failed cases:")
    for f in FAILURES:
        print(f"  - {f}")
raise SystemExit(1 if FAIL else 0)
