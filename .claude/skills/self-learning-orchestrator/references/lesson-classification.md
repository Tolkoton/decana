# Lesson Classification

For use during `triggers/session-end-dreaming.md`. Given a candidate lesson, decide where (if anywhere) it lives. Wrong classification at this step is the most common cause of memory rot — tech-scope memory gets project-pollution, project-scope memory misses general lessons.

## The 6 categories

Every candidate lands in exactly one of these:

1. **DISCARD** — obvious, generic, or already known. ~50% of candidates land here.
2. **PROJECT-SCOPE MEMORY** — observation specific to this codebase / domain / external systems.
3. **TECH-SCOPE MEMORY** — observation about library/framework behavior that applies to any project using it.
4. **BOTH** — has independent value at both scopes.
5. **DEFERRED → ADR** — this is really a decision, not a lesson; write it up as such.
6. **DEFERRED → CLAUDE.md RULE** — this should apply automatically forever; promote to a rule.

## Diagnostic questions

For each candidate, answer in order. Stop at the first match.

### Q1: Could a competent dev guess this without seeing the lesson?

If the lesson is "Pydantic v2 has migration changes from v1" → yes, that's common knowledge.
If the lesson is "Pydantic v2's `model_validate_json` on Union types order-dependent" → no, that's specific.

YES → **DISCARD**. Generic knowledge clutters memory and lowers retrieval quality.

### Q2: Does the lesson reference specific files, services, or domain terms unique to this project?

If yes → **PROJECT-SCOPE**.

