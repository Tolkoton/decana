# Artifact Scope Decision Tree

You have a piece of knowledge to capture. Which artifact does it belong in? Use this tree. The wrong choice causes duplication (which then drifts) or under-retrieval (the lesson never fires when needed).

## The decision tree

```
Start: I have <observation X> to capture.

Q1. Is X a RULE that Claude should follow automatically going forward?
   YES → CLAUDE.md (one line, positive form, ≤ 200 lines total).
         If the rule is enforceable mechanically → also add a hook / lint rule.
   NO  → Q2

Q2. Is X a DECISION with real alternatives, where someone might re-litigate it later?
   YES → decisions.md (full ADR-lite entry).
         If the decision implies a rule → ALSO add the rule to CLAUDE.md with cross-reference.
   NO  → Q3

Q3. Is X an OBSERVATION about how a library / framework behaves, that would bite in any project using the same tech?
   YES → ~/.claude/memory/<tech>/MEMORY.md
         (Tech-scope, cross-project; pruned rarely; promoted to skill if used ≥3 projects.)
   NO  → Q4

Q4. Is X an OBSERVATION about this specific project's code / domain / external systems?
   YES → .claude/architecture/MEMORY.md
         (Project-scope, prune-able when underlying code changes; never promoted globally.)
   NO  → Q5

Q5. Is X a per-TASK failure note / what-I-tried / hypothesis trail?
   YES → <task>/reflections.md
         (Task-scope, archived at task end; feeds session-end-dreaming.)
   NO  → Q6

Q6. Is X a per-line clarification that the code would otherwise need a comment to explain?
   YES → inline code comment near the relevant line.
   NO  → Q7

Q7. Is X something the user explicitly said to remember?
   YES → ask: rule? decision? observation? Re-run Q1–Q4 with that framing.

Q8. Could X be discarded?
   YES → discard. Most "lessons" are either obvious or one-offs. Discard is the most common correct answer.
   NO  → if you've reached here without a destination, the observation is too vague to capture
         usefully. Sharpen it, or discard.
```

## Same fact, different framings

The same observation can land in different artifacts depending on framing. Example:

> "We discovered that PyJWT's `decode()` raises ExpiredSignatureError instead of returning None on expired tokens."

Possible framings:

| Framing | Lands in |
|---|---|
| "All token-checking code should use try/except, not None checks." | CLAUDE.md (rule) |
| "We chose PyJWT over authlib; this exception behavior was one factor." | decisions.md (decision) |
| "PyJWT's decode() raises rather than returns None — note for any project." | `~/.claude/memory/pyjwt/MEMORY.md` (tech) |
| "In our auth.py, the legacy code expected None and we had to refactor." | `.claude/architecture/MEMORY.md` (project) |
| "During this task I assumed None and burned an hour." | `<task>/reflections.md` (per-task) |
| "Adding `try/except ExpiredSignatureError` here because PyJWT raises, not returns." | inline code comment |

If you can pick more than one, pick the **most general** layer that's still actionable. For the PyJWT case: the tech-scope MEMORY.md is the canonical home (general lesson, cross-project). The inline comment is fine too. CLAUDE.md would be over-reach for a one-library-specific observation.

## When the same fact belongs in MULTIPLE artifacts

Rarely, a fact has both general and specific aspects. Example:

> "We use Decimal for money everywhere because float accumulates error in sums > 100 items."

This is:
- A **rule** (CLAUDE.md: "money is Decimal, never float")
- An **ADR** (decisions.md: "2026-05-14: All money handled as Decimal" with rationale)
- A **tech-scope lesson** (`~/.claude/memory/python/MEMORY.md`: "float accumulates error; use Decimal for money")

Correct response: write the ADR (most detail), the CLAUDE.md line (cross-references the ADR), the tech-scope memory entry (independent, in case a different project hits the same issue). Three pointers to the same insight is fine *as long as they don't drift*. Cross-reference them:

- CLAUDE.md line: "Money is Decimal. See decisions.md 2026-05-14."
- ADR Consequences section: "Tech-scope lesson recorded in ~/.claude/memory/python/MEMORY.md."
- MEMORY.md entry: "Project <name> @<sha> made this decision; see its decisions.md."

If you ever update one, update the others. If that becomes too much work, you've over-replicated — drop the weakest copy.

## Layer comparison

| Layer | Speed of update | Authority | Retrieval |
|---|---|---|---|
| Inline comment | every commit | low (only this line) | when reading this code |
| reflections.md | per failed attempt | low (task-scope) | by session-end-dreaming |
| claude-progress.md | per commit | medium (current task) | at session-start (resume) |
| `.claude/architecture/MEMORY.md` | per session-end | medium (project-wide) | at session-start |
| `~/.claude/memory/<tech>/MEMORY.md` | per session-end | medium (cross-project) | at session-start when tech matches |
| decisions.md | per substantive decision | high (architecture history) | at session-start (recent) + on demand |
| CLAUDE.md | rare, deliberate | highest (always loaded) | every Claude operation |

Reading top to bottom: artifacts get *slower to update* and *more authoritative* the deeper you go. Match the cadence: don't put fast-changing info in CLAUDE.md, don't bury slow-changing rules in reflections.md.

## Red flags that you picked the wrong artifact

- You're updating CLAUDE.md every other commit → it has tactical info, demote to MEMORY or comment.
- You're searching decisions.md for "how do I do X" → that's a CLAUDE.md / skill question, not an ADR question.
- Same lesson appears in 3 reflections.md files across tasks → it should have been promoted to MEMORY ages ago.
- MEMORY.md has rule-shaped statements ("always use X") → these are rules; demote tactical bits to MEMORY, promote rules to CLAUDE.md.
- decisions.md has 30 entries about coding-style preferences → those are conventions; consolidate the rules into CLAUDE.md, mark the ADRs superseded.

## When in doubt

Default order of preference:
1. Discard if it's obvious or one-off.
2. Inline comment if it's per-line.
3. reflections.md if it's per-task failure trail.
4. MEMORY.md (tech or project) if it's an observation.
5. decisions.md if it's a justified choice with alternatives.
6. CLAUDE.md if it's a rule to apply automatically.

Lower layers are cheaper to write and cheaper to wrong-place. Higher layers are more powerful but more expensive to maintain. When unsure, write low and promote later in periodic-maintenance.
