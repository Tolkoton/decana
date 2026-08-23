# Template setup guide

This repo is a reusable Claude Code configuration template. Copy `.claude/` into any
project and follow these steps. The whole setup takes about 15 minutes.

---

## What you get

- **Slice flow**: design (master-architect) → build (slice-builder) → audit (overseer).
- **Memory lifecycle**: self-learning-orchestrator distils lessons across sessions.
- **6 hooks**: block dangerous commands, protect sensitive paths, format on edit,
  verify on stop, auto-approve web fetches, trigger overseer audit on unit completion.
- **Critic agents**: slice-planner-critic, feature-critic, master-critic — adversarial
  review before implementation begins.

---

## Step 1 — Copy the template

```bash
# From the template repo root:
cp -r .claude /path/to/your-project/
cp CLAUDE.md AGENTS.md .gitignore /path/to/your-project/   # starting points — edit all three

# Clean up files that should not be carried over:
find /path/to/your-project/.claude/hooks -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
rm -f /path/to/your-project/.claude/settings.local.json   # local-only, not for other machines
```

Do **not** copy `docs/` — it is template documentation, not project documentation.

---

## Step 2 — Configure `.claude/project.env`

This is the most important step. Open `.claude/project.env` and set the values for
your project's language and toolchain. Every hook reads this file at runtime.

### Full variable reference

| Variable | What it controls | Default when empty |
|---|---|---|
| `SOURCE_DIRS` | Dirs that count as "code" for overseer trigger | Any file matching `CODE_EXTENSIONS` |
| `CODE_EXTENSIONS` | File extensions that are "code files" (space-sep, no dot) | All changed files |
| `CHECK_CMDS` | Verification command names for overseer trigger (space-sep) | Built-in broad set: `pytest ruff mypy npm jest vitest go cargo swift` |
| `PROJECT_MARKER` | File that must exist before verification runs | Always verify |
| `LINT_CMD` | Lint command for verify-on-stop | Python auto-detect (ruff) |
| `TYPECHECK_CMD` | Type-check command for verify-on-stop | Python auto-detect (mypy) |
| `TEST_CMD` | Test command for verify-on-stop | Python auto-detect (pytest -x) |
| `FORMAT_CMD` | Format command for format-on-edit (`{file}` = file path) | Python auto-detect (ruff) |

### Behavior when a variable is not set

- **`SOURCE_DIRS` empty**: any code-file edit triggers the overseer (more permissive).
- **`CODE_EXTENSIONS` empty**: all changed files are treated as code — verification
  always runs, format-on-edit falls through to built-in handlers.
- **`CHECK_CMDS` empty**: the overseer's built-in broad set covers most stacks.
- **`PROJECT_MARKER` empty**: checks always run (don't skip on first clone).
- **`LINT_CMD` / `TYPECHECK_CMD` / `TEST_CMD` all empty**: Python auto-detect path.
  If your `CODE_EXTENSIONS` includes non-Python extensions (e.g. `ts`) but no
  check commands are set, the hook prints a **clear warning** and skips — no silent pass.
- **`FORMAT_CMD` empty**: built-in Python auto-detect (ruff/black) and generic
  handlers (json/md/yaml via prettier) remain active.

### List format: `SOURCE_DIRS`, `CODE_EXTENSIONS`, `CHECK_CMDS`

These three accept space- **or** comma-separated values, with or without
leading dots on extensions — `"ts tsx"`, `"ts,tsx"`, and `".ts,.tsx"` all
parse identically. If a value doesn't parse into anything usable (e.g. it's
just punctuation), every hook prints an explicit warning and falls back to
the "unset" behavior for that variable — it never fails silently.

### Examples by stack

**Python (default, no changes needed if using ruff + mypy + pytest):**
```bash
SOURCE_DIRS="src"
CODE_EXTENSIONS="py"
PROJECT_MARKER="pyproject.toml"
# LINT_CMD / TYPECHECK_CMD / TEST_CMD — leave empty for auto-detect
```

