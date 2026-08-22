# System Design patterns — reference library

> **How this is used in this system.** This is the macro / between-components playbook
> (data stores, scaling, caching, messaging, consistency, APIs, reliability, deployment
> topology). `master-architect` reads it in **Phase M2 (system design)** before proposing the
> system shape; `master-critic` reads it in its **"check against the playbook"** step — matching
> a proposal against each pattern's *Use when* / *Earns-its-place* field, and using the **§0
> first-question gate** and the thresholds to BLOCK premature patterns (its #1 YAGNI job).
> `feature-critic` may consult it too.
>
> Weight by **evidence grade**: an `established` entry settles a point and is cited, not debated;
> a `contested` one goes to **debate**, never asserted as a winner. This is *some level of truth*
> — it grounds pattern-choice and prematurity; whether a tech premise holds for *your* workload
> still needs a **PoC** (Constitution Art. 1), and the specific-to-this-domain judgment still
> needs debate.
>
> Owner-provided deep-research output. Human-curated; edits to this file are a human decision.

---

System Design Patterns — A Decision Playbook
Audience: an AI agent that proposes system designs, and a second AI agent that critiques them.
Purpose: ground proposals and reviews in matchable decision rules — not to teach the patterns,
but to decide when to apply each one and, just as importantly, when not to.

This is a playbook, not an encyclopedia. Every entry tells you when to reach for a pattern and
what to use instead when it is overkill.

How to use this (agent instructions)
Read in this order. Stop as early as the situation allows.
  1. The First-Question Gate (§0). Ask whether the problem the pattern solves actually exists
     yet. If not → take the boring default and stop.
  2. Default ("boring") choice per category (§1). Start every category here. Escalate only on the
     named signal.
  3. The Catalog (§2). Match the situation against the Use when / Earns-its-place fields. A
     pattern is a candidate only if a present, measured problem matches.
  4. Situation → Pattern matrix (§3). Fast lookup from a symptom to a candidate + the trap.
  5. Anti-patterns (§4). The critic's checklist — the smells that reveal a pattern was applied too
     early or wrongly.

Governing principles (apply to every decision):
     YAGNI — "You Aren't Gonna Need It." Do not build for a load, scale, or org size you do not
     have and cannot show is imminent.
     Choose Boring Technology (Dan McKinley) — prefer well-understood, operationally-
     cheap tools; spend your limited "innovation tokens" only where the boring option
     genuinely fails.
     Default stance for every pattern: "you probably don't need this yet." The pattern must
     justify itself against a concrete, present problem.

Evidence-grade key:
      established — broad consensus, well-proven across the industry; safe to treat as fact.

      strong-heuristic — widely recommended and usually right, but judgment- and context-
     dependent.
      contested — genuinely debated. Both sides are presented with the conditions under
     which each is right. Never assert a winner.
   The one test this document must pass: given a concrete project at a stated scale, can an
   agent use this to pick the right patterns AND correctly decide not to apply the ones it doesn't
   need yet? If only the first, it has failed.

§0 — The First-Question Gate (YAGNI-first)
Before proposing any pattern below, the proposing agent must answer these in order. A "no"
sends you to the boring default and ends the decision.
  1. Do you have the problem yet? Is there a measured signal (latency violating an SLO, a node
     at capacity, a deploy bottleneck across teams, a real consistency bug) — or only an
     anticipated one? No measured signal → boring default, stop.
  2. Will the simple option fail at the scale you can actually project for the next ~12–18
     months? Use real or conservatively-estimated numbers, not "to be safe." If the simple
     option survives the projection → boring default, stop.
  3. Is the cost of the pattern (operational burden, new failure modes, more moving parts)
     smaller than the cost of the problem it removes? If not → boring default, stop.
  4. Can it be deferred cheaply? Most patterns can be added later behind a stable interface. If
     yes, and 1–3 are uncertain → defer, take the boring default, stop.

The critic agent should flag any proposal that introduces a pattern without passing all four —
especially any that cite "scalability," "future-proofing," or "best practice" as the justification
rather than a present, measured problem.

§1 — Default ("boring") choice per category
Start here for every category. The right-hand column is the single signal that justifies escalating
into the catalog.
Category           Boring default                    The one signal that justifies escalating

Datastore          One relational database           A specific access pattern the relational DB
                   (Postgres/MySQL),                 measurably can't serve well (e.g., full-text search,
                   normalized, with indexes          graph traversal, time-series rollups, extreme write
                                                     throughput)

Scaling            Vertical scaling (a bigger box)   One machine can no longer hold the working set
                   + connection pooling              or sustain the write/IO rate, and you've already
                                                     added read replicas where reads dominate

Reads at scale     Query the primary; add            Read load measurably saturates the primary (e.g.,
                   indexes                           DB CPU dominated by reads) → read replicas, then
                                                     caching

Caching            No cache; rely on the DB and      A read is hot, expensive, and tolerant of slight
                   indexes                           staleness, and DB load or read latency is
                                                     measurably hurting

Communication      Synchronous REST over             A call must not block the caller, or must fan out to
                   HTTP/JSON within one              many consumers, or needs durable buffering
                   app/process                       under load → async/messaging

Consistency        Strong consistency inside a       You've genuinely crossed a data/service boundary
                   single relational DB              that one transaction can't span → idempotency +
                   transaction                       eventual consistency (NOT distributed
                                                     transactions)

Deployment unit    A single deployable (a            Multiple teams' deploy cadences collide on one
                   monolith), internally modular     codebase, or one component has a wildly different
                                                     scaling/runtime profile

Analytics / data   Periodic batch job reading        Latency from "event happened" to "insight
movement           from a replica                    available" must drop below what batch can give
                                                     (minutes→seconds) → streaming

Reliability        Sensible timeouts + bounded       A dependency's failure or slowness can cascade
                   retries with backoff & jitter     and take down the caller → circuit breaker /
                                                     bulkhead / load shedding

API style          REST + JSON                       A concrete REST pain you can name (over/under-
                                                     fetching, chatty mobile clients, strict typed
                                                     contracts, streaming) → GraphQL / gRPC
 Category            Boring default                 The one signal that justifies escalating

 Observability       Structured logs + a few key    You can't answer "where is the latency / error
                     metrics                        coming from?" across services → distributed
                                                    tracing

If in doubt for any row: stay in the left column.

§2 — The Pattern Catalog
Every pattern uses the same fields so an agent can match a situation:
     Definition — one plain sentence.
     Use when — concrete triggering signals.
     Don't use when / simpler — the over-application guard and the cheaper alternative.
     Earns its place at — the concrete scale/load/team-size/failure-rate where it stops being
     premature (orders of magnitude; heuristics flagged).
     Trade-offs — what it buys / what it costs.
     Failure modes & smells — how it goes wrong; symptoms it was the wrong choice.
     Combines / conflicts — partner and mutually-exclusive patterns.
     Cheapest PoC to verify — the smallest measurement that confirms or refutes it for this
     workload.
     Evidence — grade + source.

§2.1 Data Storage

