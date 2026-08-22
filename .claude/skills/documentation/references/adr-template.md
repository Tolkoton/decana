# Architecture Decision Records

An ADR captures one **architecturally significant** decision: the context that
forced it, the choice made, and the consequences. ADRs are an append-only log —
they preserve *why* the system is the way it is, which is exactly the knowledge
that evaporates fastest from a team and is hardest for an agent to reconstruct.

## When to write one

Write an ADR when a decision affects:

- the structure of the system (a new layer, a new boundary, a split or merge),
- non-functional qualities (security, availability, performance, cost),
- a dependency with real lock-in (a framework, a database, a vendor API),
- a public interface or contract.

Do **not** write an ADR for routine, easily reversible choices (variable names,
which utility helper to use). If reversing it would be cheap and local, it is
not architectural.

## Where they live

`docs/adr/NNNN-short-kebab-title.md`, numbered sequentially from `0001`. The
number never changes; the file is never renumbered.

## Status lifecycle

```
Proposed  ->  Accepted  ->  Superseded by ADR-MMMM
                  \
                   ->  Deprecated   (no longer applies, not replaced)
                   ->  Rejected     (was proposed, decided against)
```

**ADRs are append-only.** To change an accepted decision:

1. Write a new ADR describing the new decision.
2. In the new ADR, add a line: `Supersedes ADR-NNNN`.
3. In the old ADR, change only the status line to `Superseded by ADR-MMMM`.
   Do not edit the old ADR's Context, Decision, or Consequences — that history
   is the point.

## Template (MADR-style)

Copy this for each new ADR.

```markdown
# ADR-NNNN: <short decision title>

- **Status:** Proposed | Accepted | Deprecated | Superseded by ADR-MMMM | Rejected
- **Date:** YYYY-MM-DD
- **Deciders:** <names or roles>
- **Supersedes:** <ADR-NNNN, or omit>

## Context

What problem or force prompted this decision? What constraints apply
(technical, business, regulatory)? State the situation neutrally — enough that
a reader a year from now understands why a decision was even needed.

## Considered options

- **Option A** — <one line>
- **Option B** — <one line>
- **Option C** — <one line>

(For a retroactive ADR where the alternatives were never formally weighed, say
so: "Reconstructed retroactively; alternatives not formally evaluated at the
time.")

## Decision

The option chosen, stated plainly, and the reasoning that selected it over the
others. This is the heart of the record.

## Consequences

What becomes easier as a result. What becomes harder. New constraints,
follow-up work, and risks accepted. Be honest about the downsides — an ADR that
lists only benefits is not trustworthy.
```

## The first ADR

Every ADR set begins with the meta-ADR in which the project adopts the practice.
Create it as `docs/adr/0001-record-architecture-decisions.md`:

```markdown
# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** YYYY-MM-DD
- **Deciders:** <team>

## Context

Architecturally significant decisions are being made, but the reasoning behind
them is not written down. New contributors and AI agents cannot see why the
system is shaped as it is, and decisions risk being silently re-litigated or
unknowingly broken.

## Decision

We record architecturally significant decisions as ADRs in `docs/adr/`, using
the MADR-style template. ADRs are append-only: a decision is changed by adding
a new ADR that supersedes the old one, never by editing an accepted record.

## Consequences

- The reasoning behind the architecture is preserved and reviewable in PRs.
- Writing an ADR adds a small, deliberate cost to significant decisions.
- Onboarding (human and agent) improves: the "why" is discoverable.
```

References: Michael Nygard's original ADR article; the MADR project.
