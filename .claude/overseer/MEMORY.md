# Overseer cross-slice memory

Entries here are added only when a pattern recurs across 3+ slices, OR when
the user has manually ratified a pattern. Empty initially.

## Citation-or-prune rule (load-bearing)

Every entry in this file MUST cite at least two ledger.md entries by
date+slice. Uncited entries are deleted on next read. This prevents
memory pollution and confabulation amplification.

## Source-of-truth pointers

- Project conventions: `CLAUDE.md`
- Slice ledger: `PROGRESS.md`
- Architectural decisions: `docs/adr/`
- TDD discipline: slice-builder skill
- Overseer ledger: `.claude/overseer/ledger.md`
- Human escalations log: `.claude/overseer/escalations.md`
- Self-improvement proposals: `.claude/overseer/audit.md`

## Cross-slice patterns

### Artifacts state name-claims and third-party-behaviour claims at the same confidence as claims we control

**Admitted under the manual-ratification clause, owner-ratified 2026-08-26; the re-check it demanded has now run.** The original entry said "observed on **one** slice (`voice-intake-demo`) — re-check against slice 2 before treating it as settled." Slice 2 (`gemini-live`) is done, and the pattern recurred twice more, in a new library and against a new failure surface. That is **two** slices, not three, so this still does not clear the 3-slice bar on its own — but it is no longer a single-slice observation, and the two new instances are the first that were caught *before* shipping rather than after. Re-check again against slice 3 (`twilio-server`), where the third-party surface is a wire protocol rather than an SDK.

**Pattern.** Three times in one slice, the planning artifact described something more confidently than the code or the world supported, and all three read identically on the page — flat declarative sentences, no hedge, no provenance:

1. **`PR-resampler-emits-per-chunk`** (falsified 2026-08-24) — soxr was assumed to emit per push; it batches. A claim about a third party's runtime.
2. **Premise 6, bit-reproducibility** (falsified 2026-08-25) — two `ResampleStream` instances were assumed to produce identical bytes; they diverge by up to 2 LSB once streamed. Also a third party's runtime.
3. **The Exit criterion's own proof mechanism** (falsified 2026-08-26) — four test names were asserted as the proof of the unit-suite half; three did not exist. A claim about *our own* names.
4. **`AsyncSession.receive()` assumed to be a session-level iterator** (`gemini-live`, 2026-08-27) — it is per-turn: it `break`s on the first `turn_complete` (`live.py:455-459`). Taken from the signature, which returns an `AsyncIterator` and says nothing about where it stops. A third party's runtime again.
5. **A local close assumed distinguishable from a remote close** (`gemini-live`, 2026-08-27) — `AsyncSession.close()` closes the same socket the reader is blocked on, and `_receive()` converts the resulting `ConnectionClosed` to `APIError` unconditionally. The two are byte-identical. `Closed.reason` feeds `CallRecord.ended_reason`, so the label was decided by a race until Q4 imposed an ordering invariant.

The first two are already covered by the artifact's standing soxr rule ("no new claim about what soxr does at runtime enters this artifact without a measurement pasted alongside it"). The third shows the rule was scoped too narrowly: **the failure is not specific to soxr, and not specific to third parties.** A name is as checkable as a measurement and was checked as little. The common factor is that the claim was cheap to verify and expensive to be wrong about, and confidence was set by how obvious it felt rather than by whether anyone had looked.

**How to apply.** Before a claim enters a planning artifact, ask which kind it is. *Verified* (a measurement or an enumeration was run — say which, and when). *Derivable* (follows from text in this repo — cite the file). *Assumed* (neither — mark it, and name what would falsify it). Identifiers we control — test names, function names, file paths, event names — are the **verified** kind, because `grep` settles them in seconds; asserting one unchecked is the same error as asserting an unmeasured library behaviour, with less excuse.

**Structural corollary, from the third instance.** Prefer criteria that assert **properties over ratified artifacts** rather than string matches against unratified identifiers. The Exit criterion was reformulated on exactly this ground (Q21): it now asserts that every behavior in each seam's ratified behavior list has a passing test, because the behavior lists are what the owner ratified and the test names never were. A string-matching criterion breaks on the next rename and fails silently; a property-asserting one degrades into a visible finding — and did so immediately, surfacing a resampler behavior list that numbers B1-B5 and B7 with no record of B6.