Single Relational Database (the default)
One SQL database (Postgres/MySQL), normalized, with appropriate indexes, holding your
transactional data.
     Use when: almost always at the start; you need ACID transactions, ad-hoc queries, joins,
     and strong consistency on related data.
     Don't use when / simpler: there is no simpler option — this is the simple option. Only move
     off it for a named access pattern it can't serve (see below).
     Earns its place at: from line one to, for many products, millions of users. A single well-
     tuned Postgres node handles tens of thousands of transactions/sec and terabytes of data
     (heuristic).
     Trade-offs: buys correctness, flexibility, mature tooling, one thing to operate; costs a single
     write ceiling (one primary) eventually.
     Failure modes & smells: the smell is replacing it before any query is actually slow; or
     storing blobs/logs/search text in it and then blaming the DB.
     Combines / conflicts: combines with read replicas, caching, search engines (for the
     workloads it's bad at). Conflicts with premature polyglot persistence.
     Cheapest PoC to verify: load-test your real query mix at projected volume against one
     instance with proper indexes. Most "we need NoSQL" claims die here.
     Evidence: established — Kleppmann, Designing Data-Intensive Applications (DDIA,
     2017); the "default to Postgres" heuristic is near-universal in modern engineering writing.

Indexing & Query Tuning (before anything fancier)
Add B-tree/partial/composite indexes and fix slow queries before reaching for new datastores or
caches.
     Use when: any read is slow. Always the first move.
     Don't use when / simpler: rarely skipped; only when the query plan is already optimal and
     the bottleneck is genuinely volume.
     Earns its place at: immediately — it is the cheapest performance win available.
     Trade-offs: buys large read speedups cheaply; costs slower writes and storage per index,
     and index bloat if over-applied.
     Failure modes & smells: indexing everything (write amplification); adding a cache to hide
     a missing index.
     Combines / conflicts: precedes caching, replicas, sharding. A missing index is the most
     common false signal that "we need to scale."
     Cheapest PoC to verify: run EXPLAIN ANALYZE on the slow query; add the index; re-
     measure.
     Evidence: established — DDIA; standard DBA practice.

Document Database (e.g., MongoDB, DynamoDB-as-document)
Stores semi-structured records (JSON-like documents) addressed by key, with flexible schema.
     Use when: data is naturally self-contained per record, accessed by key, with a
     varying/sparse schema; you rarely join across records; you want the document shape to
     match the access pattern.
     Don't use when / simpler: you need joins, multi-record transactions, or ad-hoc analytical
     queries → relational. "Flexible schema" is often a euphemism for "we didn't model the data."
     Earns its place at: when a relational schema would require many tables/joins for a read that
     is always fetched as one aggregate, at high read volume.
     Trade-offs: buys schema flexibility and aggregate-oriented reads; costs harder cross-
     document consistency, duplicated data, and weaker ad-hoc querying.
     Failure modes & smells: modeling relational data as documents and then needing app-side
     joins; unbounded document growth; using it as the default "because SQL is old."
     Combines / conflicts: combines with denormalization, CQRS read models. Conflicts with
     rich relational/transactional needs.
     Cheapest PoC to verify: model your top 3 reads and writes as documents; check whether
     any read forces a cross-document join or any write needs a multi-document transaction. If
     yes, relational wins.
     Evidence: strong-heuristic — DDIA (Ch. 2, document vs relational); fit is access-
     pattern-dependent.

Key-Value Store (e.g., Redis, DynamoDB-as-KV)
A hash map at scale: get/set a value by a single key, very fast.
     Use when: lookups are purely by key (sessions, feature flags, counters, computed results),
     with simple values and high throughput / low latency.
     Don't use when / simpler: you need to query by anything other than the key, or need
     relations → relational/search. Often this role is better filled by a cache than a primary store.
     Earns its place at: sub-millisecond key lookups at high QPS, or when a relational round-trip
     per lookup is measurably too slow.
     Trade-offs: buys speed and simplicity; costs query power (no secondary queries unless the
     engine adds them) and, if used as source of truth, durability/consistency concerns.
     Failure modes & smells: treating an in-memory cache as the system of record (data loss on
     eviction/restart); cramming structured query needs onto a KV store.
     Combines / conflicts: combines with cache-aside, rate limiting, leaderboards. Conflicts
     with relational query needs.
     Cheapest PoC to verify: confirm every access is by a known key; if you find yourself
     wanting "all values where X," it's the wrong store.
     Evidence: established — DDIA; ubiquitous for caching/session use.

Wide-Column Store (e.g., Cassandra, ScyllaDB, Bigtable)
Stores rows partitioned by key with very wide, sparse columns; optimized for huge write volumes
and known query patterns.
     Use when: very high, evenly-distributed write throughput; queries known in advance and
     designed into the partition/clustering keys; you can accept eventual consistency and
     denormalization; horizontal scale across many nodes is a hard requirement.
     Don't use when / simpler: your data fits one relational node, or your queries aren't known
     up front, or you need joins/ad-hoc queries → relational. This is one of the most over-adopted
     "scalable" stores.
     Earns its place at: sustained write rates and dataset sizes that no single primary + replicas
     can hold (multi-node, many-TB, tens-of-thousands-plus writes/sec on time-series/event
     data — heuristic).
     Trade-offs: buys linear write scaling and multi-DC replication; costs rigid query modeling
     (you design tables per query), eventual consistency, heavy operational expertise, and
     painful query evolution.
     Failure modes & smells: picking it for "future scale" with no current write pressure; hot
     partitions from a bad partition key; trying to add a new query and discovering you must
     remodel/rewrite data.
     Combines / conflicts: combines with time-series workloads, eventual consistency,
     denormalization. Conflicts with ad-hoc analytics and relational integrity.
     Cheapest PoC to verify: enumerate every query; prove each maps cleanly to a
     partition+clustering key with no hot partition and no future query you can't anticipate. If
     you can't, you're not ready.
     Evidence: strong-heuristic — DDIA; Cassandra data-modeling guidance ("model
     around queries"). Over-adoption is a recognized anti-pattern.

Graph Database (e.g., Neo4j)
Stores nodes and relationships as first-class citizens; optimized for traversing connections.
     Use when: the relationships are the core query (multi-hop traversals, shortest path,
     recommendations, fraud rings) and would require many expensive recursive joins in SQL.
     Don't use when / simpler: shallow relationships (1–2 hops) — a relational DB with foreign
     keys is simpler and faster. Most "social" features don't need a graph DB.
     Earns its place at: when traversal depth and connectedness make relational joins blow up
     (e.g., variable-depth "friends-of-friends-of-friends," large connected components).
     Trade-offs: buys natural, fast deep traversal and expressive graph queries; costs a
     specialized store to operate, weaker non-graph querying, and a smaller ecosystem.
     Failure modes & smells: using it as a general-purpose DB; modeling tabular data as a
     graph; adopting it for relationships you only ever traverse one hop.
     Combines / conflicts: combines with polyglot persistence (graph for the graph part,
     relational for the rest). Conflicts with simple relational access.
     Cheapest PoC to verify: write your hardest traversal as a recursive SQL query and measure;
     if it's fine, you don't need a graph DB.
     Evidence: established (for genuine graph workloads) — DDIA (Ch. 2, graph models).
Optimized for timestamped, append-only data with time-range queries and
downsampling/rollups.
     Use when: metrics, sensor/IoT, or event data dominated by "value over time," high ingest,
     time-window aggregations, and retention/rollup policies.
     Don't use when / simpler: low-volume time data fits fine in a relational table with a time
     index → relational (or Postgres + a time-series extension before a separate system).
     Earns its place at: ingest rates and retention windows where relational tables bloat and
     time-range queries slow down (sustained high-cardinality, high-frequency series —
     heuristic).
     Trade-offs: buys efficient time-range queries, compression, retention/downsampling; costs
     another store and limited general-purpose querying.
     Failure modes & smells: high-cardinality tag explosion (a classic TSDB killer); using it for
     non-time-series data.
     Combines / conflicts: combines with stream processing and metrics pipelines. Conflicts
     with relational/transactional workloads.
     Cheapest PoC to verify: load representative series at projected cardinality and ingest rate;
     watch cardinality and query latency. Cardinality is what usually breaks.
     Evidence: established — standard observability/IoT practice.

Search Engine / Inverted Index (e.g., Elasticsearch, OpenSearch)
A datastore optimized for full-text search, ranking, and faceted/aggregation queries via an
inverted index.
     Use when: users need free-text search, relevance ranking, typo tolerance, or faceted
     filtering that LIKE '%term%' can't serve well.
     Don't use when / simpler: basic search over modest data → your relational DB's built-in
     full-text search (e.g., Postgres tsvector ) first. Don't make it the system of record.
     Earns its place at: when relational full-text search is too slow or too weak (relevance/facets)
     at your data size and query volume.
     Trade-offs: buys powerful, fast search; costs an eventually-consistent secondary index you
     must keep in sync, plus a cluster to operate.
     Failure modes & smells: using it as the primary store (it isn't); search index drifting out of
     sync with the source of truth; reindex storms.
     Combines / conflicts: combines with CDC/outbox to sync from the source DB. Conflicts
     with being treated as a source of truth.
     Cheapest PoC to verify: try Postgres full-text search on real data/queries first; only adopt a
     search engine if relevance or latency is provably inadequate.
     Evidence: established — standard practice; "DB first, search engine when it's not
     enough" is the common heuristic.

Normalization vs Denormalization (a decision, not a store)
Normalize = store each fact once (relational default). Denormalize = duplicate data to make a
specific read fast.
     Use when (denormalize): a hot read is provably slow because of joins/aggregation, reads
     vastly outnumber writes, and slight staleness is acceptable.
     Don't use when / simpler: by default, normalize. Denormalize only after the read is shown
     slow. Premature denormalization creates update anomalies.
     Earns its place at: when join cost on the hot path is measured and material, at high
     read:write ratios (e.g., 10:1+ — heuristic).
     Trade-offs: denormalization buys read speed; costs write complexity, storage, and the risk
     of inconsistent copies.
     Failure modes & smells: duplicating data everywhere "for performance" with no
     measurement; copies drifting out of sync; every write now updating many places.
     Combines / conflicts: denormalization combines with CQRS, materialized views, caching.
     Conflicts with strong consistency guarantees on the duplicated fields.
     Cheapest PoC to verify: measure the normalized query; if it meets SLO, stay normalized.
     Evidence: established — DDIA; classic database design.

Polyglot Persistence
Using more than one type of datastore, each for the workload it fits.
     Use when: you have distinct, proven workloads (e.g., transactional + search + cache +
     analytics) that one store serves poorly, and the cost of running multiple stores is justified.
     Don't use when / simpler: early-stage or small teams — every extra store is operational
     burden, another failure mode, and a consistency seam. One relational DB often covers more
     than expected (incl. JSON columns, full-text search).
     Earns its place at: when a single store demonstrably can't meet two or more different
     access patterns at your scale, and you have the ops capacity to run each store well.
     Trade-offs: buys best-fit per workload; costs operational sprawl, data synchronization, and
     more on-call surface.
     Failure modes & smells: "right tool for the job" used to justify a zoo of stores a small team
     can't operate; data sync bugs between stores; nobody is an expert in any of them.
     Combines / conflicts: combines with CDC/outbox for syncing. Conflicts directly with
     "choose boring technology" if adopted prematurely.
     Cheapest PoC to verify: count the distinct proven access patterns and your ops headcount;
     if one store with extensions covers them, stay single.
     Evidence: strong-heuristic — Fowler ("PolyglotPersistence"); valuable at scale, a trap
     when premature.

§2.2 Scaling

Vertical Scaling (the default)
Run on a bigger machine (more CPU/RAM/IO) instead of more machines.
     Use when: you can still buy a bigger box, and the simplicity of one node is worth keeping.
     Almost always the first scaling move.
     Don't use when / simpler: you've hit the largest practical instance, or need fault tolerance a
     single node can't give → horizontal.
     Earns its place at: from day one until a single (large) node can't hold the working set or
     sustain throughput. Modern cloud instances reach hundreds of vCPUs and terabytes of
     RAM — far more than most workloads need.
     Trade-offs: buys radical simplicity (no distribution, no coordination); costs a hard ceiling
     and a single point of failure (mitigate with a standby).
     Failure modes & smells: distributing a system that would have fit on one big machine;
     "horizontal scale" with three under-utilized nodes and a coordination headache.
     Combines / conflicts: combines with read replicas and a hot standby. Conflicts with
     nothing — it's the baseline.
     Cheapest PoC to verify: project your 12–18 month load against the largest instance you can
     buy; if it fits, don't distribute.
     Evidence: established — "scale up before you scale out" is a widely repeated heuristic.

Stateless Services + Horizontal Scaling
Make each service instance hold no client-specific state, so you can run many identical copies
behind a load balancer.
     Use when: one node can't handle the load, you need rolling deploys / fault tolerance, or
     traffic is spiky and you want to add/remove instances freely.
     Don't use when / simpler: before you've outgrown vertical scaling; or if your service is
     inherently stateful and you haven't externalized state yet.
     Earns its place at: when sustained load or availability requirements exceed one node, and
     state has been pushed to a shared store/cache.
     Trade-offs: buys near-linear capacity and resilience; costs a shared state store, a load
     balancer, and the discipline to keep services truly stateless.
     Failure modes & smells: "sticky sessions" hiding hidden in-memory state; one instance
     holding data others don't; scaling out a service that secretly isn't stateless.
     Combines / conflicts: combines with KV/session stores, load balancers, autoscaling. The
     prerequisite for most horizontal scaling.
     Cheapest PoC to verify: kill a random instance under load; if any user breaks, it wasn't
     stateless.
     Evidence: established — Twelve-Factor App; cloud-native standard practice.

Read Replicas
Copies of the primary database that serve read queries; writes still go to the primary.
     Use when: reads dominate and saturate the primary, and reads can tolerate small
     replication lag.
     Don't use when / simpler: writes are the bottleneck (replicas don't help writes); or you
     need read-your-own-writes everywhere (lag breaks it) → cache hot reads or fix indexes first.
     Earns its place at: high read:write ratios (e.g., 5–10:1+ — heuristic) where the primary's
     CPU/IO is read-bound.
     Trade-offs: buys cheap read scaling and a failover candidate; costs replication lag (stale
     reads) and routing complexity (read vs write connections).
     Failure modes & smells: reading a just-written value from a lagging replica and seeing stale
     data; routing writes to a replica by mistake; using replicas to "scale writes."
     Combines / conflicts: combines with stateless services, caching. Conflicts with strict read-
     after-write needs unless you route critical reads to the primary.
     Cheapest PoC to verify: measure read vs write CPU split on the primary; if reads dominate,
     replicas help. Test your tolerance for lag on the hottest read path.
     Evidence: established — DDIA (Ch. 5, replication).

Partitioning / Sharding
Split one dataset across multiple independent databases by a key (e.g., user_id), so each holds a
slice.
     Use when: a single primary genuinely cannot hold the data or sustain the write throughput,
     after vertical scaling and read replicas are exhausted.
     Don't use when / simpler: anything earlier. This is the heaviest data-scaling step and is
     very hard to undo. If you're considering it "to be safe," don't.
     Earns its place at: when write volume or dataset size exceeds what the biggest single
     primary can handle (multi-TB hot data and/or write rates beyond a single node's IO —
     heuristic, workload-dependent). Most products never reach this.
     Trade-offs: buys horizontal write/data scaling; costs cross-shard queries and joins
     becoming hard or impossible, no global transactions, rebalancing pain, hot shards, and a
     permanent jump in operational complexity.
     Failure modes & smells: sharding before exhausting vertical+replicas; a bad shard key
     creating hot shards; cross-shard queries fanning out everywhere; resharding becoming a
     multi-quarter project.
     Combines / conflicts: combines with stateless services, denormalization. Conflicts with
     cross-entity transactions and ad-hoc cross-shard analytics.
     Cheapest PoC to verify: prove the primary is maxed after vertical scaling and read replicas;
     model the shard key against real access to check for hot shards and unavoidable cross-
     shard queries before committing.
     Evidence: established (mechanics) / strong-heuristic (when) — DDIA (Ch. 6); "don't
     shard until you must" is near-universal advice.

§2.3 Caching

Cache-Aside (Lazy Loading) — the default cache
The app checks the cache; on a miss it reads the DB, then stores the result in the cache.

     Use when: reads are hot and repeated, the data tolerates brief staleness, and DB read load or
     latency is measurably hurting.
     Don't use when / simpler: the DB already meets SLO with proper indexing → no cache.
     Caching is a frequent source of subtle bugs; add it only when needed.
     Earns its place at: when a hot read is both expensive and frequent enough that the cache
     hit rate will be high (e.g., a small set of keys served at high QPS).
     Trade-offs: buys big read-latency and DB-load reductions; costs a second source of
     (possibly stale) data, cache-miss latency spikes, and invalidation complexity.
     Failure modes & smells: stale reads after writes (no/late invalidation); thundering herd on
     a cold/expired key (many misses hit the DB at once); treating the cache as the source of
     truth.
     Combines / conflicts: combines with TTLs, read replicas, request coalescing (to stop
     herds). Conflicts with strict freshness requirements.
     Cheapest PoC to verify: estimate hit rate from access logs (key skew); a low projected hit
     rate means the cache won't pay off.
     Evidence: established — DDIA; AWS caching guidance; the most common caching
     strategy.

Read-Through
The cache itself loads from the DB on a miss; the app only talks to the cache.
     Use when: you want caching logic centralized in the cache layer/library rather than
     scattered in app code, with read-heavy access.
     Don't use when / simpler: you need fine-grained control over what/when to cache → cache-
     aside.
     Earns its place at: same threshold as cache-aside; choose it for cleaner code when a
     provider supports it.
     Trade-offs: buys simpler app code; costs less control and the same staleness concerns.
     Failure modes & smells: identical to cache-aside (staleness, herds), plus surprise when the
     cache loads things you didn't intend.
     Combines / conflicts: an alternative to cache-aside; same partners.
     Cheapest PoC to verify: same as cache-aside.
     Evidence: established — standard caching pattern.

Write-Through
Every write goes to the cache and the DB synchronously, keeping them in sync.

     Use when: you want the cache always fresh on write and can accept slightly slower writes;
     read-heavy with low staleness tolerance.
     Don't use when / simpler: writes are frequent and rarely re-read (you cache data nobody
     reads) → cache-aside.
     Earns its place at: when freshness-on-read matters and the written keys are read often
     enough to justify caching them.
     Trade-offs: buys fresh reads; costs higher write latency and caching of possibly-unread
     data.
     Failure modes & smells: caching write-heavy, read-rarely data (wasted cache); partial
     failure (DB write succeeds, cache write fails) leaving them inconsistent.
     Combines / conflicts: combines with cache-aside (write-through + read-through).
     Conflicts with write-heavy, read-light workloads.
     Cheapest PoC to verify: check the read:write ratio on the keys you'd write through; low re-
     read rate means don't.
     Evidence: established — standard caching pattern.
Write-Behind (Write-Back)
Writes go to the cache and are flushed to the DB asynchronously later.
     Use when: extreme write throughput where synchronous DB writes are the bottleneck and
     you can tolerate the risk of losing recently-cached writes on failure.
     Don't use when / simpler: you need durability/consistency (most systems) → write-
     through or direct DB writes. This is rarely the right choice.
     Earns its place at: only at very high write rates where DB write latency is the proven
     bottleneck and the data can tolerate loss/delay.
     Trade-offs: buys very fast writes and write batching; costs durability risk (data loss if the
     cache dies before flush) and complex consistency.
     Failure modes & smells: data loss on cache failure; the cache silently becoming the de-
     facto source of truth; ordering bugs in the async flush.
     Combines / conflicts: conflicts with durability/consistency requirements; rarely combined
     with strong guarantees.
     Cheapest PoC to verify: ask "can we lose the last N seconds of writes?" If no, don't use it.
     Evidence: strong-heuristic — recognized but niche; durability risk is well documented.

CDN / Edge Caching
Cache static (and cacheable dynamic) content at edge locations close to users.
     Use when: you serve static assets (images, JS/CSS, video) or cacheable responses to a
     geographically distributed audience.
     Don't use when / simpler: purely internal APIs, or highly personalized/uncacheable
     responses → skip, or cache only the cacheable parts.
     Earns its place at: any time you have static assets and non-trivial geographic spread — it's
     cheap and almost always worth it for assets.
     Trade-offs: buys big latency reductions and origin offload; costs cache-
     invalidation/versioning effort and the risk of serving stale content.
     Failure modes & smells: stale assets after deploy (fix with content-hashed filenames);
     accidentally caching personalized/private responses; cache-poisoning via bad cache keys.
     Combines / conflicts: combines with asset fingerprinting and cache-control headers.
     Conflicts with per-user dynamic responses unless carefully scoped.
     Cheapest PoC to verify: put assets behind a CDN and measure edge latency from a far
     region; trivial to test.
     Evidence: established — universal web practice.
   Cross-cutting on caching: the two hard problems are invalidation (keeping the cache from
   serving stale data) and stampedes/herds (many simultaneous misses hammering the DB).
   Any caching proposal must say how it handles both. "There are only two hard things in
   computer science: cache invalidation and naming things" is a cliché because it's true.

§2.4 Asynchrony & Messaging

Synchronous Request/Response (the default)
The caller sends a request and waits for the response before continuing.
     Use when: the caller needs the result to proceed, the operation is fast, and a simple,
     debuggable call is enough. This is most calls.
     Don't use when / simpler: the work is slow, the caller shouldn't wait, you need durable
     buffering under load spikes, or many consumers need the same event → async/messaging.
     But sync is the simpler, correct default for most interactions.
     Earns its place at: always available; the baseline.
     Trade-offs: buys simplicity, easy debugging, immediate errors; costs tight temporal
     coupling (caller blocked, failure propagates) and no built-in buffering.
     Failure modes & smells: long synchronous chains where one slow hop stalls everything;
     using sync for work that should be fire-and-forget (e.g., sending email inline).
     Combines / conflicts: combines with timeouts, retries, circuit breakers. Conflicts with high-
     latency or fan-out workloads.
     Cheapest PoC to verify: if the caller genuinely needs the answer now and the call is fast,
     sync is right — no PoC needed.
     Evidence: established — default for most APIs.

Message Queue (point-to-point / work queue)
A producer puts messages on a durable queue; one of N workers consumes each message exactly
once (per delivery semantics).
     Use when: decouple slow or spiky work from the request path (e.g., image processing,
     emails, background jobs); smooth load spikes via buffering; retry failed work.
     Don't use when / simpler: the caller needs the result immediately, or the work is trivial → do
     it synchronously. A queue adds an async hop and new failure modes.
     Earns its place at: when work is slow/spiky enough that doing it inline hurts user latency or
     risks dropping work under load.
     Trade-offs: buys decoupling, buffering, retries, smoothing; costs eventual consistency
     (results aren't immediate), a broker to operate, and ordering/duplication handling.
     Failure modes & smells: assuming a result is ready when it's still queued; poison messages
     blocking a queue (need a dead-letter queue); unbounded queue growth under sustained
     overload; assuming "exactly-once" delivery (see consistency).
     Combines / conflicts: combines with idempotent consumers, dead-letter queues, the
     outbox pattern. Conflicts with strict synchronous request/response semantics.
     Cheapest PoC to verify: measure how long the work takes inline and how spiky it is; if
     inline latency violates SLO or spikes drop work, a queue helps.
     Evidence: established — Hohpe & Woolf, Enterprise Integration Patterns (2003).

Publish/Subscribe
A producer publishes an event to a topic; many independent subscribers each receive a copy.
     Use when: multiple consumers need to react to the same event independently (e.g., "order
     placed" → email, analytics, inventory), and you want producers ignorant of consumers.
     Don't use when / simpler: exactly one consumer does one thing → a queue or a direct call.
     Pub/sub adds indirection and makes flow harder to trace.
     Earns its place at: when adding a new reaction to an event without changing the producer
     is a recurring need (multiple, evolving consumers).
     Trade-offs: buys loose coupling and easy extension; costs harder end-to-end tracing,
     eventual consistency, and "where did this event go?" debugging.
     Failure modes & smells: nobody knows all the subscribers; a slow/broken subscriber
     silently dropping events; hidden event chains (event triggers event triggers event) nobody
     can follow.
     Combines / conflicts: combines with event-driven architecture, tracing, schema registries.
     Conflicts with simple point-to-point work.
     Cheapest PoC to verify: count the current distinct consumers; if it's one, you don't need
     pub/sub yet.
     Evidence: established — Enterprise Integration Patterns.

Event Streaming / Log (e.g., Kafka)
A durable, ordered, replayable log of events that consumers read at their own pace and can re-
read from any offset.
     Use when: you need event replay, multiple consumers reading the same ordered stream at
     different speeds, high-throughput event pipelines, or an event log as an integration
     backbone.
     Don't use when / simpler: simple background jobs or a few decoupled consumers → a
     queue or pub/sub broker. Kafka is powerful but operationally heavy; it's frequently over-
     adopted.
     Earns its place at: high event volume, a need for replay/reprocessing, or many independent
     consumers of an ordered stream. For a single work queue, it's overkill.
     Trade-offs: buys durability, replay, ordering (per partition), high throughput, decoupled
     consumer speeds; costs significant operational complexity, partition/consumer-group
     management, and a steep learning curve.
     Failure modes & smells: running a Kafka cluster to send a few emails; expecting global
     ordering (ordering is per-partition only); consumer-lag blowups; treating it as a database.
     Combines / conflicts: combines with stream processing, CDC, event sourcing, the outbox
     pattern. Conflicts with "we just need a simple queue."
     Cheapest PoC to verify: do you actually need replay or many independent consumers of an
     ordered log? If not, a managed queue/pub-sub is simpler. Prototype with a managed queue
     first.
     Evidence: established (capability) / strong-heuristic (when to adopt) — DDIA (Ch.
     11); over-adoption is a known trap.

Event-Driven Architecture (umbrella)
Components communicate primarily by emitting and reacting to events rather than direct calls.

     Use when: loose coupling between many evolving components is valuable, reactions are
     naturally asynchronous, and you can invest in the observability to trace event flows.
     Don't use when / simpler: a small system where direct calls are clear and sufficient →
     synchronous/RPC. EDA trades local clarity for global flexibility; the trade is bad when
     small.
     Earns its place at: when many components must react to shared events and decoupling
     demonstrably reduces change-coupling across teams/services.
     Trade-offs: buys extensibility and decoupling; costs harder reasoning about end-to-end
     behavior, eventual consistency everywhere, and demanding observability.
     Failure modes & smells: "event spaghetti" where no one can trace a business flow;
     eventual-consistency bugs surprising the team; hidden cyclic event chains.
     Combines / conflicts: combines with pub/sub, streaming, outbox, sagas, tracing. Conflicts
     with simple, sequential workflows.
     Cheapest PoC to verify: map one business flow as events end-to-end and try to trace a
     failure; if you can't follow it, you lack the observability to run EDA.
     Evidence: strong-heuristic — Fowler ("What do you mean by Event-Driven?"); value is
     context-dependent.

Transactional Outbox
Write the business change and an "event to publish" into the same DB transaction (an outbox
table); a separate process reads the outbox and publishes the event.
       Use when: you must update your database and publish an event/message reliably, and you
       want to avoid the "dual write" problem (DB commit succeeds but message publish fails, or
       vice versa).
       Don't use when / simpler: you don't publish events at all, or losing/duplicating the
       occasional event is harmless → skip. But if you do "save then publish," you almost certainly
       need this.
       Earns its place at: the first time you write to a DB and then publish a message in the same
       logical operation. It's the standard fix for dual writes.
       Trade-offs: buys atomicity between state change and event (no lost/phantom events); costs
       an outbox table, a relay process (or CDC), and at-least-once delivery (so consumers must be
       idempotent).
       Failure modes & smells: the classic smell it prevents is "we call the DB and then the
       message broker in sequence and hope both succeed." Its own failure mode is forgetting
       consumers must dedupe.
       Combines / conflicts: combines with idempotent consumers, CDC (to read the outbox),
       sagas. The standard alternative to distributed transactions for this case.
       Cheapest PoC to verify: look for any code path that does db.save() then
        broker.publish() ; that's the dual-write bug the outbox fixes.

       Evidence: established — Richardson, microservices.io ("Transactional Outbox").

Saga
Manage a transaction that spans multiple services/databases as a sequence of local transactions,
each with a compensating action to undo it if a later step fails.

       Use when: a business operation must update data across multiple services and you cannot
       (and should not) use a distributed transaction.
       Don't use when / simpler: the operation fits in one database transaction → just use a local
       transaction. Don't introduce a saga where one DB transaction would do.
       Earns its place at: when you've genuinely split data across services and still need a multi-
       step operation to be reliable. (Often the deeper question is whether the split was
       premature.)
       Trade-offs: buys reliable multi-service operations without 2PC; costs designing
       compensations for every step, eventual consistency (intermediate states are visible), and
       complex failure handling.
       Variants: orchestration (a coordinator drives the steps — easier to reason about, central
       point) vs choreography (services react to each other's events — more decoupled, harder to
     trace).
     Failure modes & smells: missing/incorrect compensations leaving partial state; reasoning
     about all interleavings becomes intractable; using a saga where a single transaction would
     have worked (premature service split).
     Combines / conflicts: combines with outbox, event-driven messaging, idempotency. The
     explicit alternative to distributed transactions across services.
     Cheapest PoC to verify: ask whether the data could live in one DB (then no saga needed). If
     a saga is truly required, write the compensation for the hardest step first — if you can't, the
     design is unsafe.
     Evidence: established — Garcia-Molina & Salem, "Sagas" (1987); Richardson,
     microservices.io.

CQRS (Command Query Responsibility Segregation)
Use separate models/paths for writes (commands) and reads (queries), often with a read model
optimized for queries.
     Use when: read and write workloads are so different that one model serves both badly, and
     you can accept the read model being eventually consistent with writes.
     Don't use when / simpler: the same model serves reads and writes fine (the common case)
     → don't split. CQRS is widely over-applied.
     Earns its place at: when read and write requirements truly diverge at scale (e.g., complex
     aggregations on reads, high write throughput) and a single model is a proven bottleneck.
     Trade-offs: buys independently optimizable/scalable read and write sides; costs two
     models to maintain, synchronization, and eventual consistency between command and
     query sides.
     Failure modes & smells: applying CQRS to simple CRUD; users confused by stale reads
     right after writes; the sync pipeline becoming a source of bugs.
     Combines / conflicts: combines with event sourcing, materialized views, denormalized
     read models. Conflicts with simple CRUD and strong read-after-write needs.
     Cheapest PoC to verify: show that one model is genuinely a bottleneck for either reads or
     writes before splitting.
     Evidence: strong-heuristic — Fowler ("CQRS") explicitly warns it adds risk and should
     be used sparingly.

§2.5 Consistency & Coordination

CAP / PACELC as a decision lens (framing, not a pattern)
CAP: under a network partition, a distributed datastore must choose between consistency and
availability. PACELC extends it: even without a partition, there's a latency-vs-consistency trade-
off.

     How to use it: when you span machines, decide per data type whether stale reads are
     acceptable (favor availability/latency) or unacceptable (favor consistency). Most systems
     mix both.
     Don't misuse: CAP is about partition behavior, not a blanket "CA vs CP vs AP" label for a
     whole system; and it doesn't apply within a single node.
     Trade-offs: the whole point is that you can't have unbounded consistency, availability, and
     low latency together when distributed.
     Smell: claiming a single-node system is "CP" or "AP," or treating CAP as a marketing label
     rather than a per-operation choice.
     Evidence: established — Brewer (CAP, 2000; Gilbert & Lynch proof, 2002); Abadi
     (PACELC, 2012).

Strong Consistency (the default, within one DB)
Every read sees the most recent committed write; reads and writes appear to happen in a single,
agreed order.

     Use when: correctness depends on up-to-date data (money, inventory, bookings, auth), and
     the data fits where a single system can provide it (one DB/transaction).
     Don't use when / simpler: you need it across many nodes/services at global scale and can
     tolerate staleness → eventual consistency for those parts. Forcing global strong consistency
     is expensive and often unnecessary.
     Earns its place at: any correctness-critical data; it's the default within a database.
     Trade-offs: buys simple, correct reasoning; costs latency and availability under partitions
     when distributed, and write throughput ceilings.
     Failure modes & smells: demanding strong consistency for data that doesn't need it (e.g., a
     like count), paying latency/availability for nothing.
     Combines / conflicts: combines with single-DB transactions, consensus (when
     distributed). Conflicts with high-availability-under-partition goals for the same data.
     Cheapest PoC to verify: ask "what breaks if a read is a few seconds stale?" If "nothing," you
     don't need strong consistency there.
     Evidence: established — DDIA.

Eventual Consistency
Replicas may temporarily disagree but converge to the same value if writes stop; reads can be
stale for a while.
     Use when: high availability and low latency matter more than immediate freshness for that
     data (feeds, counts, recommendations, caches), and the app/users can tolerate staleness.
     Don't use when / simpler: correctness-critical data → strong consistency. Don't default
     everything to eventual consistency for "scale" you don't have.
     Earns its place at: when you genuinely distribute data and the workload can accept
     staleness, or when availability under partition is required.
     Trade-offs: buys availability, latency, and partition tolerance; costs stale reads, conflict
     resolution, and harder reasoning.
     Failure modes & smells: applying it to money/inventory and getting double-
     spends/oversells; users seeing their own write disappear (no read-your-writes); ignored
     write conflicts.
     Combines / conflicts: combines with idempotency, conflict resolution (e.g., last-write-wins,
     CRDTs), caching. Conflicts with strict correctness needs.
     Cheapest PoC to verify: define the maximum tolerable staleness for the data; if it's "zero,"
     eventual consistency is wrong there.
     Evidence: established — DDIA; Vogels, "Eventually Consistent."

Idempotency & Idempotency Keys
Designing an operation so that performing it multiple times has the same effect as once; clients
send a unique key so the server can dedupe retries.
     Use when: anything that can be retried — network calls, message consumers,
     payment/order creation — i.e., almost all distributed operations. With at-least-once delivery,
     this is mandatory, not optional.
     Don't use when / simpler: truly side-effect-free reads need nothing extra. But any write
     that might be retried should be idempotent.
     Earns its place at: the moment retries or at-least-once messaging enter the picture — which
     is essentially every non-trivial distributed system.
     Trade-offs: buys safety under retries/duplicates (the foundation that makes "exactly-once
     processing" achievable); costs storing/checking keys or designing naturally-idempotent
     operations.
     Failure modes & smells: double charges / duplicate orders from a retried request with no
     idempotency key; non-idempotent message consumers under at-least-once delivery;
     assuming the network won't duplicate.
     Combines / conflicts: combines with retries, queues, outbox, sagas. It's the precondition
     that makes retry-based reliability safe.
     Cheapest PoC to verify: send the same write twice; if state changes twice, it's not
     idempotent.
     Evidence: established — Helland, "Idempotence Is Not a Medical Condition"; Stripe's
     idempotency-key design is a canonical reference.

Delivery Guarantees (framing: at-most / at-least / exactly-once)
At-most-once: may lose messages, never duplicates. At-least-once: never loses, may duplicate.
"Exactly-once": appears as once.
     How to decide: default to at-least-once + idempotent consumers. This is the practical way
     to get correct results. At-most-once only when loss is acceptable and duplicates are worse.
     The "exactly-once" reality: true end-to-end exactly-once delivery is impossible in general
     (the two-generals problem). What systems like Kafka provide is effectively-once processing
     within their boundary (idempotent producer + transactions), which still breaks at external
     side-effects (e.g., charging a card, calling a third party). Across system boundaries you must
     use idempotency.
     Smell: any design that relies on exactly-once delivery to be correct, instead of idempotent
     processing. This is one of the most common and dangerous distributed-systems fantasies.
     Trade-offs: at-least-once buys no data loss at the cost of duplicates (handled by
     idempotency); chasing exactly-once buys little beyond what idempotency already gives
     and adds fragility/cost.
     Cheapest PoC to verify: assume duplicates will happen and make consumers idempotent;
     then delivery semantics stop being load-bearing.
     Evidence: contested / established — the impossibility of general exactly-once delivery
     is established (two generals); Kafka's "exactly-once semantics" claim is real but bounded
     and frequently overstated — debated in practice. Sources: DDIA; Kafka/Confluent EOS
     docs; Tyler Treat, "You Cannot Have Exactly-Once Delivery."

Distributed Transactions / Two-Phase Commit (mostly an anti-default)
A coordinator makes multiple databases/services commit-or-abort atomically as one transaction
(2PC).
     Use when: very rarely — only when you truly need atomic commit across systems, the
     systems support it, and no looser approach (saga, outbox, idempotency) is acceptable.
     Don't use when / simpler: almost always → keep the data in one DB (one local transaction),
     or use the outbox + saga + idempotency combination. 2PC is widely advised against.
     Earns its place at: edge cases with hard atomicity requirements across resources that
     support distributed commit and where availability under coordinator failure is acceptable.
     Trade-offs: buys cross-resource atomicity; costs blocking on coordinator failure
     (participants can be stuck holding locks), reduced availability, latency, and operational
     fragility.
     Failure modes & smells: coordinator dies mid-commit and participants block indefinitely;
     chosen because services were split prematurely; locks held across network calls.
     Combines / conflicts: conflicts with high availability and with the saga approach (sagas
     exist to avoid this). Combines with little by design.
     Cheapest PoC to verify: ask whether the data can simply live together in one database.
     Usually it can, and then you need none of this.
     Evidence: established (it works, with costs) / strong-heuristic (avoid it) — Helland,
     "Life Beyond Distributed Transactions" (2007); DDIA (Ch. 9).

Consensus (Raft / Paxos) — when you genuinely need it
A protocol for multiple nodes to agree on a single value/order even with failures (leader election,
replicated logs, config agreement).
     Use when: you are building infrastructure that needs agreement: leader election, a
     strongly-consistent replicated store, distributed locks, cluster membership. Usually you use
     a system that already implements it (etcd, ZooKeeper, Consul, a managed DB) rather than
     implement it.
     Don't use when / simpler: application features — you almost never need to run your own
     consensus. Reach for a database/coordination service that already provides it.
     Earns its place at: when you must coordinate replicated state with strong guarantees and
     no existing managed system fits — a rare, infrastructure-level situation.
     Trade-offs: buys correct agreement under failure; costs latency (multiple round-trips,
     quorum writes), operational complexity, and the need for an odd number of nodes / quorum
     management.
     Failure modes & smells: rolling your own consensus (notoriously bug-prone); using a
     distributed lock service for things that don't need distributed coordination; quorum-loss
     outages from too few nodes.
     Combines / conflicts: combines with strong consistency, leader-based replication.
     Conflicts with "we could have just used a single database."
     Cheapest PoC to verify: ask whether an existing system (etcd/ZooKeeper/your DB) already
     gives the guarantee. It almost always does.
     Evidence: established — Lamport (Paxos); Ongaro & Ousterhout, "In Search of an
     Understandable Consensus Algorithm" (Raft, 2014).

Event Sourcing (contested)
Store the full ordered history of state changes (events) as the source of truth, and derive current
state by replaying them.
     Use when: you genuinely need a complete audit trail, temporal queries ("state as of last
     Tuesday"), or the ability to rebuild/replay state into new read models — and the domain is
     event-centric (finance, ledgers, some workflow systems).
     Don't use when / simpler: standard CRUD where current state is all you need → a normal
     database (optionally with an audit/history table). Event sourcing is powerful but adds large,
     lasting complexity and is frequently misapplied.
     Earns its place at: when audit/temporal/replay requirements are real and central, and the
     team has the expertise to handle versioning of events over time.
     Trade-offs: buys full history, auditability, replayability, temporal queries; costs event-
     schema versioning forever, eventual consistency, complex querying of current state, and a
     steep learning curve.
     Failure modes & smells: adopting it for ordinary CRUD; painful event-schema evolution
     (old events must still replay correctly); huge replay times without snapshots; "we can't
     easily answer a simple current-state query."
     Combines / conflicts: combines with CQRS (very common pairing), streaming. Conflicts
     with simple CRUD and teams without the expertise.
     Cheapest PoC to verify: ask whether a plain DB plus an audit/history table meets the audit
     need. If yes, you likely don't need event sourcing.
     Evidence: contested — Fowler ("Event Sourcing"), Greg Young (originator) on one side;
     widely documented "we regretted it / it was overkill" experience reports on the other. Right
     when audit/temporal/replay are core; wrong as a default architecture. Present the
     disagreement; do not declare a winner.

§2.6 APIs & Communication

REST over HTTP/JSON (the default)
Resource-oriented APIs using HTTP verbs and JSON; widely understood and tooled.
     Use when: public or general-purpose APIs, broad client compatibility, simple
     request/response, caching via HTTP. The default choice for most APIs.
     Don't use when / simpler: you have a named REST pain (over/under-fetching for varied
     clients, very chatty mobile flows, strict typed internal contracts, high-performance internal
     RPC, streaming) → GraphQL or gRPC. Otherwise stay REST.
     Earns its place at: immediately; it's the baseline.
     Trade-offs: buys ubiquity, simplicity, HTTP caching, easy debugging; costs over/under-
     fetching for complex clients and weaker typing than gRPC.
     Failure modes & smells: chatty designs needing many round-trips for one screen;
     inconsistent resource modeling; reinventing GraphQL via dozens of ad-hoc query params.
     Combines / conflicts: combines with API gateway, BFF, cursor pagination, idempotency
     keys. Alternative to gRPC/GraphQL.
     Cheapest PoC to verify: build the most demanding client screen against REST; if it needs
     many round-trips or massive over-fetch, consider GraphQL.
     Evidence: established — Fielding's REST dissertation; industry default.

gRPC
A high-performance RPC framework using HTTP/2 and Protocol Buffers (binary, typed
contracts), with streaming support.
     Use when: internal service-to-service communication where low latency, high throughput,
     strict typed contracts, code generation, and/or bidirectional streaming matter.
     Don't use when / simpler: public/browser-facing APIs (limited native browser support,
     harder debugging) → REST. Don't adopt it internally without a performance/contract need.
     Earns its place at: measurable latency/throughput needs on internal calls, or many services
     needing strongly-typed, versioned contracts.
     Trade-offs: buys performance, typed contracts, streaming, generated clients; costs harder
     debugging (binary), browser/edge friction, and proto tooling overhead.
     Failure modes & smells: exposing gRPC directly to browsers without a gateway; using it for
     a couple of low-traffic internal calls where REST was fine.
     Combines / conflicts: combines with service meshes, internal APIs; pairs with a gateway
     for external exposure. Alternative to REST internally.
     Cheapest PoC to verify: benchmark the hot internal call in REST/JSON vs gRPC; adopt
     only if the difference matters for your SLO.
     Evidence: established (for internal RPC) — gRPC docs; common in microservice fleets.

GraphQL
A query language letting clients request exactly the fields they need from a single endpoint,
aggregating multiple sources.
     Use when: diverse clients (web/mobile) need different shapes of data, over/under-fetching
     with REST is a proven problem, or you aggregate many backends for a client.
     Don't use when / simpler: a single client with stable needs → REST is simpler. GraphQL
     adds real complexity (caching, auth per field, query-cost control) and is frequently adopted
     prematurely.
     Earns its place at: when multiple, varied clients with divergent data needs make REST
     endpoint sprawl or over-fetch a measured pain.
     Trade-offs: buys flexible, client-driven fetching and one endpoint; costs harder HTTP
     caching, per-field authorization, the N+1 query problem, and query-complexity/DoS
     controls.
     Failure modes & smells: N+1 backend queries from nested resolvers (need
     batching/dataloaders); expensive/abusive queries with no cost limits; using it for a simple
     internal API.
     Combines / conflicts: combines with BFF, dataloaders, persisted queries. Alternative to
     REST for client-facing aggregation.
     Cheapest PoC to verify: count how many REST round-trips your richest client screen
     needs; if it's many and varied across clients, GraphQL may pay off.
     Evidence: contested — strong for varied-client aggregation; over-applied for simple APIs.
     GraphQL spec; widely debated vs REST.

Messaging as the API (asynchronous integration)
Services integrate by exchanging messages/events rather than synchronous calls.
     Use when: the interaction is naturally async, the caller shouldn't block, or you need
     durable, decoupled communication (see §2.4).
     Don't use when / simpler: the caller needs an immediate answer → synchronous
     REST/gRPC.
     Earns its place at: see Message Queue / Pub-Sub thresholds.
     Trade-offs / failure modes / PoC: see §2.4.
     Evidence: established — Enterprise Integration Patterns.

API Gateway
A single entry point in front of backend services handling cross-cutting concerns: auth, rate
limiting, routing, TLS, request shaping.
     Use when: you have multiple backend services and want one place for auth, rate limiting,
     routing, and TLS termination instead of duplicating them everywhere.
     Don't use when / simpler: a single service/monolith → you don't need a separate gateway
     (the app handles these). Don't add a gateway with one backend.
     Earns its place at: when several services share cross-cutting concerns that would
     otherwise be duplicated and drift.
     Trade-offs: buys centralized cross-cutting concerns and a clean external surface; costs an
     extra network hop, a potential single point of failure/bottleneck, and one more thing to
     operate.
     Failure modes & smells: the gateway becoming a bottleneck or SPOF; business logic
     creeping into the gateway; using it as a dumping ground.
     Combines / conflicts: combines with microservices, BFF, rate limiting. Largely
     unnecessary for a single monolith.
     Cheapest PoC to verify: count services sharing auth/rate-limiting today; one service means
     no gateway needed yet.
     Evidence: established — Richardson, microservices.io ("API Gateway").

Backend-for-Frontend (BFF)
A dedicated backend per client type (web, mobile, etc.) that tailors and aggregates data for that
client.
     Use when: different clients (e.g., mobile vs web) need substantially different data
     shapes/aggregations, and forcing one API to serve all causes over-fetch or awkward
     compromises.
     Don't use when / simpler: one client, or clients with similar needs → a single API. A BFF per
     client is extra code to maintain.
     Earns its place at: when client needs diverge enough that a shared API measurably hurts
     one client (typically a mobile vs web split at non-trivial scale).
     Trade-offs: buys client-optimized APIs and decoupled client teams; costs duplicated
     aggregation logic across BFFs and more services to run.
     Failure modes & smells: a BFF per tiny client variant; business logic duplicated across
     BFFs instead of shared; BFFs drifting apart.
     Combines / conflicts: combines with API gateway, GraphQL, microservices. Conflicts with
     single-client simplicity.
     Cheapest PoC to verify: check whether your clients' data needs actually differ; if not, one
     API suffices.
     Evidence: strong-heuristic — Newman / SoundCloud's BFF write-ups.

Pagination (offset vs cursor)
Return large result sets in pages. Offset = "skip N, take M." Cursor/keyset = "give me items after
this marker."
     Use when (cursor): large or frequently-changing datasets, infinite scroll, or deep
     pagination — cursor/keyset pagination is stable and efficient.
     Use when (offset): small, mostly-static datasets with random page access (e.g., a numbered
     admin table). Simpler but degrades deep into the set.
     Don't use when / simpler: tiny result sets → no pagination needed.
     Earns its place at: any endpoint returning unbounded lists; choose cursor once data is large
     or shifting.
     Trade-offs: cursor buys consistent, fast deep pagination; costs no random page jumps and a
     slightly more complex API. Offset buys simplicity; costs slow/incorrect results at high
     offsets (rows shift, OFFSET 100000 is expensive).
     Failure modes & smells: deep offset pagination causing slow queries and
     duplicate/missing rows as data changes; returning unbounded lists with no pagination at
     all.
     Combines / conflicts: combines with all API styles. Cursor and offset are alternatives.
     Cheapest PoC to verify: query at a large offset on real data and measure; if it's slow or rows
     shift, switch to cursor.
     Evidence: established — standard API design guidance.

API Versioning
A strategy (URL path, header, or content negotiation) to evolve an API without breaking existing
clients.

     Use when: you have external/independent clients you can't force to upgrade, and you need
     to make breaking changes.
     Don't use when / simpler: internal clients you can update in lockstep, or purely additive
     (backward-compatible) changes → no version bump needed; add fields, don't break them.
     Earns its place at: the first breaking change to an API with clients you don't control.
     Trade-offs: buys safe evolution and client stability; costs maintaining multiple versions and
     the migration burden.
     Failure modes & smells: versioning for additive changes that didn't need it; never
     deprecating old versions (maintaining many forever); breaking clients with no version
     strategy at all.
     Combines / conflicts: combines with API gateway (routing versions), deprecation policy.
     Cheapest PoC to verify: classify the change as additive or breaking; only breaking changes
     to uncontrolled clients require a new version.
     Evidence: established — standard API governance.

§2.7 Reliability
   Order of adoption: timeouts first, then retries (with backoff + jitter), then circuit breakers,
   then bulkheads / load shedding. Each prevents a specific failure; add them as those failures
   become real.
Timeouts
Cap how long a call waits for a response before giving up.
     Use when: every network/IO call. There is essentially no excuse for an unbounded wait.
     This is the most fundamental reliability control.
     Don't use when / simpler: never skip — but tune values to the operation; a too-short
     timeout causes spurious failures.
     Earns its place at: immediately, on every remote call.
     Trade-offs: buys protection against hanging on a slow/dead dependency; costs the need to
     choose sensible values and handle the timeout case.
     Failure modes & smells: no timeout → threads pile up waiting and the whole service hangs
     (the root of most cascading failures); timeouts longer than the caller's own deadline;
     identical static timeouts everywhere ignoring real latencies.
     Combines / conflicts: combines with retries, circuit breakers, deadlines/budgets. The
     prerequisite for everything else here.
     Cheapest PoC to verify: make a dependency sleep forever in a test; a service with no
     timeout will hang — proof you need one.
     Evidence: established — Nygard, Release It!; Google SRE.

Retry with Exponential Backoff & Jitter
On a transient failure, retry — but wait increasingly longer between attempts, with randomization
so clients don't retry in sync.
     Use when: failures are transient (timeouts, brief unavailability, throttling) and the
     operation is idempotent (or made idempotent).
     Don't use when / simpler: the operation isn't idempotent (retries cause duplicates), or the
     failure is permanent (4xx, validation) → don't retry; fail fast.
     Earns its place at: any call to a dependency that can have transient hiccups — i.e., most
     remote calls.
     Trade-offs: buys resilience to transient faults; costs added latency on failures and, if done
     naively, retry storms that amplify an outage.
     Failure modes & smells: retry storms / thundering herd — fixed-interval retries from
     many clients hit a struggling service in synchronized waves and keep it down (the classic
     reason jitter exists); retrying non-idempotent writes (duplicate charges); retrying
     permanent errors; unbounded retries.
     Combines / conflicts: combines with timeouts, idempotency, circuit breakers (which stop
     retries when a dependency is clearly down). Conflicts with non-idempotent operations.
     Cheapest PoC to verify: simulate a dependency outage with many clients; without jitter
     you'll see synchronized retry spikes — proof you need backoff + jitter.
     Evidence: established — Marc Brooker / AWS Architecture Blog, "Exponential Backoff
     And Jitter"; Release It!.

Circuit Breaker
After repeated failures from a dependency, "open the circuit" to fail fast (stop calling it) for a
cooldown, then test if it's healthy again.
     Use when: a dependency can fail or slow down in ways that would otherwise cause callers
     to pile up requests and cascade the failure; you want to fail fast and let the dependency
     recover.
     Don't use when / simpler: simple internal calls with no real cascade risk → timeouts +
     bounded retries may be enough. Don't wrap everything in breakers reflexively.
     Earns its place at: when a slow/failing dependency has (or clearly could) cause a cascading
     failure across services.
     Trade-offs: buys fast failure and protection against cascades, plus breathing room for
     recovery; costs tuning thresholds and handling the open state (fallbacks), with risk of
     flapping if mis-tuned.
     Failure modes & smells: thresholds so sensitive the breaker flaps; no fallback for the open
     state (just errors); using a breaker where a timeout sufficed.
     Combines / conflicts: combines with timeouts, retries, bulkheads, graceful degradation.
     Conflicts with nothing, but is overkill on low-risk calls.
     Cheapest PoC to verify: make a dependency fail under load and observe whether callers
     pile up and cascade; if they do, a breaker helps.
     Evidence: established — Nygard, Release It! (origin of the named pattern).

Bulkhead
Isolate resources (thread pools, connection pools, instances) so a failure in one area can't
consume all capacity and sink everything.
     Use when: one slow/failing dependency or tenant could exhaust a shared resource pool and
     starve unrelated work; you want to contain the blast radius.
     Don't use when / simpler: small systems with one workload and no shared-resource
     contention → not needed yet.
     Earns its place at: when multiple workloads/dependencies share a resource pool and one
     can starve the others (proven or clearly imminent).
     Trade-offs: buys fault isolation (one area's failure stays contained); costs lower overall
     utilization (reserved capacity per partition) and more configuration.
     Failure modes & smells: one slow downstream consuming the entire thread pool and
     taking the whole service down (the failure bulkheads prevent); over-partitioning into many
     tiny pools that waste capacity.
     Combines / conflicts: combines with circuit breakers, timeouts, load shedding. Conflicts
     with maximizing utilization.
     Cheapest PoC to verify: saturate one dependency in a test and see if unrelated requests
     also fail; if they do, you need isolation.
     Evidence: established — Nygard, Release It!.

Graceful Degradation / Fallback
When a dependency or feature fails, serve a reduced-but-useful response instead of failing the
whole request.
     Use when: part of a response is non-essential (recommendations, related items,
     personalization) and the core function can proceed without it.
     Don't use when / simpler: the failing piece is essential to correctness (you can't "degrade" a
     payment) → fail clearly. Don't hide critical failures behind silent fallbacks.
     Earns its place at: when user-facing flows depend on optional enrichments that can be
     unavailable.
     Trade-offs: buys availability and a better experience under partial failure; costs more code
     paths and the risk of masking real problems.
     Failure modes & smells: silently degrading something that was actually critical;
     stale/empty fallbacks shown as if normal; fallbacks that themselves fail unhandled.
     Combines / conflicts: combines with circuit breakers, caching (serve last-known-good),
     timeouts. Conflicts with strict correctness on the degraded piece.
     Cheapest PoC to verify: turn off a non-critical dependency and confirm the core flow still
     completes acceptably.
     Evidence: established — Google SRE; Release It!.

Load Shedding
Under overload, deliberately reject or drop some requests so the rest succeed, instead of
slowing/crashing for everyone.
     Use when: traffic can exceed capacity (spikes, abuse) and degrading everyone is worse
     than serving most and rejecting some (ideally lowest-priority first).
     Don't use when / simpler: load comfortably within capacity → not needed. Autoscaling
     may absorb moderate spikes without shedding.
     Earns its place at: when overload episodes are real and a graceful "serve most, reject some"
     beats a total brownout.
     Trade-offs: buys system survival and predictable behavior under overload; costs rejecting
     some users and the need for prioritization/queue-management logic.
     Failure modes & smells: unbounded queues that grow until everything times out (the
     failure shedding prevents); shedding high-value traffic indiscriminately; no shedding at all,
     so overload becomes a full outage.
     Combines / conflicts: combines with rate limiting, bulkheads, backpressure, autoscaling.
     Conflicts with "never reject a request" expectations.
     Cheapest PoC to verify: drive load past capacity in a test; without shedding, latency
     explodes and everything fails — proof of need.
     Evidence: established — Google SRE Book (handling overload).

Redundancy & Failover
Run more than one instance/replica so that if one fails, another takes over (active-active or active-
passive with health checks).
     Use when: the component's availability matters and a single instance's failure would cause
     unacceptable downtime.
     Don't use when / simpler: non-critical/internal tooling where brief downtime is fine → a
     single instance may be acceptable early on.
     Earns its place at: any production-critical path with an availability target a single node
     can't meet.
     Trade-offs: buys higher availability and fault tolerance; costs at least double the resources,
     failover complexity, and (for stateful components) replication/consistency concerns.
     Failure modes & smells: an untested failover that doesn't actually work when needed;
     "redundant" components sharing a hidden single point of failure (same rack, AZ, DB); split-
     brain in active-active without proper coordination.
     Combines / conflicts: combines with health checks, load balancers, replication, consensus
     (for stateful failover). Conflicts with minimizing cost.
     Cheapest PoC to verify: kill the primary in a controlled test and confirm automatic, correct
     failover. An untested failover is no failover.
     Evidence: established — standard HA practice; AWS Well-Architected (Reliability
     pillar).

§2.8 Deployment Topology
   This is the biggest over-engineering trap in the document. The default is a single
   deployable. Microservices should be treated as guilty-until-proven-necessary.
Monolith (the default)
The whole application built and deployed as a single unit.
     Use when: almost always at the start, and for most products throughout their life. Small-to-
     medium teams, evolving requirements, and the need to move fast favor a monolith.
     Don't use when / simpler: it is the simple option. Move off it only for the named signals
     below (team-scaling deploy conflicts, wildly divergent scaling profiles).
     Earns its place at: from day one; sustainable to large scale with internal modularity. Many
     large companies run substantial monoliths successfully.
     Trade-offs: buys simple deployment, easy local dev, straightforward
     debugging/transactions, no network between modules; costs a single deploy unit (all-or-
     nothing releases) and the risk of internal coupling without discipline.
     Failure modes & smells: the "big ball of mud" — no internal boundaries, everything
     tangled (a discipline failure, not a reason to go microservices); one giant deploy that's scary
     to ship.
     Combines / conflicts: combines with modular-monolith structure, vertical scaling, read
     replicas. The thing premature microservices abandon too early.
     Cheapest PoC to verify: ship the monolith; if deploys aren't blocking teams and no
     component needs radically different scaling, you're done — stay here.
     Evidence: established / strong-heuristic — Fowler ("MonolithFirst"); DHH ("The
     Majestic Monolith"); broad "start with a monolith" consensus.

Modular Monolith
A single deployable with strong internal module boundaries (clear interfaces, enforced
separation), so it could later be split if needed.
     Use when: you want a monolith's operational simplicity but anticipate growth and want
     clean boundaries to keep coupling low (and to make any future extraction feasible).
     Don't use when / simpler: the cleanest middle ground for most growing apps — there's
     rarely a reason not to keep a monolith modular. (A tiny app may not need formal modules
     yet.)
     Earns its place at: as soon as the codebase is large enough that internal coupling is a risk —
     which is early. This is the recommended default for serious applications.
     Trade-offs: buys low coupling + monolith simplicity, and a cheaper future path to services
     if ever needed; costs discipline to enforce boundaries (no shortcuts across modules).
     Failure modes & smells: modules that leak into each other (shared mutable internals,
     cross-module DB access) — at which point it degrades into a ball of mud.
     Combines / conflicts: combines with domain-driven boundaries, the strangler fig (for any
     eventual extraction). The strongly-preferred alternative to premature microservices.
     Cheapest PoC to verify: try to change one module without touching others; if you can't, the
     boundaries aren't real.
     Evidence: strong-heuristic — Shopify (Kirsten Westeinde, "Deconstructing the
     Monolith"); widely advocated as the pragmatic default.

Microservices (guilty until proven necessary)
Decompose the system into independently deployable services, each owning its data,
communicating over the network.
     Use when: you have organizational scale — multiple teams whose independent deploy
     cadences collide on one codebase — and/or components with genuinely different scaling,
     runtime, or availability profiles; and the team has the operational maturity (CI/CD,
     observability, on-call) to run a distributed system.
     Don't use when / simpler: small teams, early products, or unclear domain boundaries →
     modular monolith. Microservices are premature far more often than they're justified. The
     primary driver should be team/org scaling, not "scalability" in the abstract.
     Earns its place at: Fowler's "you must be this tall" bar — roughly when you have multiple
     independent teams (commonly cited around several teams / dozens of engineers —
     heuristic) blocked by a shared deploy, and solid automated infrastructure. Below that, the
     cost dominates.
     Trade-offs: buys independent deployability, team autonomy, fault isolation, and per-
     service scaling; costs distributed-systems complexity everywhere — network failures,
     eventual consistency, distributed tracing/debugging, data split across services (no easy
     joins/transactions), and heavy operational overhead.
     Failure modes & smells: the distributed monolith (services so coupled they must deploy
     together — all the costs of distribution, none of the autonomy); chatty services (one user
     action triggers many synchronous cross-service calls, multiplying latency and failure
     probability); shared database across services (defeats the point); premature adoption with
     two engineers and five services nobody can operate.
     Combines / conflicts: combines with API gateway, service discovery, saga, outbox,
     distributed tracing, database-per-service. Conflicts with strong cross-entity consistency
     and small-team simplicity.
     Cheapest PoC to verify: before splitting, define service boundaries inside a modular
     monolith and confirm they're stable (low cross-boundary change). Extract one service via
     the strangler fig and verify you can deploy and operate it independently before splitting
     further. If boundaries keep shifting, you're not ready.
     Evidence: contested — Fowler ("MicroservicePremium," "MonolithFirst"), Newman
     (Building Microservices, Monolith to Microservices) advise monolith-first and extraction
     only with cause; the Amazon Prime Video team (2023) consolidated a
     serverless/distributed monitoring tool back into a monolith for ~90% cost reduction (a
     widely-cited counter-example — though it was one tool's re-architecture, not a blanket
     reversal). Right at org scale with operational maturity; wrong as a starting architecture.
     Present the disagreement.

Serverless / Functions-as-a-Service (e.g., Lambda)
Run code in managed, event-triggered functions with no servers to manage and pay-per-use,
scale-to-zero billing.
     Use when: spiky or low/intermittent traffic, event-driven glue, cron-style jobs, or rapid
     prototypes where scale-to-zero and zero ops are attractive; unpredictable load you don't
     want to provision for.
     Don't use when / simpler: steady high-throughput workloads (often more expensive than
     a always-on box at scale), latency-sensitive paths sensitive to cold starts, long-running or
     stateful processes, or chatty function-to-function flows → a normal service. Don't
     decompose a whole app into hundreds of functions reflexively.
     Earns its place at: event-driven/bursty/intermittent workloads, or early-stage glue where
     ops savings dominate. The economics flip toward always-on compute as utilization rises.
     Trade-offs: buys no server management, automatic scaling (incl. to zero), pay-per-use;
     costs cold-start latency, execution-time/resource limits, vendor lock-in, harder local
     testing/debugging, and per-request cost that can exceed always-on at high steady load.
     Failure modes & smells: cold-start latency hurting user-facing requests; runaway cost at
     high steady volume; an over-decomposed "function soup" with complex orchestration (the
     Prime Video lesson); hitting timeout/memory limits on real work.
     Combines / conflicts: combines with event streaming/queues, managed databases, API
     gateway. Conflicts with steady high-throughput, latency-critical, and long-running/stateful
     workloads.
     Cheapest PoC to verify: model cost at projected steady volume vs an always-on instance,
     and measure cold-start latency on a representative function. The numbers usually decide it.
     Evidence: contested — strong for bursty/event-driven/low-traffic; over-applied for steady
     high-load apps. AWS Lambda docs; the Prime Video case is the canonical cautionary tale.

Strangler Fig (migration pattern)
Incrementally replace an old system by routing pieces of functionality to the new one over time,
until the old system can be retired — instead of a risky big-bang rewrite.
     Use when: migrating off a legacy system or extracting services from a monolith; you want
     to reduce risk by moving incrementally with the ability to roll back.
     Don't use when / simpler: trivially small systems where a direct rewrite is genuinely low-
     risk → just rewrite. (Rare; most rewrites are riskier than they look.)
     Earns its place at: any non-trivial migration or extraction where a big-bang rewrite would
     be high-risk.
     Trade-offs: buys incremental, reversible, lower-risk migration; costs running old and new
     in parallel (a routing/facade layer) and a longer total timeline.
     Failure modes & smells: the migration stalling with both systems running forever; the
     routing facade becoming permanent complexity; no plan to actually retire the old system.
     Combines / conflicts: combines with API gateway/facade, modular monolith →
     microservices extraction, feature flags. The recommended alternative to a big-bang rewrite.
     Cheapest PoC to verify: route one small slice of traffic/functionality to the new system
     behind the facade and confirm you can switch back instantly.
     Evidence: established — Fowler ("StranglerFigApplication"); Newman, Monolith to
     Microservices.

§2.9 Data Movement

Batch Processing (the default for analytics)
Process large volumes of data on a schedule (hourly/daily) in bulk jobs.
     Use when: results don't need to be real-time (reports, ETL, billing, nightly aggregations);
     throughput and simplicity matter more than latency.
     Don't use when / simpler: insights must be near-real-time → streaming. But don't build
     streaming when a nightly batch is fine — batch is simpler and cheaper.
     Earns its place at: any analytical/aggregation workload where minutes-to-hours latency is
     acceptable. This covers a lot.
     Trade-offs: buys simplicity, easy reprocessing (rerun the job), high throughput; costs
     latency (data is as fresh as the last run) and large periodic resource spikes.
     Failure modes & smells: building streaming for data nobody consumes in real time; batch
     windows growing until they overrun the next run; reprocessing without idempotency
     double-counting.
     Combines / conflicts: combines with data warehouses, read replicas (read from a replica,
     not the primary), ELT. The default alternative to stream processing.
     Cheapest PoC to verify: ask the consumer how fresh the data must be; if "by tomorrow
     morning" is fine, batch wins.
     Evidence: established — DDIA (Ch. 10).

Stream Processing
Process events continuously as they arrive, producing low-latency results.
     Use when: you need near-real-time results (fraud detection, live dashboards, alerting, real-
     time personalization) and the freshness justifies the added complexity.
     Don't use when / simpler: periodic results suffice → batch. Streaming is operationally
     harder and is often adopted before any real-time need exists.
     Earns its place at: when the latency from event to insight must drop below batch (seconds
     vs minutes/hours) and that latency has business value.
     Trade-offs: buys low-latency, continuous results; costs handling out-of-order/late events,
     windowing, exactly-once-processing concerns, state management, and 24/7 operational
     burden.
     Failure modes & smells: streaming where batch was fine (complexity for no benefit);
     ignoring late/out-of-order events; unbounded state growth; consumer lag.
     Combines / conflicts: combines with event streaming logs (Kafka), CDC, idempotency. The
     alternative to batch when latency matters.
     Cheapest PoC to verify: quantify the business value of going from "minutes" to "seconds"
     of freshness; if it's negligible, stay batch.
     Evidence: established — DDIA (Ch. 11).

ETL vs ELT
ETL: extract, transform, then load into the warehouse. ELT: extract, load raw, then transform
inside the warehouse.
     Use when (ELT): modern cloud data warehouses (with cheap storage and powerful
     compute) — load raw data and transform with SQL in-warehouse; flexible and increasingly
     the default.
     Use when (ETL): strict pre-load validation/cleansing/privacy needs, or limited warehouse
     compute, where transforming before loading is required.
     Don't use when / simpler: small data that doesn't need a pipeline → query the source (or a
     replica) directly.
     Earns its place at: when analytical data volumes/sources warrant a warehouse pipeline at
     all.
     Trade-offs: ELT buys flexibility (transform later, keep raw) and uses warehouse scale; costs
     raw data sprawl and in-warehouse transformation discipline. ETL buys clean, validated
     loads; costs rigidity (re-transforming means re-extracting).
     Failure modes & smells: building heavy pipelines for trivial data; ELT without governance
     becoming a data swamp; brittle ETL that breaks on schema changes.
     Combines / conflicts: combines with batch/stream processing, CDC, warehouses/lakes.
     ETL and ELT are alternatives.
     Cheapest PoC to verify: check whether your warehouse can do the transforms at
     acceptable cost/speed; if yes, ELT is simpler.
     Evidence: strong-heuristic — modern data-engineering practice trending to ELT with
     cloud warehouses.

Change Data Capture (CDC)
Stream a database's row-level changes (inserts/updates/deletes) to other systems by tailing its
transaction log.
     Use when: you must propagate DB changes to other systems (search index, cache,
     warehouse, other services) in near-real-time without modifying application write paths,
     and without expensive polling.
     Don't use when / simpler: a periodic batch sync or the application emitting its own events
     (outbox) is sufficient → use those. CDC adds a moving part tied to DB internals.
     Earns its place at: when multiple downstreams need near-real-time DB changes and app-
     level eventing/polling is impractical or too invasive.
     Trade-offs: buys low-latency, low-impact change propagation decoupled from app code;
     costs operating CDC infrastructure (e.g., Debezium), coupling to DB log formats, schema-
     change handling, and at-least-once semantics (idempotent consumers required).
     Failure modes & smells: CDC breaking on a schema migration; treating the change stream
     as a guaranteed-ordered source of truth without care; using CDC where a simple nightly
     sync sufficed.
     Combines / conflicts: combines with event streaming, the outbox pattern (CDC can read
     the outbox), search-index/cache sync, warehouses.
     Cheapest PoC to verify: confirm downstreams truly need near-real-time changes; if a batch
     sync's latency is acceptable, you don't need CDC.
     Evidence: established — DDIA (Ch. 11); Debezium / log-based CDC practice.

§2.10 Observability
   The three pillars — logs, metrics, traces — answer different questions. Start with structured
   logs and a few metrics; add tracing when "where is the problem?" spans services.

Structured Logging
Emit logs as machine-parseable records (e.g., JSON with consistent fields) rather than free-text
lines.
     Use when: always, from the start. Structured logs are queryable, filterable, and
     aggregatable; free-text isn't.
     Don't use when / simpler: a throwaway script may not need it, but any real service should
     log structured.
     Earns its place at: day one.
     Trade-offs: buys searchable, correlatable logs (filter by user/request/field); costs slightly
     more setup and log volume/storage management.
     Failure modes & smells: logging secrets/PII; unstructured text you can't query; log volume
     so high it's unusable or expensive; no correlation/request ID to tie a request's logs together.
     Combines / conflicts: combines with correlation/trace IDs, metrics, tracing, log
     aggregation.
     Cheapest PoC to verify: try to answer "show me all logs for request X across the system"; if
     you can't, your logging isn't structured/correlated enough.
     Evidence: established — standard practice; Twelve-Factor (logs as event streams).

Metrics (RED / USE)
Numeric time-series for system health. RED (Rate, Errors, Duration) for request-driven services;
USE (Utilization, Saturation, Errors) for resources.
     Use when: any production service — to alert, dashboard, and understand health and trends
     cheaply at scale.
     Don't use when / simpler: you can't skip metrics for production, but avoid drowning in
     vanity metrics; instrument the few that drive decisions.
     Earns its place at: as soon as you run anything in production you need to keep healthy.
     Trade-offs: buys cheap, high-level, alertable health signals; costs choosing the right
     metrics, cardinality management, and alert tuning.
     Failure modes & smells: high-cardinality label explosion (a top cost/breakage source in
     metrics systems); alerting on causes instead of user-facing symptoms; hundreds of
     dashboards nobody reads.
     Combines / conflicts: combines with logs, traces, SLOs/error budgets, alerting. RED and
     USE are complementary lenses.
     Cheapest PoC to verify: define the 3–4 RED/USE metrics that would page you for a real
     user-facing problem; if you can't, you're measuring the wrong things.
     Evidence: established — Google SRE (the "Four Golden Signals"); Tom Wilkie (RED);
     Brendan Gregg (USE).

Distributed Tracing
Follow a single request as it flows across multiple services, with timing for each hop (via a
propagated trace ID).
     Use when: requests span multiple services and you need to find where latency or errors
     originate across the chain.
     Don't use when / simpler: a monolith or single service → logs + metrics usually suffice;
     tracing's main payoff is cross-service. Don't stand up tracing infra for one service.
     Earns its place at: when you have several services in a request path and "which hop is
     slow/failing?" is a question you can't answer with logs alone.
     Trade-offs: buys end-to-end request visibility and pinpointed bottlenecks across services;
     costs instrumenting every service to propagate context, sampling decisions, and trace-
     backend operation.
     Failure modes & smells: broken traces because one service doesn't propagate the trace
     context; 100% sampling overwhelming cost/storage; adopting tracing for a single-service
     app.
     Combines / conflicts: combines with structured logs (share the trace/correlation ID),
     metrics, service mesh. Most valuable in microservices/distributed systems.
     Cheapest PoC to verify: instrument two services in one request path with a propagated
     trace ID and confirm you can see per-hop timing end-to-end.
     Evidence: established — Google "Dapper" paper; OpenTelemetry standard.

§2.11 Cross-cutting

Multi-Tenancy (shared vs siloed)
Serve multiple customers (tenants) from one system. Shared: tenants share
infrastructure/database (with isolation logic). Silo: each tenant gets dedicated resources.
     Use when (shared): SaaS with many small/medium tenants — best resource efficiency and
     simplest operations; isolate via a tenant_id column or schema-per-tenant.
     Use when (silo): strict isolation/compliance, "noisy neighbor" risk, or a few large tenants
     willing to pay for dedicated resources.
     Don't use when / simpler: a single-customer system → no multi-tenancy needed. Don't
     build elaborate tenant isolation before you have multiple tenants.
     Earns its place at: when you actually serve multiple customers from shared software; the
     shared-vs-silo split depends on isolation/compliance needs and tenant size.
     Trade-offs: shared buys efficiency and simple ops; costs isolation risk (a bug or query
     leaking across tenants) and noisy-neighbor effects. Silo buys strong isolation; costs higher
     per-tenant cost and operational multiplication.
     Failure modes & smells: a missing tenant filter leaking one tenant's data to another (the
     cardinal multi-tenancy bug); one heavy tenant degrading others (noisy neighbor) in a
     shared model; per-tenant infrastructure sprawl in a silo model.
     Combines / conflicts: combines with bulkheads (isolate noisy tenants), rate limiting/quotas
     per tenant, row-level security. Shared and silo are points on a spectrum (hybrid is common).
     Cheapest PoC to verify: write a query without the tenant filter in a test and confirm your
     isolation layer still prevents cross-tenant leakage. If it doesn't, shared multi-tenancy isn't
     safe yet.
     Evidence: established — AWS SaaS multi-tenancy guidance; standard SaaS architecture.

Geo-Distribution / Multi-Region
Run the system in multiple geographic regions for lower latency to distant users and/or resilience
to a regional outage.
     Use when: you have a genuinely global user base with latency requirements a single region
     can't meet, or a regulatory/availability requirement to survive a full-region failure.
     Don't use when / simpler: a regional audience, or no hard cross-region availability
     requirement → a single region (with multi-AZ redundancy) is far simpler. Multi-region is
     one of the most complex topologies; adopt it last.
     Earns its place at: proven global latency needs or a hard "survive a region outage" / data-
     residency requirement.
     Trade-offs: buys low latency for distant users and regional fault tolerance; costs enormous
     complexity in cross-region data consistency (this is the crux — strong consistency across
     regions is slow; eventual brings conflicts), data-residency handling, replication cost, and
     failover testing.
     Failure modes & smells: going multi-region for resilience without solving cross-region data
     consistency (the actual hard part); a "multi-region" setup whose database still lives in one
     region (no real regional independence); untested regional failover.
     Combines / conflicts: combines with CDN/edge, eventual consistency or specialized
     globally-distributed databases, redundancy/failover, data-residency partitioning. Conflicts
     with simple strong-consistency assumptions.
     Cheapest PoC to verify: decide the consistency model for write data across regions first
     and prototype it; if you can't make the data story work, multi-region compute is moot.
     Evidence: established (complexity is well-known) / strong-heuristic (adopt late) —
     AWS multi-region guidance; DDIA on multi-datacenter replication.

Rate Limiting / Quotas
Cap how many requests a client/tenant can make in a time window, to protect the system and
ensure fair use.
     Use when: any public/multi-tenant API, to prevent abuse, protect against traffic spikes,
     ensure fairness, and (for paid APIs) enforce plan limits. (Algorithms: token bucket / sliding
     window.)
     Don't use when / simpler: internal, trusted, low-volume callers → may not need it yet. Don't
     over-engineer limits for a single trusted client.
     Earns its place at: the moment you expose an API to clients you don't fully control, or need
     fairness/abuse protection.
     Trade-offs: buys protection from abuse/overload and fairness across clients; costs
     implementing limits, distributed counter coordination (shared state across instances), and
     clear client communication (429 responses, Retry-After ).
     Failure modes & smells: per-instance limits that don't actually cap a client across the fleet
     (need shared/distributed counters); limits so tight they block legitimate use; no clear
     error/retry signaling to clients.
     Combines / conflicts: combines with API gateway (a common place to enforce it), load
     shedding, bulkheads, quotas/billing. Closely related to load shedding (graceful overload
     behavior).
     Cheapest PoC to verify: hammer the API from one client across multiple instances and
     confirm the global limit holds (not just per-instance).
     Evidence: established — standard API-protection practice; AWS API Gateway throttling.

§3 — Situation → Pattern Matrix
Fast lookup. Match the signal, get a candidate pattern, and heed the trap to avoid. Always re-
check against §0 first.
Situation / signal                  Recommended pattern(s)             Trap to avoid

A read is slow                      Add an index; tune the query       Adding a cache or new datastore
                                                                       to hide a missing index

Reads dominate and saturate the     Read replicas; then cache-aside    Sharding (writes aren't the
primary DB                                                             bottleneck); "scaling writes"
                                                                       with replicas

One DB node can't hold data or      Partitioning / sharding            Sharding before exhausting
sustain writes (after vertical +                                       vertical scaling and replicas; a
replicas)                                                              hot-spot shard key

A hot, expensive read tolerant of   Cache-aside (+ TTL, stampede       Cache-as-source-of-truth; no
slight staleness                    protection)                        invalidation; thundering herd

Static assets, geographically       CDN / edge caching                 Caching personalized/private
spread users                                                           responses; stale assets after
                                                                       deploy (use content hashing)

Slow/spiky background work on       Message queue (async)              Doing it synchronously and
the request path                                                       blocking the user; assuming
                                                                       exactly-once delivery

Many components must react to       Publish/subscribe / event-driven   Event spaghetti you can't trace;
one event                                                              hidden cyclic event chains

Need event replay or many           Event streaming (Kafka)            Running Kafka for a few emails;
consumers of an ordered log                                            expecting global (not per-
                                                                       partition) ordering

Must update the DB and publish a    Transactional outbox (+            Dual write (save then publish
message reliably                    idempotent consumers)              and hope); forgetting
                                                                       consumers must dedupe

One operation spans multiple        Saga                               Distributed transactions / 2PC;
services' data                      (orchestration/choreography)       (deeper trap: the service split
                                                                       was premature)

Need atomic change across           Keep data in one DB; else saga +   Two-phase commit (blocking,
systems                             idempotency                        fragile)

Operation may be retried            Idempotency + idempotency          Relying on exactly-once
(network/messaging)                 keys                               delivery; non-idempotent
                                                                       retried writes (double charges)
Situation / signal                    Recommended pattern(s)             Trap to avoid

Transient dependency failures         Retry with exponential backoff +   Retry storms (no jitter); retrying
                                      jitter                             non-idempotent or permanent
                                                                         errors

A dependency can hang and stall       Timeouts (always) + circuit        No timeout (threads pile up →
callers                               breaker                            cascade); breaker with no
                                                                         fallback

One slow dependency/tenant can        Bulkhead (resource isolation)      One pool for everything; over-
exhaust shared capacity                                                  partitioning into wasteful tiny
                                                                         pools

Traffic can exceed capacity           Load shedding + rate limiting      Unbounded queues that brown
(spikes/abuse)                                                           out everyone; no shedding → full
                                                                         outage

Non-essential part of a response      Graceful degradation / fallback    Silently degrading something
can fail                                                                 actually critical (e.g., payments)

Diverse clients need different data   GraphQL or BFF                     GraphQL for a simple single-
shapes                                                                   client API; N+1 resolvers; a BFF
                                                                         per tiny variant

Low-latency, typed internal           gRPC                               Exposing gRPC to browsers
service calls                                                            without a gateway; using it for
                                                                         trivial low-traffic calls

Public API needing auth/rate-         API gateway                        Adding a gateway in front of a
limit/routing in one place                                               single monolith

Returning large/changing lists        Cursor (keyset) pagination         Deep offset pagination (slow,
                                                                         rows shift); no pagination at all

Multiple teams blocked by one         Microservices (extract via         Premature microservices;
shared deploy                         strangler fig)                     distributed monolith; chatty
                                                                         services

App is growing; want clean            Modular monolith                   Jumping to microservices; or a
boundaries cheaply                                                       ball-of-mud monolith with no
                                                                         boundaries

Spiky/intermittent or event-glue      Serverless / FaaS                  Serverless for steady high load
workload                                                                 (cost) or latency-critical paths
 Situation / signal                  Recommended pattern(s)           Trap to avoid
                                                                      (cold starts)

 Insights can wait hours             Batch processing                 Building streaming for data
                                                                      nobody consumes in real time

 Insights needed in seconds          Stream processing                Streaming where nightly batch
                                                                      was fine; ignoring late/out-of-
                                                                      order events

 Propagate DB changes to             CDC (or outbox)                  CDC where a nightly sync
 search/cache/warehouse live                                          sufficed; breaking on schema
                                                                      migrations

 "Where is the latency across        Distributed tracing              Tracing a single-service app;
 services?"                                                           broken traces from missing
                                                                      context propagation

 Need correctness on                 Strong consistency in one DB     Eventual consistency here
 money/inventory/bookings            transaction                      (double-spend/oversell);
                                                                      distributed transactions

 Data can be briefly stale (feeds,   Eventual consistency +           Forcing global strong
 counts)                             idempotency                      consistency you don't need
                                                                      (latency/availability cost)

 Multiple customers on shared        Multi-tenancy (shared, isolate   Missing tenant filter (data leak);
 software                            via tenant_id)                   noisy neighbor with no isolation

 Global users / survive a region     Multi-region (solve write-data   Multi-region compute with a
 outage                              consistency first)               single-region database; untested
                                                                      failover

§4 — Anti-Patterns (the critic agent's checklist)
Each entry: the mistake, the smell that detects it, and the fix. The critic should scan every
proposal for these.
  1. Premature Microservices. Smell: services introduced with a small team / early product,
     justified by "scalability" or "best practice" rather than multiple teams colliding on deploys;
     more services than engineers who can operate them. Fix: start with a modular monolith;
   extract a service only when team-scaling deploy conflicts or a divergent scaling profile is
   present, via the strangler fig.
2. Distributed Monolith. Smell: "microservices" that must be deployed together; a change in
   one forces changes/redeploys in others; services share a database; tight synchronous
   coupling everywhere. Fix: either re-merge into a (modular) monolith, or fix boundaries so
   services are genuinely independently deployable with their own data. You're paying
   distribution's costs for none of its benefits.
3. Premature Sharding. Smell: sharding proposed before vertical scaling and read replicas are
   exhausted; no measured proof the single primary is maxed; "to handle future scale." Fix:
   scale up, add read replicas, add caching/indexes first. Shard only when a single (large)
   primary provably can't hold the data or sustain writes — and validate the shard key against
   real access patterns.
4. Cache as Source of Truth. Smell: the system can't function or loses data if the cache is
   cleared/restarted; writes go only to the cache; the durable store is treated as optional. Fix:
   the database is the source of truth; the cache is a disposable performance layer that can be
   rebuilt at any time. (Write-behind is the rare, risk-accepted exception — and even then,
   mind durability.)
5. Chatty Services. Smell: one user action fans out into many synchronous cross-service calls;
   latency = sum of hops; failure probability multiplies; an N+1 pattern across the network. Fix:
   redraw boundaries so a single action stays mostly within one service; batch/aggregate calls;
   use a BFF; or async events where appropriate. Network calls are expensive and fail —
   minimize them on the hot path.
6. Exactly-Once Delivery Fantasy. Smell: the design's correctness depends on a message
   being delivered exactly once across systems; no deduplication/idempotency; assumes the
   network/broker won't duplicate. Fix: assume at-least-once delivery and make consumers
   idempotent (idempotency keys, dedup). True end-to-end exactly-once delivery is
   impossible; idempotent processing is the real solution.
7. Dual Write. Smell: code commits to the database and then separately publishes a
   message/calls another system, "hoping both succeed"; no atomicity between the two. Fix:
   the transactional outbox (write state + event in one DB transaction; relay/CDC publishes),
   with idempotent consumers.
8. Distributed Transactions for Convenience. Smell: two-phase commit reached for across
   services; the deeper cause is usually data that was split prematurely. Fix: keep
   transactionally-related data in one database (then a local transaction suffices); if truly split,
   use a saga with compensations + idempotency.
9. Retry Storm / No Backoff or Jitter. Smell: fixed-interval retries; all clients retry in sync and
   hammer a struggling dependency, preventing its recovery; retries on non-idempotent or
   permanent errors. Fix: exponential backoff with jitter, bounded attempts, retry only
   idempotent operations and transient errors, and pair with a circuit breaker to stop retrying
   a clearly-dead dependency.
10. No Timeouts. Smell: remote calls with no time limit; under a slow dependency,
    threads/connections pile up and the whole service hangs — the root of most cascading
    outages. Fix: set sensible timeouts on every network/IO call, shorter than the caller's own
    deadline; add circuit breakers for repeat offenders.
11. Resume-/CV-Driven Development (a.k.a. shiny-tech-itis). Smell: a fashionable
    technology (Kafka, Kubernetes, microservices, a new NoSQL store, event sourcing) chosen
    without a present problem it uniquely solves; "best practice" or "everyone uses it" as the
    rationale. Fix: apply "choose boring technology" and the §0 gate — the advanced option
    must beat the boring default on a concrete, measured problem, spending a scarce
    innovation token deliberately.
12. Premature Optimization / Speculative Generality. Smell: heavy abstraction, caching,
    async, or scaling machinery built for load and use cases that don't exist and aren't
    projected; complexity with no measured driver. Fix: build the simple thing; measure;
    optimize the proven hot path. Most patterns can be added later behind a stable interface —
    defer them.
13. Event Sourcing / CQRS by Default. Smell: full event sourcing or split read/write models
    applied to ordinary CRUD with no audit/temporal/replay requirement; users confused by
    stale reads; painful event-schema evolution. Fix: use a normal database (plus an
    audit/history table if you just need history). Adopt event sourcing/CQRS only where
    audit/temporal/replay or genuinely divergent read/write scaling is core — and present it as a
    contested choice.
14. Ball of Mud Monolith. Smell: a monolith with no internal boundaries — everything imports
    everything, no module separation, change is risky and global. (Note: this is a discipline
    failure, not an argument for microservices.) Fix: impose module boundaries (a modular
    monolith) before considering any service extraction. Microservices won't fix a coupling
    problem you can't solve in one codebase.
15. Ignoring Backpressure / Unbounded Queues. Smell: queues or buffers with no limit; under
    sustained overload they grow until memory/latency collapse; producers outrun consumers
    indefinitely. Fix: bound queues, apply backpressure (slow/refuse producers), and add load
    shedding so overload degrades gracefully instead of brownout.

Sources (canonical & authoritative)
Books

    Martin Kleppmann — Designing Data-Intensive Applications (O'Reilly, 2017). The primary
    reference for storage, replication, partitioning, consistency, batch/stream, and consensus.
    Michael T. Nygard — Release It! (2nd ed., Pragmatic Bookshelf, 2018). Origin/home of
    timeouts, circuit breaker, bulkhead, and stability patterns.
     Sam Newman — Building Microservices (2nd ed., O'Reilly, 2021) and Monolith to
     Microservices (O'Reilly, 2019). Monolith-first, when/how to decompose, strangler fig.
     Gregor Hohpe & Bobby Woolf — Enterprise Integration Patterns (Addison-Wesley, 2003).
     Messaging, queues, pub/sub.
     Martin Fowler — Patterns of Enterprise Application Architecture (Addison-Wesley, 2002).
     Chris Richardson — Microservices Patterns (Manning, 2018), and microservices.io — saga,
     transactional outbox, API gateway, database-per-service, CQRS.
     Betsy Beyer et al. — Site Reliability Engineering (Google/O'Reilly, 2016) and The SRE
     Workbook (2018). Golden signals, load shedding, error budgets.
Articles / papers / write-ups
     Martin Fowler (martinfowler.com) — MonolithFirst, MicroservicePremium, CQRS, Event
     Sourcing, StranglerFigApplication.
     Dan McKinley — Choose Boring Technology.
     David Heinemeier Hansson — The Majestic Monolith. Kirsten Westeinde (Shopify) —
     Deconstructing the Monolith (modular monolith).
     Eric Brewer — CAP theorem (PODC keynote, 2000); Seth Gilbert & Nancy Lynch — formal
     CAP proof (2002). Daniel Abadi — PACELC (2012).
     Pat Helland — Life Beyond Distributed Transactions (2007), Idempotence Is Not a Medical
     Condition.
     Marc Brooker / AWS Architecture Blog — Exponential Backoff And Jitter.
     Leslie Lamport — Paxos. Diego Ongaro & John Ousterhout — In Search of an
     Understandable Consensus Algorithm (Raft, 2014).
     Google — Dapper (distributed tracing); Tom Wilkie — RED method; Brendan Gregg — USE
     method; OpenTelemetry.
     Confluent/Apache Kafka — exactly-once semantics docs; Tyler Treat — You Cannot Have
     Exactly-Once Delivery (on delivery-guarantee limits).
     Amazon Prime Video Tech blog (2023) — Scaling up the Prime Video audio/video
     monitoring service and reducing costs by 90% (the widely-cited monolith/serverless
     counter-example; note it concerns one tool's re-architecture, not a blanket reversal).
     AWS — Well-Architected Framework (Reliability/Performance pillars); SaaS multi-tenancy
     and API Gateway throttling guidance.

   Method note on contested entries: for microservices, serverless, event sourcing, GraphQL,
   and "exactly-once," this playbook deliberately presents the disagreement and the conditions
   under which each side is right, rather than declaring a winner. Treat any source — including
   this one — that presents a contested choice as settled fact with suspicion.
