---
name: claude-autonomy
description: One-time configuration of Claude Code for autonomous Python work — minimizes permission prompts by writing a generous .claude/settings.json (wide allow-list for routine ops, narrow ask-list for things that touch external/shared state, hard deny for truly destructive ops), installing safety hooks (block dangerous commands, protect secrets/migrations, auto-format on edit, verify on stop), and adding a minimal CLAUDE.md autonomy policy block. Use whenever the user says "configure Claude Code", "set up autonomy", "stop asking permission", "make Claude run without prompts", "I want fewer interruptions", "set up the project for autonomous coding", or is starting a fresh Python repo and wants Claude to just work. This skill ONLY configures — it does NOT do implementation, planning, testing, or review. Commits remain a manual human checkpoint by design.
---

# Claude Autonomy — Configuration Only

This skill configures Claude Code so it runs without constant permission prompts on routine work, while keeping hard guardrails against destructive operations and a manual `git commit` checkpoint. **It does not implement features, write tests, or review code** — that's for other skills.

## Install scope: project vs user

Claude Code reads settings from multiple locations. This skill can install at either:

- **Project scope** (`./.claude/`): applies only to this project. Files live in the repo and can be committed for the team.
- **User scope** (`~/.claude/`): applies to ALL Claude Code sessions for this user. Better default for solo developers who want autonomy everywhere without per-project setup.

Default is project scope. Ask the user which they want if it's ambiguous.

**Tip**: the user scope is what you want if the user complains that Claude prompts when reading other skills' files in `~/.claude/skills/`, or when working across multiple projects.

## What this skill writes

For **project scope**:
```
.claude/
├── settings.json              # Permissions, hooks, env, mode, additionalDirectories
└── hooks/
    ├── block-dangerous.sh     # PreToolUse: block destructive bash
    ├── protect-paths.sh       # PreToolUse: defense-in-depth path deny
    ├── format-on-edit.sh      # PostToolUse: auto-format Python after Edit/Write
    └── verify-on-stop.sh      # Stop: lint + typecheck + tests, REPORT (no commit)
CLAUDE.md                       # Autonomy policy block (appended if file exists)
.gitignore                      # Appends Claude-related entries
```

For **user scope** (only settings + hooks, not project-specific files):
```
~/.claude/
├── settings.json
└── hooks/
    ├── block-dangerous.sh
    ├── protect-paths.sh
    ├── format-on-edit.sh
    └── verify-on-stop.sh
```

Nothing else. No `plans/`, no implementation conventions, no project scaffolding beyond what's needed for autonomous operation.

## additionalDirectories — why it matters

By default Claude Code restricts file access to the current working directory and its subdirectories. Operations against paths outside (like reading `~/.claude/skills/some-other-skill/`) prompt even if the relevant `Bash(ls:*)` is in the allow list — because the limitation is at the **path scope**, not the command pattern.

The template includes a sensible `additionalDirectories` covering:
- `~/.claude/` and subdirectories (skills, agents, commands, output-styles)
- `~/.config/claude/`
- `/tmp/claude/`

This lets Claude read its own skill folders without prompts. If the user works in monorepos or needs access to other directories (e.g., a sibling `../backend/` repo), add them to `additionalDirectories` in the generated `settings.json`.

## The core philosophy

**Allow generously, deny narrowly, ask rarely.**

The previous (overly cautious) shape: lots of "ask" → constant interruption.
The new shape:

- **deny** (hard block, no override in-session): truly destructive ops (rm -rf, force-push, publish, secret reads, migration edits).
- **ask** (prompt for confirmation): things that touch the world outside the repo or change shared state (`git push`, `gh pr create`, `uv add`, schema migrations).
- **allow** (no prompt): everything else routine — reading files, editing source, running tests, fetching docs, normal git operations.

The `defaultMode` is `acceptEdits`, so all file edits to non-protected paths happen without prompts.

## Procedure