**TypeScript / Node:**
```bash
SOURCE_DIRS="src"
CODE_EXTENSIONS="ts tsx"
PROJECT_MARKER="package.json"
LINT_CMD="npm run lint"
TYPECHECK_CMD="npx tsc --noEmit"
TEST_CMD="npm test"
FORMAT_CMD="npx prettier --write {file}"
```

**Go:**
```bash
SOURCE_DIRS="."
CODE_EXTENSIONS="go"
PROJECT_MARKER="go.mod"
LINT_CMD="golangci-lint run ./..."
TYPECHECK_CMD=""
TEST_CMD="go test ./..."
FORMAT_CMD="gofmt -w {file}"
```

**Monorepo (multiple source roots):**
```bash
SOURCE_DIRS="backend/src frontend/src"
CODE_EXTENSIONS="py ts tsx"
```

---

## Step 3 — Tailor `.claude/settings.json` and copy env overrides (optional)

`.claude/settings.json`'s `ask` list ships with a neutral cross-language default:
git/gh/docker operations, plus the "add/remove a dependency" command for six
package managers (`uv`, `poetry`, `pip`, `pipx`, `npm`, `yarn`, `pnpm`, `cargo`,
`go`, `gem`, `bundle`). You don't have to edit this — unused entries are inert,
they only prompt if you actually run that command. Trim it if you want a
shorter approval list:

| Your stack | Safe to remove from `ask` |
|---|---|
| Python only | `cargo add/remove`, `go get/mod tidy`, `gem install`, `bundle add/remove` |
| JS/TS only | all `uv/poetry/pip/pipx`, `cargo`, `go`, `gem`, `bundle` entries |
| Go only | all `uv/poetry/pip/pipx`, `npm/yarn/pnpm`, `cargo`, `gem/bundle` entries |
| Rust only | all `uv/poetry/pip/pipx`, `npm/yarn/pnpm`, `go`, `gem/bundle` entries |

Also copy the local-machine env override template:

```bash
cp /path/to/your-project/.claude/settings.local.json.example \
   /path/to/your-project/.claude/settings.local.json
```

Open it and keep only the section for your language (e.g. `_python` for
`PYTHONPYCACHEPREFIX`), moving its `env` block up to a real top-level `"env"`
key — the `_python`/`_javascript`/`_rust` wrapper keys are inert labels, not
real settings. Example for a Python project:

```json
{
  "env": {
    "PYTHONPYCACHEPREFIX": ".cache/pycache"
  }
}
```

`settings.local.json` is gitignored — it never leaves this machine.

---

## Step 4 — Write your `CLAUDE.md`

`CLAUDE.md` at the repo root is the standing policy every agent reads. The template
ships with a generic version. Update it with:

- Your project name and one-line purpose.
- Any migration or generated-code paths that should be write-protected — add them
  to `.claude/hooks/protect-paths.sh` under the `PROTECTED` array.
- Anything domain-specific every agent should know by default.

The format is already established — follow the existing structure.

---

## Step 5 — Write your `AGENTS.md`

`AGENTS.md` is loaded via `@AGENTS.md` at the start of every conversation. Minimal:

```markdown
# Agents guide — <project name>

## Project in one sentence
<What the project does.>

## Active agents
- slice-builder (build layer)
- overseer (audit layer)
- self-learning-orchestrator (memory layer)

## Pipeline
Slice flow: master-architect → slice-builder → overseer.
```

---

## Step 6 — Smoke-test the hooks

Run these in the project root to confirm the hooks are wired correctly:

