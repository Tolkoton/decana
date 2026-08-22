# Software Architecture patterns — reference library

> **How this is used in this system.** This is the micro / code-internal playbook
> (architectural styles, dependency rules, DDD tactical patterns, code organization,
> cross-cutting concerns, testability). `master-architect` reads it in **Phase M3 (software
> architecture)** before proposing the code structure; `master-critic` reads it in its **"check
> against the playbook"** step; `feature-critic` consults it for decomposition / contract and
> abstraction-prematurity questions. Match a situation against each pattern's *Use when* /
> *Earns-its-place threshold*, and let the **§0 prime directive** and the thresholds BLOCK
> premature abstraction.
>
> Weight by **evidence grade**: `established` settles a point and is cited, not debated;
> `contested` goes to **debate**, never asserted as a winner. This is *some level of truth* — it
> grounds structure-choice and prematurity; the specific-to-this-domain judgment still needs
> debate.
>
> Owner-provided deep-research output. Human-curated; edits to this file are a human decision.

---

# Software Architecture Patterns Playbook (Micro / Code-Internal)

A decision tool for an AI agent that **proposes** a codebase's internal structure and a second agent that **critiques** it. This is reference knowledge to ground proposals and reviews — match a concrete situation against it; do not read it as a survey.

Scope: the *micro* level — how code *inside* one deployable system is structured (layering, boundaries, dependency direction, domain modelling, cross-cutting concerns, folder/module organization). The *macro* between-services topic (service decomposition, inter-service communication, data ownership across services) lives in a separate **system-design** playbook and is out of scope here.

---

## 0. Prime directive: do not over-engineer

The most common and most expensive code-architecture mistake is **premature abstraction** — adding layers, interfaces, factories, and indirection before a concrete, present force demands them. Every entry below therefore leads with the boring, direct default and names the *specific signal* that justifies escalating. **The abstraction must earn its place. The default answer to "should I add this layer/interface/pattern?" is no, until a named force says otherwise.**

A useful framing (Sandi Metz / "wrong abstraction" lore): **duplication is far cheaper than the wrong abstraction.** Inlined, duplicated, obvious code is reversible. A premature abstraction calcifies decisions and is expensive to unwind. When unsure, prefer the duplication and wait for the third occurrence to reveal the real shape.

### How to read this playbook
- **The selection layer (Section 1) is the entry point.** Start at the first-question gate, then the per-category default, then the matrix. Only descend into the catalog once a candidate is identified.
- **The catalog (Sections 2–9)** gives each pattern a fixed schema so a situation can be matched against it.
- **The anti-pattern section (Section 10)** is the critic agent's primary tool: each entry is a detection smell for premature abstraction or structural rot.

### Per-pattern schema
- **Definition** — one plain sentence.
- **Use when** — concrete triggering signals.
- **Do NOT use when / simpler alternative** — the over-application guard and the direct thing to write instead.
- **Earns-its-place threshold** — the specific condition that justifies the abstraction.
- **Trade-offs** — what it buys vs. what it costs.
- **Failure modes & misapplication smells** — how it goes wrong; symptoms of premature/wrong application.
- **Combines with / conflicts with** — partners and mutually-exclusive choices.
- **Cheapest check** — the fastest test that it fits.
- **Evidence grade** — `established` | `strong-heuristic` | `contested`, with a source.

> **Schema note for the GoF / code-level pattern mini-catalog (Section 7):** applying all nine fields to ~12 small patterns would bloat the document and dilute its decision value, which contradicts the "cut anything that doesn't change a decision" rule. Those entries therefore use a tightened schema centered on the four decision-critical fields (*use when*, *do NOT use / simpler alternative*, *earns-its-place*, *misapplication smell*). Architectural styles, DDD tactical patterns, and CQRS/ES get the full schema.

### Evidence-grade legend
- **`established`** — canonical, broadly agreed, taught as baseline practice. Disagreement is at the margins.
- **`strong-heuristic`** — widely endorsed by respected practitioners and works well in practice, but is a guideline, not a law; context-dependent.
- **`contested`** — respected sources genuinely disagree, or "when it's worth it" is actively debated. The entry states both sides and the conditions under which each is right.

---

## 1. Selection layer

### 1.1 First-question gate (run this before proposing ANY abstraction)

Ask, in order. Stop at the first "no."

1. **Is there a concrete, present force demanding structure beyond the simple direct version?** A force is one of:
   - a **second real implementation** that exists *now* (not "we might swap the DB someday"),
   - a **genuine boundary** between teams, bounded contexts, or independently-changing concerns,
   - a **measured testability problem** (something is genuinely hard to test because it is welded to I/O, time, or an external service),
   - a **demonstrated change-locality problem** (a kind of change keeps forcing edits scattered across the codebase).
   - **If none of these are true → write the simple, direct thing. Stop here.** No interface, no port, no layer.

2. **Can you name the thing the abstraction protects against?** If you cannot point to the second implementation, the specific boundary, or the concrete change, the abstraction is speculative. Defer it.

3. **Is the cost of adding it later high?** Most internal structure is cheap to introduce later (extract an interface, split a module). If "later" is cheap, "later" is the answer. Reserve up-front structure for the rare cases where retrofitting is genuinely expensive (e.g., a boundary that, once crossed sloppily everywhere, is very hard to re-establish).

**Critic-agent corollary:** if a proposal introduces an abstraction and the proposing rationale is a future possibility ("so we can later…", "in case we need…", "to be flexible"), flag it as speculative generality unless a present force from step 1 is named.

### 1.2 Default ("boring") choice per category — and the one signal to escalate

| Category | Boring default for a small/new codebase | The single signal that justifies escalating |
|---|---|---|
| Overall style | A simple **layered** organization (or even a single module) — handlers/controllers → services → data access. | The business logic becomes hard to test or reason about because it is tangled with frameworks/I/O → move to **ports & adapters / hexagonal** (push I/O to the edges). |
| Domain modelling | Plain data structures + procedural service functions (transaction-script style). | The domain has **real invariants/rules that keep getting violated or duplicated** → introduce **DDD tactical** (entities, value objects, aggregates). |
| Code organization | **Package-by-feature** from day one (group by what the code *does* for the user). | Cross-feature technical concerns proliferate → add a thin shared/infrastructure module; do *not* flip to package-by-layer. |
| Cross-cutting concerns | Call them inline, or a single shared helper. | The same concern (auth/logging/validation/tx) is **copy-pasted across many handlers** → centralize via **middleware/decorator**. |
| Reads vs. writes | One model, one path. | A **measured** read/write asymmetry (very different scaling, or queries that twist the write model) → consider **CQRS** (often just split query methods, not infrastructure). |
| Dependency injection | Pass dependencies as constructor/function arguments (manual). | Wiring becomes genuinely unmanageable across many components → adopt a DI container. Manual DI is fine far longer than people think. |
| Persistence access | Call the data-access library directly, or a thin function. | You need to **swap the store, fake it in tests, or you have a real aggregate to reconstitute** → introduce a **repository**. |

### 1.3 Situation → recommended structure → trap to avoid

| Situation | Recommended structure | Primary trap to avoid |
|---|---|---|
| **Small CRUD app / admin tool / internal API** | Layered or single-module; transaction-script services; package-by-feature; direct data-access. | Clean/onion/hexagonal ceremony, repositories over an ORM that is already a repository, DDD aggregates for data with no invariants. |
| **Complex domain with real rules/invariants** (pricing, scheduling, insurance, trading) | DDD tactical (aggregates as consistency boundaries) inside a hexagonal or onion shell; rich domain model. | Anemic model (rules leak into services); aggregates drawn too large; one-repository-per-table instead of per-aggregate. |
| **Many external integrations** (payment, shipping, third-party APIs, legacy systems) | Ports & adapters; an **anti-corruption layer** per messy external model. | Letting an external/vendor model become your internal model; an adapter per integration that still leaks vendor types inward. |
| **High-change area / feature factory** (frequent new features, parallel teams) | **Vertical-slice** + package-by-feature; keep slices independent. | Shared "core service" classes that every feature must touch (a change-amplifier); over-layering each slice. |
| **Read-heavy with complex queries / reporting** | Separate read models / query services (lightweight **CQRS**); denormalized read views. | Full event-sourcing infrastructure when a read replica + query objects suffice. |
| **Audit/temporal requirement is a hard, stated requirement** (you must reconstruct past state, full history is the product) | **Event sourcing** for the specific aggregate that needs it — not the whole system. | Event-sourcing the entire app; treating ES as a default rather than a targeted answer to a real auditing/temporal requirement. |
| **Modular monolith for a growing team** | Modules by bounded context with explicit public interfaces; enforce no-reach-into-internals. | Modules that share a database schema freely (a distributed-monolith-in-waiting); circular module dependencies. |
| **Library / SDK others depend on** | Stable public surface; hide internals; apply REP/CCP/CRP and SDP/SAP deliberately. | Leaking internal types in the public API; unstable core that breaks consumers on every release. |
| **Prototype / spike / throwaway** | The least structure that runs. Inline everything. | Any architecture at all. Optimize for deletion, not maintenance. |

---

## 2. Architectural styles