### 1. Determine install scope

Ask the user (one of):
- **Project scope** (default for new projects): writes to `./.claude/` in the current directory. Apply when user is in a specific repo and only wants autonomy there.
- **User scope**: writes to `~/.claude/`. Apply when user wants the same autonomy across ALL their projects, or when they're complaining Claude prompts even on skills/files in `~/.claude/`.

If unsure: pick project scope but offer user scope as a follow-up if needed.

### 2. Discover the project (project scope only)

For project-scoped install only, run these checks first:

```bash
test -f pyproject.toml && echo "has pyproject"
test -f uv.lock && echo "uv"
test -f poetry.lock && echo "poetry"
test -d .git && echo "git repo" || echo "WARNING: not a git repo"
test -f CLAUDE.md && echo "CLAUDE.md exists"
test -d .claude && echo ".claude exists"
git branch --show-current 2>/dev/null
```

**If not a git repo**: warn — the manual-commit checkpoint depends on git. Offer `git init`, proceed only after user confirms.

**If `.claude/settings.json` already exists at the target scope**: read it first. ASK before overwriting. Default to MERGE (union allow-lists, intersect ask, union deny). Show the user the diff before writing.

**If `CLAUDE.md` exists**: do not overwrite. Append a clearly-marked autonomy section at the end.

### 3. Render the templates

Based on chosen scope, write files to:

**Project scope**:
- `assets/settings.json.template` → `./.claude/settings.json`
- `assets/CLAUDE.md.template` → `./CLAUDE.md` (append if exists)
- `assets/gitignore.append.template` → append to `./.gitignore`
- `scripts/*.sh` → `./.claude/hooks/*.sh` (chmod +x)

**User scope**:
- `assets/settings.json.template` → `~/.claude/settings.json`
- `scripts/*.sh` → `~/.claude/hooks/*.sh` (chmod +x)
- (Do NOT touch project-level `CLAUDE.md` or `.gitignore` for user-scope install)

### 4. Detect toolchain and patch settings (project scope only)

After writing `settings.json` to project scope, detect the project's toolchain and ADD relevant allow entries if missing. Examples:

- `uv.lock` present → already covered by default template
- `poetry.lock` present → already covered
- `manage.py` present (Django) → add `Bash(uv run python manage.py:*)`, `Bash(poetry run python manage.py:*)`, `Bash(python manage.py:*)` to allow; add `Bash(python manage.py migrate*)`, `Bash(python manage.py makemigrations*)` to ask
- FastAPI in deps → add `Bash(uvicorn:*)`, `Bash(uv run uvicorn:*)` to allow
- `nox` / `tox` in deps → add `Bash(nox:*)`, `Bash(tox:*)` to allow
- `pytest-watch` in deps → add `Bash(ptw:*)` to allow

For user-scope install: skip toolchain detection. The user-level config should be stack-agnostic; per-project specifics go in `./.claude/settings.json` later if needed.

### 5. Verify

```bash
# JSON validity
python3 -c "import json; json.load(open('<dest>/settings.json'))" && echo "valid"

# Hook scripts executable and syntactically sound
ls -la <dest>/hooks/
for f in <dest>/hooks/*.sh; do bash -n "$f" && echo "OK: $f"; done
```

If any check fails: STOP and report — do not present a broken setup.

### 6. Present and stop — TELL THE USER TO RESTART

The most common reason "autonomy doesn't work" after install: Claude Code only reads `settings.json` at session start. Mid-session changes are NOT picked up.

Output explicitly:

