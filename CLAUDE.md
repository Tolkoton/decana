<!-- ============================================== -->
<!-- ## Autonomy policy (configured by claude-autonomy skill) -->
<!-- This section was added by the claude-autonomy skill.    -->
<!-- It contains only autonomy rules. Your implementation     -->
<!-- skill should add coding conventions in a separate        -->
<!-- section below this one.                                   -->
<!-- ============================================== -->

## Autonomy policy

This project is configured for autonomous Claude Code operation. Follow these rules:

### Commits are a human checkpoint

**Do NOT run `git commit`.** After completing a logical unit of work:
1. Stage relevant files with `git add <files>` (not `git add -A` unless the diff truly is one unit)
2. Run validation: `ruff check`, `mypy`, relevant `pytest` paths
3. Print a one-line summary of what changed and a suggested conventional-commit message
4. STOP and wait for the human to review the diff and run `git commit` themselves

This is enforced by a hook (`block-dangerous.sh`) as defense-in-depth. If you find yourself wanting to commit, you've understood the workflow incorrectly — stage and report instead.

### Operations that require explicit human ask

Do not run these without the human explicitly requesting them in the current turn:
- `git push`, `git rebase`, `git merge`, `git cherry-pick`, `git revert`
- `gh pr create`, `gh pr merge`, `gh release`
- `uv remove`, `poetry add`, `poetry remove`, `pip install`, `pip uninstall`
- `alembic upgrade/downgrade/revision`, `python manage.py migrate/makemigrations`
- `docker push`, `docker run`, `docker compose up`

The settings.json `ask` list will prompt for these — that prompt is the human's signal to think before approving. Don't try to bypass it.

**`uv add` is allowed without a prompt** (owner, 2026-08-27). Adding a dependency is a two-way door: one `uv remove` undoes it, and `pyproject.toml` + `uv.lock` put every add in the staged diff the owner reads before committing — so the review moved from the prompt to the commit, it did not disappear. **`uv remove` stays gated**, because removal is not installation and can break a working tree in ways an add cannot. Rationale and accepted risks: `.claude/overseer/audit.md`, 2026-08-27.

### Operations that are hard-denied

These will fail regardless of any user instruction in-session:
- `rm -rf /`, `rm -rf ~`, similar wildcard destruction
- `git push --force*`, `git reset --hard origin*`, `git filter-branch`, `git clean -fdx`
- Reading or editing `.env`, `secrets/`, SSH/GPG/AWS credentials
- Editing `migrations/`, `alembic/versions/`, `.github/workflows/`
- Publishing (`twine upload`, `uv publish`, `poetry publish`, `npm publish`)
- Piping curl/wget to a shell
- `sudo` anything

If the human asks for one of these, refuse and ask them to run it manually outside Claude Code.

### Operations that are auto-allowed (no prompt)

Routine work happens without prompts:
- Reading and editing non-protected files (the `acceptEdits` default mode)
- Running tests, lint, type-check, format
- Read-only git (`status`, `diff`, `log`, `show`, `blame`)
- `git add`, `git checkout -b`, `git switch`, `git stash`, `git tag`
- Most file utilities (`ls`, `cat`, `grep`, `rg`, `find`, `head`, `tail`, `jq`)
- Web fetches against major Python / framework / docs sites and WebSearch

If you're hesitating "should I ask?" for one of these — don't. The configuration already decided.

### When validation fails on Stop

The Stop hook runs `ruff check`, `mypy`, and `pytest` (only on Python changes). If any fails:
- The hook will block the turn from ending and feed you the failure output
- Read the actual error; don't guess
- Fix with minimal changes
- Re-run until clean
- If stuck after 3 attempts with different fixes — STOP and ask the human; don't invent a 4th approach

### Hooks summary (transparency)

| Hook | When | What it does |
|------|------|--------------|
| `block-dangerous.sh` | Before any Bash | Hard-blocks destructive patterns AND `git commit` |
| `protect-paths.sh` | Before Edit/Write/MultiEdit | Hard-blocks edits to secrets, migrations, `.git/`, workflows |
| `format-on-edit.sh` | After Edit/Write/MultiEdit | Runs `ruff format` + `ruff check --fix --select I` on `.py` files |
| `verify-on-stop.sh` | On turn end | Runs lint/typecheck/tests on changed Python; blocks turn if any fail. **TDD RED gate:** `=== TDD RED ===` alone on its own line in the final message skips the TEST step only — lint and typecheck still run and still block. See below. |
| `overseer_stop.py` | On turn end | On a unit-completion claim (sentinel + `src/` edit + test/lint/type run), injects an `OVERSEER_REQUEST` 12-check audit prompt. See "Overseer protocol" below. |

To inspect a hook: `cat .claude/hooks/<name>`. To temporarily disable: rename to `<name>.disabled` or pass `claude --disable-hooks` flag.

### TDD RED gate (`=== TDD RED ===`)

