# Trigger: Pre-Commit Checkpoint

About to commit, or to declare a task "done". This is the densest learning moment in the dev cycle: the diff is in front of you, everything that just happened is fresh, and the cost of writing down what you learned now is much lower than ever again.

## When this fires

Any of:
- User says "ready to commit", "commit this", "let's commit", "review my changes".
- User says "done", "looks good", "are we done", "wrap this up".
- You finished implementing a sub-task and the diff is non-trivial.
- The `Stop` hook fires (Claude finishes a turn that produced a meaningful diff).

## Procedure

This trigger orchestrates *three* concerns in the right order: review, memory updates, then commit.

### Step 1 — Self-review

Speak the cue phrase:

> "Let me run the pre-commit self-review checklist."

This activates the `pre-commit-self-review-checklist` skill, which walks the 8-section checklist (correctness, conventions, types, tests, security, performance, style, commit hygiene). If that skill is not installed, the inline minimum:

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest -q
```

Fix any issues. Do not proceed to Step 2 with red gates.

### Step 2 — Memory checks (the part this trigger adds)

After the diff is clean, ask three quick questions:

**Q1: Did this change establish a new convention?**

If yes — propose adding a line to CLAUDE.md. Show the user the exact text. Wait for confirmation.

Examples of new conventions:
- "All HTTP clients now use httpx instead of requests" → CLAUDE.md line.
- "Tests for handlers go in `tests/handlers/`" → CLAUDE.md line (or layout section).
- "We commit lockfile changes in a separate commit" → CLAUDE.md commit-discipline line.

Examples that look like conventions but aren't:
- "This particular function uses generators" → that's code, not a convention.
- "We use Pydantic v2 in this module" → if it's already a project-wide rule, skip; if it's a new rule, add it.

**Q2: Was there a substantive decision in this change?**

If yes — invoke decision-checkpoint:

> "This change involved a decision worth recording. Let me apply the decision-checkpoint protocol."

This dispatches to `triggers/decision-checkpoint.md` (or to the `decisions-log-adr-lite` skill). The ADR is committed in the **same commit** as the code that implements it.

**Q3: Was there a non-obvious bug found and fixed in this work?**

If yes — append to `.claude/lesson-queue.md`:

```bash
echo "- $(date +%F) | $(git log -1 --format=%h 2>/dev/null || echo pending) | <one-line lesson>" >> .claude/lesson-queue.md
```

Defer the full lesson processing to session-end-dreaming. Do not stop now to write a full MEMORY.md entry — the lesson queue exists exactly to avoid this interruption.

### Step 3 — Update progress file

If a `claude-progress.md` exists for this task:

1. Move items from "What's left" to "Files affected" (mark touched).
2. Update "Last working state": new commit SHA, tests passing, branch position.
3. Refresh "Next session: pick up here" if more work remains.
4. If the task is fully complete, mark `Status: completed` and add a "Result" section with PR link or final commit.

The progress file should always reflect the *current* state after this commit. If you skip this step, the next session start will use stale information.

### Step 4 — Commit

Propose the commit message in conventional-commits format:

```
<type>(<scope>): <short description>

<body — why, not what>

<footer — refs, breaking changes>
```

Show it to the user. Get confirmation. Then commit.

If a decision (Q2) or convention (Q1) was added in this trigger, they go in the **same commit** as the code change. One commit, one logical unit including the memory updates.

If a lesson was queued (Q3), the queue file itself is gitignored — don't commit it. It'll be processed at session-end.

## Sequencing rules

- Self-review BEFORE memory checks: don't propose ADRs for code that doesn't pass quality gates.
- Memory checks BEFORE commit: ADRs and convention lines must be in the same commit as the code.
- Progress file update BEFORE commit message: the file's state should match what's about to be committed.
- Commit AFTER user confirmation. Never auto-commit.

## Skip conditions

If ALL of the following are true, skip everything except the self-review and commit message:
- Diff < 30 LOC.
- Single file changed.
- No new public API.
- No new dependency.
- Obviously a typo / minor fix / version bump.

In that case: just `ruff format` + `pytest -q` + commit. The full checklist is overhead for trivial changes.

## Failure modes

- **Convention added to CLAUDE.md but not to behavior.** You wrote "always use X" but the code still has Y in 5 places. Either fix Y first, or don't add the rule yet.
- **ADR with no code reference.** Someone reading the code later won't know to look in decisions.md. At minimum add `# See decisions.md <date>` near the relevant code.
- **Progress.md left stale.** "Tests passing" written before tests were re-run. Always update progress.md *after* the quality gates pass, not before.
- **Lesson written as memory entry instead of queued.** Premature classification. The queue gives you the benefit of seeing patterns across the session.
- **Commit message describing WHAT not WHY.** "Add function foo" tells future-you nothing. "Add foo because Y was too slow on batch sizes > 1000" is useful.

## After commit

If the queue has lesson candidates:
- Continue with the next task.
- Process the queue at session-end (`triggers/session-end-dreaming.md`).

If this commit completed the task:
- Trigger session-end-dreaming now, even if the session continues with a different task.
- Memory hygiene is per-task, not per-session.

## What this trigger does NOT do

- Does not run `git push`. Push is a separate user action.
- Does not open a PR. That's a separate trigger if you have one.
- Does not write MEMORY.md entries directly. Those go through session-end-dreaming with classification.
- Does not run the full periodic-maintenance review. That's a different cadence.
