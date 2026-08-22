# Memory Pollution Prevention

Living memory has a fragility: once it gets too big or too noisy, Claude stops following it and you stop reading it. This file enumerates the limits, anti-patterns, and detection signals so the rot stays controlled.

## The fundamental constraint

Anthropic research (effective context engineering, 2025) shows large language models reliably follow **roughly 300 instructions** at a time. CLAUDE.md typically lives entirely in context. So:

- CLAUDE.md should consume no more than ~30% of that budget — call it **≤ 100 substantive rules / ≤ 200 lines**.
- The other 70% is needed for the current task, code, search results, etc.

Beyond that line, additional rules don't increase compliance — they just push earlier rules out of attention.

## Hard limits

| Artifact | Soft limit | Hard limit | What to do when hit |
|---|---|---|---|
| CLAUDE.md | 100 rules / 200 lines | 150 rules / 300 lines | Split into `CLAUDE.md` (always-loaded steering) and `docs/CONVENTIONS.md` (referenced when needed) |
| `~/.claude/memory/<tech>/MEMORY.md` | 30 entries | 50 entries | Split by sub-topic into multiple files in `~/.claude/memory/<tech>/` |
| `.claude/architecture/MEMORY.md` | 30 entries | 50 entries | Aggressive prune in periodic-maintenance; archive old entries |
| `decisions.md` | 50 entries | 100 entries | Add an index section at top; otherwise leave (history is sacred) |
| `claude-progress.md` | 1 screen of "What's left" | 2 screens | Decompose the task; create a separate file per sub-task |
| `.claude/lesson-queue.md` | 10 entries between session-ends | 20 entries | Session-ends are happening too rarely or threshold for queueing is too low |

When you hit a soft limit, **review**. When you hit a hard limit, **act**.

## The anti-patterns

### 1. "While I'm here" bloat

You opened CLAUDE.md to fix one rule, noticed another that could be improved, then added a new tactical fact you remembered. CLAUDE.md grows ~5 lines per edit even though only 1 was needed.

**Detection**: `git log -p CLAUDE.md | wc -l` ÷ number of intentional edits > 5 lines per edit.

**Fix**: every CLAUDE.md edit should have a single justification. Anything else is a separate edit (or skip).

### 2. Decision-theatre

You're capturing every minor choice as an ADR — "use list comprehension here", "use f-string instead of .format()". Six months later there are 200 ADRs, none are findable, and no one reads them.

**Detection**: `decisions.md` grows > 10 entries / month sustainably.

**Fix**: re-run the ADR filters before writing. If you can explain the choice in a single inline comment, it's not an ADR. ADRs are for choices that *need a paragraph* of context.

### 3. Reflection theatre

`reflections.md` files contain entries like "I refactored the function. It worked. I committed it." — no actual reflection, no lesson, just narration.

**Detection**: read 3 random reflections.md entries. If none contains "I expected X but got Y" or "next time I should..." — you're narrating, not reflecting.

**Fix**: every reflection entry must include either (a) what you misunderstood at the start, or (b) what you'll do differently next time. Without one of these, discard.

### 4. Memory junk drawer

`~/.claude/memory/python/MEMORY.md` has 100 entries with no structure, in random order, accumulated over 2 years. You stop searching it because the signal-to-noise ratio is too low.

**Detection**: when stuck, you'd rather search Stack Overflow than your own MEMORY.md.

**Fix**: periodic-maintenance pass 4. Group by sub-topic, consolidate duplicates, split if > 50 entries.

### 5. Stale rule that nobody follows

CLAUDE.md says "always commit migrations separately" but the last 20 commits violate this rule and no one caught it.

**Detection**: spot-check 10 random rules in CLAUDE.md against recent git history. If any rule has been silently violated, it's stale.

