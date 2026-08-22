# Promotion Paths

Memory layers form a hierarchy. As knowledge proves itself useful, it can be **promoted** to a more permanent / higher-authority home. Promotion is rare but high-value — it's how the system learns *generally*, not just per-task.

## The promotion graph

```
                    ┌─────────────────────────┐
                    │   New Skill in ~/.claude/│ ← rare, requires ≥3 projects
                    │       skills/           │
                    └────────────▲────────────┘
                                 │ promote (periodic-maintenance pass 5)
                                 │
                    ┌────────────┴────────────┐
                    │ ~/.claude/memory/<tech>/│ ← cross-project
                    │       MEMORY.md         │
                    └────────────▲────────────┘
                                 │ promote (when lesson recurs in ≥3 projects)
                                 │
                    ┌────────────┴────────────┐
                    │ .claude/architecture/MEMORY.md│ ← project-scope
                    └────────────▲────────────┘
                                 │ promote (when lesson is general)
                                 │
                    ┌────────────┴────────────┐
                    │ <task>/reflections.md   │ ← task-scope
                    └────────────▲────────────┘
                                 │ during session-end-dreaming
                                 │
                    ┌────────────┴────────────┐
                    │  .claude/lesson-queue.md│ ← in-flow capture
                    └─────────────────────────┘


    Independent track for rules (not memory):

    ┌─────────────────┐  promote when rule  ┌─────────────┐
    │ decisions.md    │ ─── consistently ──►│  CLAUDE.md  │
    │ ADR             │     applied         │  rule       │
    └─────────────────┘                     └─────────────┘


    Independent track for enforcement:

    ┌─────────────────┐  promote when rule  ┌─────────────────┐
    │  CLAUDE.md rule │ ── is mechanical ──►│  Hook / lint    │
    │                 │                     │  rule           │
    └─────────────────┘                     └─────────────────┘
```

## Promotion criteria (specific)

### lesson-queue → task reflections.md OR MEMORY.md

**When**: session-end-dreaming.
**Criterion**: the lesson is genuine (not generic), specific enough to fire on a future symptom search.
**Frequency**: every session-end that has a non-empty queue.
**How**: see `triggers/session-end-dreaming.md` and `references/lesson-classification.md`.

### task reflections.md → project MEMORY.md

**When**: session-end-dreaming.
**Criterion**: the lesson is about the project's code/domain/external systems, not about *this specific task*. A task-specific failure ("I forgot to pass the user_id to authenticate") is not a project lesson. A pattern-specific failure ("our authentication boundary expects user_id in kwargs, not args") IS a project lesson.
**Frequency**: per session-end.

### project MEMORY.md → tech MEMORY.md

**When**: periodic-maintenance pass 5, OR explicit promotion request.
**Criterion**: the lesson appears in 2+ projects' `.claude/architecture/MEMORY.md` files, OR the lesson is clearly about a library's behavior rather than the project's domain.

**Test**: rewrite the lesson removing all project-specific names. Does it still make sense and still teach a useful thing? If yes, promote.

Example:
- Project lesson: "In our project, when we call the Stripe webhook endpoint, the `amount` field is in cents (integer), not dollars."
- Rewrite: "Stripe webhook `amount` is always integer cents, not a float." — still useful for any project using Stripe.
- → Promote to `~/.claude/memory/stripe/MEMORY.md`. Mark a "promoted from <project>" footnote.

### tech MEMORY.md → new Skill

**When**: periodic-maintenance pass 5.
**Criterion**: ALL of:
- The lesson has been referenced (matched in a stuck-protocol search, or actively recalled) in **≥ 3 different projects**.
- The lesson is **procedural** (it tells you how to do something, not just what to know).
- The lesson is **>= 50 lines** when written out in detail (Skills are heavyweight; small lessons stay as memory).
- There's a **distinct trigger phrase** users could naturally say to activate it.

**Process**:
1. Draft a new SKILL.md following the `skill-creator` conventions (YAML frontmatter with pushy description, imperative body, examples).
2. Move the canonical content out of MEMORY.md into the skill.
3. In the MEMORY.md location, leave a one-line breadcrumb: "See ~/.claude/skills/<name>/SKILL.md (promoted on <date>)."
4. Install in `~/.claude/skills/<name>/`.

**Anti-criterion**: do NOT promote based on "this is interesting" or "this is high-quality content". Promote only when the lesson has *demonstrated demand* (≥3 retrievals) AND meets the procedural / size bars.

### ADR → CLAUDE.md rule

