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

**A third instance, and the sharpest one: an assertion written before the code exists is
treated as established the moment it goes green.** (Owner-ratified 2026-08-27.) In
`twilio-server`, an `app` fixture injected a `live_factory` that raised
`AssertionError("live_factory must not run for these tests")`. That asserts the
*opposite* of ratified contract text — S3-Q1 says `POST /voice` opens the Live session —
and it passed for exactly as long as the webhook was an empty stub. It failed the moment
the endpoint was implemented **correctly**, and the instinct at that point is to
"fix" the code back toward the guard.

This is the same shape as the exit criterion that named four test functions, three of
which did not exist: **text written before the thing it describes, never checked against
the contract, and promoted to established by a green run.** A green suite is evidence
that code and tests agree, not that either matches what was ratified.

**How to apply.** When you write a fixture or guard asserting something must **NOT**
happen, check it against the contract before you write it — a guard that passes because
nothing is implemented yet proves nothing at all. And when a newly-correct
implementation breaks an older assertion, the first question is which one the contract
supports, not which one is older.

**Citations (per the citation-or-prune rule above):**
- `ledger.md` 2026-08-27T09:00:00Z — twilio-server — PLANNING_COMPLETE, category
  `strategy`. 17 findings across 20 rounds, the enumeration axes, and both cold-reader
  passes finding omissions in the same deliverables enumeration.
- `ledger.md` 2026-08-27T00:30:00Z — gemini-live — PLANNING_COMPLETE, category
  `strategy`. `Interrupted` missed by ten round-anchored rounds and found by the cold
  read — the same lesson one slice earlier, and the evidence base for
  `.claude/commands/plan-slice.md`'s cold-reader section.

### A guarantee stated in prose, with tests, and no mechanism behind it

**Admitted under the manual-ratification clause; recorded 2026-08-27 during unattended
operation.** Two slices, same shape, and it is the most productive single check this
project has.

**Pattern.** A contract states a guarantee. The seams test it. Nobody writes the
decision that *implements* it — and because the tests are written against fakes that
never exercise the branch, the suite is green and the guarantee is absent.

- `twilio-server`: ratified guarantee (b) — an exception from `on_call_end` is logged
  and does not affect the socket — had no decision. The teardown ended with a bare
  `await on_call_end(record)`. Found by walking guarantees against decisions.
- `analysis`: the Errors section claimed "`analyse` never raises" and Phase 3's Seam 4
  had five test cases for it, but no decision supplied the try/except.
  `asyncio.wait_for` intercepts only `TimeoutError`, so `APIError` and JSON parse
  failures propagated — **the two branches the ratified contract named most
  explicitly.** Found the same way.

**Why prose and tests together are not enough.** The prose reads as a commitment and
the seams read as coverage, so a reviewer checking either alone finds nothing wrong.
Only the *decision* names the mechanism, and only a map with a row per guarantee shows
that the row is empty.

**How to apply.** For every guarantee in the ratified contract **and every member of
every ratified type**, require three things before the phase converges: **a decision
that names the mechanism, a seam that names the wrong implementation, and an id that
names the test node.** Two out of three is the failure mode above, and it has never
announced itself — every instance was found by a coverage map walked row by row, never
by re-reading.

**It recurred FIVE times inside one artifact (`analysis`, 2026-08-27), and each
instance was found by enumeration and none by re-reading.** In order:
`analyse never raises` (prose + seams, no mechanism); the SDK entry point (the sync
facade blocks the loop and defeats the timeout); `compliance_notes`; `model`
(`live_model` vs `analysis_model`, one attribute apart); and `api_key`.

**The last one is the one to remember, because it inverts the usual comfort.** The SDK
falls back to `os.environ['GEMINI_API_KEY']` when no key is passed
(`google/genai/_api_client.py:128-140`, verified by execution), and that variable is
exactly what this project's deploy injects. So an implementation that drops the
argument passes the unit suite, passes the real-API smoke, **and passes production** —
there is no environment in the project's own deploy shape where it reveals itself. The
usual reassurance "a real call would catch it" is false here.

**A third instance, found by the cold read on `analysis` after the round-anchored
review had credited the area as handled.** `Analysis.compliance_notes` had the type
member and a seam whose *title* claimed to cover it — "`raw` and `compliance_notes`
survive the failure paths" — but no decision naming the success-path mechanism and no
id exercising one. Its only assertion sat on the failure path, where the code
hardcodes `()`: it asserted that an empty tuple is a tuple, which a passthrough
`Analysis(compliance_notes=data["compliance_notes"])` — shipping a mutable list inside
a frozen dataclass — satisfies just as well.

**A seventh instance added a sub-class the first six did not cover: an INCOMPLETE
REPAIR.** Seam 4 enumerates five failure modes. The round that added `summary`-content
assertions applied them to four of the five and silently skipped the empty-transcript
one — so a `summary=""` on that branch would have passed all 24 nodes, violating the
same guarantee the round had just been convened to enforce. The first six instances
were coverage that never existed; this was a fix that did not cover its own scope, and
it was introduced *by the repair itself*.

**The rule that follows:** when a fix applies to a family, apply it to the whole family
and then **count the family**. The sibling that gets skipped is the one nobody looks at
again, because the area now reads as recently handled.

**Two sharpenings this instance adds:**
- **A seam's title is not coverage.** "Seam 5 covers `compliance_notes`" was true of
  the heading and false of the assertions. Check what a seam *asserts*, not what it is
  called.
- **An assertion on a hardcoded value proves nothing.** Asserting a property of a
  literal the implementation supplies — `()` here — passes for every implementation,
  correct or not. The assertion has to sit on the path where the value is actually
  *computed*.