### The two new instances sharpen the detection story, not just the count

Instances 1-3 were caught by measurement, by `grep`, or after the fact. Instances 4 and 5 were caught by **reading the SDK's source**, and neither was reachable any other way:

- **A green suite could not have caught either one.** Both live in the gap between what the SDK does and what a test fake does. The fake is built from the assumed contract, so a suite that passes against it has confirmed the assumption, not the SDK. Instance 4 is the sharp case: a fake that streams every event in one pass makes a session-level reader and a per-turn reader indistinguishable, and every test passes either way.
- **Both would have surfaced first on a live call**, which for this feature means a PSTN call — the most expensive place in the project to discover anything, and the one where the failure is silent (instance 4 ends the conversation after the greeting; instance 5 mislabels the record).

**Corollary, stated so it is actionable: a fake cannot be evidence for the contract the fake implements.** When the contract under test is a third party's, the evidence has to come from outside the test — the vendor's source, or a measurement against the real thing. The test then locks in what you found; it does not discover it.

### The concrete rule (owner-ratified 2026-08-27)

**For `google-genai`, read the source, not the signature.** The package is installed and readable; `receive()`, `_receive()` and `close()` are ~100 lines total. Every one of the three build-time defects in `gemini-live` was settled by opening `google/genai/live.py` and reading it, and none of them was visible in the signature, the type stub, or the published docs.

The general form, for the next vendor: **a signature tells you the shape of a call, not the lifecycle of what it returns.** Iterator termination, exception identity across causes, and idempotency of teardown are all lifecycle, and all three bit here. Ask those three questions of any streaming vendor API before writing the fake, and answer them from source or measurement.

**Citations (per the citation-or-prune rule above):**
- `ledger.md` 2026-08-27T00:30:00Z — gemini-live — PLANNING_COMPLETE, category `strategy`. Records all four build-time defects with SDK source line references, and notes that defect (1) also falsified the earlier spike's own `OPEN_not_a_premise` conclusion.
- `ledger.md` 2026-08-25T21:56:31Z — voice-intake-demo — OVERSEER_ESCALATE, category `recovery`. Check #1 fired on the Exit criterion's four test names; the enumeration of all 36 tests is the evidence.
- `ledger.md` 2026-08-24T20:18:01Z — voice-intake-demo — OVERSEER_ADR_REQUIRED, category `recovery`. Check #8 on the artifact describing a contract the code did not implement — the same artifact-vs-code drift, one level down.
- Owner decision and the reasoning for asserting a property rather than a string: `.claude/overseer/escalations.md`, 2026-08-26 ADR_RATIFICATION. Folded into the slice artifact as Q21; falsification records for the first two instances are Premise 6 and the standing soxr rule in `.claude/overseer/slice/voice-intake-demo.md`.

### For a claim that is cheap to check, the check is not diligence — it is the only thing that has ever worked

**Admitted under the manual-ratification clause.** Written 2026-08-27 from the
`twilio-server` planning session; the owner may strike it. This is the operational
half of the entry above: that one says *classify your claims before asserting them*,
this one says what to do once a claim is classified as checkable.

**Pattern.** Across one session, the planner made six assertions about things already
written down. Every one was wrong. Every one was a single `grep`, `git branch`, or
column-sum away from being right:

| asserted | one check showed |
|---|---|
| S2 `gemini-live` did not exist | it was on `origin/slice/s2-gemini-live` |
| `Q19`/`Q20` were S2's decisions | both belong to `voice-intake-demo` |
| barge-in was "permanently cut" | deferred, live trigger, `vertical-profile-bridge.md:263` |
| UK-region storage was a DAG slice | feature-level deferral, `:262`, trigger never fires from build order |
| the exit criterion held no threshold | it held one, inside the audio assertion |
| the test-node total (45, then 47, then 52) | all hand-counts, all wrong; 57 by regex |

None required judgment. Two were made **in the same document that warned against that
exact confusion**, and one was made while extending the memory entry above it.

**The counterpart, which is the actionable half.** In the same session, 17 blocking
defects were found — and **not one came from re-reading carefully.** Every one came
from a mechanical operation someone ran:

