"""Run one mutation against the suite, and ALWAYS restore the tree.

WHY this exists as a script rather than an ad-hoc shell loop: on 2026-08-27 an
ad-hoc mutation runner hit a timeout, was killed between applying a mutant and
restoring it, and left `src/decana/twilio/server.py` carrying the mutation. It
was caught only because a checksum had been taken by hand. Unattended, nothing
would have caught it and every later unit would have been built on corrupted
source. The ratified rule is now: any operation that deliberately mutates the
tree restores in a `finally` and VERIFIES the restore before continuing, and a
harness that can die mid-mutation without restoring is not allowed to run.

Three guarantees, each earned by a specific failure:

  1. The mutation is asserted to have APPLIED. A mutation that silently failed
     to apply produces a green run that proves nothing -- the wrong conclusion
     reached from a passing suite (`voice-intake-demo`, Seam 5).
  2. The restore happens in a `finally` AND on SIGTERM/SIGINT, and is verified
     by SHA-256 against the pre-mutation digest. A restore that did not happen
     is a hard error, not a warning.
  3. The pytest run is bounded. A test that waits on a socket close with no
     timeout blocks rather than fails, which is what killed the runner above.
  4. A run that collected NO tests is reported as such, never as a survival.
     Passing `"file -k name"` as one shell argument made pytest look for a path
     that does not exist, collect nothing, and report zero failures -- which this
     script then read as "the mutation survived". That is failure (1) reappearing
     through this script's own interface, so pytest args are now `*argv[4:]`.

Usage:
    uv run python scripts/mutate_check.py <file> <old-file> <new-file> [pytest args...]

`old-file` and `new-file` hold the exact text to replace and its replacement,
read from disk so shell quoting can never corrupt them -- the same quoting that
produced failure (1).
"""

from __future__ import annotations

import hashlib
import signal
import subprocess
import sys
import types
from pathlib import Path

TIMEOUT_S = 120


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restore(target: Path, original: bytes, before: str) -> None:
    """Put the file back and prove it. A failed restore is fatal, never a warning."""
    target.write_bytes(original)
    after = digest(target)
    if after != before:
        raise SystemExit(
            f"FATAL: restore of {target} did not verify.\n"
            f"  expected sha256 {before}\n  got sha256      {after}\n"
            "The working tree is CORRUPTED. Restore from git before continuing."
        )


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2

    target = Path(sys.argv[1])
    old = Path(sys.argv[2]).read_text()
    new = Path(sys.argv[3]).read_text()
    pytest_args = sys.argv[4:] or ["tests"]

    original = target.read_bytes()
    before = digest(target)
    source = original.decode()

    if old not in source:
        print(f"MUTATION DID NOT APPLY: the old text is not present in {target}")
        return 3
    if source.count(old) != 1:
        print(f"MUTATION AMBIGUOUS: old text appears {source.count(old)}x in {target}")
        return 3

    def _on_signal(_signum: int, _frame: types.FrameType | None) -> None:
        restore(target, original, before)
        raise SystemExit("interrupted; tree restored and verified")

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    try:
        target.write_text(source.replace(old, new, 1))
        if digest(target) == before:
            print("MUTATION DID NOT APPLY: file unchanged after write")
            return 3
        print(f"mutation applied to {target}")

        run = subprocess.run(
            [
                "uv",
                "run",
                "pytest",
                *pytest_args,
                "-q",
                "--no-header",
                "--tb=no",
                "-p",
                "no:cacheprovider",
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=False,  # a failing suite is the expected outcome here
        )
        failures = [
            line.split("::")[-1].split()[0]
            for line in run.stdout.splitlines()
            if line.startswith("FAILED")
        ]
        if "no tests ran" in run.stdout or "error" in run.stdout.lower() and not failures:
            print("NO TESTS RAN -- this proves nothing. Check the pytest args.")
            print(run.stdout[-500:])
            return 5
        summary = next(
            (
                ln
                for ln in reversed(run.stdout.splitlines())
                if "passed" in ln or "failed" in ln
            ),
            "?",
        )
        print(f"result: {summary}")
        if failures:
            print("KILLED BY: " + ", ".join(failures))
        else:
            print("SURVIVED: no test failed against this mutation")
        return 0
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT after {TIMEOUT_S}s -- a test hangs under this mutation.")
        print("A hang is a defect in the test, not a survival: bound it and re-run.")
        return 4
    finally:
        restore(target, original, before)
        print("tree restored and verified")


if __name__ == "__main__":
    raise SystemExit(main())
