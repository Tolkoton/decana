# Trigger: Session Start

The first thing every Claude Code session does. Reading prior learning before any code work is the single largest leverage in the self-learning loop — every later decision benefits from this 30 seconds of context loading.

## When this fires

- First user message in a new Claude Code session.
- First message after `/clear`.
- After a long pause where context might be lost (>1h idle in the same session).
- Whenever the user says "let's continue", "where did we leave off", "resume", "pick up".

## Procedure

Execute in order. Stop and report at the end.

### 1. Read CLAUDE.md

```
Read CLAUDE.md
```

If it does not exist:
- Note that to the user.
- Suggest invoking the `claude-code-project-scaffolding` skill if this is a serious project.
- Continue with reduced context; do not block.

What to extract:
- The stack (Python version, frameworks, package manager).
- Layout conventions.
- Commands for tests/lint/typecheck.
- "No-go zones" (paths/operations to never touch).
- Any project-specific glossary terms.

### 2. Read per-tech memory files

For each tech listed in CLAUDE.md's stack section, attempt:

```
Read ~/.claude/memory/<tech>/MEMORY.md
```

Typical files to look for (depending on the project):
- `~/.claude/memory/python/MEMORY.md`
- `~/.claude/memory/fastapi/MEMORY.md`
- `~/.claude/memory/sqlalchemy/MEMORY.md`
- `~/.claude/memory/pydantic/MEMORY.md`
- `~/.claude/memory/pytest/MEMORY.md`
- `~/.claude/memory/hypothesis/MEMORY.md`
- `~/.claude/memory/<domain>/MEMORY.md` (e.g., `payments` for vendor-API work, `auth` for authentication work)

Missing files are fine — silently skip. The point is to load whatever exists.

### 3. Read project-scoped memory

```
Read .claude/architecture/MEMORY.md
```

Or wherever the project keeps project-scoped lessons (some projects use `docs/lessons.md` instead). Check CLAUDE.md for the canonical path.

### 4. Read decisions log

```
Read decisions.md
```

If long (>50 entries), read the most recent 10 — older decisions are background.

### 5. Check for resume context

```
ls claude-progress.md claude-progress-*.md 2>/dev/null
```

If any progress file exists:
- Read it.
- Pay special attention to the `## Next session: pick up here` block.
- Verify the "Last working state" matches reality:
  ```
  git status
  git log -1 --oneline
  ```
- If they diverge, that is the first thing to investigate, not the listed next-step.

If no progress file exists:
- This is a fresh task. Proceed normally.

### 6. Quick git context (lightweight)

```
git status --short
git log -5 --oneline
git branch --show-current
```

This tells you what was being worked on, what's uncommitted, and what branch you're on. Five seconds of input that contextualizes everything else.

### 7. Briefly report back

Summarize to the user in 3–5 lines:
- "I've loaded CLAUDE.md, <N> tech memory files, decisions.md (last <N> entries), and <claude-progress.md OR fresh task>."
- "Current branch: <branch>. Uncommitted: <yes/no>. Last commit: <sha> <message>."
- "Last task notes say: <one-line from progress.md if relevant>."
- "Ready to proceed. What's next?"

Do not dump the full memory content — the user already knows what's there. Just confirm what you read so they know you're informed.

## What to do if memory is missing

- **No CLAUDE.md**: workable but degraded. Mention this. Offer to invoke `claude-code-project-scaffolding` later.
- **No `~/.claude/memory/`**: workable but degraded. Mention this. Offer to start the structure at session-end.
- **No `decisions.md`**: workable. Mention it. Offer to start one when the first ADR-worthy decision happens.

## What to do if memory disagrees with reality

The most important "session start" failure mode: progress.md says one thing, git says another.

| Disagreement | Action |
|---|---|
| progress.md says "tests passing", `git status` shows uncommitted changes | Run tests, report actual state, ask user how to reconcile |
| progress.md lists files modified that don't appear in git diff | Stash or commit state may have changed; pause and ask |
| Last commit doesn't match progress.md's "Last commit" | Someone committed/reset in between; treat progress.md as stale and investigate |
| MEMORY.md mentions a library that's no longer in pyproject.toml | Note as a memory-maintenance candidate; don't block |

When in doubt, trust git over the memory files. Memory files are descriptive of past intent; git is the source of truth.

## What this trigger does NOT do

- Does not write to memory. This is read-only.
- Does not start any task work — that's the next user message.
- Does not run code or tests beyond `git status / log` for context.
- Does not invoke other skills. Their cue phrases come later as the user's task unfolds.

## Cost vs. benefit

Cost: ~1000–3000 tokens of memory content + 5 git calls. Roughly 30 seconds wall-time.
Benefit: every later decision in the session is informed. The math is overwhelming.