**When**: pre-commit-checkpoint, OR periodic-maintenance pass 2.
**Criterion**: ALL of:
- The ADR's decision implies a rule that should apply automatically going forward.
- The rule has been applied in ≥ 3 commits since the ADR was written, with no exceptions.
- The rule fits in one line.

**Process**:
1. Add a one-line rule to CLAUDE.md with a cross-reference to the ADR.
2. Leave the ADR intact (it has the WHY; CLAUDE.md has the WHAT).

Example:
- ADR: "2026-05-14: All money handled as Decimal..."
- After ~10 commits all using Decimal, add to CLAUDE.md:
  ```
  - Money is the `Money` dataclass; never raw float. (See decisions.md 2026-05-14.)
  ```

### CLAUDE.md rule → hook / lint enforcement

**When**: as soon as the rule is mechanical (can be checked by a script).
**Criterion**: the rule is verifiable without human judgment (formatting, type check, presence of a function, structure of a directory, etc.).

**Process**:
1. Add a ruff rule, mypy config flag, or PostToolUse hook that enforces the rule.
2. **Keep the CLAUDE.md rule** — the hook provides the failure, the rule provides the explanation.
3. If the rule was negative ("don't use X"), the hook should reject usage of X; the CLAUDE.md rule helps Claude know not to write it in the first place.

Example:
- CLAUDE.md rule: "Use `pathlib.Path`, not `os.path`."
- Hook: ruff `PTH` (flake8-use-pathlib) catches `os.path.join` and flags it.
- Both stay — they reinforce each other.

## Inverse: demotion (rare but valid)

Knowledge moves up by default. But sometimes it moves down:

### CLAUDE.md rule → decisions.md note (demote)

**When**: the rule has become situational rather than universal.
**Example**: CLAUDE.md says "use FastAPI for all APIs". Then a new module needs gRPC. The rule becomes "we use FastAPI by default; gRPC for streaming, see decisions.md 2026-07-XX."
- Move the decision detail to decisions.md.
- Keep a one-line CLAUDE.md pointer.

### Skill → tech memory (demote)

**When**: a skill was created prematurely, gets used rarely, and the content fits in a memory entry.
**Process**: rare, but during periodic-maintenance, if a skill hasn't triggered in 6 months and isn't worth its complexity:
1. Distill the skill's key content into a tech MEMORY.md entry.
2. Archive the skill folder (don't delete — record what was tried).

### MEMORY.md entry → discard

**When**: the underlying tech/library no longer exists, OR the project no longer uses it.
**Process**: archive to `~/.claude/memory/<tech>/ARCHIVE-<year>.md` rather than delete.

## How to detect a promotion candidate

You can't proactively scan for promotion candidates — that's expensive. Instead, *track usage*:

- Every time stuck-protocol's tier 1 finds a hit in memory, note it. After 3 hits across projects → tech promote.
- Every time a CLAUDE.md rule is applied → note. After 3 consecutive non-violations across project commits → consider hook enforcement.
- Every time an ADR is cited in commit messages or other ADRs → note. After 3 citations → consider CLAUDE.md rule.

Lightweight tracking: append to `.claude/promotion-candidates.md`:
```
- 2026-05-20 | hit ~/.claude/memory/argon2-cffi/MEMORY.md "verify raises" | project: <your-project> | task: auth
```

At periodic-maintenance, scan this file for entries with ≥ 3 matching hits → those are promotion candidates.

## Why promotion matters

Without promotion, memory is just a flat dump of everything that ever happened. With promotion, the memory layer **gains structure over time**:

- Frequently-useful patterns become skills (highest-leverage, always available).
- Consistently-applied decisions become rules (always loaded).
- Mechanical rules become hooks (never forgotten).
- One-off observations stay where they are (still useful, no overhead).

This is the actual self-improving loop, expressed in artifacts: each promotion is an instance of the system getting better at its own job, without needing the LLM to "learn" anything new.

## Cadence summary

| Promotion | Frequency | Trigger |
|---|---|---|
| queue → reflections / MEMORY | every session-end | session-end-dreaming |
| project MEMORY → tech MEMORY | weekly–monthly | periodic-maintenance pass 5 |
| tech MEMORY → skill | every few months | periodic-maintenance pass 5, when criteria met |
| ADR → CLAUDE.md rule | per cycle | pre-commit-checkpoint OR periodic-maintenance |
| CLAUDE.md rule → hook | when rule becomes mechanical | opportunistic, during any work that touches the rule |

The highest-tier promotions (memory → skill) are the rarest. That's correct — a working system should have many lessons, fewer rules, and few skills.
