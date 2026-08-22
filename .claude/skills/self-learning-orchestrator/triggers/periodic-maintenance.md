# Trigger: Periodic Maintenance

Memory files rot. Without periodic review they grow to the point Claude ignores them. This trigger is the gardening pass — prune what's stale, consolidate what's scattered, promote what's earned promotion.

## When this fires

- User says "/memory-maintenance", "review memory", "clean up CLAUDE.md", "prune decisions".
- Calendar reminder (recommended cadence: weekly for active projects, monthly for slow projects, every 3 months minimum).
- Before a major project milestone (release, end of quarter, project handoff).
- When CLAUDE.md exceeds 200 lines or any MEMORY.md exceeds 50 entries (signal to consolidate).
- When `git log --oneline -- CLAUDE.md decisions.md` shows no changes in > 3 months — possibly stale.

## Cost

15–45 minutes depending on memory volume and how long since last maintenance. This is real work; budget it as such. Don't squeeze it in at the end of an exhausting session.

## Procedure (5-pass review)

### Pass 1 — CLAUDE.md audit

Read CLAUDE.md in full. For each line/section, ask:

| Question | Action if YES |
|---|---|
| Has this been violated by recent code without anyone noticing? | Either the rule is wrong (delete) or enforcement is missing (add a hook / lint rule) |
| Does Claude already do this correctly without being told? | Delete the line |
| Is this rule contradicted by another rule in the file? | Resolve the contradiction |
| Is this >3 months old and never referenced in any reflections/lessons? | Probably dead; delete |
| Is this a tactical fact rather than a rule? (e.g., "the auth service is at port 8001") | Move to README or service docs, not steering |
| Is the wording negative ("Do NOT use X") when it could be positive ("Use Y")? | Rewrite positive — LLMs handle positives better |
| Is the section now > 30 lines? | Split: put detail in a `docs/` file, keep the one-line rule in CLAUDE.md with a reference |

Target: CLAUDE.md ≤ 200 lines. Per Anthropic research, models reliably follow ~300 instructions; CLAUDE.md should not consume more than ~30% of that budget.

After the pass, show the user the proposed diff. Get confirmation. Commit with `chore(docs): prune CLAUDE.md`.

### Pass 2 — decisions.md audit

Read decisions.md. For each entry:

| Question | Action |
|---|---|
| Has this decision been silently reversed in the code? | Add a new entry that supersedes it, with explanation. Mark the old one as superseded. |
| Is the Context now stale (refers to a library or version that no longer applies)? | Add a footnote: "Note <date>: Context refers to <old state>; current state is <new state>." Do NOT rewrite the original Context. |
| Is the Status still `draft` after >1 month? | Either accept or reject. Drafts are noise. |
| Does any entry have no link to code? | Add a `<see commit X>` link if findable; otherwise add a `# See decisions.md <date>` comment in the relevant code. |
| Are there clusters of related entries (e.g., 5 entries about auth)? | Consider adding an index section at the top of decisions.md grouping them. |

Do NOT delete old entries. The supersession chain is the history; deletion is lossy.

### Pass 3 — Project memory (`.claude/architecture/MEMORY.md`)

This file accumulates project-specific lessons. Apply harsher pruning than tech memory because project memory is less likely to bite again once the underlying code has changed:

| Question | Action |
|---|---|
| Is the entry's "Source" commit/code now deleted or heavily refactored? | The lesson likely no longer applies; delete or archive. |
| Is the same observation made in 2+ entries? | Consolidate into one. |
| Is the entry generic enough to belong in `~/.claude/memory/<tech>/` instead? | Move it. (Promotion path.) |
| Is the entry > 1 year old and not referenced since? | Archive to `.claude/architecture/MEMORY-archive-<year>.md`. |

After pruning, group remaining entries by topic if there are >20 of them. Topic headers improve search.

### Pass 4 — Per-tech memory (`~/.claude/memory/<tech>/MEMORY.md`)