**Citations (per the citation-or-prune rule above):**
- `ledger.md` 2026-08-27T18:20:00Z — analysis — PLANNING_IN_FLIGHT, category
  `strategy`. The `analyse`-never-raises instance, with the SDK source that proved it.
- `ledger.md` 2026-08-27T09:00:00Z — twilio-server — PLANNING_COMPLETE, category
  `strategy`. Guarantee (b), and the coverage-map technique that found it.

### A vendor's sync and async facades are interchangeable to the type checker and not to the event loop

**Admitted under the manual-ratification clause; recorded 2026-08-27.** One slice so
far (`analysis`), so this does not clear the 3-slice bar — but it is recorded now
because the defect is invisible to the entire testing approach this project relies on,
and the next async vendor wrapper is the moment to re-check it.

**Pattern.** `google-genai` ships the same method twice:
`client.models.generate_content` (a blocking `def`) and
`client.aio.models.generate_content` (an `async def`). Verified by execution —
`inspect.iscoroutinefunction` is False and True respectively. Wrapping the **sync** one
inside an `async def` produces a coroutine function with **no internal `await`**, which:

- **silently disables `asyncio.wait_for`.** A timeout can only cancel at an `await`
  point, so the call runs for the real network duration regardless of the timeout the
  contract promises;
- **blocks the whole event loop** — in this project, the loop forwarding audio for
  every other live call, so one post-call analysis becomes dead air on strangers' calls.

Both pass `mypy --strict`: the wrapper's signature is `async def … -> str` either way.

**Why no fake can catch it, which is the part that matters.** A fake client is written
`async def generate_json(...): await asyncio.sleep(...); return ...` — a real coroutine
that suspends correctly. Every timeout test passes against it whether or not the real
client ever awaits anything. This is the "a fake cannot be evidence for the contract
the fake implements" rule from the entry above, in its most expensive form: here the
fake is not merely uninformative, it is *actively reassuring* about the exact property
that is broken.

**How to apply.** When wrapping any vendor SDK in an `async def`, check
`inspect.iscoroutinefunction` on the method you are calling, name the entry point in
the decision, and assert it with a mock on the async path — `AsyncMock` on
`.aio.…`, asserting it was **awaited**. The sync facade typically appears first in
`dir()` and in the vendor's own examples, so it is what gets reached for.

**Citations (per the citation-or-prune rule above):**
- `ledger.md` 2026-08-27T19:00:00Z — analysis — PLANNING_COLD_READ, category
  `strategy`. The finding, the execution that verified it, and S4-Q9/Seam 7(b)/`A7.c`.
- `ledger.md` 2026-08-27T00:30:00Z — gemini-live — PLANNING_COMPLETE, category
  `strategy`. The three earlier `google-genai` defects that established "read the
  source, not the signature" — this is the same rule reaching a fourth time.

### The mutation harness is unverified infrastructure used to verify everything else

**Admitted under the manual-ratification clause; owner-ratified 2026-08-27.** Observed
on two slices (`voice-intake-demo`, `twilio-server`), so it does not clear the 3-slice
bar on its own — but both instances are the same mechanism failing in opposite
directions, which is what makes it a pattern rather than two accidents.

**Pattern.** Mutation checking is this project's strongest evidence that a test
discriminates rather than merely passes. It is used to justify keeping
passed-on-arrival tests, and its results are written into slice artifacts as proof. But
**the harness itself is ad-hoc shell and Python written in the moment, and nothing
verifies it.** Both failures were invisible from the result alone:

1. **A mutation that never applied produced a meaningless pass** (`voice-intake-demo`,
   Seam 5). The shell escaping was wrong, the guard `assert` failed, and the suite ran
   against *unmutated* code. The output looked exactly like "the test survived a
   mutation" — the wrong conclusion, reached from a green run.
2. **A harness that died mid-mutation left the tree corrupted** (`twilio-server`,
   2026-08-27). A 2-minute timeout killed the runner between applying a mutant and
   restoring it, so `server.py` kept the mutant. Caught only because a checksum had
   been taken by hand; nothing in the harness would have noticed, and every later unit
   would have been built on corrupted source.

The two directions matter: the first makes a *result* false, the second makes the
*tree* false. A harness can therefore lie about what it proved, or silently change what
is being proved about — and in both cases the visible output is a normal-looking test
run.

**How to apply — three rules, each earned by a specific failure.**
- **Assert the mutation applied** before trusting any result from it (`assert old in
  source`, or grep for a token the mutant removes). A "survived" verdict from a
  mutation that never landed is worse than no check, because it is recorded as evidence.
- **Restore in a `finally`, and verify the restore** by checksum or diff before
  continuing. A harness that can die mid-mutation without restoring must not be run at
  all — written into `.claude/skills/slice-builder/SKILL.md` on 2026-08-27.
- **Bound anything that can hang.** A test waiting on a socket close with no timeout
  does not fail under a non-closing implementation, it blocks — so the mutant that
  should have died loudly instead stalls the run and, in that stall, is what killed the
  harness above. The two defects were causally linked, not merely adjacent.

**Citations (per the citation-or-prune rule above):**
- `ledger.md` 2026-08-27T09:00:00Z — twilio-server — PLANNING_COMPLETE, category
  `strategy`. The slice whose implementation produced instance 2.
- `ledger.md` 2026-08-25T21:56:31Z — voice-intake-demo — OVERSEER_ESCALATE, category
  `recovery`. The slice whose Seam 5 produced instance 1; its `PROGRESS.md` entry
  records "a mutation run that appears to prove something can prove nothing".
- Rule text and accepted risks: `.claude/overseer/audit.md`, 2026-08-27 (RATIFIED).

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
