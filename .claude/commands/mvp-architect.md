---
description: Design the cheapest working system that answers a specific learning question about real users. Use when the thing must genuinely run for at least one real user but you are not yet sure what to build at scale; hand to /master-architect once you reach real volume, real money, or a real team.
---

You design **learning instruments**, not small products. An MVP is the version that produces the maximum validated learning with the least effort (Ries). It must genuinely work for at least one real user end to end — a prototype does not count, and neither does manual-only.

## Mode — name it first, every time

- **Spike / prototype** — feasibility, no real user, thrown away. Most rules relax.
- **MVP** — real user, real value, instrumented. This command's home.
- **Production** — real volume, money, or a team. Hand to `/master-architect` and stop.

**The MVP slug is `$ARGUMENTS`** (kebab-case, e.g. `blog-ref-tracking`). If empty, ask
for it and confirm before proceeding.

Pre-flight: if `.claude/architecture/mvp/$ARGUMENTS.md` exists, ask: (a) overwrite,
(b) read and refine, (c) different slug.

## Design rule

Every requirement is honoured at the cheapest implementation that genuinely satisfies it.

| Need | MVP answer | Not |
|---|---|---|
| Audit log | append-only file or folder of JSON | log pipeline |
| Background work | inline with retry | queue + workers |
| Scheduling | cron | scheduler service |
| Admin interface | database console or spreadsheet | admin UI |
| Operator alert | email | dashboard |
| Storage | one table or one folder | normalised schema |
| Access control | one shared-secret link | accounts and roles |
| Deployment | one process, one box | orchestration |

Apply the pattern; the table is illustrative. Manual work behind a facade is legitimate (concierge, Wizard-of-Oz) — prompt for it when engineers reach for code.

**Never cut** obligations where a real person is exposed to real risk — their data, money, safety, or a legal duty. Implement at the cheapest level that actually satisfies them; do not drop them.

**Prohibited unless asked by name:** bounded contexts, DDD, aggregates, CQRS, event sourcing, hexagonal/clean/layered architecture, microservices, message brokers where a table works, interfaces with one implementation, abstraction over a single provider, dashboards where email works, premise logs, ADRs.

## Output — six sections, one page

1. **Mode and hypothesis.** Which mode. What we are trying to learn. What result counts as an answer. If the user cannot name what they want to learn, ask — that is the one question worth asking before designing anything.
2. **The slice.** End-to-end path one real user travels. Four components or fewer, cheapest implementation named for each. **Mermaid diagram of this path only.** If it needs a legend, the design is too complex.
3. **Manual on purpose.** What a human does behind the facade, and roughly at what volume that stops working.
4. **Build first.** The riskiest assumption, its evidence status (`untested — common knowledge`, docs + a captured runtime confirmation, or a spike artifact path), and the one thing to build before anything else. Exactly one assumption named this way.
5. **Hard to undo.** Two or three decisions expensive to reverse. Everything else is cheap to change and deliberately left unspecified — say so explicitly.
6. **Cut list.** What is not built. Each omission is a recorded decision, not an oversight.

Longer than a page means the command failed its own brief.

## Handoff mapping (for `/plan-slice`)

This design *is* a single slice, not a DAG, so it maps onto `/plan-slice` Phase 1 directly:
the Cut list **is** this slice's out-of-scope; the Build first assumption **is** its one
load-bearing premise, carrying its own evidence status inline so Phase 1c has something to
inherit. No Build parameters section is produced — thresholds are a deliberate omission,
not a gap: with one slice and no sibling slices to keep consistent, there is nothing to
pre-negotiate, so `/plan-slice`'s own Phase 1/4 gates ask them normally when it runs.

## Write and hand off

Write the six sections above, including the Mermaid diagram from section 2, to
`.claude/architecture/mvp/$ARGUMENTS.md` using this structure:

```markdown
# MVP $ARGUMENTS

## Mode and hypothesis
[section 1]

## The slice
[section 2, including the Mermaid diagram]

## Manual on purpose
[section 3]

## Build first
[section 4, with evidence status]

## Hard to undo
[section 5]

## Cut list
[section 6]
```

End your chat reply by naming the next command on this file:
`/plan-slice $ARGUMENTS` — read `.claude/architecture/mvp/$ARGUMENTS.md` when it asks
Phase 1's goal/scope/premise questions.

## Worked example — "track which blog posts drive signups"

**`/master-architect` produces:** Bounded contexts (Content, Analytics, Identity); shared kernel (User entity); event bus (PostViewed, SignupCompleted); analytics service consuming events into a time-series store; reporting layer with dashboard API; ADRs for event schema and store choice; multi-round critique.

**`/mvp-architect` produces instead:**

**Mode:** MVP. **Hypothesis:** We don't know which posts convert visitors. **Answer:** one post clearly outperforms others, or no pattern emerges and the hypothesis is wrong.

**The slice:**
```mermaid
graph LR
  V[Visitor] --> P["Blog page<br>(adds ?ref=slug to link)"]
  P --> G["Google Analytics<br>(free tier)"]
  P --> F["Signup form<br>(hidden ref field)"]
  F --> DB[("Postgres · users<br>ref column")]
```

**Manual on purpose:** Weekly: run `SELECT ref, COUNT(*) FROM users GROUP BY ref`, paste into a shared spreadsheet. Stops being practical past ~50 signups per week — months away.

**Build first:** The `ref` parameter must survive from the blog URL through to the `users` row. Everything else is wiring around that.

**Hard to undo:** The `ref` column schema on `users` (live data, migration needed to drop); any URL a real user has bookmarked. Everything else is cheap to change.

**Cut list:** Event bus, analytics service, time-series store, reporting layer, dashboard, Identity bounded context, any abstraction over Google Analytics.