This is the most precious memory layer — it survives across all projects. Prune carefully but consolidate aggressively:

| Question | Action |
|---|---|
| Are there 3+ entries about the same quirk in slightly different words? | Consolidate into one canonical entry with all symptom keywords. |
| Is the entry about a library version that's no longer in use anywhere? | Note "applies to vN.x" in the entry. Don't delete — the version might come back. |
| Has any entry been useful (referenced during stuck-protocol search) ≥ 3 times across projects? | Candidate for promotion to a Skill. See `references/promotion-paths.md`. |
| Are entries chronological with no structure? | Group by sub-topic within the file (e.g., for python: "stdlib quirks", "typing", "asyncio gotchas"). |

After this pass, decide for each tech memory file: is it under 50 entries? Good. Over 50? Decide between (a) split into multiple `~/.claude/memory/<tech>/<subtopic>.md` files or (b) aggressive consolidation.

### Pass 5 — Promotion check

Look across all memory layers for promotion candidates:

| Candidate | Promote to | Criterion |
|---|---|---|
| MEMORY.md entry referenced in ≥3 projects' stuck-protocol searches | New `~/.claude/skills/<name>/` skill | Pattern is general and recurring |
| `decisions.md` rule consistently applied across multiple tasks | CLAUDE.md convention | Should be automatic, not re-derived |
| `claude-progress.md` template variation used in 5+ tasks | New version of the `progress-file-for-long-tasks` skill | Workflow innovation |
| Reflection that recurs in ≥3 task reflections.md | MEMORY.md tech-scope entry | Was tech-scope all along |

Promotion is rare — most reviews produce 0–2 promotions. The act of looking is what matters; finding none is a successful review.

## Report format

At the end, give the user a summary:

```
Memory maintenance complete — <date>

CLAUDE.md:
  - was <N> lines, now <M> lines
  - deleted: <count> rules (now obvious, contradicted, or stale)
  - rewrote: <count> rules (clearer wording / positive form)
  - added: <count> rules (promoted from MEMORY)

decisions.md:
  - <N> entries reviewed
  - marked superseded: <count>
  - drafts resolved: <count>
  - added missing code links: <count>

.claude/architecture/MEMORY.md:
  - was <N> entries, now <M> entries
  - consolidated: <count>
  - archived: <count>
  - moved to tech-scope: <count>

~/.claude/memory/ (per-tech):
  - <tech>: <N> → <M> entries
  - <tech>: <N> → <M> entries
  ...

Promotions:
  - <list, or "none">

Next maintenance recommended: <date + 1 week / 1 month>
```

Commit each affected layer as a separate commit:
- `chore(claude-md): prune to <N> lines`
- `chore(decisions): mark superseded, add missing links`
- `chore(memory): consolidate and archive`

## Failure modes

- **"Just one more entry."** Resist. The point is to subtract, not add. Adding goes through session-end-dreaming, not maintenance.
- **Rewriting old ADRs.** Don't. Add notes, mark superseded, write new entries. Never edit the original Context/Decision text.
- **Promoting too eagerly.** Wait until 3+ uses across projects. A skill is heavyweight; not every pattern earns one.
- **Skipping when memory feels small.** Even 10-entry memory files benefit from a 5-minute review every few months. The cost of "is anything stale?" is small.
- **Maintenance during a stuck task.** Don't context-switch into maintenance to escape a stuck task. That's procrastination disguised as productivity. Solve the stuck task or escalate, then maintain later.

## What this trigger does NOT do

- Does not add new lessons — that's session-end-dreaming.
- Does not capture new decisions — that's decision-checkpoint.
- Does not touch active progress.md files — they're task-scoped, not memory.
- Does not run a full architecture review — that's a separate master-architect concern.

## Calendar discipline

Recommended: schedule periodic-maintenance as a recurring 30-minute slot. Friday afternoon works well — diff is fresh, week's work is reflected in lessons, weekend buffer for follow-up. Without a calendar slot, this trigger rarely fires; with one, it happens automatically.
