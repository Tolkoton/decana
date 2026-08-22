# Hooks reference

Four hooks ship with this skill. Each lives in `.claude/hooks/<name>.sh`. They're ordinary bash scripts you own — read and modify them freely.

## `block-dangerous.sh` — PreToolUse for Bash

**When**: before every Bash tool call.
**Purpose**: hard-block destructive patterns and `git commit` regardless of settings.json.
**Exit semantics**:
- `exit 2`: blocks the tool call; the stderr message is shown to Claude so it knows why.
- `exit 0`: allows the call.

**What it blocks**:
- Wildcard `rm -rf` shapes that could destroy data outside the project
- Force-push, hard-reset to origin, filter-branch, `git clean -fdx`
- Direct `git commit` (defense-in-depth for manual-commit policy)
- Direct `git commit/push` on `main`/`master`/`production`/`release` branches
- `sudo`, `mkfs`, raw `dd` to disk devices, `shred`, `wipefs`
- `chmod 777` (open-to-everyone permissions)
- Piping `curl | sh` (network code execution)
- Publishing operations (`twine upload`, `uv publish`, `poetry publish`, `npm publish`)

**To extend**: edit the `DANGEROUS_PATTERNS` array. Patterns are regex; test with `grep -E` semantics.

**To weaken** (e.g., allow `git commit` because you genuinely want auto-commit elsewhere): remove the `git commit` block at the bottom. Also remove `Bash(git commit:*)` from settings.json `ask` and add to `allow`. This skill discourages this; commits-as-checkpoint is the workflow it's designed for.

## `protect-paths.sh` — PreToolUse for Edit/Write/MultiEdit

**When**: before any Edit/Write/MultiEdit tool call.
**Purpose**: deny edits to paths that should never be modified by Claude even if settings.json glob misses.
**Output format**: emits JSON with `permissionDecision: "deny"` and a `permissionDecisionReason` shown to Claude.

**What it blocks**:
- `.env`, `.env.*`, anything matching environment files
- `secrets/`, `.ssh/`, `.aws/`, `.gnupg/`, `.npmrc`, `.pypirc`
- SSH keys (`id_rsa`, `id_ed25519`, with or without `.pub`)
- Crypto material (`.pem`, `.key`, `.p12`, `.pfx`)
- Cloud creds (`credentials.json`, `service-account*.json`, `gcloud-key.json`)
- `migrations/*.py`, `alembic/versions/*.py`, `alembic.ini`
- `.github/workflows/`
- `.git/` internals

**To extend**: edit the `PROTECTED_PATTERNS` array. Patterns are regex against the full file path.

**False positives**: if you have a file legitimately named `foo.key` that isn't a key, either rename it (best) or remove that pattern.

## `format-on-edit.sh` — PostToolUse for Edit/Write/MultiEdit

**When**: after every successful Edit/Write/MultiEdit.
**Purpose**: auto-format the just-edited file so diffs stay clean and lint failures don't accumulate.
**Never blocks**: if the formatter fails or isn't installed, the hook silently exits. Better an unformatted file than a halted Claude session.

**What it formats**:
- `.py`: `ruff format` + `ruff check --fix --select I` (import sorting). Falls back to `black` if ruff isn't installed.
- `.json`: pretty-prints via `jq` (only if jq is on PATH).
- `.md`, `.yml`, `.yaml`, `.toml`: `prettier --write` (only if prettier is on PATH).

**To extend**: add a new `case` branch for your file type. Keep it idempotent and fast (<1s typically).

**To disable for a session**: rename to `format-on-edit.sh.disabled`. Or pass `claude --disable-hooks PostToolUse`.

## `verify-on-stop.sh` — Stop hook

**When**: when Claude declares the turn done.
**Purpose**: run lint, type-check, and tests on the project. If anything fails, the turn doesn't actually end — Claude continues with the failure output.
**Critically**: does NOT commit. The hook prints a "ready for review, run `git add` then `git commit`" message and exits.

**Logic**:
1. If `stop_hook_active` is true (recursive call), exit silently to avoid loops.
2. If no Python files have changed since HEAD, exit silently — no need to lint markdown changes.
3. Run `ruff check .` (if `[tool.ruff*]` in pyproject); on failure, block with output.
4. Run `mypy .` (if `[tool.mypy*]` in pyproject); on failure, block with output.
5. Run `pytest -x --no-header -q` (if `tests/` or `test/` exists); on failure, block with output.
6. If all pass, print a success line and exit 0.

**Output on failure**: emits JSON `{"decision":"block","reason":"<error output>"}`. Claude reads the reason and continues to fix.

**To make faster**:
- Skip pytest on every Stop: comment out section 3.
- Only run pytest if a test file changed: add a filter on `$CHANGED`.
- Use `pytest --picked` (with `pytest-picked` installed) to only run tests for changed code.

**To make stricter**:
- Add `bandit`, `pylint`, `safety check` as further sections.
- Run full pytest (not `-x`) so all failures are reported, not just the first.

**To disable**: rename to `verify-on-stop.sh.disabled` or pass `claude --disable-hooks Stop`.

## `SessionStart` (defined in settings.json, not a separate script)

The settings.json includes an inline `SessionStart` hook that prints `git status`, recent commits, and current branch when a session starts. This gives Claude immediate orientation.

To customize: edit the command in `.claude/settings.json` under `hooks.SessionStart[0].hooks[0].command`. Common additions: print the active feature branch's diff against main, print the latest CI status, print the open issue count.

Keep it short (<1KB output). It eats context.

## Hook performance

Hooks run synchronously and block Claude's turn. Budget roughly:

- PreToolUse: <100ms ideal. The block-dangerous and protect-paths hooks shipped here are <50ms each.
- PostToolUse: <2s ideal. ruff format is ~200-500ms.
- Stop: <10s ideal for fast-feedback. Pytest dominates this — if your test suite is 30s+, consider running only a fast subset in the hook.
- SessionStart: <500ms. Don't do heavy work here.

If a hook takes longer than ~5s consistently, Claude's turn time visibly suffers.

## Audit / debug hooks

To see what hooks are firing, add this to any of them at the top:

```bash
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $(basename "$0"): cmd=$CMD" >> "${CLAUDE_PROJECT_DIR:-.}/.claude/audit.log"
```

The `audit.log` is in `.gitignore` by default.

To trace WHY a hook fired (or didn't), run Claude with `--debug` and inspect the hook input/output in the verbose log.

## Disabling hooks per session

For a single session, you can disable specific hook events:

```bash
claude --disable-hooks PreToolUse,PostToolUse
claude --disable-hooks Stop
```

Or override the whole settings.json with a local file:

```bash
cp .claude/settings.json .claude/settings.local.json
# Edit .local to remove hooks section
```

`.claude/settings.local.json` is gitignored and takes precedence over `settings.json`.