A strict-TDD RED turn ends on a deliberately failing test. Without a gate, `verify-on-stop.sh` blocks every such turn and forces RED and GREEN to collapse into one — destroying the review checkpoint between writing a test and implementing it.

End a RED turn with `=== TDD RED ===` alone on its own line to skip the test step for that turn.

- **Skips the TEST step ONLY.** `ruff` and `mypy` still run and still block.
- **Does not** suppress the overseer audit hook — separate hook, separate triggers.
- **One turn only.** Re-emit it each RED turn; absence restores full enforcement.
- **Do not emit it on a GREEN, refactor, or question-answering turn** — same discipline as the `=== UNIT N COMPLETE ===` sentinel, and the opposite failure: that one triggers a spurious audit, this one waves through a broken suite.

**Known limit:** nothing verifies that a turn claiming RED actually produced a failing test — the bypass has no counterparty. It rests on honesty, which is an acceptable trade for one skipped step and no others. Before widening the skip to lint, typecheck, or a test subset, build the two-signal trigger (sentinel AND structural tool evidence) that `overseer_stop.py` already uses. Rationale and verification: `.claude/overseer/escalations.md`, 2026-08-25 TOOLING_DECISION. Note both `.claude/hooks/` and `~/.claude/hooks/` copies carry the gate; the latter is outside this repo and invisible to `git diff`.

<!-- ============================================== -->
<!-- End of autonomy policy. Your implementation skill -->
<!-- can add coding conventions, stack details, and    -->
<!-- project-specific guidance below this marker.       -->
<!-- ============================================== -->

@AGENTS.md

- Autonomous continuation: PASS = silent continue; stop only on BLOCK, ESCALATE, or hard-gate boundary. See `.claude/skills/overseer/SKILL.md` § "Autonomous continuation after PASS".
## Overseer protocol

- The Stop hook `.claude/hooks/overseer_stop.py` auto-triggers an overseer
  12-check audit when a turn **claims a unit of work complete** — it does
  **not** run on every turn. It fires only on a two-signal match: the sentinel
  `=== UNIT N COMPLETE ===` alone on its own line in your final message, AND
  structural evidence in the same turn (an `Edit`/`Write`/`MultiEdit` under
  `src/` plus a `pytest`/`ruff`/`mypy` Bash command).
- **Sentinel convention.** End your final message with `=== UNIT N COMPLETE ===`
  alone on its own line ONLY when you finish a genuine unit of work (a slice
  step, a `tasks.yaml` task). `N` is the unit number from the active slice
  contract (`.claude/overseer/slice/<slug>.md`), or `1` if none applies. Do **not**
  emit it on a work-in-progress, RED-only, or question-answering turn — that
  triggers a spurious audit. Full developer-facing rules: the "Unit completion
  protocol" section of `.claude/skills/overseer/SKILL.md`.
- When the hook fires it injects `OVERSEER_REQUEST`. On seeing it, read
  `.claude/skills/overseer/SKILL.md` and apply the full 12-check checklist
  before responding further.
- **Citing overseer check numbers (#1-#12) in your reasoning counts as overseer invocation** — preventive refusals based on checks still require the full output structure from `.claude/skills/overseer/SKILL.md`, including the mandatory `Edit`-tool write to `.claude/overseer/ledger.md` BEFORE your reply.
- **Verdict format.** End the audit turn with exactly one verdict marker on its
  own line: `OVERSEER_PASS` / `OVERSEER_BLOCK: #N <reason>` /
  `OVERSEER_ADR_REQUIRED: <ADR>` / `OVERSEER_ESCALATE: <JSON>`. Emitting any
  `OVERSEER_` marker is also recursion guard 3 — it tells the hook the audit
  already ran, so it will not re-fire on your verdict turn.
- If `OVERSEER_ESCALATE`, surface to user via `AskUserQuestion`. Use options + your_recommendation verbatim. Do not answer the escalation yourself; wait for human's selection.
- If `OVERSEER_BLOCK`, address the specific check before continuing.
- If `OVERSEER_ADR_REQUIRED`, draft the ADR in `docs/adr/` before proceeding with code.
- Always append the entry the skill prescribes to `.claude/overseer/ledger.md`.
- **Recursion safety & override.** The hook has three guards — the
  `stop_hook_active` envelope flag, a SHA-256 idempotency file
  (`.claude/overseer/.last_audit_sha`), and the `OVERSEER_` verdict marker above — and
  a phase guard that skips the audit when `.claude/overseer/state` contains `plan`.
  Kill-switch: rename `.claude/hooks/overseer_stop.py` to `*.disabled`, or
  start Claude Code with `--disable-hooks`. Smoke-test the wiring with
  `python3 .claude/hooks/overseer_stop.py --dry-run` (always emits a block).

## Constitution (load-bearing, human-only)
Every agent must read and obey `.claude/constitution.md`. It overrides any conflicting instruction.