### 2.1 Layered / N-tier
- **Definition.** Code is grouped into horizontal layers (typically presentation → application/service → domain → data access), each depending only on the layer below.
- **Use when.** Small-to-medium apps; CRUD-shaped work; teams that need an obvious, conventional structure; the request/response flow is the dominant axis of change.
- **Do NOT use when / simpler alternative.** When the app is tiny, a single module is enough — don't manufacture three layers for a 500-line service. When business logic is rich and rule-heavy, strict layering tends to push logic *out* of the domain and *into* service layers, producing an **anemic domain model**; prefer hexagonal/onion + DDD.
- **Earns-its-place threshold.** There is a real, recurring need to separate request handling from business logic from persistence — i.e., you can point to changes that touch only one of these and benefit from the separation.
- **Trade-offs.** Buys: familiarity, easy onboarding, clear request flow. Costs: tends toward anemic domains; the database often becomes the conceptual center ("database-driven design"); cross-layer features (a single feature touching all layers) get smeared across the tree.
- **Failure modes & smells.** "Lasagna architecture" — so many thin layers that each call passes through five near-empty pass-through methods. Business rules living in service classes while entities are bags of getters/setters. A "DTO ↔ entity ↔ DAO" mapping tax with no payoff.
- **Combines with.** DI; repository (as the data layer). **Conflicts with / tension with.** Vertical-slice and screaming architecture (layering organizes by technical role, not by feature).
- **Cheapest check.** Can you name a change that touches exactly one layer and is easier because of the split? If every change touches all layers anyway, the layering is paying no rent.
- **Evidence grade.** `established` as a baseline; the *anemic-model tendency* critique is `strong-heuristic` (Fowler, Evans). Source: Fowler, *Patterns of Enterprise Application Architecture* (PoEAA); Evans, *Domain-Driven Design*.

### 2.2 Hexagonal (Ports & Adapters)
- **Definition.** The application core defines technology-agnostic **ports** (interfaces); the outside world (web, DB, queues, external APIs) plugs in via **adapters**; all dependencies point inward toward the core.
- **Use when.** Business logic is worth isolating from frameworks/I/O; you have (or genuinely foresee *now*) multiple delivery mechanisms (HTTP + CLI + queue consumer) or multiple infrastructure backends; you want fast unit tests of logic without standing up a DB.
- **Do NOT use when / simpler alternative.** A small CRUD app with one delivery channel and one database: the ports are pure overhead — call the DB directly. If you have exactly one adapter behind a port and no test or substitution need, the port is a speculative interface; inline it.
- **Earns-its-place threshold.** A *second* adapter exists for a port (e.g., a real and a fake/in-memory implementation that you actually use in tests, or two real delivery mechanisms), **or** the core logic is demonstrably hard to test because it is welded to I/O.
- **Trade-offs.** Buys: testable core, framework independence, deferred infrastructure decisions, clear inside/outside boundary. Costs: more interfaces and indirection; mapping between core and adapter models; conceptual overhead newcomers must learn.
- **Failure modes & smells.** A port with a single adapter and no test double (interface-for-its-own-sake). "Ports" that expose infrastructure types (e.g., an ORM entity or HTTP request) — the boundary leaks. The core importing the web framework or the ORM (see *framework in the core* anti-pattern).
- **Combines with.** DDD tactical (core = domain + application services); dependency inversion; repository (a kind of port). **Conflicts with.** Nothing structurally; it is a refinement over layered. Vertical-slice can be layered *on top* (slices each respect the inward dependency rule).
- **Cheapest check.** For each port, name the second implementation or the test that uses a fake. If you can't, delete the port.
- **Evidence grade.** `established` / `strong-heuristic`. Source: Alistair Cockburn, "Hexagonal Architecture" (2005).

### 2.3 Onion Architecture
- **Definition.** Concentric layers with the domain model at the center; each ring depends only inward; infrastructure and UI are the outermost rings.
- **Use when.** Essentially the same situations as hexagonal — it is a close cousin that emphasizes the **domain at the center** and an explicit application-services ring. Choose it when you want a layered mental model with an enforced inward dependency rule.
- **Do NOT use when / simpler alternative.** Same guard as hexagonal: overkill for small CRUD. Treat onion vs. hexagonal vs. clean as **three framings of the same idea** (dependency inversion at the system boundary); do not stack all three or agonize over which name to use.
- **Earns-its-place threshold.** Same as hexagonal — a real isolation/substitution/testability force.
- **Trade-offs.** Same family as hexagonal. The ring metaphor can mislead teams into adding more rings than they need.
- **Failure modes & smells.** Over-ringing: inventing extra concentric layers ("application core", "application services", "domain services", "domain core") that are indistinguishable in practice.
- **Combines with / conflicts with.** Same as hexagonal.
- **Cheapest check.** Same as hexagonal.
- **Evidence grade.** `strong-heuristic`. Source: Jeffrey Palermo, "The Onion Architecture" (2008).

### 2.4 Clean Architecture
- **Definition.** A synthesis (hexagonal + onion + use-case-centric) with concentric circles — Entities → Use Cases → Interface Adapters → Frameworks & Drivers — governed by the **Dependency Rule**: source-code dependencies point only inward.
- **Use when.** Large, long-lived systems with complex business rules and a real need to keep those rules independent of frameworks, UI, and persistence; multiple delivery mechanisms; long maintenance horizon and team turnover.
- **Do NOT use when / simpler alternative.** **(Contested — see below.)** For a small/medium app, full clean architecture (entities, use-case interactors, request/response models, boundary interfaces, presenters, gateways) is usually *more machinery than the problem justifies*. The simpler alternative is layered or plain hexagonal; adopt the *principle* (dependency rule) without the full ceremony (you rarely need separate request/response DTOs and presenters in a typical web service).
- **Earns-its-place threshold.** The business rules are valuable and long-lived enough that isolating them from delivery/infrastructure has demonstrated payoff, **and** you have multiple boundaries (delivery mechanisms or infrastructure backends) that the structure actually serves.
- **Trade-offs.** Buys: maximal independence of business rules; very testable use cases; deferred/replaceable infrastructure. Costs: substantial boilerplate (mappers, boundary interfaces, DTOs in both directions, presenters); steep learning curve; high risk of cargo-culting the diagram.
- **Failure modes & smells.** A CRUD app drowning in interactors and boundary interfaces; one-to-one DTO ↔ entity mapping with no behavioral difference; "presenters" that just copy fields; the structure imposed uniformly regardless of whether a given feature has any business rules at all.
- **Combines with.** DDD tactical (entities/use cases); dependency inversion; repository (as a gateway). **Conflicts with.** Vertical-slice partisans argue clean's layering fights feature-locality (see 2.5); the honest position is that you can apply the dependency rule *within* vertical slices.
- **Cheapest check.** For the feature in front of you, does isolating its business rules from the framework protect against a concrete, named change? If the feature is plumbing with no rules, skip the full structure for it.
- **Evidence grade.** The dependency rule / inward-dependency principle is `established`. **Whether full clean architecture is worth its overhead for a given app is `contested`:** Robert C. Martin (*Clean Architecture*, 2017) presents it as broadly applicable; many experienced engineers (e.g., proponents of vertical slices and "transaction script for simple cases") argue it is routinely over-applied and adds ceremony for typical apps. Both are right under different complexity/longevity conditions. Sources: Martin, *Clean Architecture*; counter-position: Jimmy Bogard and the vertical-slice community; Fowler on "transaction script" for simple logic.

