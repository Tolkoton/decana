# Premise log — what we assume is true, and what depends on it

Governed by **Constitution Article 1** (verify before you commit) and **Article 8**
(a falsified premise re-opens whatever depended on it). Every level records its
load-bearing assumptions here — not only inside its own plan — so that when one turns
out false, the system can trace *everything it affects* instead of hoping someone
remembers.

(Markdown for now because every agent reads it natively and a human can scan it. If a
tool ever needs to query it programmatically, graduate it to JSON with the same
fields.)

## How to use — four operations

1. **RECORD.** When a plan states a load-bearing assumption about an external system
   or a chosen technology, add a row with status `unverified` and list what depends
   on it.
2. **VERIFY.** Attach evidence (a spike, a PoC, or docs + a captured runtime check)
   and set the status and the date checked. External-system checks go **stale after
   ~7 days**.
3. **FALSIFY & PROPAGATE.** If a check refutes the assumption, set status
   `falsified`, then mark every item in *depended-on-by* for review and route each to
   its level's human gate (Article 8).
4. **QUERY.** Before committing a plan: does it rely on any `unverified` or stale
   premise? Before deleting or changing something: what depends on it?

**Status:** `unverified` · `verified` · `accepted-as-risk` · `falsified`
**Level:** `slice` · `feature` · `architecture`

## Premises

| id | statement (one falsifiable sentence) | level | status | evidence | checked | depended-on-by |
|----|----|----|----|----|----|----|
| PR-example-01 | External API supports pagination via ?offset=N | feature | `unverified` | none | | `feature:data-sync` |

*(Add a new row whenever a plan states a new load-bearing assumption. Ensure the statement is a single falsifiable sentence. If an assumption is falsified, immediately flag all items in the 'depended-on-by' column for review.)*