```bash
# 1. Overseer dry-run — must print a BLOCK (that is expected)
python3 .claude/hooks/overseer_stop.py --dry-run <<< '{}'

# 2. Verify-on-stop — exit 0 expected. If you have staged code files it will
#    attempt your LINT_CMD/TEST_CMD; "command not found" is expected when
#    tools aren't installed globally — it means config was read correctly.
echo '{"stop_hook_active":false}' | bash .claude/hooks/verify-on-stop.sh; echo "exit: $?"

# 3. Block-dangerous — must exit non-zero (or print a block decision) for 'git commit'.
#    This tests the hook directly; in a live session `git commit` is also
#    hard-denied in settings.json's permissions.deny before the hook even runs.
echo '{"tool_name":"Bash","tool_input":{"command":"git commit -m test"}}' \
  | bash .claude/hooks/block-dangerous.sh; echo "exit: $?"
```

If hook 1 prints `DRY-RUN: would have blocked`, hooks are wired. Adjust expectations
for hooks 2–3 based on your project state (hook 2 may exit 0 silently if no Python
files are tracked yet).

---

## Step 7 — First session orientation

Start Claude Code in the project root. In the first message, say:

> "New project. Read CLAUDE.md, AGENTS.md, and .claude/README.md. Summarise
> the active agents and what the first thing to do is."

This forces the agent to load the policy and map before doing anything else.

---

## What happens if you skip a step?

| Skipped step | Consequence |
|---|---|
| Step 2 (project.env) | File ships with `SOURCE_DIRS="src"` and `CODE_EXTENSIONS="py"` pre-filled — overseer triggers on `src/` edits, verify-on-stop runs Python auto-detect. Non-Python stacks work if their check commands are in the built-in broad set (`npm jest vitest go cargo swift`); verification silently skips if no `pyproject.toml` found |
| Step 3 (settings.json / settings.local.json) | `ask` list stays broader than necessary (harmless, just extra prompts); no PYTHONPYCACHEPREFIX / CARGO_TARGET_DIR override — build caches may land inside tracked dirs |
| Step 4 (CLAUDE.md) | Agents use the generic template policy — safe but not project-aware |
| Step 5 (AGENTS.md) | Agents lack project context; slice-planner-critic may misfire on scope |
| Step 6 (smoke test) | You discover broken hooks in production, not during setup |
| Step 7 (orientation) | Agent starts with no context; first actions may be off-target |

---

## Directory reference (after setup)

```
.claude/
  project.env     — ← fill this in (Step 2)
  hooks/          — 6 enforcement hooks (wired in settings.json)
  skills/         — vendored skills: overseer, slice-builder, master-architect,
                    feature-architect, self-learning-orchestrator, documentation,
                    claude-autonomy
  agents/         — critic subagents: slice-planner-critic, feature-critic,
                    master-critic, critic-core
  commands/       — project commands: plan-slice, master-architect, feature-architect
  overseer/       — audit ledger, escalations, slice contracts
  architecture/   — design artifacts from master-architect (created on first use)
  artifacts/      — spikes, notes (created on first use)
  premises/       — premise log (created on first use)
  references/     — reference materials for agents (ADR format, C4, etc.)
  README.md       — agentic system map (read this before adding a new agent)
  settings.json   — hook wiring and permissions
  settings.local.json.example — ← copy to settings.local.json, trim to your stack (Step 3)
  constitution.md — load-bearing rules every agent must follow

CLAUDE.md         — standing policy (every agent reads this)
AGENTS.md         — agent roster and project context (loaded via @AGENTS.md)
PROGRESS.md       — slice completion history (created by slice-builder)
```

---

## Keeping the template up to date

The skills in `.claude/skills/` are vendored copies — they do not auto-update.
To pick up improvements from the template repo:

```bash
# Pull the latest template into a temp location
git clone <template-repo-url> /tmp/claude-template

# Diff and selectively copy updated skills
diff -r /tmp/claude-template/.claude/skills .claude/skills

# Copy specific files you want to update
cp /tmp/claude-template/.claude/skills/<name>/SKILL.md .claude/skills/<name>/SKILL.md
```

Treat updates as deliberate decisions — inspect the diff, don't blindly overwrite.
