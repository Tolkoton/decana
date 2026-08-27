#!/usr/bin/env python3
"""Regression harness for .claude/hooks/format-on-edit.sh  (DAG node S3).

WHY THIS EXISTS
---------------
The prior S3 pass could not verify format-on-edit.sh. ``ruff`` is absent on the
authoring machine, so the hook's Python branch no-ops -- and observing that
"nothing bad happened" proves nothing, because a dead hook also does nothing.
That is the residual gap the DAG node was reopened for.

This harness closes it two ways:

1. It exercises a branch that ACTS using tooling that IS installed (the
   ``.json`` built-in, which needs only ``jq``). That proves the whole
   pre-dispatch machinery works end to end: stdin parse -> path extract ->
   project-root resolve -> project.env source -> extension dispatch -> file
   mutation. Everything except the choice of formatter binary is shared with
   the ``.py`` path.
2. For the branches whose tool is genuinely absent (ruff, uv), it puts an
   executable SHIM on PATH that records its argv and appends a marker to the
   file. That proves the hook issues the exact commands it claims to, and that
   the formatter's writes land -- without pretending ruff is installed.

Every case asserts an observable: bytes changed, argv recorded, or bytes
provably unchanged. Negative cases are first class (NEG-*), because for a hook
"it allowed the thing" and "it was dead" produce identical output, so only a
case that pins the *difference* is evidence.

WHY IT LIVES HERE AND NOT UNDER .claude/
    The intended home was .claude/artifacts/spikes/. Every Write under .claude/
    is refused by the harness sensitive-path classifier in an unattended
    session. Moving it back is a one-line git mv once a human can approve.
WHY THE DIRECTORY IS NOT CALLED tests/
    verify-on-stop.sh runs `pytest -x` whenever a `tests/` or `test/` directory
    exists and a .py file changed. pytest is absent here, so creating tests/
    would make the Stop hook fail every turn and block the run. Do not rename
    this directory to tests/ until pytest is a declared dependency.

Run:   python3 hook-checks/test_format_on_edit.py
Exit:  0 = all green, 1 = at least one case failed.

EXPECTED STATE AS OF 2026-08-27: 19 PASS, 3 FAIL.
    The three failures -- NEG-3, EDGE-1 and NEG-6 -- are REAL DEFECTS in
    format-on-edit.sh, not broken cases. They are red on purpose and must stay
    red until the hook is patched. The patches are staged as an appliable diff
    in hook-checks/hooks-s3.patch and written up in HANDOFF-S3.md; they could
    not be applied in the session that found them because every write under
    .claude/ was refused by the harness sensitive-path classifier.
    After `git apply hook-checks/hooks-s3.patch` this must go to 22 PASS / 0 FAIL.

    A note on ACT-7/NEG-6 vs the shims: ACT-2/3/4 use an argv-recording shim,
    which proves which command the hook ISSUES and which branch wins. ACT-7
    uses a real ruff (fetched by uvx) and proves the file actually comes back
    formatted. Both are needed -- and NEG-6 is the case that shows why: a shim
    writes to its log rather than chattering on stdout, so no shim-based case
    could ever have caught the stdout leak. A substitute proves the call, never
    the consequence.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
)
# FOE_HOOK overrides the hook under test. Used to validate a proposed patch
# against a copy before it is applied to the real hook — so a patch is never
# handed over unproven.
HOOK = Path(os.environ.get("FOE_HOOK") or REPO_ROOT / ".claude" / "hooks" / "format-on-edit.sh")
REAL_PROJECT_ENV = REPO_ROOT / ".claude" / "project.env"

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


def new_root(with_real_env: bool = False) -> Path:
    """Fixture root with a PINNED project.env.

    These cases exercise the hook's built-in formatter branch, so they depend on
    FORMAT_CMD being empty. They used to copy the HOST project's real
    project.env, which meant the suite tested whatever the surrounding project
    happened to configure rather than the hook: migrated into a uv project that
    sets FORMAT_CMD, 5 cases failed because the hook correctly took the
    configured branch and never reached the built-in one.

    That is the third instance of one bug today -- a test inheriting ambient
    state instead of pinning it (see test_deny_hooks pinning its git branch).
    A portable suite states its own preconditions.
    """
    root = Path(tempfile.mkdtemp(prefix="foe-"))
    (root / ".claude").mkdir()
    if with_real_env:
        (root / ".claude" / "project.env").write_text(
            'SOURCE_DIRS="src"\n'
            'CODE_EXTENSIONS="py"\n'
            'CHECK_CMDS=""\n'
            'PROJECT_MARKER=""\n'
            'LINT_CMD=""\n'
            'TYPECHECK_CMD=""\n'
            'TEST_CMD=""\n'
            'FORMAT_CMD=""\n',
            encoding="utf-8",
        )
    return root


def run_hook(
    file_path: Path,
    root: Path,
    extra_path: Path | None = None,
    path_override: str | None = None,
) -> subprocess.CompletedProcess:
    """Feed the hook a PostToolUse payload and return the finished process."""
    payload = json.dumps({"tool_input": {"file_path": str(file_path)}})
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    if path_override is not None:
        env["PATH"] = path_override
    elif extra_path is not None:
        env["PATH"] = f"{extra_path}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(HOOK)], input=payload, capture_output=True, text=True, env=env
    )


def make_shim(shim_dir: Path, name: str, log: Path) -> None:
    """A fake formatter: records its argv, and appends a marker to any file arg.

    The marker makes "the hook invoked it" visible in the file itself, not only
    in a log -- so the assertion is about the hook's effect on disk, which is
    what the real formatter would also produce.
    """
    shim_dir.mkdir(parents=True, exist_ok=True)
    p = shim_dir / name
    p.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "{name} $*" >> "{log}"\n'
        'for a in "$@"; do\n'
        f'  if [ -f "$a" ]; then printf "# touched-by-{name}\\n" >> "$a"; fi\n'
        "done\n"
        "exit 0\n"
    )
    p.chmod(0o755)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_env(root: Path, **kv: str) -> None:
    (root / ".claude" / "project.env").write_text(
        "".join(f'{k}="{v}"\n' for k, v in kv.items())
    )


def formatter_script(root: Path, body: str) -> Path:
    """A real, tiny Python 'formatter' used as the FORMAT_CMD target."""
    p = root / "fmt.py"
    p.write_text("import sys\np = sys.argv[1]\n" + body)
    return p


def real_ruff_dir(root: Path) -> Path | None:
    """Put a REAL ruff on PATH via `uvx`, or return None if unavailable.

    The shims above prove the hook issues the right argv. They cannot prove
    what a real formatter does in response -- in particular they cannot show
    what it writes to stdout, because a shim writes only to its log. ACT-7 and
    NEG-6 need genuine ruff behaviour, and `uvx` supplies it without installing
    anything into the project (it resolves into uv's own tool cache).
    """
    if not shutil.which("uvx"):
        return None
    probe = subprocess.run(
        ["uvx", "--quiet", "ruff", "--version"], capture_output=True, text=True
    )
    if probe.returncode != 0:
        return None
    d = root / "realruff"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "ruff"
    p.write_text('#!/usr/bin/env bash\nexec uvx --quiet ruff "$@"\n')
    p.chmod(0o755)
    return d


# Ugly-but-valid Python: bad spacing AND unsorted imports, so `ruff format` and
# `ruff check --fix --select I` each have something distinct to do. That lets a
# single file distinguish which of the two invocations actually landed.
UGLY_PY = 'import sys\nimport os\n\n\n\ndef  f( a,b ):\n    return {  "x":a,   "y":b }\n'


print("format-on-edit.sh regression")
print(f"  hook: {HOOK}")
print(f"  jq:   {shutil.which('jq') or 'ABSENT'}")
print(f"  ruff: {shutil.which('ruff') or 'ABSENT'}")
print()

# ---------------------------------------------------------------------------
# ACT-1  .json built-in, REAL jq. No shim, no simulation.
#        Uses this repo's actual project.env (FORMAT_CMD="", CODE_EXTENSIONS="py")
#        so the configured branch is correctly skipped and the built-in runs.
# ---------------------------------------------------------------------------
print("ACT-1  .json built-in handler, real jq -- the hook is seen to ACT")
r = new_root(with_real_env=True)
target = r / "data.json"
target.write_text('{"b":2,"a":[1,2]}')
before = target.read_text()
run_hook(target, r)
after = target.read_text()
if before != after and '\n  "b": 2' in after:
    ok("hook reformatted the file (one line -> pretty-printed)")
else:
    bad("json built-in should rewrite the file", "pretty-printed JSON", after)
if json.loads(after) == {"b": 2, "a": [1, 2]}:
    ok("content preserved exactly (formatting only, no data change)")
else:
    bad("json content must be unchanged", {"b": 2, "a": [1, 2]}, after)

# ---------------------------------------------------------------------------
# ACT-2  .py built-in branch via a ruff shim -- the branch the prior pass
#        could not reach.
# ---------------------------------------------------------------------------
print("ACT-2  .py built-in branch (ruff shim records argv)")
r = new_root(with_real_env=True)
shims, log = r / "shims", r / "ruff.log"
log.write_text("")
make_shim(shims, "ruff", log)
target = r / "mod.py"
target.write_text("import sys\nx=1\n")
run_hook(target, r, extra_path=shims)
logtext = log.read_text()
if f"ruff format {target}" in logtext:
    ok("invoked: ruff format <file>")
else:
    bad("ruff format must run on the edited file", f"ruff format {target}", logtext or "<empty>")
if f"ruff check --fix --select I {target}" in logtext:
    ok("invoked: ruff check --fix --select I <file>  (import sort)")
else:
    bad("ruff import-sort must run", f"ruff check --fix --select I {target}", logtext or "<empty>")
marks = target.read_text().count("touched-by-ruff")
if marks == 2:
    ok("formatter writes reached the file (2 marks = both invocations)")
else:
    bad("formatter output must land in the file", 2, marks)

# ---------------------------------------------------------------------------
# ACT-3  uv.lock takes precedence over bare ruff (first branch of the case).
# ---------------------------------------------------------------------------
print("ACT-3  uv.lock present -> 'uv run ruff', bare ruff must NOT fire")
r = new_root(with_real_env=True)
(r / "uv.lock").touch()
shims = r / "shims"
uv_log, ruff_log = r / "uv.log", r / "ruff.log"
uv_log.write_text("")
ruff_log.write_text("")
make_shim(shims, "uv", uv_log)
make_shim(shims, "ruff", ruff_log)
target = r / "mod.py"
target.write_text("x=1\n")
run_hook(target, r, extra_path=shims)
if f"uv run ruff format {target}" in uv_log.read_text():
    ok("invoked: uv run ruff format <file>")
else:
    bad("uv.lock must route through 'uv run'", f"uv run ruff format {target}", uv_log.read_text())
if ruff_log.read_text() == "":
    ok("bare ruff NOT invoked (branch precedence is exclusive)")
else:
    bad("bare ruff must not run when uv.lock exists", "", ruff_log.read_text())

# ---------------------------------------------------------------------------
# ACT-4  Configured path: FORMAT_CMD + CODE_EXTENSIONS, real formatter, real
#        mutation, and it must SHORT-CIRCUIT the built-in branch.
# ---------------------------------------------------------------------------
print("ACT-4  configured FORMAT_CMD path ({file} substitution)")
r = new_root()
fmt = formatter_script(r, 's = open(p).read()\nopen(p, "w").write(s.replace("x=1", "x = 1"))\n')
write_env(r, CODE_EXTENSIONS="py", FORMAT_CMD=f"python3 {fmt} {{file}}")
shims, ruff_log = r / "shims", r / "ruff.log"
ruff_log.write_text("")
make_shim(shims, "ruff", ruff_log)
target = r / "mod.py"
target.write_text("x=1\n")
run_hook(target, r, extra_path=shims)
if "x = 1" in target.read_text():
    ok("FORMAT_CMD ran with {file} substituted, and mutated the file")
else:
    bad("FORMAT_CMD must run on a CODE_EXTENSIONS match", "x = 1", target.read_text())
if ruff_log.read_text() == "":
    ok("built-in ruff branch NOT reached (configured path exits first)")
else:
    bad("configured path must short-circuit built-ins", "", ruff_log.read_text())

# ---------------------------------------------------------------------------
# ACT-5  CODE_EXTENSIONS normalisation: ".PY, ts" must still match a .py file.
# ---------------------------------------------------------------------------
print("ACT-5  CODE_EXTENSIONS normalisation (leading dots, case, commas)")
r = new_root()
fmt = formatter_script(r, 'open(p, "a").write("# normalised\\n")\n')
write_env(r, CODE_EXTENSIONS=".PY, ts", FORMAT_CMD=f"python3 {fmt} {{file}}")
target = r / "mod.py"
target.write_text("x=1\n")
run_hook(target, r)
if "# normalised" in target.read_text():
    ok("'.PY, ts' normalised and matched mod.py")
else:
    bad("extension list must tolerate dots/case/commas", "# normalised", target.read_text())

# ---------------------------------------------------------------------------
# ACT-6  Uppercase filename extension also matches a lowercase config.
# ---------------------------------------------------------------------------
print("ACT-6  uppercase file extension matches a lowercase config")
r = new_root()
fmt = formatter_script(r, 'open(p, "a").write("# upper\\n")\n')
write_env(r, CODE_EXTENSIONS="py", FORMAT_CMD=f"python3 {fmt} {{file}}")
target = r / "MOD.PY"
target.write_text("x=1\n")
run_hook(target, r)
if "# upper" in target.read_text():
    ok("MOD.PY matched CODE_EXTENSIONS='py'")
else:
    bad("extension match must be case-insensitive", "# upper", target.read_text())

# ---------------------------------------------------------------------------
# NEG-1  Extension with no handler and no config match -> byte-identical.
# ---------------------------------------------------------------------------
print("NEG-1  unhandled extension is left alone")
r = new_root(with_real_env=True)
target = r / "notes.txt"
target.write_text("ragged   text\n\n\n")
before_sha = sha(target)
run_hook(target, r)
if sha(target) == before_sha:
    ok(".txt untouched (sha256 identical)")
else:
    bad(".txt must not be modified", before_sha, sha(target))

# ---------------------------------------------------------------------------
# NEG-2  Nonexistent path -> exit 0, no file created.
# ---------------------------------------------------------------------------
print("NEG-2  nonexistent path is a clean no-op")
r = new_root()
ghost = r / "ghost.py"
res = run_hook(ghost, r)
if res.returncode == 0 and not ghost.exists():
    ok("exit 0 and no file conjured")
else:
    bad("missing file must no-op", "rc=0, absent", f"rc={res.returncode}, exists={ghost.exists()}")

# ---------------------------------------------------------------------------
# NEG-3  A file with no extension at all -> no dispatch, no crash.
#        (format-on-edit.sh:72-74 has an explicit guard for this: without it,
#        EXT would equal the whole basename and could match a config entry.)
# ---------------------------------------------------------------------------
print("NEG-3  extensionless file does not fall through to a handler")
r = new_root()
fmt = formatter_script(r, 'open(p, "a").write("# WRONG\\n")\n')
write_env(r, CODE_EXTENSIONS="Makefile", FORMAT_CMD=f"python3 {fmt} {{file}}")
target = r / "Makefile"
target.write_text("all:\n\techo hi\n")
before_sha = sha(target)
res = run_hook(target, r)
if res.returncode == 0 and sha(target) == before_sha:
    ok("'Makefile' treated as extensionless even when configured; untouched")
else:
    bad(
        "extensionless file must not dispatch",
        "rc=0, sha unchanged",
        f"rc={res.returncode}, changed={sha(target) != before_sha}",
    )

# ---------------------------------------------------------------------------
# NEG-4  Malformed JSON on stdin -> exit 0. A formatter must never block.
# ---------------------------------------------------------------------------
print("NEG-4  malformed stdin never blocks an edit")
r = new_root()
env = dict(os.environ, CLAUDE_PROJECT_DIR=str(r))
res = subprocess.run(
    ["bash", str(HOOK)], input="not json at all", capture_output=True, text=True, env=env
)
if res.returncode == 0:
    ok("exit 0 on garbage stdin")
else:
    bad("garbage stdin must not block", "rc=0", f"rc={res.returncode}: {res.stderr[:200]}")

# ---------------------------------------------------------------------------
# NEG-5  jq absent -> silent no-op. Pins the degradation explicitly.
#        For THIS hook the `jq ... || echo ""` idiom is benign: it degrades to
#        skipping formatting. In the DENY hooks the same idiom is a hole, which
#        is what the CLAUDE.md warning is about. Asserting it here records the
#        difference instead of leaving both hooks under one blanket caveat.
# ---------------------------------------------------------------------------
print("NEG-5  jq absent -> silent no-op (benign here, unlike the deny hooks)")
r = new_root(with_real_env=True)
target = r / "data.json"
target.write_text('{"b":2,"a":1}')
before_sha = sha(target)
minimal = Path(tempfile.mkdtemp(prefix="nojq-"))
for b in ("bash", "cat", "basename", "echo", "tr", "sed", "mktemp", "mv", "rm",
          "git", "dirname", "grep", "python3"):
    src = shutil.which(b)
    if src:
        os.symlink(src, minimal / b)
res = run_hook(target, r, path_override=str(minimal))
if res.returncode == 0 and sha(target) == before_sha:
    ok("exit 0, file untouched -- degrades to doing nothing, not to doing harm")
else:
    bad(
        "no-jq must degrade silently",
        "rc=0, sha unchanged",
        f"rc={res.returncode}, changed={sha(target) != before_sha}",
    )

# ---------------------------------------------------------------------------
# EDGE-1  Path containing a space, through the CONFIGURED FORMAT_CMD branch.
#         format-on-edit.sh:85-86 substitutes {file} unquoted, then eval's it.
# ---------------------------------------------------------------------------
print("EDGE-1  path with a space through FORMAT_CMD + eval")
r = new_root()
fmt = formatter_script(r, 'open(p, "a").write("# spaced\\n")\n')
write_env(r, CODE_EXTENSIONS="py", FORMAT_CMD=f"python3 {fmt} {{file}}")
target = r / "my file.py"
target.write_text("x=1\n")
run_hook(target, r)
if "# spaced" in target.read_text():
    ok("formatted a path containing a space")
else:
    bad(
        "space in path must survive {file} substitution + eval",
        "# spaced appended",
        target.read_text(),
    )

# ---------------------------------------------------------------------------
# EDGE-2  Same path shape through the BUILT-IN branch, which quotes its arg.
#         If EDGE-1 fails while EDGE-2 passes, the defect is isolated to the
#         eval on line 86 -- that is the point of running both.
# ---------------------------------------------------------------------------
print("EDGE-2  path with a space through the built-in ruff branch")
r = new_root(with_real_env=True)
shims, ruff_log = r / "shims", r / "ruff.log"
ruff_log.write_text("")
make_shim(shims, "ruff", ruff_log)
target = r / "my file.py"
target.write_text("x=1\n")
run_hook(target, r, extra_path=shims)
marks = target.read_text().count("touched-by-ruff")
if marks == 2:
    ok("built-in branch handles a spaced path (arg is quoted)")
else:
    bad("built-in branch must handle spaces", 2, marks)

# ---------------------------------------------------------------------------
# ACT-7  The .py built-in branch driven by a REAL ruff (via uvx), not a shim.
#        ACT-2 proves the hook ISSUES the right commands. This proves the hook
#        ACTS: a real formatter runs and the file is genuinely reformatted.
#        That was the exact residual gap S3 was reopened for, and it is
#        closeable after all -- `ruff` is absent from PATH, but `uvx` can fetch
#        it, which the earlier pass did not try.
# ---------------------------------------------------------------------------
print("ACT-7  .py built-in branch with a REAL ruff (uvx) -- hook seen to ACT")
r = new_root(with_real_env=True)
rr = real_ruff_dir(r)
if rr is None:
    print("  SKIP uvx unavailable -- cannot supply a real ruff")
else:
    target = r / "ugly.py"
    target.write_text(UGLY_PY)
    before_sha = sha(target)
    res = run_hook(target, r, extra_path=rr)
    body = target.read_text()
    if res.returncode == 0 and sha(target) != before_sha:
        ok("real ruff ran and the file was rewritten")
    else:
        bad("real formatter must mutate the file", "sha changed", f"rc={res.returncode}, changed={sha(target) != before_sha}")
    if "def f(a, b):" in body:
        ok("ruff format normalised the signature")
    else:
        bad("ruff format must reformat", "def f(a, b):", body.splitlines()[:6])
    # Import sort is the fingerprint of the SECOND invocation. If only `format`
    # ran, spacing would be fixed but `sys` would still precede `os`.
    first_import = next((ln for ln in body.splitlines() if ln.startswith("import ")), "")
    if first_import == "import os":
        ok("ruff check --fix --select I sorted imports (second invocation landed)")
    else:
        bad("import sort must land", "import os", first_import)

# ---------------------------------------------------------------------------
# NEG-6  The hook must write NOTHING to stdout.
#        stdout is the hook protocol channel: a PostToolUse hook's stdout is
#        surfaced back into the session. The hook's own header says "Silent on
#        success", and it redirects 2>/dev/null -- but NOT stdout, and
#        `ruff format` reports "1 file reformatted" on stdout.
#
#        This case is only meaningful with a REAL formatter. It cannot be
#        written against a shim, because a shim writes to its log file rather
#        than chattering on stdout -- which is precisely why ACT-2 could pass
#        while this defect sat undetected. A machine with no ruff at all also
#        passes it vacuously, so it skips rather than lying.
# ---------------------------------------------------------------------------
print("NEG-6  hook stays silent on stdout even when the formatter chatters")
r = new_root(with_real_env=True)
rr = real_ruff_dir(r)
if rr is None:
    print("  SKIP uvx unavailable -- a shim cannot exercise this")
else:
    target = r / "ugly.py"
    target.write_text(UGLY_PY)
    res = run_hook(target, r, extra_path=rr)
    if res.stdout == "":
        ok("stdout empty (contract in the hook header: 'Silent on success')")
    else:
        bad(
            "formatter output must not leak to the hook's stdout",
            "",
            res.stdout[:200],
        )

print()
print("---------------------------------------------")
print(f"PASS {PASS}   FAIL {FAIL}")
if FAIL:
    print("failed cases:")
    for f in FAILURES:
        print(f"  - {f}")
sys.exit(1 if FAIL else 0)