- a **decision → seam coverage map**, walked row by row (found `S3-Q5`, `S3-Q9`);
- the same map extended to **ratified guarantees**, then **type members**, then
  **AND-split properties**, then **endpoint error paths** (found guarantee (d),
  `Interrupted`, `streamSid`, the `POST /voice` failure path) — each new axis produced
  a finding, so the map was repeatedly a map of the territory already thought about;
- **constructing the wrong implementation** and asking whether any test fails against
  it (found the bare `del`, the dispatch-table `KeyError`, the registry `popitem`);
- a **letter-by-letter sub-clause diff** between two sections restating the same thing
  (found three assertions that vanished in compression: `S11.c`, `S14.c`, `S12.c`);
- **walking the parent contract's obligations** against the plan (found the `__main__`
  gate, then `fastapi`/`uvicorn` absent from `pyproject.toml` and the environment).

**How to apply.** When a claim is checkable, run the check — do not budget care instead.
Carefulness has a measured hit rate of zero here across six attempts. And when a
defect is found by an enumeration, **do not fix only the instance: run the enumeration
to exhaustion**, because every axis that produced one finding produced another the
moment it was extended. Where two sections of an artifact restate the same content,
diff them mechanically rather than reading both attentively; that transcription step is
where clauses die silently.

**Citations (per the citation-or-prune rule above):**
- `ledger.md` 2026-08-27T09:00:00Z — twilio-server — PLANNING_COMPLETE, category
  `strategy`. 17 findings across 20 rounds, the enumeration axes, and both cold-reader
  passes finding omissions in the same deliverables enumeration.
- `ledger.md` 2026-08-27T00:30:00Z — gemini-live — PLANNING_COMPLETE, category
  `strategy`. `Interrupted` missed by ten round-anchored rounds and found by the cold
  read — the same lesson one slice earlier, and the evidence base for
  `.claude/commands/plan-slice.md`'s cold-reader section.

### Escalation calibration — decide two-way doors, escalate the named seven

**Admitted under the manual-ratification clause, not the 3-slice clause.** This
file's rule is "3+ slices, OR the user has manually ratified." The owner ratified
this on 2026-08-25. It has been observed on **one** slice
(`voice-intake-demo`) — stated plainly so a later reader does not mistake it for
a pattern that recurred across three. Re-check it against slice 2 before treating
it as settled.

**Pattern.** Escalating a reversible, module-local decision buys nothing when the
fold-in discipline already records it where the owner can review it. Decide those
alone, fold in the same turn, report as "Decided X because Y; overrule if you
disagree." Escalate without exception on: ratified artifact text; what the exit
criterion asserts or how it is measured; the evidence log's integrity; a falsified
premise (Article 8); the slice's hard-to-undo set; anything that audits your own
work (hooks, overseer — Article 7); and a verification with no available oracle.

**The condition that makes it safe:** the fold-in lands in the same turn as the
implementation. A decision made alone and recorded next turn is a violation, not a
delay — it costs the project both the stop and the record.

**Why it is not "escalate less":** across 9 escalations on `voice-intake-demo`,
all resolved immediately and 6 took the recommendation unchanged — but the single
reversal (clock ownership) amended ratified seam text, and the two where the
implementer declined to recommend touched the ratified seam and the exit
criterion's measurement basis. The classes where the owner changed the outcome are
exactly the escalate list. Constitution Article 5 already stated the principle
("two-way door → automate it"); the over-escalation was a failure to apply a rule
already written down.

**Citations (per the citation-or-prune rule above):**
- `ledger.md` 2026-08-24T20:18:01Z — voice-intake-demo — OVERSEER_ADR_REQUIRED,
  category `recovery`. Check #8 fired on chat-only design; its resolution is the
  source of the same-turn fold-in condition.
- `ledger.md` 2026-08-24T11:35:00Z — voice-intake-demo — PLANNING_COMPLETE,
  category `strategy`. Records the 7 owner-ratified decisions whose latencies are
  the evidence base.
- Full proposal and per-entry evidence: `.claude/overseer/audit.md`, 2026-08-25
  (RATIFIED). Written into `.claude/skills/slice-builder/SKILL.md` §"Escalation
  calibration".
