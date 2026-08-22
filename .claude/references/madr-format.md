# MADR (Markdown Architectural Decision Records)

Reference for Phase 2 ADR generation. Master-architect uses MADR 4.0 format by default.

## ADR format comparison

Three common formats; pick one and stick to it:

| Format | Style | Strength | Weakness |
|--------|-------|----------|----------|
| **Nygard** (the original) | Short, narrative | Easy to write | Vague on alternatives, decision drivers |
| **MADR 4.0** | Structured, optional sections | Captures alternatives well; templates supported | Slightly more ceremony |
| **Y-statement** | One-sentence template | Forces structured thinking in minimum space | Doesn't scale to complex decisions |

**Master-architect default**: MADR 4.0 for substantial decisions, Y-statement for trivial ones (rare — most trivial decisions don't need an ADR at all).

## MADR 4.0 structure

```markdown
# ADR-<NNN>: <Short noun-phrase title>

## Status

<DRAFT | PROPOSED | ACCEPTED | DEPRECATED | SUPERSEDED by ADR-<NNN>>

Date: YYYY-MM-DD

## Context and Problem Statement

What's the issue? Use one-paragraph problem statement + relevant context.
Reference Phase 0/1 artifacts: QASes, constraints, stakeholders.

## Decision Drivers <!-- optional -->

- Driver 1 (e.g., "Phase 1 QAS-03 requires p99 latency ≤200ms under 1000 RPS")
- Driver 2

## Considered Options

- Option A
- Option B
- Option C

## Decision Outcome

Chosen option: "Option A", because <justification linking to drivers>.

### Consequences

* Good, because ...
* Bad, because ...
* Neutral, because ...

### Confirmation <!-- optional -->

How will we verify the decision is honored? (e.g., import-linter rule, test, observability metric)

## Pros and Cons of the Options <!-- optional -->

### Option A

* Good, because ...
* Bad, because ...

### Option B

* Good, because ...
* Bad, because ...

### Option C

* Good, because ...
* Bad, because ...

## More Information <!-- optional -->

Links, related ADRs, future considerations.
```

## Nygard format (for reference)

```markdown
# ADR <NNN>. <Title>

Date: YYYY-MM-DD

## Status

<Proposed | Accepted | Superseded by ADR-NNN>

## Context

The forces at play, the constraints.

## Decision

What we decided to do.

## Consequences

What becomes easier or more difficult because of this decision.
```

Lighter than MADR. Use when alternatives genuinely aren't worth enumerating.

## Y-statement format

> In the context of <use case/user story>, facing <concern> we decided for <option> to achieve <quality>, accepting <downside>.

Example:
> In the context of the order service, facing the need for sub-100ms confirmation latency, we decided for PostgreSQL with synchronous commit disabled to achieve write throughput, accepting the small risk of losing the last few transactions on power loss.

One sentence forces clarity. Hard to write well.

## When to write an ADR (Zimmermann's 5+2 significance criteria)

An architectural decision is worth recording when it satisfies at least one of the **5 primary** criteria, and you should especially write an ADR if any **+2 reinforcing** signals apply.

### 5 primary criteria

1. **Concerns more than one component / spans a boundary**: cross-cutting decisions deserve documentation.
2. **Difficult to reverse**: anything requiring migration, retraining, or significant rewrite to undo.
3. **Externally visible**: API contracts, file formats, protocols visible to other systems.
4. **Investment-significant**: requires substantial time/money to implement; you don't want to forget why later.
5. **Quality-attribute-driven**: directly addresses a specific QAS (especially security, performance, reliability).

### +2 reinforcing signals

6. **Constraint imposed externally**: regulation, vendor requirement, organizational mandate.
7. **Disagreement during decision-making**: if there was meaningful debate, capture the alternative and why it lost.

### Conversely: do NOT write an ADR for

- Library choices within an obvious ecosystem ("we use FastAPI because Python web is given")
- Internal coding conventions (Phase 3 concern, capture in CLAUDE.md / style guide instead)
- Decisions trivially reversible by editing a few lines
- Operational details that don't affect architecture (logging format, color scheme)

## Numbering

Zero-padded 3-digit: ADR-001, ADR-002, ... Stable forever.

When superseding:
- Original ADR-005 status: `SUPERSEDED by ADR-042`
- ADR-042 status: `ACCEPTED`, with "Supersedes ADR-005" in context
- Never delete ADR-005

## Single-file vs separate-folder

- ≤5 ADRs per phase → inline in `phase-2-architecture.md` under an "ADRs" section
- >5 ADRs → separate folder `.architecture/adrs/<NNN>-<slug>.md`

Master-architect picks based on count, but inline is fine to start; promote to folder when count grows.

## ADR storage location

The Architecture chat output puts ADRs in `.architecture/` (alongside other phase artifacts). Some teams put them in `docs/adrs/` at repo root.

For master-architect: `.architecture/adrs/` is the default location; can be configured.

## Anti-patterns

- **ADR for trivial decisions**: writing an ADR for "we'll use the latest version of X library" is noise. Recognize when no decision was made.
- **ADR with no context**: just decision and consequences. Context is what makes the ADR useful later.
- **ADR that loses to time**: if 6 months from now the ADR makes no sense, the context was incomplete.
- **ADR rewriting**: don't edit ADRs to "fix" past mistakes; supersede them. The trail of thinking has value.
- **ADRs that name the team's preferences not the system's constraints**: "we like Python" is not an ADR. "Python because Phase 1 constraint specified team skills" is.

## Sources

- Michael Nygard, "Documenting Architecture Decisions" (2011) — the original
- Olaf Zimmermann, "Architectural Decision Records: 5+2 Significance Criteria" (2020) — when to write
- MADR project: adr.github.io / madr.github.io
- Y-statement: Olaf Zimmermann et al.
