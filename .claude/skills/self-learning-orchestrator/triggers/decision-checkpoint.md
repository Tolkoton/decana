# Trigger: Decision Checkpoint

A real engineering decision was about to be (or just was) made. Decide whether it warrants an ADR entry, and if so, capture it.

## When this fires

Three signals — any one is enough:

1. **Explicit user phrasing**: "we picked", "going with", "let's use X over Y", "trade-off", "why did we choose".
2. **Self-recognition in your own reasoning**: you just chose between real alternatives (not forced by constraints).
3. **Pre-commit check** (from `triggers/pre-commit-checkpoint.md`) noticed a substantive change without a corresponding ADR.

## Two-step filter

Before writing anything, run the filter. Most "decisions" are not ADRs.

### Filter 1: Was there really a choice?

If the answer was forced by external constraint (only one library available, regulation requires X, existing code already uses Y), this is a **constraint**, not a decision. Record it in CLAUDE.md's "Constraints" section, not in decisions.md. Skip the rest of this trigger.

### Filter 2: Would someone re-litigate this in 6 months?

Imagine yourself or a teammate reading the code in 6 months, thinking "why did we do this when X seems obviously better?" If the answer is yes — write the ADR. If the answer is no (the choice is obvious in retrospect to anyone familiar with the domain) — skip; the code is self-documenting.

A useful heuristic: if you can explain the choice in a single inline comment, do that and skip the ADR. ADRs are for choices that *need a paragraph* of context.

## If both filters pass: write the ADR

Speak the cue phrase aloud so the per-skill activates:

> "This is an ADR-worthy decision; let me apply the ADR-lite format."

This triggers `decisions-log-adr-lite`, which has the full template. If that skill is not installed, use the inline fallback below.

### Inline fallback template

If `decisions-log-adr-lite` is not available, append this directly to `decisions.md` at the project root (create the file if missing):

```markdown
## YYYY-MM-DD: <short title in present tense>

**Status**: accepted

**Context**
<2–4 sentences. What problem are we solving? What constraints / forces are at play?>

**Decision**
<1–3 sentences. Concrete and specific.>

**Why this and not the alternatives**
- <Alt A>: <why ruled out>
- <Alt B>: <why ruled out>
- The chosen option: <why it wins for THIS context>

**Consequences**
- <Positive>
- <Cost we accept>
- <What becomes easier>
- <What becomes harder>

**Links**
- <PR / commit / issue / related ADR>
```

## When this trigger should ALSO update CLAUDE.md

If the decision establishes a **rule** that should apply automatically from now on (e.g., "all money handled as Decimal, never float"), the rule belongs in CLAUDE.md, with a cross-reference to the ADR:

```markdown
# CLAUDE.md
## Conventions
- Money is the `Money` dataclass; never raw Decimal or float. (See decisions.md "2026-05-14: All money handled as Decimal".)
```

Without the rule in CLAUDE.md, the decision lives in `decisions.md` but Claude won't apply it consistently. The ADR is the WHY; the CLAUDE.md line is the WHAT.

## When this trigger should NOT update CLAUDE.md

- The decision is project-specific tactical (e.g., "use PostgreSQL 16 specifically, not 15") — that's a constraint, not a convention.
- The decision is one-off (we're doing X this once, not establishing a pattern).
- The decision is reversible cheaply (no need to bake into the steering doc).

## Show the user, then write

Even after the filters pass, never write `decisions.md` silently. Show the proposed entry. Get confirmation. Then commit it in the **same commit** as the code that implements the decision. Code without ADR loses the why; ADR without code is fantasy.

## Common mistakes to avoid

- **Writing 5 ADRs in one day.** This is decision-theatre. Most of them are tactical implementation choices. Re-run the filters.
- **Writing the ADR before the decision is real.** "We might use X" is not an ADR. Wait until you commit to it.
- **Writing the ADR and forgetting CLAUDE.md.** Then the rule doesn't get applied.
- **Writing the ADR but no cross-reference from the relevant code.** Future code archaeologist won't find it. At least put `# See decisions.md <date>` in the code.
- **Status: draft forever.** Either accept or reject. Drafts are noise.

## What about superseding an old decision?

If today's decision overrides one already in `decisions.md`:

1. Write the new entry as normal.
2. In the old entry, change `Status: accepted` → `Status: superseded by <date of new entry>`.
3. In the new entry's Context, briefly explain what changed.
4. **Do not delete the old entry.** The supersession chain is the history.

## After writing

Return to the task that prompted the decision. The detour was 5–15 minutes; that's the cost. The benefit is months of "wait, why did we do this?" avoided.