Examples:
- "Our `dunning` service uses raw `text()` SQL because of legacy partner format" → project (it's about *our* dunning service).
- "Our payment provider's amount field can be string or number depending on endpoint" → project (it's about *our specific vendor contract*).
- "The `BillingBase` is separate from `UserBase` to avoid coupling" → project (it's about *our* base classes).

### Q3: Would this same observation bite someone using the same library in a different codebase?

If yes → **TECH-SCOPE**.

Examples:
- "argon2-cffi's verify raises VerifyMismatchError, not returns False" → tech (true for anyone using argon2-cffi).
- "SQLAlchemy 2.0's `Mapped[Optional[T]]` requires explicit `nullable=True` in mapped_column" → tech.
- "pytest's `tmp_path` is auto-cleaned; `tmp_path_factory` is session-scoped" → tech.

### Q4: Could the answer to Q2 AND Q3 both be yes?

If yes → **BOTH**.

Example: "We picked PyJWT over authlib because the latter's API surface is unstable across minor versions."
- Project: the *we picked* part is project-specific (it's our decision).
- Tech: the *authlib API instability* observation is tech-scope (true for anyone).

Split:
- Project (`.claude/architecture/MEMORY.md`): "We use PyJWT not authlib (see decisions.md 2026-05-20)."
- Tech (`~/.claude/memory/authlib/MEMORY.md`): "authlib's API surface changes across minor versions — pin tightly or expect breakage on upgrade."

### Q5: Is this a CHOICE with alternatives, deserving rationale?

If yes → **DEFERRED TO ADR**. Write it up via `decision-checkpoint.md`, not as a memory entry.

A test: can you describe alternatives that were considered and rejected? If yes, ADR. If no, memory.

### Q6: Is this a RULE that should apply to all future code automatically?

If yes → **DEFERRED TO CLAUDE.md**.

A test: is the statement of the form "always do X" or "never do Y"? CLAUDE.md material.

A test: is enforcement mechanical (lint rule, type check, hook)? Then BOTH CLAUDE.md (for visibility) AND the hook / lint config (for enforcement).

## The "default to project-scope" rule

When a candidate could plausibly be project-scope OR tech-scope, prefer **project-scope**. Why:

- Tech-scope memory is global and forever; once polluted it's painful to clean.
- Project-scope memory is bounded; pruning is cheaper.
- Promotion path goes project → tech, never tech → project. If the lesson recurs in 3+ projects, periodic-maintenance promotes it.

So when in doubt, write to `.claude/architecture/MEMORY.md` and let promotion handle the rest.

## Tech-scope file naming

`~/.claude/memory/<tech>/MEMORY.md` uses a per-tech directory. Pick `<tech>` to match how Claude would search:

| Observation about | File |
|---|---|
| Python stdlib | `~/.claude/memory/python/MEMORY.md` |
| Pydantic (v1 or v2) | `~/.claude/memory/pydantic/MEMORY.md` |
| FastAPI | `~/.claude/memory/fastapi/MEMORY.md` |
| SQLAlchemy 2.0 | `~/.claude/memory/sqlalchemy/MEMORY.md` |
| pytest | `~/.claude/memory/pytest/MEMORY.md` |
| Hypothesis | `~/.claude/memory/hypothesis/MEMORY.md` |
| uv (package manager) | `~/.claude/memory/uv/MEMORY.md` |
| ruff | `~/.claude/memory/ruff/MEMORY.md` |
| mypy | `~/.claude/memory/mypy/MEMORY.md` |
| Vendor API (project-specific) | `~/.claude/memory/<vendor>/MEMORY.md` |
| Domain (project-specific) | `~/.claude/memory/<domain>/MEMORY.md` |

A lesson can fit multiple files. If it's clearly about ONE library's behavior, pick that. If it's about an interaction between two (e.g., SQLAlchemy + Pydantic), pick the primary one and link from the other. Don't duplicate full entries — link.

## Worked examples

### Example 1: argon2-cffi verify() behavior

> "I assumed argon2-cffi's verify() returns False on mismatch; it actually raises VerifyMismatchError."

- Q1: Common knowledge? No, it's a library-specific gotcha.
- Q2: Project-specific? No, the library behaves this way everywhere.
- Q3: Bites in other projects? Yes.
- → **TECH-SCOPE**: `~/.claude/memory/argon2-cffi/MEMORY.md` (or `~/.claude/memory/auth/MEMORY.md` if you group by concern).

### Example 2: vendor API quirk

> "Our payment provider's webhook amount field returns string sometimes, Decimal other times."

- Q1: Common knowledge? No.
- Q2: Project-specific? Yes — this vendor is specific to our project.
- → **PROJECT-SCOPE**: `.claude/architecture/MEMORY.md`. Don't put it in tech-scope; another project won't use the same vendor contract.

### Example 3: We chose Pydantic for I/O, dataclass internally

> "After discussion, we went Pydantic for I/O boundaries and @dataclass for internal types."

- Q5: Is this a choice with alternatives? Yes (could've gone Pydantic-everywhere or dataclass-everywhere).
- → **DEFERRED TO ADR**: write up via decision-checkpoint, not memory.

### Example 4: All money is Decimal

> "Float accumulates error in sums; use Decimal for money."

- Q6: Rule that should apply forever? Yes.
- → **DEFERRED TO CLAUDE.md RULE**. Plus, since the WHY is non-obvious, also write an ADR. Plus, since it's a tech-scope fact (true for any Python money code), also write to `~/.claude/memory/python/MEMORY.md`.
- → **BOTH** plus rule and ADR.

### Example 5: Tests should use tmp_path

> "Tests should use pytest's tmp_path, not tempfile."

- Q1: Common knowledge among Python testers? Borderline — many devs reach for tempfile by habit.
- Q6: Rule that should apply forever? Yes, but it's also enforceable by a ruff rule (`flake8-pytest-style`).
- → **CLAUDE.md** for visibility AND **enforce with ruff** so the rule never silently rots.

### Example 6: We learned that mypy strict catches None bugs

> "mypy strict mode caught several None-handling bugs in our refactor."

- Q1: Common knowledge that mypy strict is good? Yes.
- → **DISCARD**. Generic platitude, no specific gotcha.

### Example 7: Hypothesis falsifying example I want to remember

> "Hypothesis found that our format_amount() function breaks on Decimal('0.00000001') — too many fractional places."

- Q1: Generic? No, specific to our code.
- Q2: Project-specific? Yes, it's about our format_amount().
- → **PROJECT-SCOPE**. Also: pin the failing input as a regression test via `@example` in the property test. The test is the canonical home; memory is the backup.

## When the queue is large

If session-end-dreaming has > 10 candidates, classification takes time. Apply this fast filter:

1. First pass: discard all obvious / generic (~50% of queue typically).
2. Second pass: identify ADRs and CLAUDE.md rules (defer those, don't process them as memory).
3. Third pass: of remaining, decide project vs tech vs both.

Don't try to classify all at once — separating the deferred items first reduces the cognitive load on the real memory work.

## Edge case: the lesson is about Claude itself

> "Claude keeps suggesting 'use a global config' when I want injection — I have to keep correcting it."

- This is about Claude's behavior in our project context.
- → **CLAUDE.md RULE**. Add a positive-form line: "Prefer dependency injection over global config in this project."
- The point of CLAUDE.md is to teach Claude what we want. This is exactly its purpose.

## Final check: would a 6-month-future self benefit?

For each candidate that survives the filters, do a final sanity check. Read the lesson back and ask: "If I'd seen this lesson when I was about to make the original mistake, would it have prevented the mistake?"

If yes — write it.
If no — the lesson is too vague to fire. Sharpen it (add symptom keywords, code references) or discard.