### 2.5 Vertical-Slice Architecture
- **Definition.** Organize code by **feature/use-case** end-to-end (each slice owns its request, handling, logic, and data access), rather than by horizontal technical layer; slices are as independent as possible.
- **Use when.** High rate of feature addition/change; teams working in parallel who want to avoid stepping on shared layer code; CQRS-style request handling (one handler per request); you value change-locality (a feature change lives in one place).
- **Do NOT use when / simpler alternative.** When there is heavy, genuinely-shared domain logic that many slices must reuse — forcing it into independent slices causes duplication or awkward sharing; a domain-centric (onion/DDD) core may serve better. For a tiny app, slices are fine but may be indistinguishable from "just put related code together."
- **Earns-its-place threshold.** You can point to repeated friction where a feature change forced edits across many horizontal layers, or to teams colliding on shared layer classes — and slicing demonstrably localizes those changes.
- **Trade-offs.** Buys: high change-locality, easy parallel work, easy deletion of a feature, less abstraction per feature. Costs: cross-cutting/shared logic needs deliberate handling; risk of inconsistency between slices; can hide duplication that should be unified.
- **Failure modes & smells.** Copy-paste between slices that has clearly become the *same* abstraction (apply the rule of three before extracting). Slices that secretly all depend on one fat shared service (you've reinvented a layer). No shared kernel for genuinely common value objects, so the same concept is modelled five ways.
- **Combines with.** CQRS (handler-per-request); package-by-feature; mediator-style dispatch. Can apply the **dependency rule within each slice**. **Conflicts with.** Strict horizontal layering and "share everything" core-domain approaches (manage the tension deliberately).
- **Cheapest check.** Does a typical feature change live inside one slice/folder? If features routinely sprawl across the tree, slicing isn't being respected.
- **Evidence grade.** `strong-heuristic` (popular, well-regarded, less canonically formalized than layered/clean). Source: Jimmy Bogard, "Vertical Slice Architecture."

### 2.6 Modular Monolith (internal structure)
- **Definition.** A single deployable unit internally divided into **modules aligned to bounded contexts**, each with an explicit public interface and hidden internals; modules communicate through those interfaces, not by reaching into each other.
- **Use when.** A growing codebase/team where you want clear internal boundaries and the option to extract services later, *without* paying distributed-systems costs now; the standard default before reaching for microservices.
- **Do NOT use when / simpler alternative.** For a small app, formal modules with enforced boundaries are overhead — a package-by-feature layout is enough. Conversely, do not use it as a euphemism for a big ball of mud with folders; the boundaries must be *enforced* (compile-time visibility, architecture tests) to be real.
- **Earns-its-place threshold.** Multiple distinct subdomains exist and you can name where one team/context ends and another begins; you want independent evolution of those areas inside one deployable.
- **Trade-offs.** Buys: clear boundaries, in-process simplicity (one deploy, transactions across modules still possible), a clean future extraction path, no network/serialization tax. Costs: discipline to keep modules from sharing internals/schema; tooling to enforce boundaries; risk of accidental coupling via a shared database.
- **Failure modes & smells.** Modules sharing the same database tables freely (the boundary is fake → a distributed-monolith-in-waiting if later split). Circular dependencies between modules. A module exposing its internal entities in its public API.
- **Combines with.** DDD (modules = bounded contexts); ports & adapters per module; ADP (no cycles). **Conflicts with.** Nothing inherently; it is the recommended midpoint between a single tangled module and microservices.
- **Cheapest check.** Can module A be compiled/tested without reaching into module B's internals, only its published interface? If not, the boundary doesn't exist yet.
- **Evidence grade.** `strong-heuristic` / increasingly `established` as the recommended default. Sources: Simon Brown ("modular monolith" talks, C4); Kamil Grzybek, "Modular Monolith" series.

---

## 3. Dependency management

### 3.1 Dependency Inversion Principle (DIP)
- **Definition.** High-level policy should not depend on low-level details; both depend on abstractions, and the abstraction is owned by the high-level side.
- **Use when.** You need to keep core logic independent of a volatile detail (DB, external API, framework) — this is the mechanism that makes hexagonal/onion/clean work.
- **Do NOT use when / simpler alternative.** When the "detail" is stable and there is one implementation with no test/substitution need, inverting the dependency just adds an interface with no payoff. Depend directly on stable things (the standard library, a well-established value type). **You do not need an interface for everything.**
- **Earns-its-place threshold.** The dependency is *volatile* (likely to change, or needs a test double) and crosses an architecturally significant boundary. Stable + single-implementation + no test double = no inversion.
- **Trade-offs.** Buys: substitutability, testability, boundary isolation. Costs: an extra interface and indirection per inverted dependency.
- **Failure modes & smells.** `IFoo`/`Foo` pairs with exactly one implementation and no test double, scattered everywhere (interface-bloat / "header interfaces"). Interfaces defined next to their single implementation rather than owned by the consumer.
- **Combines with.** Hexagonal, onion, clean; DI; SDP/SAP at the component level. **Conflicts with.** YAGNI when over-applied.
- **Cheapest check.** Name the second implementation or the test fake. None? Don't invert.
- **Evidence grade.** `established` (the "D" in SOLID). Source: Robert C. Martin, SOLID principles; *Clean Architecture*.

### 3.2 The Dependency Rule (direction of dependencies)
- **Definition.** Source-code dependencies point in one consistent direction — inward toward stable, high-level policy; lower-level/outer code depends on inner, never the reverse.
- **Use when.** Any layered/hexagonal/onion/clean system — it is the rule that keeps the core independent of the edges.
- **Do NOT use when / simpler alternative.** It is essentially always desirable *as a direction*, even in a tiny app (the domain shouldn't import the web framework). The "simpler alternative" is not to violate the rule but to have fewer layers; the direction still holds.
- **Earns-its-place threshold.** Free to adopt; adopt it by default. The *cost* is only in the machinery (interfaces) used to enforce it across a boundary — apply that machinery only at real boundaries (per 3.1).
- **Trade-offs.** Buys: the core never breaks because an outer detail changed. Costs: requires inverting some dependencies (interfaces) to keep the direction at boundaries.
- **Failure modes & smells.** The domain layer importing the ORM, the web framework, or the serialization library. "Just this once" upward dependencies that accumulate into a cycle.
- **Combines with.** DIP, ADP, hexagonal/onion/clean. **Conflicts with.** Nothing.
- **Cheapest check.** Grep the domain/core for imports of framework/infrastructure packages. Any hit is a violation.
- **Evidence grade.** `established`. Source: Martin, *Clean Architecture*; Cockburn (hexagonal).

### 3.3 Acyclic Dependencies Principle (ADP) — keep the graph acyclic
- **Definition.** The dependency graph among components/modules must have no cycles (no A→B→C→A).
- **Use when.** Always, at the module/component level — cycles make independent building, testing, and reasoning impossible.
- **Do NOT use when / simpler alternative.** No exception. The "alternative" when a cycle appears is to **break it**: either move the shared thing to a new component both depend on, or apply DIP to invert one edge.
- **Earns-its-place threshold.** Free; this is a constraint to maintain, not an abstraction to add.
- **Trade-offs.** Buys: independent buildability/testability, comprehensible structure, clean release boundaries. Costs: occasionally you must introduce an interface or a new small component to break a cycle.
- **Failure modes & smells.** Two modules that import each other; a "utils"/"common" grab-bag that everything depends on and that in turn depends back on feature modules. Build tools that can't determine compilation order.
- **Combines with.** DIP (to break cycles), SDP, modular monolith. **Conflicts with.** Nothing.
- **Cheapest check.** Run a cycle-detection / architecture-test tool (e.g., dependency-cruiser, ArchUnit, import-linter). Zero cycles is the bar.
- **Evidence grade.** `established`. Source: Martin (component principles), originally *Agile Software Development, Principles, Patterns, and Practices*.

### 3.4 Component cohesion principles — REP / CCP / CRP
State these as practical rules for *what to group into a module/package/release unit*. They pull against each other; you balance them by context.
- **REP — Reuse/Release Equivalence Principle.** The unit of reuse is the unit of release: things reused together should be versioned and released together. *Rule:* don't bundle unrelated things that consumers can't adopt as a unit.
- **CCP — Common Closure Principle** (SRP for components). Gather into one component the classes that **change for the same reasons at the same times**; separate things that change for different reasons. *Rule:* group by reason-to-change, so a typical change hits one component.
- **CRP — Common Reuse Principle** (ISP for components). Classes used together belong together; **don't force a consumer to depend on things it doesn't use.** *Rule:* split a component if consumers routinely need only part of it.
- **The tension.** REP + CCP make components *bigger*; CRP makes them *smaller*. Early in a project, **favor CCP (developability)** — group for ease of change — and worry about REP/reuse later. (Martin's "tension triangle.")
- **Evidence grade.** `established` as a framework, `strong-heuristic` in application. Source: Martin, *Clean Architecture*.

### 3.5 Component coupling principles — ADP / SDP / SAP
- **SDP — Stable Dependencies Principle.** Depend in the direction of stability: a component should depend only on components more stable than itself. *Rule:* volatile (frequently-changing) code may depend on stable code, never the reverse. (Stability ≈ how many things depend on it and how few it depends on.)
- **SAP — Stable Abstractions Principle.** A component should be as **abstract** as it is **stable**: stable components should be abstract (so they can be extended without modification); unstable components should be concrete. *Rule:* if something is highly depended-upon (stable), make it an abstraction. SDP + SAP together ≈ DIP at the component level.
- **Use when.** Designing the dependency structure of a larger codebase or a published library where stability of the core matters.
- **Do NOT over-apply.** Don't compute stability/abstractness metrics for a tiny app. Use these as *directional* rules; reserve the formal metrics for genuinely large or library-grade systems.
- **Failure modes & smells.** A stable, widely-depended-on core that is concrete and changes often (the "zone of pain" — everything breaks when it changes). A highly abstract component nobody depends on (the "zone of uselessness").
- **Evidence grade.** `established` (framework), `strong-heuristic` (metric application). Source: Martin, *Clean Architecture*.

---

## 4. Domain-Driven Design (tactical)

> **When is tactical DDD worth it at all?** `contested` at the margins, but the consensus shape is clear: **DDD earns its place when the domain has genuine complexity — real invariants, rich rules, evolving ubiquitous language — and is the heart of the business.** For a simple CRUD app (data in, data out, few rules), full DDD tactical machinery (aggregates, repositories, domain events, value objects everywhere) is ceremony. Default to transaction-script/anemic-data + services for CRUD; escalate to DDD when rules keep being violated or duplicated. Sources: Evans, *Domain-Driven Design* (2003); Vernon, *Implementing Domain-Driven Design* (2013); Fowler.

### 4.1 Entity
- **Definition.** A domain object defined by a stable **identity** that persists through changes to its attributes (a `Customer`, an `Order`).
- **Use when.** The concept has a lifecycle and identity that matters across state changes; two instances with identical fields are still distinct.
- **Do NOT use when / simpler alternative.** When identity doesn't matter and the thing is defined purely by its values → use a **value object** instead. When there are no rules at all and it's just a row → a plain record/struct is fine.
- **Earns-its-place threshold.** Identity-based equality and a lifecycle genuinely exist in the domain.
- **Trade-offs.** Buys: a natural home for identity-scoped behavior and invariants. Costs: identity/equality handling; persistence mapping.
- **Failure modes & smells.** An "entity" that is a bag of public getters/setters with all logic elsewhere (anemic). Using entities where value objects belong (and then fighting equality/sharing bugs).
- **Combines with.** Aggregates (an aggregate root is an entity), repositories, value objects. **Conflicts with.** Pure value-object modelling for the same concept.
- **Cheapest check.** "If two of these have all the same field values, are they the same thing?" If no → entity. If yes → value object.
- **Evidence grade.** `established`. Source: Evans, DDD.

### 4.2 Value Object
- **Definition.** An immutable object defined entirely by its attributes, with no identity (`Money`, `DateRange`, `Address`).
- **Use when.** A concept is described, measured, or quantified and equality is by value; you want to attach behavior/validation to a value (e.g., `Money` enforcing currency rules) and make illegal states unrepresentable.
- **Do NOT use when / simpler alternative.** When a primitive truly suffices and there are no rules/operations — wrapping a bare integer with no behavior or validation in a value object is often ceremony. (But beware "primitive obsession": if the primitive keeps attracting validation/logic, a value object pays off.)
- **Earns-its-place threshold.** The value carries rules, invariants, or operations (validation, arithmetic, formatting) that you'd otherwise duplicate; or value-equality semantics genuinely matter.
- **Trade-offs.** Buys: immutability (safe sharing), self-validation, expressive types, fewer "stringly-typed" bugs. Costs: more small types; mapping to/from persistence/primitives.
- **Failure modes & smells.** Mutable "value objects" (defeats the purpose). A value object that is just a renamed primitive with zero behavior, created reflexively.
- **Combines with.** Entities (entities hold value objects), making-illegal-states-unrepresentable. **Conflicts with.** Treating everything as primitives.
- **Cheapest check.** Does this value have rules or operations that keep showing up? If yes, a value object removes duplication. If it's an inert wrapper, skip it.
- **Evidence grade.** `established`. Source: Evans, DDD.

### 4.3 Aggregate & aggregate boundary
- **Definition.** A cluster of entities/value objects treated as one consistency boundary, accessed only through a single **aggregate root**; invariants within the boundary are enforced together and transactions don't span aggregates.
- **Use when.** You have invariants that must hold across several related objects (e.g., an `Order` and its `OrderLines` must satisfy a total/limit rule); you need a clear transactional consistency unit.
- **Do NOT use when / simpler alternative.** When there are no cross-object invariants — don't draw aggregates around data just because it's related. For CRUD with no invariants, plain entities/records and direct access are simpler.
- **Earns-its-place threshold.** A real invariant spans multiple objects and must be kept consistent atomically. **Design aggregates as small as the invariants allow** — prefer referencing other aggregates by identity over containing them.
- **Trade-offs.** Buys: a guarded consistency boundary; a single entry point that protects invariants; a natural transaction scope. Costs: large aggregates cause contention/locking and load whole object graphs; cross-aggregate operations need eventual consistency / domain events.
- **Failure modes & smells.** Giant aggregates ("the customer aggregate contains everything") → lock contention, slow loads, merge conflicts. Reaching past the root to mutate internals. Transactions spanning multiple aggregates (should be one aggregate per transaction; coordinate the rest via events/eventual consistency).
- **Combines with.** Repositories (one repository *per aggregate root*), domain events (to coordinate across aggregates), entities/value objects. **Conflicts with.** One-repository-per-table thinking; transactions across aggregate boundaries.
- **Cheapest check.** "What invariant forces these objects to change together atomically?" If you can't name one, it isn't an aggregate — it's just related data.
- **Evidence grade.** `established`; the "keep aggregates small / reference by id" guidance is `strong-heuristic`. Sources: Evans, DDD; Vaughn Vernon, "Effective Aggregate Design."

### 4.4 Repository
- **Definition.** A collection-like abstraction for retrieving and persisting **aggregates**, hiding the storage mechanism behind a domain-shaped interface.
- **Use when.** You have aggregates to reconstitute and persist as units; you want the domain to express persistence in its own terms (`orders.findById`, `orders.save`) and to swap or fake the store in tests.
- **Do NOT use when / simpler alternative.** When your ORM/data-mapper *already* provides a repository-like, testable abstraction, wrapping it in another repository per table is redundant indirection — use the ORM directly. For simple CRUD reads, a query method or the data library directly is simpler than a full repository.
- **Earns-its-place threshold.** A real aggregate exists (per 4.3), **or** you need substitution/faking in tests, **or** you must isolate domain code from a specific persistence technology.
- **Trade-offs.** Buys: persistence-ignorant domain, testable logic (in-memory repo), a clear seam for the store. Costs: another layer; the temptation to leak query concerns; can degenerate into a thin pass-through over the ORM.
- **Failure modes & smells.** One repository per database table (instead of per aggregate). Repositories that expose `IQueryable`/raw query builders, leaking persistence into the domain. A repository with one implementation and no test double (pure indirection).
- **Combines with.** Aggregates, DIP (interface owned by the domain), unit-of-work for transactions, hexagonal (repository = a port). **Conflicts with.** Active Record style (where the entity persists itself) — pick one persistence philosophy.
- **Cheapest check.** Is there an aggregate to load/save as a unit, or a test fake you actually use? If neither, and the ORM is already testable, skip the repository.
- **Evidence grade.** `established` as a pattern; the "don't wrap an ORM that's already a repository" caution is `strong-heuristic`. Sources: Evans, DDD; Fowler, PoEAA.

### 4.5 Domain service vs. Application service
- **Definition.** A **domain service** holds domain logic that doesn't naturally belong to a single entity/value object (a calculation/operation spanning several). An **application service** orchestrates a use case — loads aggregates, calls domain logic, manages the transaction — but contains *no business rules itself*.
- **Use when.** Domain service: a genuine domain operation has no natural home object (e.g., a transfer between two accounts). Application service: you need a thin use-case entry point that coordinates without owning rules.
- **Do NOT use when / simpler alternative.** Don't create domain services as a dumping ground for logic that *should* live on entities/value objects — that produces an anemic model. Don't multiply application-service layers; one thin orchestration layer is enough.
- **Earns-its-place threshold.** Domain service: the operation truly spans objects or belongs to none. Application service: you have a use case to orchestrate and want transaction/IO coordination kept out of the domain.
- **Trade-offs.** Buys: a home for cross-object domain logic; a clean orchestration boundary. Costs: blurry line between "domain" and "application" service (a recurring source of bikeshedding); risk of logic draining out of entities into services.
- **Failure modes & smells.** "Service" classes holding all the behavior while entities are anemic. Application services containing business rules (decisions, validations) instead of orchestration. Endless `XxxManager`/`XxxService` god classes.
- **Combines with.** Aggregates, repositories, domain events. **Conflicts with.** Rich-domain modelling if services hoard the logic.
- **Cheapest check.** For each method, ask: "Is this a business *decision/rule* (→ belongs in the domain, ideally on an entity/VO/domain service) or *orchestration/IO* (→ application service)?" Mixed responsibilities are the smell.
- **Evidence grade.** `established`; the domain-vs-application boundary being fuzzy is `strong-heuristic` (widely noted). Source: Evans, DDD; Vernon, IDDD.

### 4.6 Domain Events
- **Definition.** An immutable record that something significant happened in the domain (`OrderPlaced`), used to decouple side effects and coordinate across aggregates/contexts.
- **Use when.** Something happening in one aggregate must trigger work in another aggregate or context without a synchronous, tightly-coupled call; you want to decouple "what happened" from "what reacts"; you need a basis for eventual consistency across aggregates.
- **Do NOT use when / simpler alternative.** When a direct method call within one transaction is sufficient and the coupling is fine — introducing events for a single local side effect adds indirection and makes flow hard to follow. Don't event-ify everything; events shine at boundaries, not inside a single small operation.
- **Earns-its-place threshold.** A real need to decouple reactions, coordinate across aggregate/context boundaries, or support eventual consistency — not "to be decoupled" in the abstract.
- **Trade-offs.** Buys: loose coupling, extensibility (new reactions without touching the source), a natural integration/eventual-consistency mechanism. Costs: indirection (control flow is no longer linear/visible), ordering/idempotency/delivery concerns, harder debugging ("who handled this?").
- **Failure modes & smells.** Event spaghetti: cascades of events triggering events with no one able to trace the flow. Events used where a simple in-process call would do. Missing idempotency causing double-processing.
- **Combines with.** Aggregates (events emitted by roots), event sourcing (events as the source of truth), CQRS, anti-corruption layer (events crossing contexts). **Conflicts with.** A desire for simple, traceable, synchronous flow in a small app.
- **Cheapest check.** "Does a reaction need to be decoupled from the action across a boundary?" If it's one local side effect, call the method directly.
- **Evidence grade.** `established` within DDD; `strong-heuristic` on scope/granularity. Sources: Evans, DDD; Vernon, IDDD.

### 4.7 Context integration patterns (relationships between bounded contexts)
These describe how one context consumes another's model. The over-engineering guard: **choose the lightest relationship the situation allows; reserve the heavy ones (ACL) for genuinely messy or untrusted upstreams.**
- **Anti-Corruption Layer (ACL).** A translation layer that converts an external/legacy/messy model into your own clean model so foreign concepts don't leak inward. **Use when** the upstream model is messy, unstable, or semantically mismatched and you must protect your domain. **Do NOT use when** the upstream model is clean and aligns with yours (a direct mapping or conformist relationship is cheaper). `established` — the canonical defense against a vendor/legacy model contaminating your core.
- **Shared Kernel.** A small shared model/code subset that two contexts agree to co-own and co-change carefully. **Use when** two teams share a genuinely common, stable concept and the coordination cost is worth avoiding duplication. **Do NOT use when** teams can't coordinate tightly — a shared kernel that one team changes unilaterally becomes a breakage source; prefer separate models. `strong-heuristic`.
- **Conformist.** The downstream simply adopts the upstream's model as-is (no translation). **Use when** the upstream model is acceptable and you have no leverage/need to translate; cheapest option. **Do NOT use when** the upstream model is messy and would corrupt your domain (use ACL). `established`.
- **Customer/Supplier.** Upstream and downstream are in a negotiated relationship where downstream needs influence upstream's roadmap. **Use when** there's an organizational relationship allowing negotiation. `strong-heuristic`.
- **Open Host Service / Published Language.** Upstream publishes a well-defined, stable protocol/format (e.g., a documented API + schema) for many consumers. **Use when** one context serves many downstreams and wants to avoid bespoke integrations. `established`.
- **Separate Ways.** Decline to integrate at all when the cost outweighs the benefit. **Use when** integration is expensive and the value is low — sometimes the right call is no integration. `strong-heuristic`.
- **Evidence grade (group).** `established` as a vocabulary. Source: Evans, DDD (Context Mapping); Vernon, IDDD.

---

## 5. Code organization

### 5.1 Package-by-feature vs. Package-by-layer
- **Definition.** *By-layer:* top-level folders by technical role (`controllers/`, `services/`, `repositories/`, `models/`). *By-feature:* top-level folders by business capability (`billing/`, `orders/`, `users/`), each containing its own controller/service/data code.
- **Use when (by-feature, the recommended default).** Almost always for application code — it gives change-locality (a feature lives in one folder), supports parallel work, and reveals what the app *does*.
- **Use when (by-layer).** Rarely as the *top* level; acceptable *within* a feature or for a thin app where the layer is the only meaningful axis. Frameworks sometimes impose it; resist letting it dominate the top level.
- **Do NOT use when / simpler alternative.** Don't default to by-layer just because tutorials do — it scatters each feature across the tree and turns the folder structure into a description of your framework rather than your domain.
- **Earns-its-place threshold.** By-feature: free and beneficial from day one. By-layer at top level: only when there is genuinely no feature axis (rare).
- **Trade-offs.** By-feature buys change-locality and screaming architecture; costs a small amount of deliberate handling for shared/cross-cutting code. By-layer buys "all controllers in one place" (rarely the axis of change); costs feature-scatter.
- **Failure modes & smells.** A `models/` folder with 200 unrelated classes; a feature change that edits four sibling folders; new engineers unable to tell what the app does from the top-level tree.
- **Combines with.** Vertical-slice, screaming architecture, modular monolith. **Conflicts with.** Top-level by-layer.
- **Cheapest check.** Look at the top-level folders: do they name business capabilities or technical roles? Capabilities = good default.
- **Evidence grade.** `strong-heuristic` (strongly favored by most practitioners). Sources: Robert C. Martin ("Screaming Architecture"); the broad package-by-feature consensus.

### 5.2 Screaming Architecture
- **Definition.** The top-level structure should "scream" the domain/use cases (a `Billing`/`Reservations` system), not the framework (a "Rails app" / "Spring app").
- **Use when.** Always, as an organizing aspiration — the directory layout should communicate intent and business purpose.
- **Do NOT use when / simpler alternative.** It's a principle, not machinery; there's nothing to over-build. The failure is the opposite: letting the framework's conventions name your top level.
- **Earns-its-place threshold.** Free.
- **Trade-offs.** Buys: instant comprehension of what the system is about; supports package-by-feature. Costs: occasionally fights a framework's default scaffolding.
- **Failure modes & smells.** Top-level folders named after the framework's MVC roles; you can't tell whether the app sells insurance or books flights from its structure.
- **Combines with.** Package-by-feature, vertical-slice. **Conflicts with.** Framework-dictated by-layer scaffolding.
- **Cheapest check.** Show the top-level tree to someone unfamiliar: can they guess what the business does? 
- **Evidence grade.** `strong-heuristic`. Source: Robert C. Martin, "Screaming Architecture" (*Clean Architecture*).

### 5.3 Where boundaries should fall (folder/module boundary principles)
- **Definition.** Boundaries (module/package edges) should align with **reasons to change** and **bounded contexts**, not with technical layers or arbitrary size limits.
- **Use when.** Deciding how to split a growing codebase into modules.
- **Practical rules.** Put things that change together in the same place (CCP). Don't force consumers to depend on parts they don't use (CRP). Keep the boundary's public surface small and explicit; hide internals. Align module boundaries with bounded contexts. Keep the dependency graph acyclic (ADP).
- **Do NOT use when / simpler alternative.** Don't pre-split a small codebase into many modules "for cleanliness." Start with package-by-feature folders; promote a folder to an enforced module only when a real boundary (team/context/independent-change) appears.
- **Failure modes & smells.** Boundaries drawn by technical layer (so every feature crosses them); a "common/utils" module everyone depends on (a coupling magnet); boundaries with huge public surfaces that expose internals.
- **Combines with.** Modular monolith, DDD bounded contexts, CCP/CRP/ADP.
- **Cheapest check.** Does a typical change stay within one boundary? Does each boundary have a small, intentional public interface?
- **Evidence grade.** `strong-heuristic`. Sources: Martin (component principles); Evans (bounded contexts).

---

## 6. Cross-cutting concerns (done cleanly)

### 6.1 Middleware / Decorator / Aspect for cross-cutting concerns
- **Definition.** Handle concerns that touch many operations (authentication/authorization, validation, logging, error handling, transactions, caching, retries) in a single composable place — a middleware pipeline, decorator wrapper, or aspect — instead of scattering them through every function.
- **Use when.** The *same* concern is needed across many handlers/use cases and is currently (or would be) copy-pasted; the concern is orthogonal to business logic.
- **Do NOT use when / simpler alternative.** When a concern appears in one or two places, just write it inline or in a small shared function — a full aspect/decorator framework for two call sites is over-engineering. Prefer explicit middleware/decorators over "magic" AOP weaving when traceability matters (implicit aspect weaving can make control flow hard to follow).
- **Earns-its-place threshold.** A genuinely cross-cutting concern repeated across many sites, where centralizing removes real duplication and the risk of inconsistent application (e.g., one handler forgetting auth).
- **Trade-offs.** Buys: one place to change the concern; consistent application; business logic stays clean and focused. Costs: indirection (the concern isn't visible at the call site); ordering/composition complexity in the pipeline; debugging "where did this behavior come from?".
- **Failure modes & smells.** Auth/validation/logging copy-pasted into every handler (the problem this solves). Conversely, a deep middleware stack where request behavior is impossible to trace, or "magic" annotations doing surprising things far from the code.
- **Per-concern notes.**
  - **Auth (authn/authz):** centralize in middleware/policy; keep business logic unaware of transport-level auth where possible.
  - **Validation:** input/structural validation at the edge (middleware/DTO); *domain* invariants belong in the domain (value objects/aggregates), not in edge validators. Don't conflate the two.
  - **Logging:** structured, via middleware/decorators or a logging port; avoid scattering ad-hoc log lines that duplicate concerns.
  - **Error handling:** a single error-to-response mapping boundary (e.g., one error-handling middleware) rather than try/catch noise in every handler.
  - **Transactions:** wrap a use case in one transactional boundary (decorator/unit-of-work) — one transaction per use case / per aggregate; avoid transactions sprawling through business logic or spanning aggregates.
- **Combines with.** Hexagonal (concerns at the edges), application services (transaction boundary), DIP. **Conflicts with.** Scattering concerns inline at scale.
- **Cheapest check.** Is this concern repeated across many handlers? If yes, centralize. If it's in one place, leave it inline.
- **Evidence grade.** `established` (middleware/decorator); AOP "magic" weaving is `strong-heuristic`/`contested` on traceability grounds. Sources: GoF (Decorator); Fowler (PoEAA — Unit of Work); widespread middleware practice.

---

## 7. Code-level design patterns (GoF and beyond)

> **The over-application warning (read first).** GoF patterns are a *vocabulary* for structures that recur — not a checklist of things to add. Reaching for a pattern before the recurring structure exists is the single biggest source of agent over-engineering. **For every pattern below, the default is "you probably don't need this yet."** The classic smell is a `Factory`, `Strategy`, or `Manager` introduced with a single implementation, "for flexibility." Apply the **rule of three**: don't abstract a variation until you've seen it three times. Patterns are recognized in refactoring, not imposed up front. (Source: Gang of Four, *Design Patterns*, 1994; Fowler, *Refactoring*; this catalog's "when NOT to" emphasis is the priority field.)

Tightened schema: **Use when / Don't use (simpler thing) / Earns its place / Misapplication smell.**

### 7.1 Strategy
- **Use when.** You have *multiple, co-existing* interchangeable algorithms/behaviors selected at runtime, and they actually vary.
- **Don't use (simpler thing).** With one algorithm and no second on the horizon — just write the function. A simple conditional or a function parameter often beats a strategy hierarchy.
- **Earns its place.** A *second* real strategy exists now (not hypothetically), or behavior must be swapped at runtime/config.
- **Misapplication smell.** A strategy interface with one implementation; a "pluggable" design where nothing else ever plugs in.

### 7.2 Factory Method / Abstract Factory
- **Use when.** Object creation is genuinely complex, varies by family/config, or you must decouple callers from concrete types that legitimately differ.
- **Don't use (simpler thing).** When `new Thing(...)` works and there's one concrete type — a factory adds a layer for nothing. Plain constructors and simple builder functions usually suffice.
- **Earns its place.** Multiple product families, or construction logic that is complex/duplicated and must be centralized, or a real need to vary the concrete type.
- **Misapplication smell.** A factory that always returns the same single type; "AbstractFactoryFactory" indirection; a factory wrapping a one-line constructor.

### 7.3 Builder
- **Use when.** Constructing an object with many optional parameters or step-by-step assembly, where telescoping constructors get unwieldy.
- **Don't use (simpler thing).** For 2–3 parameters — just use the constructor (or named/default args in languages that have them).
- **Earns its place.** Many optional fields or a genuinely multi-step construction with validation along the way.
- **Misapplication smell.** A builder for a two-field object; a builder that's just constructor-with-extra-steps.

### 7.4 Observer / Publish-Subscribe
- **Use when.** One change must notify many independent, loosely-coupled reactors that you don't want the source to know about.
- **Don't use (simpler thing).** When there's one known reactor and a direct call is clearer — observers obscure control flow. Domain events (4.6) are the domain-level form; the same cautions apply.
- **Earns its place.** Multiple, changing subscribers and a real need to decouple producer from consumers.
- **Misapplication smell.** Event indirection for a single hard-wired listener; untraceable notification cascades.

### 7.5 Decorator
- **Use when.** You need to add responsibilities to objects dynamically/compositionally (e.g., wrapping a handler with logging then auth then caching) without subclass explosion.
- **Don't use (simpler thing).** When behavior is fixed — just put it in the method. For cross-cutting concerns at scale, middleware (6.1) is often the cleaner form.
- **Earns its place.** Behaviors that genuinely compose in varying combinations at runtime.
- **Misapplication smell.** A single decorator that never composes with anything; decoration where a simple inline call would do.

### 7.6 Adapter
- **Use when.** You must make an existing/incompatible interface fit what your code expects (wrapping a third-party or legacy API).
- **Don't use (simpler thing).** When the interface already fits — no adapter needed.
- **Earns its place.** A real interface mismatch at a boundary (this is the everyday hero pattern of hexagonal architecture and ACLs).
- **Misapplication smell.** An adapter that just forwards calls 1:1 to an already-compatible interface (pointless pass-through).

### 7.7 Facade
- **Use when.** You want to offer a simple, unified entry point over a complex subsystem.
- **Don't use (simpler thing).** When the subsystem is already simple — a facade over one class is noise.
- **Earns its place.** A genuinely complex subsystem that many callers would otherwise wire up themselves.
- **Misapplication smell.** A facade wrapping a single underlying object; a "service" that just delegates one call.

### 7.8 Template Method
- **Use when.** Several variants share a fixed algorithm skeleton differing only in specific steps.
- **Don't use (simpler thing).** With one variant; often **composition/strategy** is more flexible than the inheritance this relies on. Favor composition over inheritance generally.
- **Earns its place.** Multiple variants with a truly shared skeleton and small varying steps.
- **Misapplication smell.** Deep inheritance hierarchies created to share a few lines; an abstract base with one subclass.

### 7.9 Command
- **Use when.** You must represent an action as an object — to queue, log, undo/redo, or dispatch it (e.g., CQRS commands, task queues).
- **Don't use (simpler thing).** When you can just call the method — don't objectify every action.
- **Earns its place.** A real need for queuing, undo, audit, or uniform dispatch.
- **Misapplication smell.** Command objects with no queue/undo/dispatch need — a method call dressed up as a class.

### 7.10 Singleton
- **Use when.** *Rarely.* A genuinely single, stateless, globally-shared resource where one instance is a real invariant.
- **Don't use (simpler thing — usually).** Most "singletons" are global mutable state in disguise → prefer **dependency injection** of a single instance managed by the composition root. This keeps things testable.
- **Earns its place.** Almost never as the GoF pattern; the *need* (one shared instance) is usually better met by DI lifetime management.
- **Misapplication smell.** Global state that makes code untestable and order-dependent; singletons reached for hidden coupling. Widely treated as an **anti-pattern** in modern practice.

### 7.11 Mediator
- **Use when.** Many objects interact in complex ways and you want to centralize/decouple their coordination (also the basis of "mediator" request dispatch in some vertical-slice/CQRS setups).
- **Don't use (simpler thing).** When a couple of objects talk directly without trouble — a mediator adds an indirection hub. Don't route everything through a mediator just to "decouple."
- **Earns its place.** Genuinely tangled many-to-many interaction that the mediator demonstrably simplifies.
- **Misapplication smell.** A mediator that becomes a god object; indirection with no reduction in coupling.

### 7.12 State
- **Use when.** An object's behavior changes across well-defined states and the state-transition logic is otherwise a sprawling conditional.
- **Don't use (simpler thing).** For two states and a boolean — an `if`/enum is clearer.
- **Earns its place.** A real state machine with several states and complex transitions.
- **Misapplication smell.** State classes for a two-value flag; more ceremony than the conditional it replaced.

> Other GoF patterns (Proxy, Composite, Chain of Responsibility, Visitor, Flyweight, Bridge, Iterator, Memento, Prototype, Interpreter) follow the same rule: **introduce only when the recurring structure they name has actually appeared.** Each has a narrow, real use; none should be added speculatively.

---

## 8. CQRS and Event Sourcing (code level)

### 8.1 CQRS (Command Query Responsibility Segregation)
- **Definition.** Separate the model/path for **writes (commands)** from the model/path for **reads (queries)**, instead of one model serving both.
- **Use when.** Reads and writes have genuinely different shapes or scaling needs; complex queries are distorting the write model; you want independent optimization of reads (denormalized views) and writes (rich domain model); high read/write asymmetry that you've *measured*.
- **Do NOT use when / simpler alternative.** For ordinary CRUD where one model serves both fine — CQRS doubles the models and the mapping for no benefit. **Note the spectrum:** lightweight CQRS can be *just separate read query methods/objects* in the same service; you do **not** need separate databases, message buses, or eventual consistency to "do CQRS." Start there.
- **Earns-its-place threshold.** A concrete, measured asymmetry: queries that twist the write model, or read scaling that needs separate denormalized views — not "CQRS is best practice."
- **Trade-offs.** Buys: independently optimizable read and write sides; cleaner write model; tailored read models. Costs: two models to maintain and keep in sync; if the read side is a separate store, eventual consistency and its complexity; more moving parts.
- **Failure modes & smells.** Full CQRS-with-separate-stores-and-buses applied to a small CRUD app. Treating CQRS as inseparable from event sourcing (it is not). Read/write divergence bugs from poorly-managed synchronization.
- **Combines with.** Vertical-slice (handler-per-command/query), domain events, event sourcing (optional), separate read models. **Conflicts with.** A single shared model when there's no asymmetry to justify splitting.
- **Cheapest check.** Can you name a query that's awkward because it shares the write model, or a measured read-scaling need? If not, keep one model.
- **Evidence grade.** `strong-heuristic`; frequently over-applied. Sources: Greg Young; Udi Dahan; Fowler ("CQRS" bliki, which explicitly cautions against default use).

### 8.2 Event Sourcing
- **Definition.** Persist state as an **append-only log of events**; current state is derived by replaying events, rather than storing only the latest snapshot.
- **Use when.** Full history/audit is a genuine, stated requirement (regulatory audit, "show me state as of any past date," the event log *is* the product); you need temporal queries, replay, or to derive multiple projections from the same facts; the domain is naturally event-driven.
- **Do NOT use when / simpler alternative.** For most apps — storing current state in a normal database is far simpler and sufficient. If you only need *some* audit, an audit/history table or change-data-capture is dramatically cheaper than full event sourcing. **This is one of the most over-applied patterns; the default is: don't.**
- **Earns-its-place threshold.** A hard requirement that can't be met by current-state storage + an audit log: you must reconstruct arbitrary past state, or replay to build new projections, or history is the core value.
- **Trade-offs.** Buys: complete audit trail, time-travel/temporal queries, replayable projections, events as integration facts. Costs: high complexity — event versioning/schema evolution, snapshots for performance, rebuilding projections, eventual consistency on read models, harder debugging, no simple "update the row." Hard to reverse once adopted broadly.
- **Failure modes & smells.** Event-sourcing the whole system "to be modern." Underestimating event-schema evolution (old events must remain replayable forever). No snapshot strategy → slow rehydration. Coupling it reflexively to CQRS everywhere. Choosing it without a concrete temporal/audit requirement.
- **Combines with.** Domain events, CQRS (read models as projections), aggregates (the consistency boundary that emits events). **Conflicts with.** Simplicity; CRUD; teams without the operational maturity for it.
- **Cheapest check.** "Is full, replayable history a real requirement here — and is it insufficient to add an audit table to normal storage?" If an audit table would do, don't event-source. Apply it to the *specific aggregate* that needs it, never reflexively system-wide.
- **Evidence grade.** `strong-heuristic` / `contested` on scope. Sources: Greg Young; Fowler ("Event Sourcing" bliki); Vernon, IDDD.

---

## 9. Testability as an architectural property

> Core idea: testability is not a test-suite concern bolted on afterward — it is a *consequence of structure*. Code is hard to test exactly where it is welded to I/O, time, randomness, or external services. The architectural job is to put **seams** at those welds so logic can be exercised in isolation. (Sources: Michael Feathers, *Working Effectively with Legacy Code* — "seams"; Mike Cohn, *Succeeding with Agile* — the test pyramid.)

### 9.1 Test pyramid (and the seams it implies)
- **Definition.** Favor many fast, isolated **unit** tests at the base, fewer **integration** tests in the middle, and few slow **end-to-end** tests at the top.
- **Use when.** As the default shape for a test suite — most coverage from cheap, fast tests; reserve expensive end-to-end tests for critical paths.
- **Do NOT use when / simpler alternative / debate.** `contested` at the edges: the **"testing trophy"** (Kent C. Dodds) argues for proportionally more *integration* tests in many web apps, because over-isolated unit tests can test mocks rather than behavior. Reconcile: write unit tests where logic is rich and isolable; lean on integration tests where the value is in components working together; avoid both over-mocked unit tests and an all-E2E "ice-cream cone."
- **Earns-its-place threshold.** The pyramid is a default proportion, not machinery; adopt it, then adjust toward integration where units would only test mocks.
- **Trade-offs.** Buys: fast feedback, cheap maintenance, pinpoint failure localization. Costs: heavy mocking can ossify implementation details if units are drawn too small.
- **Failure modes & smells.** The "ice-cream cone" (mostly slow E2E, few units) → slow, flaky, expensive. Unit tests that mock everything and assert on mocks (testing the test). 
- **Combines with.** DI, hexagonal (test the core without infrastructure), repository fakes. 
- **Cheapest check.** Are most tests fast and isolated, with a thin layer of integration/E2E on top? Are unit tests asserting behavior, not mock call-counts?
- **Evidence grade.** Pyramid `established`; testing-trophy emphasis `contested`. Sources: Cohn; Fowler ("TestPyramid"); Dodds ("Testing Trophy").

### 9.2 Seams for testing
- **Definition.** A **seam** is a place where you can substitute behavior without editing the code under test (e.g., an injected dependency, an interface, a clock abstraction).
- **Use when.** Isolating logic from a hard-to-control collaborator (DB, network, time, randomness) so it can be tested deterministically.
- **Do NOT use when / simpler alternative.** Don't create seams for code that is already pure and deterministic — there's nothing to isolate. Don't introduce an interface solely to enable a mock if the real thing is fast and deterministic (e.g., a pure function); over-mocking is its own anti-pattern.
- **Earns-its-place threshold.** A *measured* testability problem: logic you genuinely cannot test cheaply because it's welded to I/O/time/external state.
- **Trade-offs.** Buys: deterministic, fast, isolated tests. Costs: indirection (interfaces, injected clocks); risk of mocking so much you test the wiring, not the behavior.
- **Failure modes & smells.** Interfaces created only to satisfy a mock, with one production implementation. Tests that break on every refactor because they assert on mock interactions. Hidden statics/singletons/`new` calls deep inside that leave no seam (untestable islands).
- **Combines with.** DI, hexagonal/ports, repository fakes, clock/time abstractions. **Conflicts with.** Hard-coded `new`, statics, and singletons that admit no substitution.
- **Cheapest check.** "Can I exercise this logic without real I/O/time/network?" If not, you need a seam *there* — and only there.
- **Evidence grade.** `established`. Source: Michael Feathers, *Working Effectively with Legacy Code*.

### 9.3 Dependency Injection (for isolation, not as a religion)
- **Definition.** Provide a component's dependencies from outside (constructor/parameters) rather than having it construct or locate them, so they can be substituted.
- **Use when.** A component depends on a volatile or hard-to-test collaborator you want to swap in tests or configuration; managing object lifetimes and wiring in a non-trivial app.
- **Do NOT use when / simpler alternative.** **Manual/constructor DI is the default; a DI container is not required.** Don't add a DI framework to a small app — passing dependencies explicitly is simpler and clearer far longer than people assume. Don't inject things that are stable and have no test/substitution need (don't inject the standard library).
- **Earns-its-place threshold.** Real substitution/test/lifetime needs across enough components that manual wiring is genuinely painful (then a container helps); for a few components, manual DI wins.
- **Trade-offs.** Buys: testability (inject fakes), configurability, explicit dependencies (constructor signatures document needs). Costs: wiring overhead; containers add "magic" and indirection; over-injection inflates constructors.
- **Failure modes & smells.** A DI container in a 1,000-line app. Constructors with 12 injected dependencies (a god-object smell, not a DI win). **Service Locator** used as a hidden global (anti-pattern: dependencies become implicit again). Interfaces-for-everything purely to enable injection.
- **Combines with.** Hexagonal/ports, DIP, repository, seams, composition root. **Conflicts with.** Service locator / hidden global state; singletons.
- **Cheapest check.** Are dependencies explicit (visible in the signature) and substitutable in tests, without a framework you didn't need?
- **Evidence grade.** DI `established`; "container not always needed / prefer constructor injection / avoid service locator" `strong-heuristic`. Sources: Fowler ("Inversion of Control / Dependency Injection"); Seemann & van Deursen, *Dependency Injection*.

---

## 10. Anti-patterns (first-class — the critic agent's toolkit)

Each entry leads with the **detection smell**. These are what the reviewing agent matches against to catch both premature abstraction and structural rot.

### 10.1 Big Ball of Mud
- **Detection smell.** No discernible architecture: tangled, sprawling dependencies; everything reachable from everything; changes ripple unpredictably; no module boundaries hold.
- **Why it happens.** Expedient growth with no boundary maintenance; "just one more" cross-cutting reach repeated for years.
- **What to do instead.** Establish and *enforce* boundaries (modular monolith, ADP, package-by-feature); introduce seams; strangle/refactor incrementally rather than rewrite.
- **Nuance.** Sometimes a deliberate early-stage state (move fast); the failure is letting it *persist* past the point boundaries would pay off. Source: Foote & Yoder, "Big Ball of Mud" (1997).

### 10.2 God Object / God Class (and god "Manager"/"Service")
- **Detection smell.** One class/module that knows or does too much — huge, many responsibilities, depended on by everything, central to every change; constructor with many dependencies.
- **Why it happens.** Logic accreting in one convenient place; no responsibility boundaries; service classes hoarding behavior drained from anemic entities.
- **What to do instead.** Split by responsibility (SRP/CCP); move behavior to the objects that own the data (rich domain); extract cohesive collaborators.
- **Nuance.** A large class isn't automatically a god object — the smell is *many unrelated responsibilities + central coupling*. Source: long-established OO literature.

### 10.3 Anemic Domain Model
- **Detection smell.** Domain "objects" are bags of getters/setters with no behavior; all rules live in service/manager classes; the object model mirrors database tables.
- **The genuine debate (`contested`).** **Fowler** and **Evans** call this an anti-pattern in a domain with real complexity: it claims the benefits of OO domain modelling while putting all logic in procedural services, splitting data from the behavior that governs it. **The counter-position:** for **simple CRUD** with few invariants, an anemic model + transaction-script services is perfectly appropriate and *simpler* — not every app needs a rich domain model. Some functional-programming and CQRS practitioners also deliberately separate data from behavior with good results. **Reconciliation:** "anemic" is a *misapplication* when a complex, invariant-rich domain would benefit from a rich model but logic is scattered into services; it is a *reasonable default* for genuinely simple, rule-light CRUD. The critic should flag anemia only when domain complexity warrants richness.
- **What to do instead (when warranted).** Move invariants and behavior onto entities/value objects/aggregates; keep application services to orchestration.
- **Sources.** Fowler ("AnemicDomainModel," 2003); Evans, DDD; counter-views from CRUD-pragmatist and FP communities.

### 10.4 Premature Abstraction
- **Detection smell.** Interfaces, factories, layers, generics, or plugin points with a **single implementation** and no present force; abstractions justified by "we might need…", "to be flexible," "in case." The codebase is harder to follow than the problem warrants.
- **Why it happens.** Anticipating change that hasn't arrived; cargo-culting patterns; equating abstraction with quality.
- **What to do instead.** Apply the **first-question gate (1.1)** and the **rule of three**; inline the direct version; extract the abstraction only when the second implementation or concrete change actually appears. Prefer the cost of duplication over the cost of the wrong abstraction.
- **Nuance.** The rare exception is a boundary genuinely expensive to introduce later — but those are few; name the expense explicitly. Sources: "YAGNI" (Jeffries/XP); Fowler ("Yagni"); Sandi Metz ("the wrong abstraction").

### 10.5 Over-Layering ("Lasagna")
- **Detection smell.** Many thin layers where calls pass through several near-empty pass-through methods (controller → service → manager → helper → repository, each adding nothing); DTO ↔ entity ↔ DAO mapping with no behavioral difference.
- **Why it happens.** Applying clean/onion/layered ceremony uniformly regardless of whether a feature has logic; equating layers with rigor.
- **What to do instead.** Collapse layers that add no behavior; a layer must earn its place by isolating a real concern or change. Fewer, meaningful layers.
- **Nuance.** Distinct from healthy layering — the smell is *empty* layers and mapping tax with no payoff. Source: counterpart to "lasagna code" lore; Fowler.

### 10.6 Circular Dependencies
- **Detection smell.** Modules/packages/classes that depend on each other (A→B→A), directly or transitively; the build can't determine order; you can't test or reason about one without the other.
- **Why it happens.** "Just this once" upward references; a shared utility that depends back on its consumers.
- **What to do instead.** Break the cycle: extract the shared piece into a new component both depend on, or apply DIP to invert one edge (ADP). Run cycle detection in CI.
- **Nuance.** None — cycles at the component level are unambiguously to be removed. Source: Martin (ADP).

### 10.7 Framework in the Core ("the leak")
- **Detection smell.** Domain/business code importing the web framework, ORM, serialization library, or HTTP/DB types; entities annotated with persistence/serialization concerns; the core can't be compiled or tested without the framework.
- **Why it happens.** Convenience; following framework tutorials that put everything together; no enforced dependency rule.
- **What to do instead.** Push framework/infrastructure to the edges (hexagonal/onion); keep the core dependent only on abstractions it owns (dependency rule); map between framework types and domain types at the boundary.
- **Nuance.** For a tiny app, full isolation may be overkill — but the *core importing the framework* is still a smell to watch as the app grows. Sources: Cockburn (hexagonal); Martin (dependency rule).

### 10.8 Speculative Generality
- **Detection smell.** "Just in case" hooks: unused parameters, abstract base classes with one subclass, configuration for things that never vary, extension points nothing extends, generic machinery for a single concrete case. (Closely related to premature abstraction; this is the *refactoring-smell* framing.)
- **Why it happens.** Designing for imagined future requirements.
- **What to do instead.** Remove the unused generality; build for today's known requirements; add generality when a real second case arrives. ("You aren't gonna need it.")
- **Nuance.** Genuine, *known-near-term* variation can justify a seam — but "speculative" by definition means the case hasn't materialized. Source: Fowler, *Refactoring* (code smell "Speculative Generality"); Jeffries (YAGNI).

### 10.9 Bonus smells the critic should also catch
- **Primitive obsession** — modelling domain concepts (money, email, id) as bare primitives, scattering validation; remedy: value objects (but don't wrap inert primitives reflexively).
- **Service Locator as hidden global** — dependencies fetched from a global registry instead of injected; makes dependencies implicit and code hard to test; remedy: explicit DI.
- **One-repository-per-table** — repositories mirroring tables instead of aggregates; remedy: repository per aggregate root.
- **Mock-heavy tests asserting on mocks** — tests that verify wiring, not behavior; remedy: fewer, real-collaborator or integration tests; seams only where I/O/time genuinely intrude.
- **Distributed monolith via shared schema** (relevant within a modular monolith) — modules coupled through a shared database; remedy: module-owned data with explicit interfaces.

---

## Appendix A — Pattern combination & conflict quick-reference

**Natural partners**
- Hexagonal/Onion/Clean + DIP + DI + Repository (as a port) + DDD core.
- DDD aggregates + Repositories (per aggregate) + Domain events.
- Vertical-slice + Package-by-feature + Screaming architecture + (optionally) CQRS handlers + Mediator dispatch.
- CQRS + Domain events + (optionally) Event sourcing + separate read models.
- Cross-cutting middleware/decorators + application-service transaction boundary + DIP.
- Modular monolith + DDD bounded contexts + ADP + CCP/CRP + ports per module.

**Tensions / mutually-exclusive-ish (choose deliberately)**
- Strict horizontal **layering** ⟷ **vertical-slice** / screaming architecture (organize by role vs. by feature). You can apply the dependency rule *inside* slices to get both.
- **Rich domain model (DDD)** ⟷ **anemic + transaction script** (rich vs. procedural — pick by domain complexity).
- **Active Record** (entity persists itself) ⟷ **Repository + data mapper** (pick one persistence philosophy).
- **Full Clean Architecture ceremony** ⟷ **transaction-script simplicity** (pick by complexity/longevity; don't apply uniformly).
- **AOP "magic" weaving** ⟷ **explicit middleware/decorators** (implicit power vs. traceability).
- **DI container** ⟷ **manual constructor DI** (scale-dependent; start manual).

---

## Appendix B — The one-question audit for the critic agent

For any proposed structure or abstraction, ask the proposing rationale to satisfy **all** of:

1. **Name the force.** Which present force justifies this — a second real implementation, a genuine boundary (team/context/independently-changing concern), a measured testability problem, or a demonstrated change-locality problem? If the rationale is "flexibility," "best practice," or "we might need," → **flag as speculative; recommend the direct version.**
2. **Name the second thing.** Point to the *second* implementation, the *specific* boundary, or the *concrete* change this protects against. If it can't be named, → **flag premature abstraction.**
3. **Check the cost of deferral.** Is adding this later genuinely expensive? Most internal structure is cheap to retrofit. If "later" is cheap, → **recommend deferring.**
4. **Check proportionality.** Does the machinery match the problem's complexity (CRUD vs. rule-rich domain; small app vs. long-lived system)? If clean/DDD/CQRS/ES ceremony is applied to a simple problem, → **flag over-engineering.**
5. **Check for the rot smells.** Cycles? God object? Framework in the core? Empty pass-through layers? Anemic model in a complex domain? Mocks asserting on mocks? → **flag the specific anti-pattern (Section 10).**

> **The whole playbook's success test:** given a concrete codebase of stated size and complexity, this should let an agent both pick the right structure *and* correctly decide **not** to add the layers and abstractions it doesn't need yet. If a proposal can't pass Appendix B, it has likely failed the second, harder half.

---

## Sources (canonical references)
- **Eric Evans**, *Domain-Driven Design: Tackling Complexity in the Heart of Software* (2003) — tactical & strategic DDD, bounded contexts, context mapping.
- **Vaughn Vernon**, *Implementing Domain-Driven Design* (2013) and "Effective Aggregate Design" — aggregates, repositories, events in practice.
- **Robert C. Martin**, *Clean Architecture* (2017) and *Agile Software Development, Principles, Patterns, and Practices* — SOLID, the dependency rule, component cohesion/coupling principles (REP/CCP/CRP, ADP/SDP/SAP), Screaming Architecture.
- **Martin Fowler**, *Patterns of Enterprise Application Architecture* (2002), *Refactoring* (1999/2018), and bliki entries ("AnemicDomainModel," "CQRS," "Event Sourcing," "Yagni," "TestPyramid," "Inversion of Control") — enterprise patterns, code smells, and explicit cautions against default use of CQRS/ES.
- **Alistair Cockburn**, "Hexagonal Architecture (Ports & Adapters)" (2005).
- **Jeffrey Palermo**, "The Onion Architecture" (2008).
- **Jimmy Bogard**, "Vertical Slice Architecture."
- **Simon Brown** (C4 model) and **Kamil Grzybek** ("Modular Monolith") — modular monolith structure.
- **Gang of Four (Gamma, Helm, Johnson, Vlissides)**, *Design Patterns* (1994) — code-level patterns as a vocabulary.
- **Michael Feathers**, *Working Effectively with Legacy Code* (2004) — seams and testability.
- **Mike Cohn**, *Succeeding with Agile* (test pyramid); **Kent C. Dodds**, "The Testing Trophy" (the contested counter-emphasis).
- **Greg Young** / **Udi Dahan** — CQRS and event sourcing foundations and cautions.
- **Foote & Yoder**, "Big Ball of Mud" (1997); **Sandi Metz**, "The Wrong Abstraction" — anti-pattern framing and the duplication-vs-wrong-abstraction trade-off.

*Evidence grades reflect the state of professional consensus: `established` = canonical and broadly agreed; `strong-heuristic` = widely endorsed guideline, context-dependent; `contested` = respected sources genuinely disagree (notably: how much architecture a small app needs, anemic vs. rich domain model, the test pyramid vs. testing trophy, and when CQRS/event-sourcing are worth their cost).*