**Fix**: either delete the rule (it's not actually a rule) or add enforcement (lint / hook / CI check). Rules without enforcement and without consequences are noise.

### 6. Negative-form overload

CLAUDE.md is full of "Do NOT use X", "Never do Y", "Avoid Z". LLMs process negation poorly — these rules are followed unreliably.

**Detection**: count "NOT", "never", "avoid", "don't" in CLAUDE.md. If > 30% of rules are negative, rewrite.

**Fix**: rewrite as positive. "Do NOT use float for money" → "Use Decimal for money". The rule fires more reliably.

### 7. Conflicting rules

Two CLAUDE.md sections give contradictory guidance, neither author noticing the other rule existed.

**Detection**: ask Claude to scan CLAUDE.md for internal contradictions. Or use `mypy`-style internal consistency check during periodic-maintenance.

**Fix**: resolve the contradiction. Choose one rule. Delete the other or mark it superseded.

### 8. Duplicate fact across layers

The same observation lives in CLAUDE.md, decisions.md, MEMORY.md, AND inline comments. Updating one but not the others causes silent drift.

**Detection**: search for distinctive phrases across all memory files; if the same fact appears in 3+ places, you have a duplication.

**Fix**: identify the *canonical home* (usually the most-specific layer). Make the other layers cross-reference it instead of restating. Per `references/artifact-scope-decision-tree.md`.

### 9. Lesson queue that never empties

`.claude/lesson-queue.md` has 30 entries. session-end-dreaming hasn't run in 3 weeks. None of the lessons have been classified.

**Detection**: `.claude/lesson-queue.md` exists and has > 10 entries.

**Fix**: process the queue NOW (not at next session end). If processing is taking > 20 minutes, do it in two passes (project-scope this session, tech-scope next).

### 10. CLAUDE.md as project documentation

CLAUDE.md is meant to *steer Claude's behavior*, not to *document the project*. When it contains "the project is a billing system for tax advisors" or "we have a customer named X" — that's documentation, not steering.

**Detection**: read each CLAUDE.md line. If it doesn't change what Claude *does*, it's documentation.

**Fix**: move documentation to README.md or `docs/`. Keep CLAUDE.md focused on rules.

## Detection signals — when to prune

Memory needs pruning when ANY of:

- CLAUDE.md > 200 lines.
- Any MEMORY.md file > 50 entries.
- Lesson queue > 10 entries.
- A periodic-maintenance hasn't run in > 3 months.
- You catch yourself re-reading CLAUDE.md but not actually following one of the rules.
- Claude (in your sessions) violates a CLAUDE.md rule and the violation goes unnoticed for a commit.
- decisions.md has any entries with Status: draft older than 1 month.
- `git log --oneline -- CLAUDE.md` shows zero commits in 3 months on an actively developed project.

## Detection signals — when to PROMOTE

Promotion (memory → skill, MEMORY → CLAUDE rule, etc.) is rarer but equally important:

- A specific lesson in MEMORY.md is matched in the stuck-protocol search in ≥ 3 different projects.
- A decisions.md rule has been re-applied in ≥ 5 commits without Claude needing to be told.
- A workflow pattern (e.g., specific kind of test setup) appears in 3+ skills' instructions.
- A lesson-queue topic appears in 3+ sessions in a row.

## Defensive practices

A few practices reduce pollution proactively:

1. **One-line rule.** When adding to CLAUDE.md, the addition must fit in one line. If it needs two lines or a paragraph, it belongs in `docs/` with a one-line CLAUDE.md pointer.

2. **Always cross-reference.** Every CLAUDE.md rule that has a backstory should link to the ADR. Every ADR should link to the implementing commit. Without links, you can't verify the rule is still alive.

3. **Date everything.** Every memory entry has a date. Without a date, you can't see what's stale.

4. **No drafts.** decisions.md entries are either `accepted` or `rejected`. `draft` is allowed for ≤ 1 week. Then resolve.

5. **Re-read trigger.** During periodic-maintenance, force a re-read of CLAUDE.md as if you'd never seen it. Would you still write each rule today? If not, delete.

6. **Hook over text.** If a rule is mechanical (formatting, import order, line length), prefer a hook over a CLAUDE.md line. Hooks don't rot; text does.

## When pollution detection fails

The hardest case: pollution has happened, but nobody noticed because the memory is too big to spot-check. Symptoms:

- Sessions feel slower than they used to.
- Claude makes "obvious" mistakes that CLAUDE.md says not to make.
- You stop trusting MEMORY.md because the entries are too generic to be useful.

When this happens: do an emergency periodic-maintenance pass. Block off 1–2 hours. Don't try to incremental-clean — start from "what would I write if this file were empty?" and prune everything that isn't on that list.

## Summary

The single biggest threat to a working memory system is its own growth. Discipline is at three points:

1. **At write time** — re-run the filters before adding. Most candidates are discards.
2. **At session-end** — process the queue, don't let it accumulate.
3. **At periodic-maintenance** — prune what's stale, consolidate what's scattered, promote what's earned it.

Without all three, the memory layer eventually becomes ignored — and you're back to memoryless Claude with extra steps.
