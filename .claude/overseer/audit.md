# Overseer self-improvement audit log

Proposals from the overseer for changes to its own SKILL.md. The overseer
NEVER modifies SKILL.md directly — proposals here await human ratification
(propose → gate → ratify → replay).

This file is the V2 path. In V1, the overseer just appends proposals; the
human reads them and edits SKILL.md manually when ratified.

## Proposal format

```
## <ISO timestamp UTC> — <proposed change>
- Evidence: <ledger entries supporting this — minimum 3 cited>
- Rationale: <why this would improve the overseer>
- Risk: <how this could go wrong>
- Status: PROPOSED | RATIFIED | REJECTED
```

## When to propose

- A pattern fired 5+ times across 3+ slices and is not in the current
  12-check checklist → propose adding it.
- A current check fires often but is reversed by the human in
  escalations.md → propose tuning or removal.
- A class of escalation is consistently waved through → propose
  autonomous handling.

## What NOT to propose

- Removing any check just because it triggers BLOCKs frequently. Frequent
  BLOCKs are the point. Anti-Goodhart.
- Adding checks that mimic existing tooling (linters, type checks).
- Lowering the citation-or-prune threshold.

---

## 2026-08-25 — Escalation calibration: decide-and-fold-in for two-way doors, with an explicit non-negotiable escalate list

**Scope note.** This file's header scopes it to "changes to the overseer's own
SKILL.md". This proposal targets `.claude/skills/slice-builder/SKILL.md`
instead. Filed here anyway because Article 7 names `audit.md` generically as
*the* propose → ratify → replay channel, and it is the only such channel the
repo has. Widening the file's scope from "the overseer's definition" to "any
agent definition" is itself part of this proposal; the alternative was an
unrecorded edit to an agent definition, which Article 7 forbids outright.

- **Evidence** (9 entries in `escalations.md`, all on `slice:voice-intake-demo`;
  the audit rule asks for 3+):
  - `2026-08-23T16:08:00Z` DESIGN_FORK — recommendation A, human chose A, immediate.
  - `2026-08-24T10:33:00Z` DESIGN_FORK — recommendation A, human chose A, immediate.
  - `2026-08-24T10:47:00Z` PRODUCT_DECISION — recommendation B, human chose B, immediate.
  - `2026-08-24T11:29:00Z` PREMISE_PROBE — recommendation A, human chose A, immediate.
  - `2026-08-24T19:41:13Z` ADR_RATIFICATION — recommendation A, human chose A, immediate.
  - `2026-08-25T00:00:00Z` TOOLING_DECISION — recommendation (b), human chose (b), immediate.
  - Ledger corroboration: `ledger.md` `2026-08-24T20:18:01Z` (OVERSEER_ADR_REQUIRED,
    category `recovery`) and `2026-08-24T11:35:00Z` (PLANNING_COMPLETE, category
    `strategy`).
  - **Every one of the 9 records "Latency to decision: immediate."**

- **Rationale — this rule discriminates; it does not loosen.** That distinction is
  the whole proposal, so it is stated before the count that prompted it.

  The raw signal is that 6 of 9 escalations took the recommendation unchanged, and
  the "Audit signal interpretation" section of `escalations.md` says such a class
  "can likely be handled without escalation." Read only that far, the conclusion
  would be *escalate less* — a rule that uniformly loosens, and one Article 3
  should be suspicious of.

  The sharper reading, which is the one this proposal rests on: **the classes where
  the owner's input actually changed the outcome are precisely ratified-text
  amendments, exit-criterion measurement, and precedent-setting decisions.** Those
  are not a subset of the waved-through class — they are its complement. So the
  escalate list survives *intact* while exactly one class is reclassified. The rule
  gets sharper, not slacker: it discriminates by whether the owner's judgment has
  ever been load-bearing for that class, rather than by how often stopping felt
  expensive.

  *Provenance, recorded because the two readings license different rules:* the
  owner's initial framing was the count-based one ("six waved through means less
  escalation"). The discriminating reading was the implementer's, offered in the
  same session; the owner then directed that it replace the count-based framing
  here, as the better argument. Attribution is noted because a future audit reading
  "the owner proposed relaxing escalation" would misread who argued what, and
  because the count-based version is the one that would decay badly under pressure.

  Underneath both, **the calibration is not a new rule at all.** Constitution
  Article 5 already says it: *"If reversing the decision later would be cheap, it is
  a two-way door → automate it."* The over-escalation was a failure to apply a rule
  already written down. What the skill gains is the operational form of Article 5 at
  slice altitude.

