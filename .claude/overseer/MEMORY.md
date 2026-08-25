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

**Admitted under the manual-ratification clause, not the 3-slice clause** — same caveat as the entry below. Observed on **one** slice (`voice-intake-demo`), owner-ratified 2026-08-26. Stated plainly so a later reader does not mistake it for a pattern that recurred across three. Re-check against slice 2 before treating it as settled.

**Pattern.** Three times in one slice, the planning artifact described something more confidently than the code or the world supported, and all three read identically on the page — flat declarative sentences, no hedge, no provenance:

1. **`PR-resampler-emits-per-chunk`** (falsified 2026-08-24) — soxr was assumed to emit per push; it batches. A claim about a third party's runtime.
2. **Premise 6, bit-reproducibility** (falsified 2026-08-25) — two `ResampleStream` instances were assumed to produce identical bytes; they diverge by up to 2 LSB once streamed. Also a third party's runtime.
3. **The Exit criterion's own proof mechanism** (falsified 2026-08-26) — four test names were asserted as the proof of the unit-suite half; three did not exist. A claim about *our own* names.

The first two are already covered by the artifact's standing soxr rule ("no new claim about what soxr does at runtime enters this artifact without a measurement pasted alongside it"). The third shows the rule was scoped too narrowly: **the failure is not specific to soxr, and not specific to third parties.** A name is as checkable as a measurement and was checked as little. The common factor is that the claim was cheap to verify and expensive to be wrong about, and confidence was set by how obvious it felt rather than by whether anyone had looked.

**How to apply.** Before a claim enters a planning artifact, ask which kind it is. *Verified* (a measurement or an enumeration was run — say which, and when). *Derivable* (follows from text in this repo — cite the file). *Assumed* (neither — mark it, and name what would falsify it). Identifiers we control — test names, function names, file paths, event names — are the **verified** kind, because `grep` settles them in seconds; asserting one unchecked is the same error as asserting an unmeasured library behaviour, with less excuse.

**Structural corollary, from the third instance.** Prefer criteria that assert **properties over ratified artifacts** rather than string matches against unratified identifiers. The Exit criterion was reformulated on exactly this ground (Q21): it now asserts that every behavior in each seam's ratified behavior list has a passing test, because the behavior lists are what the owner ratified and the test names never were. A string-matching criterion breaks on the next rename and fails silently; a property-asserting one degrades into a visible finding — and did so immediately, surfacing a resampler behavior list that numbers B1-B5 and B7 with no record of B6.

**Citations (per the citation-or-prune rule above):**
- `ledger.md` 2026-08-25T21:56:31Z — voice-intake-demo — OVERSEER_ESCALATE, category `recovery`. Check #1 fired on the Exit criterion's four test names; the enumeration of all 36 tests is the evidence.
- `ledger.md` 2026-08-24T20:18:01Z — voice-intake-demo — OVERSEER_ADR_REQUIRED, category `recovery`. Check #8 on the artifact describing a contract the code did not implement — the same artifact-vs-code drift, one level down.
- Owner decision and the reasoning for asserting a property rather than a string: `.claude/overseer/escalations.md`, 2026-08-26 ADR_RATIFICATION. Folded into the slice artifact as Q21; falsification records for the first two instances are Premise 6 and the standing soxr rule in `.claude/overseer/slice/voice-intake-demo.md`.

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