```
✓ Configured for autonomous operation (<scope> scope).

Written:
  <dest>/settings.json
  <dest>/hooks/             (4 scripts, executable)
  <CLAUDE.md and .gitignore if project scope>

⚠ IMPORTANT — RESTART CLAUDE CODE
  Settings.json is read at session start. Your current session is still using
  the OLD permissions. To activate the new ones:
    1. Exit Claude Code (Ctrl+C or `/exit`)
    2. Start a new session: `claude`
    3. Then test: ask Claude to 'list files in src/' — should NOT prompt.

Permission shape installed:
  • defaultMode: acceptEdits  → file edits to non-protected paths don't prompt
  • additionalDirectories: ~/.claude/, ~/.config/claude/, /tmp/claude/
  • Allow: routine ops (read/edit/test/lint/typecheck/format/git read-ops/doc fetches)
  • Ask:   git push, gh pr/release, dependency adds, schema migrations
  • Deny:  rm -rf, force-push, publish, secret reads, migrations edits, git commit

Auto-runs:
  • On Edit/Write/MultiEdit:  ruff format + ruff import-sort
  • On Stop (turn end):       ruff check, mypy, pytest — blocks 'done' if any fails
  • Pre Bash:                 dangerous-pattern check
  • Pre Edit/Write:           protected-path check

NOT configured by this skill (intentional):
  • Auto-commit (manual checkpoint by design)
  • Auto-push or PR creation
  • MCP servers (use a separate skill for that)
  • Implementation conventions in CLAUDE.md (your implementation skill adds them)

After restarting, if SOMETHING STILL prompts that shouldn't:
  - Check it's actually in the allow list
  - Note: compound commands like `cmd1 && cmd2` need each part in allow
  - Open <dest>/settings.json and add the command pattern
  - For paths outside project, extend `additionalDirectories`
```

Then STOP. Do not commit. Do not start any implementation.

## What changed vs. a more cautious setup

If you've used a more cautious configuration before, this skill is more permissive in three ways:

1. **WebFetch allowlist is broader** — covers most major Python docs, GitHub, Stack Overflow, and common technical sources. Fewer "may I fetch this URL?" prompts.

2. **Bash allowlist covers more dev tooling** — most pytest/ruff/mypy/coverage flags, common file-reading utils (`rg`, `jq`, `tree`), all read-only git, and the common toolchain wrappers (`uv run`, `poetry run`).

3. **acceptEdits as default mode** — Claude doesn't ask before editing files in non-protected paths. The protected paths (`.env`, `migrations/`, `.git/`, `.github/workflows/`, secrets) are still denied at hook level as defense-in-depth.

If this feels too permissive for a particular project, edit `.claude/settings.json` directly — the file is yours.

## Hard rules of this skill

- **Never enable `--dangerously-skip-permissions` in the generated config.** That's a runtime flag the user can add per-invocation if they want; baking it in removes the safety net entirely.
- **Never put real secrets in any generated file.** Use `${ENV_VAR}` placeholders.
- **Never write a `PostToolUse` or `Stop` hook that runs `git commit`.** Commits are a human checkpoint by design (see `references/permission-philosophy.md` for rationale).
- **Never edit files outside the configured paths** (`.claude/`, `CLAUDE.md`, `.gitignore`). Don't drift into setting up tests, plans, or source layout.
- **Never run `git commit` itself.** Tell the user to commit; don't do it for them.

## Adjusting for your taste

After running this skill, common edits:

- **Even less prompting**: move `Bash(uv add *)`, `Bash(poetry add *)`, `Bash(pip install *)` from `ask` to `allow`. Risk: silently growing dependencies; review your lockfile diff regularly.
- **Even more prompting**: move common operations from `allow` to `ask`. Defeats the purpose of this skill — consider whether you actually want autonomy.
- **Stricter path protection**: extend the deny list in `protect-paths.sh` with project-specific paths.
- **Different formatter**: edit `format-on-edit.sh` to use `black`, `autopep8`, etc.

See references for deeper guidance.

## References

- `references/permission-philosophy.md` — what goes in deny vs ask vs allow, with rationale
- `references/hooks-reference.md` — what each hook does and how to extend it
- `references/auto-mode-and-flags.md` — Auto Mode (v2.1.85+) and per-session flags for even more autonomy