- **The per-category evidence behind that reading.** Of the nine:
  - One **reversal**: `2026-08-23T16:27:00Z` DESIGN_FORK — recommended A
    (BridgeSession owns the clock), human chose **B** (TimingRecorder owns it).
    That decision amended already-finalized Phase 2 seam text.
  - Two with **no recommendation offered**, because the implementer judged the
    question beyond its authority: `2026-08-24T20:14:00Z` (touched the ratified
    seam *and* the exit criterion's measurement basis) and `2026-08-24T20:18:01Z`
    (creating the project's first ADR directory).

  So the classes where the human's input actually changed the outcome are
  precisely: ratified artifact text, exit-criterion measurement, and structural
  one-way doors. **The evidence argues for keeping those escalations while
  dropping the rest** — it is not a general case for less escalation. Anti-Goodhart
  (Article 3) is satisfied: no check is being weakened because it fired often;
  one class is being reclassified because the record shows it never changed an
  outcome, and the classes that *did* change outcomes are being written down as
  non-negotiable.

- **Hard condition attached (this is what makes the loosening safe, and it is a
  condition, not a suggestion).** Deciding alone is conditional on the fold-in
  landing in **the same turn as the implementation**. If the record lags the
  decision, the project loses both the stop and the record, and is strictly worse
  off than before. This is not hypothetical: the `2026-08-24T20:18:01Z` entry
  closes with the owner's standing correction — *"chat ratification from the owner
  authorises writing the change into the artifact — it is not itself the record.
  Fold in during the same turn as the implementation, without waiting to be
  asked."* That correction was issued because check #8 (chat-only design) had
  already fired once on this slice, for exactly this failure.

- **Risk.** (1) Scope creep in what counts as "local and reversible" — mitigated
  by the escalate list being absolute rather than a balancing test, and by the
  one-commit-to-undo test being stated in concrete terms. (2) The fold-in
  condition silently decaying, leaving decisions unrecorded — this is the real
  risk, and its detector is the overseer's existing check #8, which caught it once
  already. (3) An agent widening the decide-alone list by reading it generously;
  countered by the list being enumerated, not principled.

- **Status: RATIFIED** by the owner in-session, 2026-08-25, who directed it be
  written into the skill, logged here, and recorded in `MEMORY.md`. Replay: the
  remaining Seam 4 behaviors (G1-G4, C1-C3) run under it.

- **Not proposed, deliberately:** no edit to `constitution.md`. Article 5 already
  carries the principle, the file is HUMAN-ONLY-EDITABLE, and Article 7 forbids an
  agent touching it. The skill references Article 5 rather than restating it.

---

## 2026-08-25 — Stop-discipline narrowing: the gate is the behavior list, not the TDD cadence

**Amends a guard ratified earlier in the same session.** The entry directly
above added the escalation calibration and, with it, a protective paragraph in
`## Stop discipline` asserting that the calibration loosens *decisions* and
never the workflow's cadence — that "a RED→GREEN→REFACTOR transition is a
checkpoint, not a question." This proposal narrows that paragraph. A future
auditor seeing a guard added and narrowed within a day of itself is right to be
suspicious, so both moves are grounded here rather than in preference.

**Why the original guard was added, and what it got right.** It was written to
stop one specific misreading: that "decide alone" licenses unreviewed judgment
calls at speed. That risk is real and this proposal does not touch it. What the
guard got wrong was the *mechanism* it credited with preventing it. It assumed
the RED→GREEN stop was the thing standing between the implementer and
unreviewed drift. The record says otherwise.

- **Evidence that the cadence stops never changed an outcome.** Every
  RED→GREEN and GREEN→REFACTOR stop taken on Seam 4 produced "go" with no
  redirection. Most recently and most legibly, C1 (2026-08-25, this session):
  RED shown, `NotImplementedError` at `session.py:182`, owner replied "go".
  The GREEN→REFACTOR stop is weaker still, and structurally so: at that point
  the suite is already green, so the refactor either holds it green or does
  not, visibly, in seconds. There is no judgment for the owner to exercise that
  the suite does not exercise for them.

- **Evidence that the behavior-list gate repeatedly did change outcomes.** This
  is the complement, and it is why the amendment narrows rather than removes:
  - **Q18** — `frame_error` must carry `stage`. The artifact records it as
    "Raised by the owner while approving the Seam 4 behavior list, before any
    handler code was written." Without it, T3/T4/G3 would have asserted a
    `frame_error` line that provably cannot name which step dropped the frame,
    because `reject_partial_pcm16` is shared and emits a byte-identical message
    from two stages.
  - **G4** — explicitly declined for cutting by the owner (2026-08-25) when
    offered as redundant with T5. The artifact now records why: T5's drop lands
    before the resampler on a structurally protected leg, so a recovery path
    proven only there is proven on the wrong leg.
  - **Q8** (`2026-08-24T19:41:13Z`) — the μ-law reference-table provenance,
    where owner review caught a false basis (`audioop` on a 3.12.3 interpreter)
    that had entered two separate artifact locations.
  - **Q14** — reserved-key exception type, owner-ratified *overruling* the
    implementer's "no caller exists yet" lean.
  - **Seam 4's critic note** — real instance and file re-read rather than a
    spy, resolved by owner direction 2026-08-25.
  - Plus the ratified-text and vehicle classes already enumerated in the entry
    above: the clock-ownership reversal (`2026-08-23T16:27:00Z`) and the ADR
    vehicle (`2026-08-24T20:18:01Z`).

- **The amendment.** Once the owner has approved a behavior list for a seam,
  each behavior runs RED→GREEN→REFACTOR in one turn, and the implementer
  continues to the next behavior in that list without stopping. The RED output
  and the sentinel are still written to the transcript — they are read
  afterwards, not attended live.

- **What the narrowed guard still forbids, and this is the load-bearing half.**
  Chaining is licensed *within* an approved behavior list and not across one.
  Do not invent a behavior mid-flight, do not extend the list, do not begin a
  seam whose list the owner has not seen. That is the unreviewed-judgment-at-
  speed failure the original guard was written for, and it is now attached to
  the mechanism that actually prevents it.

- **What still stops, unchanged.** The escalate list in the entry above, in
  full. Plus genuine failure: a test that fails for a reason its behavior did
  not predict, a falsified premise, an assertion that cannot be made to hold as
  specified. Stop for surprises, not for milestones — and explicitly, do not
  stop to report success. "It works, here is the count" is a line in the next
  report, not a turn of its own.

- **Risk.** (1) The list boundary eroding — an implementer treating a behavior
  it discovered mid-flight as though it were on the approved list. Detector:
  the behavior list is written into the slice artifact (Seam 4's is, precisely
  because two sessions had already lost it), so a test with no corresponding
  entry is visible in review, and overseer check #11 (scope drift) covers it.
  (2) A failure inside a chained run going unnoticed until the end of the seam.
  Mitigated by the stop-on-genuine-failure rule above, and by `verify-on-stop`
  blocking a turn that ends on a red suite without the TDD RED sentinel.
  (3) Loss of the per-cycle transcript record — not incurred: the RED output
  and sentinel are still emitted, only the wait is dropped.

- **Status: RATIFIED** by the owner in-session, 2026-08-25, who directed the
  narrowing, specified its bounds, and required this proposal be filed before
  the skill edit. Replay: C1's REFACTOR plus C2 and C3 run to completion under
  it, in one turn, and Seam 4 is delivered complete.

- **Recorded separately:** both this entry and the one above it, together with
  the skill edits they authorise, were uncommitted at the time of writing —
  present only in the working tree. Owner directed they be committed together
  so the record outlives the session. `git commit` is a human checkpoint under
  this project's autonomy policy and is hook-blocked for agents, so the files
  are staged and the command handed over rather than run.
