# Trigger: Stuck Protocol

You've tried multiple approaches, none have worked, and the next attempt is likely to be more of the same. Stop. Apply this protocol. The cost of stopping for 5 minutes here is much lower than the cost of thrashing for another 30.

## When this fires

Any of:
- You've tried ≥ 3 distinct approaches to the same problem without progress.
- Same test/error has been failing for > 20 minutes despite attempted fixes.
- You've edited the same file ≥ 5 times in succession without converging.
- User said "stuck", "tried everything", "this isn't working", "/stuck".
- Your hypotheses are getting wilder / more speculative.

## The escalation ladder

Apply the steps in order. Stop at the first one that resolves the stuck state.

### Tier 0 — Pause and write down what you know

Often the act of articulating the problem reveals the next step. Open or update `claude-progress.md` (or the task's `reflections.md` if one exists) and write:

```markdown
## Stuck state — <timestamp>

**What I'm trying to do**: <one sentence>
**What I expect to happen**: <one sentence>
**What actually happens**: <verbatim error / unexpected behavior>
**Approaches tried**:
  1. <approach> — result: <what happened>
  2. <approach> — result: <what happened>
  3. <approach> — result: <what happened>
**Current hypothesis**: <what I think is wrong>
**Why I'm not sure**: <what doesn't fit my hypothesis>
```

If writing this exposes that approaches (1)–(3) are all variations of the same hypothesis — you have a hypothesis problem, not an approach problem. Skip to Tier 3.

### Tier 1 — Re-read existing memory

Before generating more hypotheses, check if past-you (or past-Claude) already solved this. Speak the cue phrase aloud:

> "Let me search past chats and memory for similar stuck states."

Then:

```
conversation_search "<symptom keywords from the error>"
```

And:

```
grep -r "<symptom keywords>" ~/.claude/memory/ .claude/architecture/MEMORY.md CLAUDE.md decisions.md 2>/dev/null
```

If you find anything — read it, apply the lesson, re-attempt. If it resolves, **add the symptom keywords to the matched MEMORY entry** so it's more searchable next time.

### Tier 2 — Apply execution-feedback-debugging discipline

Speak the cue phrase to activate the skill:

> "Let me apply the execution-feedback-debugging five-phase loop."

If that skill is not installed, the inline version:
1. **Reproduce**: write the smallest possible script/test that fails the same way. If you can't, the bug is not what you think it is.
2. **Isolate**: bisect. Comment out half the code. Does it still fail? Halve again.
3. **Hypothesize**: write down WHY mechanism, not just WHAT symptom.
4. **Fix minimally**: change only what your mechanism explains.
5. **Verify**: re-run; confirm + check no new breakage.

If after this you're still stuck, your hypothesis is wrong. Go to Tier 3.

### Tier 3 — Re-plan

Often "stuck" means the original approach was wrong from the start. Speak the cue phrase:

> "Let me re-enter plan mode and re-decompose this."

Or hit Shift+Tab twice to enter plan mode explicitly. In plan mode:
- Restate the goal in fresh language.
- Identify what assumptions you made at the start that turned out wrong.
- Propose a different approach entirely. Not a variation — a different shape.
- Show the new plan to the user before executing.

### Tier 4 — Reduce scope

If a different approach also looks hard, the problem may be too large for one task. Apply:

> "Let me invoke feature-architect to decompose this further."

Or inline: identify a smaller sub-problem that, if solved, would unblock you. Solve that, commit it, then re-attempt the original.

### Tier 5 — Ask the user

Not a failure mode. The user has context you don't:
- They know the domain history.
- They know related decisions not yet in `decisions.md`.
- They may know the answer outright.

When asking, be specific:
- Show the verbatim error.
- List the approaches you tried, with one-line results.
- State your current hypothesis and what doesn't fit.
- Ask a *focused* question, not "what should I do?"

## After the stuck state resolves

This is the most important learning moment in the development cycle. The stuck state was a sign that some assumption was wrong; the resolution exposed which assumption. Capture it.

### Lightweight capture (in-flow)

Append to `.claude/lesson-queue.md`:

```
- <date> | <commit-ref> | <one-line lesson — what I misunderstood and what's actually true>
```

This will be processed at session-end. Do not interrupt flow now.

### Heavyweight capture (if the lesson is big)

If the lesson is large enough that you'd want to skip Tiers 0–4 next time:

- **Project-specific lesson** → add a one-line "Gotcha" to CLAUDE.md.
- **Tech-specific lesson** → process via `triggers/session-end-dreaming.md` immediately (don't wait).
- **Architectural mistake** → write an ADR with `Status: rejected` documenting what NOT to do.

## Anti-patterns when stuck

- **Wider hypothesis space.** When stuck, try NARROWER hypotheses, not wider. The bug is usually one specific thing, not "maybe one of these 10 things."
- **More retries with no change.** Retrying without changing the approach is not debugging.
- **Wallpaper fixes.** Adding try/except, sleeping, retrying — these silence symptoms. They are not Tier 2 fixes; they are Tier "give up and lie to ourselves."
- **Pivot to easier task.** Tempting but corrosive — the stuck state will recur on the next hard task. Resolve it now or escalate to user.
- **Reading the codebase top-to-bottom.** Stuck-state navigation should be targeted (Grep by symptom keywords), not exhaustive.

## What this trigger writes

- `claude-progress.md` (or `reflections.md`) — the Tier 0 stuck-state writeup. Always.
- `.claude/lesson-queue.md` — the post-resolution lesson, one-liner. Almost always.
- Maybe CLAUDE.md or a rejected-status ADR — only for big lessons.
- Maybe an update to an existing MEMORY.md entry to add the symptom keywords you wished were there when you searched in Tier 1.

## When NOT to escalate

If you've been stuck for < 15 minutes and have only tried one approach — keep going. The protocol is for genuinely stuck states, not the normal try-fail-try-success rhythm of any non-trivial task.
