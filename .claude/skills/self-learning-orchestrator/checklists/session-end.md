# Session-End Quick Checklist

Run before `/clear`, `/bye`, or closing the session. Should take 1–3 minutes if everything has been captured in-flow; longer if there's a backlog.

## The checklist

- [ ] **Quality gates green**: `uv run ruff check .` and `uv run mypy src` and `uv run pytest -q` all pass (or known-failing tests are tagged).
- [ ] **All commits made**: `git status` is clean OR uncommitted state is intentional and documented.
- [ ] **`.claude/lesson-queue.md` is processed**: run `triggers/session-end-dreaming.md` if the queue has any entries.
- [ ] **`claude-progress.md` is up to date**: "Last working state" reflects the actual current state. "Next session: pick up here" tells future-you exactly which file and which function to start with.
- [ ] **Task status**: if the task is complete, mark `Status: completed` in progress.md; otherwise leave as `in-progress` and ensure the next-session instruction is clear.
- [ ] **decisions.md is current**: any ADR-worthy decisions from this session are committed (not pending in your head).
- [ ] **CLAUDE.md is current**: any new conventions established this session are added (or queued for periodic-maintenance review).
- [ ] **Memory commit**: if `.claude/architecture/MEMORY.md` was updated, commit it.

## Quick fail-fast diagnostics

If you're rushing and want a minimum-viable check:

```bash
# All three on one line — should produce no errors
git status -s && cat .claude/lesson-queue.md 2>/dev/null && cat claude-progress.md 2>/dev/null | grep -A1 "Next session"
```

What this tells you:
- `git status -s` → any uncommitted state?
- `lesson-queue.md` content → did you forget to process?
- `claude-progress.md` "Next session" → does it actually say something useful?

If all three pass scrutiny, you're safe to `/clear`.

## Common items to forget

- The `.claude/lesson-queue.md` file with 3+ entries from a debugging session you don't remember.
- An "OK" in your head that a decision was "obvious" but no ADR was written.
- A new convention that was established by exception in one commit but never propagated to CLAUDE.md.
- Memory files that were updated in your `~/.claude/memory/` but not committed to whatever git repo you use to back up `~/.claude/`.

## When to skip the checklist

- The session was purely exploratory (no commits, no code changes).
- < 30 minutes of work and no debugging.
- The user explicitly said "just stop, don't ceremony".

Even then, glance at `.claude/lesson-queue.md` — if it has anything, process it. Discarded lessons are silent losses.
