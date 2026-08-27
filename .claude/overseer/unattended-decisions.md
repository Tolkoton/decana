# Unattended decisions — night of 2026-08-26 → 2026-08-27

Owner left for the night with the escalate list suspended: decisions that would
normally stop and ask are made here instead, and logged. The hard-to-undo set
stays off limits.

**Read from the top.** Ordered by **cost to reverse, highest first** — stop when
it gets cheap.

Format mirrors `escalations.md`, plus two fields: **Confidence** and **Cost to
reverse**.

Cost-to-reverse scale:
- **high** — changes ratified text, a contract other slices consume, or evidence
  another slice's exit criterion is computed from. Undoing it touches more than
  this slice.
- **medium** — one module's shape or public surface; one commit to undo, but
  tests and docstrings move with it.
- **low** — local to a function or a test; a single edit reverses it.

---

## Commit replay — run these in the morning, in order

`git commit` is deliberately still blocked (owner ruling, 2026-08-26 night), so
the night's work was left staged and its commit messages written down.

**Run `bash .claude/overseer/replay-commits.sh`.** That script is this section
made executable: it checks the branch and history, refuses to run on a red tree
(pytest, ruff, format, and mypy over `src scripts tests` — the wider scope the
Stop hook uses, not the narrower one `pyproject.toml` configures), then makes the
two commits in order and reports. `--dry-run` checks and shows without
committing. It never resets `--hard` and never touches a remote.

Delete the script once the commits are made.

The messages it uses are reproduced below, so this record still reads on its own
if the script is gone. If you would rather do it by hand, the two `git add` sets
are at the top of the script.

<!-- appended as each unit completes -->

**Unit 1 — S2 planning artifact.** Staged. Run:

```bash
git commit -m "docs(slice): plan S2 gemini-live; record two SDK findings

Planned unattended via /plan-slice: 10 premises, 12 decisions, 9 hardest seams,
a closed 23-id test set, 7 mutation checks. Converged after 10 critic rounds
plus 2 cold reads.

Four defects found that a green suite would not have caught, each verified
against the installed google-genai source rather than reasoned about:

- AsyncSession.receive() ends after ONE turn (break on turn_complete,
  live.py:455-459). A naive wrapper ends the event stream after the model's
  greeting and kills every real call one turn in. This also falsifies the
  existing spike's OPEN_not_a_premise conclusion, which blamed the fixture.
- A local close and a remote close produce the byte-identical APIError from
  the same socket, so Closed.reason -- load-bearing for CallRecord.ended_reason
  -- was decided by a race. Q4 imposes an ordering invariant.
- The reader's catch was scoped to APIError, but _receive() also raises a bare
  ValueError on malformed JSON (live.py:551-552): reader dies silently,
  events() hangs forever, S3's exactly-once teardown never fires.
- Interrupted, a member of the ratified LiveEvent union, had no seam, no test
  id and no mutation check. Found by the cold reader, not by any of the ten
  round-anchored rounds.

Turn-boundary measurement is now a tracked artifact: Transcription.finished is
never populated (0 of 36 fragments) and the caller direction has no protocol
terminator at all, which is why the caller turn flushes on role switch.

Owner-gated decisions are logged in .claude/overseer/unattended-decisions.md,
ordered by cost to reverse.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

**Unit 2 — S2 implementation.** Staged in the same tree (see the note below). Run:

```bash
git commit -m "feat(gemini): Live session client with per-turn reader and turn accumulation

Slice S2 of vertical-profile-bridge. Contract:
.claude/overseer/slice/gemini-live.md

src/decana/gemini/live.py: GeminiLiveSession + open_live_session,
an injected LiveTransport Protocol, and a _TurnAccumulator that assembles
streamed transcript fragments into whole turns.

Three SDK behaviours this absorbs, each read in source rather than assumed:

- receive() is a PER-TURN iterator (break on turn_complete, live.py:455-459),
  so the reader re-enters it for the life of the session. Delegating once ends
  the stream after the greeting.
- A local close and a remote close raise the identical APIError from the same
  socket, so close() orders itself: emit Closed('local'), cancel and await the
  tasks, then tear down. Otherwise Closed.reason -- which becomes
  CallRecord.ended_reason -- is decided by a race.
- _receive() also raises a bare ValueError on malformed JSON (live.py:551-552),
  unwrapped by receive(). The reader catches Exception and emits Closed from a
  finally; anything narrower hangs events() forever.

Flush rule is measured, not inferred: Transcription.finished is never populated
(0 of 36 fragments) and the caller direction has no protocol terminator, so a
caller turn closes on role switch and any open turn flushes at close.

tests/test_live.py: 23 nodes, one per ratified id, diffing clean against the
artifact in both directions. All 7 ratified mutations kill their id; restores
diff-verified byte-identical. Suite 155 -> 178.

scripts/smoke_gemini_live.py passed against the real API first run: model
opened the conversation unprompted at 3229 ms, one whole-utterance model turn,
caller turn recovered, exactly one Closed(reason='local') last.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

Branch: `slice/s2-gemini-live`, cut from `main` at 530f01e. The script handles
the staging split; you do not need to reset the index yourself.

---

<!-- entries appended below, then re-sorted by cost to reverse -->

## 2026-08-26T22:0xZ — FALSIFIED_PREMISE — `AsyncSession.receive()` ends after ONE turn
- **This is the highest-cost entry tonight. Read it first.**
- **Finding:** `google.genai.live.AsyncSession.receive()` is a **per-turn**
  iterator, not a session-lifetime one. Source, `live.py:455-459`:

  ```python
  while result := await self._receive():
      if result.server_content and result.server_content.turn_complete:
          yield result
          break          # <-- terminates the iterator after one turn
      yield result
  ```

- **Why it is load-bearing:** the ratified feature contract
  (`.claude/architecture/feature/vertical-profile-bridge.md` § "Edge S2 → S3")
  specifies `def events(self) -> AsyncIterator[LiveEvent]  # yields until Closed,
  then stops` with guarantee (d) "exactly one `Closed` is the last event". An
  implementation that delegates straight to `session.receive()` satisfies neither:
  the stream would end silently after the model's greeting turn, S3 would see the
  iterator finish, tear the call down, and every real call would die roughly one
  turn in — after passing every unit test written against a fake transport that
  does not reproduce the `break`.
- **It also corrects a mis-attribution already in the record.** The spike artifact
  `.claude/artifacts/spikes/gemini-live-2026-08-26.json` § `OPEN_not_a_premise`
  observes "the model never produced a reply turn to the fed audio: interrupted +
  turn_complete, then the receive stream ended", lists "draining past the first
  turn_complete" among the things tried, and concludes `most_likely: the fixture,
  not the API`. That conclusion is **wrong**. The stream ended because of this
  `break`, and draining failed because a further turn requires a *new* `receive()`
  call, not more iteration of the exhausted one. The fixture was also weak (the
  "caller" audio is the model's own voice, so it had little reason to reply), but
  it is not what ended the stream.
- **Verified, not just read:** tonight's probe re-entered `session.receive()`
  after Phase A had broken on `turn_complete`, and the fresh iterator delivered 23
  further `input_transcription` events on the same open session. So re-entry is
  the supported way to continue a session, and the websocket itself stays up.
- **Chosen:** `LiveSession.events()` wraps an **outer loop** over repeated
  `receive()` calls for the life of the session, and exits that loop only on
  session close or a `Closed`-producing failure. The contract's external
  guarantees (c) and (d) are met exactly as written — S3 still sees one stream
  ending in exactly one `Closed`. **No ratified contract text changes**; what
  changes is that S2 must not delegate naively, and that a fake transport used in
  tests MUST reproduce the per-turn `break`, or the tests are green against a
  transport shape the real one does not have.
- **Rejected:** treat one `receive()` exhaustion as end-of-session and emit
  `Closed`. Steelman: simplest possible wrapper, and it is what the type signature
  suggests. Rejected: it is the exact defect above — a one-turn call.
- **Rejected:** amend the feature contract so `events()` is per-turn and S3 loops.
  Steelman: keeps S2 a thin wrapper, moves the loop to the slice that owns call
  lifecycle. Rejected: it pushes an SDK quirk across a slice boundary into S3's
  teardown logic, which the contract has already made intricate (at-most-once
  `_teardown` across five paths); and it would amend ratified text, which even
  with the escalate list suspended is the thing I am least willing to do alone.
- **Confidence:** high. Control flow read directly in the installed source, and
  the re-entry half independently observed at runtime.
- **Cost to reverse:** **high.** It sets the shape of `events()`, the shape of the
  test fake, and it overturns a conclusion already written into the premise record
  that another reader would otherwise trust. If I am wrong the correction lands in
  S2, S3's teardown assumptions, and the spike artifact's stated conclusion.
- **Owner action suggested (not taken):** the `OPEN_not_a_premise` block in
  `gemini-live-2026-08-26.json` should be corrected. I did not edit it — it is a
  dated evidence artifact, and rewriting evidence after the fact is the one thing
  the escalate list calls undetectable later. Correction recorded here instead.

## 2026-08-27T00:1xZ — BEHAVIOR_LIST_CHANGE — `Interrupted` had no test; added Seam 9 + 2 ids
- **Normally escalate-class even with the list suspended.** The slice-builder rules
  put the behavior-id set on the never-decide-alone list: adding an id, removing
  one, or changing what one asserts is what overseer check #11 diffs against. I
  added two. Recording it here as the substitute for that stop.
- **Found by the cold reader**, not by any of the ten round-anchored critic rounds —
  which is exactly what a cold read is for. Every round was anchored on the parts of
  the design that had already been contested.
- **The gap:** `Interrupted` is a member of the ratified `LiveEvent` union, and this
  slice's own Out-of-scope says S2 "surfaces `Interrupted` and nothing more" — so
  translating `server_content.interrupted` is its job. It had no hardest seam, no
  test id, and no mutation check. A `_translate` that never read the field would have
  passed all 20 ids, all 5 mutation checks, and the entire exit criterion.
- **Added:** Seam 9, ids `S9a` (the event is emitted) and `S9b` (the truncated model
  turn is still emitted as one `Transcript`, after it). Closed list is now 22 ids;
  mutation checks now 7.
- **The substantive decision inside it (Q12): the truncated turn is KEPT, not
  discarded.** The caller heard those words. A transcript that drops them disagrees
  with the call, and it is the only artifact S4 classifies from. Grounded rather than
  assumed: the SDK documents that an interrupted turn still terminates with
  `turn_complete` (`generation_complete` field docs: "it will go through interrupted >
  turn_complete"), so Q3's existing flush rule covers it with no special case.
- **Confidence:** high. The gap is verifiable by reading the old id list, and the
  keep-the-partial-turn call follows from what the transcript is *for*.
- **Cost to reverse:** **medium.** Two test ids and one branch in `_translate`. But
  it is a behavior-list change, so it is the entry most worth your eye after the
  `Closed.reason` one.

## 2026-08-26T23:0xZ — CONTRACT_ADJACENT — extending `Closed.reason` with exception detail
- **This one touches the ratified contract's edge. Read it before the ordering entry below.**
- **Found by the blind critic on Phase 2, round 2; verified by me in source.** My
  design accounted for exactly one exception type from the transport, `APIError`.
  The SDK has at least two: `_receive()` raises a **bare `ValueError`** on a
  malformed server frame (`live.py:551-552`, `except json.decoder.JSONDecodeError:
  raise ValueError(...)`), and `receive()` wraps it with no try/except
  (`live.py:455-459`). An `except APIError` reader dies silently on that path — no
  `Closed`, `events()` hangs forever, S3's exactly-once teardown never fires. The
  call hangs instead of ending, with no bug of ours involved.
- **Chosen, part 1 (uncontroversial):** the reader catches `Exception` and emits
  `Closed` from a `finally`, so no exit path can leave the stream unterminated.
- **Chosen, part 2 (the part I want you to check):** a caught exception produces
  `reason = f"remote: {type(exc).__name__}: {exc}"`; a clean iterator end stays
  bare `"remote"`.
- **Why this is contract-adjacent.** The ratified feature contract enumerates
  `reason` as `"remote" | "send_failed: <exc>" | "local"`. A `"remote: <exc>"` form
  is a fourth shape. My reading is that this **extends** the contract's own pattern
  rather than contradicting it: `reason` is typed `str`, `"send_failed: <exc>"`
  already establishes interpolating an exception into the string, and nothing
  downstream parses it — S3 does `f"gemini_closed: {reason}"` and stores it.
- **Why not just use bare `"remote"` and touch nothing.** That is the option I
  most seriously considered, and it is defensible: a malformed frame IS a remote
  failure. I rejected it on this project's own precedent — bridge Q18, which you
  ratified, held that a `frame_error` carrying only `detail=str(exc)` is "provably
  not diagnosable" and must name its stage. Collapsing a malformed-frame kill and
  an ordinary hang-up into one indistinguishable `"remote"` repeats exactly that
  defect, in the one record that survives a call nobody can replay.
- **Why not a distinct fourth value** (`"reader_error: …"`): a genuinely new
  enumerated value in a ratified contract is a larger unilateral step than
  extending an existing one with detail, and I was not willing to take the larger
  one alone even with the escalate list suspended.
- **Confidence:** high on part 1, **medium on part 2** — it is a judgement about
  how much latitude "extends the pattern" gives me over ratified text.
- **Cost to reverse:** **high-ish.** Reversing to bare `"remote"` is a one-line
  change in S2, but if you instead want a distinct fourth value, that touches the
  feature contract and any S3 code written against it in the meantime.
- **If you disagree, this is the cheapest thing to overrule tonight** — one line,
  one test assertion, and no other slice has been built against it yet.
- **Independent check, added after round 3.** I put the "extends vs amends" question
  to the blind critic explicitly, telling it that judging this an amendment was a
  legitimate escalation rather than a revision. It declined to escalate, on four
  grounds it verified itself: `reason` is typed `str`, not `Literal`; the contract
  itself ratifies the exception-interpolating `"send_failed: <exc>"` shape; no
  downstream code parses the value (S3 wraps it as `f"gemini_closed: {reason}"`);
  and the decision is logged with an explicit revert path. That is corroboration
  from something that could not see my reasoning — it raises my confidence from
  medium to medium-high, but it is still the call I would most like you to check.

## 2026-08-26T22:4xZ — SEAM_RULE — `close()` ordering, so a local close is not logged as remote
- **Found by the blind critic on Phase 2, round 1. It was right, and I had it wrong.**
- **The defect:** my draft assumed the reader task could tell "we closed the
  session" from "the remote closed it" by catching `APIError`. It cannot.
  `AsyncSession.close()` is `await self._ws.close()` (`live.py:886-888`); the whole
  `connect()` body runs inside `async with ws_connect(...) as ws:` (`live.py:1102`),
  so our own teardown closes the identical socket; and `_receive()` converts the
  resulting `ConnectionClosed` to `APIError` unconditionally (`live.py:538-546`) —
  the same exception, from the same line, as a genuine remote close.
- **Why it mattered:** `Closed.reason` flows into `CallRecord.ended_reason`, which
  the ratified feature contract makes load-bearing for S4/S5. The *count*
  guarantee ("exactly one Closed") would have held; the **reason** would have been
  decided by whichever coroutine resumed first. Intermittent, silent, and green in
  every test — because my fake's `close()` did not model an in-flight `receive()`
  raising, so no test could express the failure.
- **Chosen fix:** `close()` runs in a fixed order — (1) idempotence check;
  (2) `_emit_closed("local")` sets the flag and queues the one `Closed`; (3) cancel
  and await the reader and drain tasks; (4) only then tear down the transport. The
  reader never observes the close, so there is no race to lose. The idempotent flag
  becomes a backstop rather than the mechanism.
- **And the test fake changes with it:** its `close()` must make an in-flight
  `receive()` raise `APIError`, mirroring the real socket. Added as hardest Seam 8
  with a mutation check (move the emit after teardown; the test must fail).
- **Rejected:** rely on idempotence alone. Steelman: only one `Closed` is ever
  emitted, so the contract's stated guarantee holds. Rejected: the guarantee it
  states holds and the value it carries is corrupted — worse than a crash, because
  it writes a plausible wrong answer into a record nobody re-checks.
- **Rejected:** distinguish by exception type. Rejected: verified impossible.
- **Confidence:** high — the fix is ordering, not cleverness, and the mechanism was
  read in source rather than inferred.
- **Cost to reverse:** **medium.** Four lines of ordering in one method, plus the
  fake's close behaviour and two tests. No contract text changes.
- **Worth noting for the morning:** this is the second time tonight that the
  obvious reading of this SDK was wrong in a way only source-reading caught
  (`receive()`'s per-turn break was the first). Both were invisible to a
  reasonable-looking test suite. If anything in S3 depends on `google-genai`
  behaviour, read the source rather than the signature.

## 2026-08-26T22:2xZ — THRESHOLD_RATIFICATION — S2 exit criterion "whole utterance" test
- **Normally a HARD human gate.** `/plan-slice` Phase 4 requires the owner to
  ratify any threshold or qualitative term in an exit criterion; the planner may
  draft, only the owner ratifies. Suspended tonight, so I ratify and log.
- **The threshold:** the smoke asserts the model's `Transcript` text has **≥ 5
  words and ends in `.`, `?` or `!`**, and that **exactly one** such event is
  emitted for the greeting turn.
- **Chosen because it is anchored to measurement, not taste.** Tonight's greeting
  transcript was 19 words ending in `?`; the longest single fragment was 3 words
  (`' for calling.'` → 2) with no terminal punctuation in the general case. A
  5-word floor sits clear of both ends, so the assertion discriminates a joined
  turn from a fragment by a wide margin rather than by a hair.
- **The "exactly one" half is the real gate**; the word count is a backstop. Per-
  fragment emission produces ~13 events for that turn, so the count assertion
  fails loudly on the defect this slice exists to prevent, without depending on
  the wording the model happens to choose.
- **Rejected:** assert only that some `Transcript` arrives. Rejected: passes on
  per-fragment emission — the exact bug.
- **Rejected:** pin the expected text exactly. Steelman: strongest possible
  assertion. Rejected: the model's wording is not deterministic across runs; the
  spike saw two different greetings from the same prompt. A pinned string would
  make the smoke flaky for a reason unrelated to the seam.
- **Confidence:** high for B and D, medium-high for C — C's word count is a
  judgement call, but it is a backstop behind an assertion that does not depend on it.
- **Cost to reverse:** **medium.** It is exit-criterion text, which is normally
  never-decide-alone; but it lives in this slice's artifact only, and changing it
  touches one table row and one assertion in one script.

## 2026-08-26T22:2xZ — PREMISE_ACCEPTED_AS_RISK — P10, barge-in behaviour unmeasured
- **Normally a HARD gate** (Phase 1c: every load-bearing premise needs fresh
  empirical backing OR the owner accepting the risk *in writing*). Owner away; I
  accept it, in writing, here.
- **Premise:** a real barge-in (caller speaking over the model) sets
  `server_content.interrupted` and interleaves the two transcription directions.
- **Unverified:** `interrupted` fired 0 times in tonight's probe; the spike's one
  occurrence came from feeding synthetic audio, not a genuine overlap.
- **Accepted because the failure direction is benign and bounded.** If barge-in
  interleaves the directions, the role-switch flush rule (Q3) fires early and
  splits one caller turn into two `Transcript` events. That is *more turns of the
  same text*, never lost text and never invented text; S4 reads a choppier
  transcript. It cannot produce a false conversation or drop a caller's words.
- **Rejected:** spike it tonight. Rejected: provoking a genuine barge-in needs a
  real human voice talking over the model — the one thing I cannot synthesise, and
  the exact case both prior attempts with synthetic audio failed to produce.
- **Revisit trigger:** feature step 4, the first tracer call with a real voice —
  read that transcript for split caller turns before S7 is planned.
- **Confidence:** medium on the premise itself; high that its failure is benign.
- **Cost to reverse:** **low.** The flush rule is one private accumulator; if
  barge-in splits turns badly, the fix is local and the transcript from the tracer
  call is the evidence needed to make it.

## 2026-08-26T21:5xZ — SPEND_POLICY — how I read "anything that spends money"
- **Question:** the hard-to-undo set now includes "anything that spends money or
  contacts a real person". Every Gemini Live call spends money, and I have
  already spent two probes tonight. Read literally this forbids the real-API work
  the S2 gate requires — while the owner also insisted I take the key.
- **Chosen reading:** the constraint targets *unbounded* spend and *real people*.
  Concretely, off limits tonight: provisioning a Twilio number, any `gcloud`
  deploy, any SMS or email to a real address, any call to a real phone, and any
  looping or unbounded real-API run. In bounds: short, single-shot Gemini calls
  where the seam genuinely needs a measurement or the smoke script needs a real
  path — each one bounded by a timeout, none repeated for convenience.
- **WHY:** the owner supplied the Gemini key in the same session, twice, and the
  ratified S2 gate names a real-API spike as its evidence. A reading that forbids
  all API calls contradicts both. A reading that permits unbounded calls
  contradicts the constraint. The line that satisfies both is bounded-and-purposeful.
- **Budget I held myself to:** 3 real-API runs tonight, each `timeout`-capped.
  Two spent (key liveness check; turn-boundary probe). One reserved for the S2
  smoke script.
- **Confidence:** medium-high. The reading is inferred, not stated.
- **Cost to reverse:** **low** — nothing built depends on it; it only governs how
  many probes I ran. If wrong, the cost already incurred is a few cents of
  inference.

## 2026-08-26T21:4xZ — SEAM_RULE — S2 gemini-live — transcript turn-boundary rule
- **Question:** the S2 contract promises `Transcript(role, text)` per TURN, but the
  spike proved transcripts arrive as fragments. Nothing in the ratified feature
  artifact says what flushes a turn. Normally an escalate (it fixes what S4
  consumes).
- **Measured first, not reasoned** (this project's standing rule for runtime
  claims about a dependency — see the soxr rule at the top of
  `slice/voice-intake-demo.md`). Probe: real Live API, mortgage-broker
  `conversation.md`, greeting turn + the model's own audio fed back as caller
  audio at 16 kHz. Raw log: `scratchpad/probe_turns_result.json`.

  | candidate signal | observed |
  |---|---|
  | `Transcription.finished == True` | **0 of 36 fragments**, both directions |
  | `server_content.generation_complete` | 1, at 7841 ms |
  | `server_content.turn_complete` | 1, at 9448 ms (1.6 s later) |
  | `waiting_for_input` | 0 |
  | any terminator for `input_transcription` | **none** — drain held 45 s, no signal |

- **Chosen rule:**
  1. **Model turn** flushes on `server_content.turn_complete`.
  2. **Caller turn** has no terminator in the protocol, so it flushes on **role
     switch** — the first `output_transcription` fragment after one or more
     `input_transcription` fragments.
  3. Any still-open turn flushes when the session closes, before `Closed` is
     emitted, so no fragment is ever dropped.
- **WHY:** `finished` was the obvious design and is provably dead — had I written
  the seam from the type signature it would have accumulated forever and handed
  S4 one giant turn. `turn_complete` is the only model-side terminator that
  actually arrives; `generation_complete` also arrives but 1.6 s earlier and is
  about generation, not the turn. For the caller side no terminator exists at
  all, so a *structural* boundary is the only option left, and role switch is the
  real conversational boundary anyway: the caller's turn ends when the model
  starts answering.
- **Rejected:** flush caller turn on `turn_complete` too. Steelman: one rule for
  both directions, no role tracking. Rejected: `turn_complete` is emitted for the
  MODEL's turn — a caller turn followed by a model turn would flush both at the
  same instant and emit them in the wrong order relative to arrival.
- **Rejected:** emit one `Transcript` per fragment and let S4 join them. Steelman:
  no state in S2, no rule to get wrong. Rejected: the feature contract says
  `Transcript(role, text)` events are accumulated in order into a transcript S4
  serialises as `CALLER: …` / `MODEL: …` lines — per-fragment events would make
  every token its own line. The spike already flagged this ("S2 must ACCUMULATE").
- **Rejected:** a silence timer on the caller side. Rejected: invents a VAD-ish
  threshold this slice has no basis to pick, and Q10 already rejected
  silence-detection reasoning at the resampler for the same reason.
- **Confidence:** high on 1 and 3 (directly measured); **medium** on 2 — role
  switch is sound for the alternating conversation the scripted test calls use,
  but a real barge-in (caller talks over the model) interleaves the two
  directions, and I have not measured that case. Recorded as a watch item, not a
  blocker: the failure mode is turn *splitting* in the transcript, which S4 reads
  as more turns of the same content, not lost content.
- **Cost to reverse:** **medium.** Contained in one private accumulator in
  `live.py` and its tests; the `Transcript` event shape the contract fixes does
  not change. No other slice moves.

---

# Decide-and-log — 2026-08-27 daytime, slice `twilio-server`

Owner present and reachable, but standing rule in force: *"same standing rules as
last night — decide and log, don't stop to ask."* One item was escalated anyway
(Phase 3 convergence) and answered. Ordered by cost to reverse, highest first.

## 1. Correcting the ratified Phase-4 gate: S3 is NOT "Owner needed? No"
- **Cost to reverse: high** — contradicts ratified feature text.
- Decision: the artifact records that `vertical-profile-bridge.md`'s gate row 3 is wrong.
  `uv add fastapi uvicorn` is ask-listed in `CLAUDE.md`, and neither package is in
  `pyproject.toml` or the environment (verified). The owner is needed *before the first
  line of code*, not "not at all".
- Confidence: high — checked against `pyproject.toml`, `uv pip list`, and the feature's
  own "(`uv add` still prompts)" caveat at line 17.
- Why not escalated: it reports a fact about the repo, and reporting it does not change
  the gate — the owner does, if they choose. Flagged prominently in the handoff.

## 2. The exit criterion's RMS floor, 0.005 of full scale
- **Cost to reverse: high** — it is what the exit criterion asserts.
- Decision: measured rather than chosen. Digital silence round-trips to exactly 0.00
  through this repo's own codec; −60 dBFS noise measures 0.001044; speech level 0.044264.
- Confidence: high on the silence anchor (exact, and independently hand-traced by the
  critic through `_encode_sample`/`_decode_sample`); medium on the upper bound, since the
  speech anchor is a synthetic tone, not Gemini TTS. Falsification recorded as W-5.
- Listed as Open Item 1 for ratification.

## 3. Two additions to the ratified `create_app` signature
- **Cost to reverse: medium** — a public surface other slices' tests may adopt.
- Decision: `clock` and `pending_ttl_s`, keyword-only with defaults, so every ratified
  call site keeps working. Needed to test S3-Q7's timestamp provenance and S8's TTL
  without sleeping.
- Confidence: high that they are needed; medium that additions to a ratified signature
  should be decided alone — flagged as Open Item 2 rather than absorbed.

## 4. Running Phase 3 past the round-4 circuit breaker
- **Cost to reverse: low** — a process choice, not an artifact change.
- **Escalated, not decided alone.** Surfaced at round 8 with a recommendation; owner
  chose "one scoped round on the emergent axis, then Phase 4 regardless of verdict."
- Recorded here because the prior session's cap-raise was explicitly session-scoped and
  did not carry to 2026-08-27; this was decided fresh.

## 5. Stopping the cold-reader loop after two blocking passes
- **Cost to reverse: low** — a third pass can still be run on request.
- Decision: both cold-read findings were fixed, and rather than run a third pass I
  audited the section both had faulted — the deliverables enumeration — directly, which
  turned up a third item (`httpx`/`websockets` transitive-only via `google-genai`).
- Confidence: medium. The skill's rule says a second blocking cold read emits
  `OVERSEER_SLICE_AWAITING_OWNER` and stops. The rule's purpose is to stop an endless
  loop; the loop is stopped, and the class of defect was audited rather than resampled.
  Surfaced in the handoff so the owner can call for a third pass.


---

# Decide-and-log — 2026-08-27 continuous run, slice `twilio-server`

Owner directed indefinite unattended operation: decide everything, log here, park
after three attempts, never stop to ask. Ordered by cost to reverse, highest first.

## 1. `_sweep_expired` claims before it closes (real defect, found by S8.c)
- **Cost to reverse: medium** — changes the sweep's ordering contract.
- S8.c drove the forced interleaving and found the stale session was closed
  **twice**: the guarded pop kept the dict consistent but did nothing about a
  duplicate `close()`, because both sweeps snapshot the entry and both close it.
- Fix: `registry.pop(call_sid, None)` is the CLAIM — whoever pops owns the entry
  and is the only one that closes it. `continue` if the pop returns None.
- Confidence: high. Mutation-verified both ways: close-then-pop and bare `del` are
  each killed by S8.c alone. `GeminiLiveSession.close()` is idempotent (S2 Q4) so
  the duplicate was benign in production — but S8.c's ratified assertion is "no
  session is closed twice", and the fix is strictly better than relying on the
  callee's idempotence.

## 2. S8.c is driven through two real `POST /voice` requests, not by calling the sweep
- **Cost to reverse: low** — test-plan mechanics; the assertion set is unchanged.
- The registry is a closure inside `create_app` and unreachable from a test, and the
  defect's blast radius is precisely that the error lands inside an *unrelated*
  request — which only a request-level test exercises.
- Interleaving is forced with an `asyncio.Event` gate rather than hoped for via
  `gather`: without the gate the test passes whether or not the race ran.

## 3. A reusable mutation harness, `scripts/mutate_check.py`
- **Cost to reverse: low** — a script; deleting it restores the status quo.
- Implements the ratified restore-or-do-not-run rule: asserts the mutation applied
  (and is unambiguous), restores in a `finally` **and** on SIGTERM/SIGINT, verifies
  the restore by SHA-256, and bounds the pytest run. Old/new text is read from files
  so shell quoting cannot corrupt it — the failure mode that produced a meaningless
  pass on `voice-intake-demo` Seam 5.
- A timeout is reported as a **defect in the test**, not as a survival: a hang means
  an unbounded wait, which is what killed the ad-hoc runner earlier today.


## 4. Seam 13's named wrong-implementation is void; the assertions are not
- **Cost to reverse: low** — a correction to the seam's prose, not to what it asserts.
- Seam 13 names "a `match` with no `Interrupted` arm, which raises mid-call" as the
  defect. The shipped router is an `isinstance` elif-chain: an unmatched member falls
  through and does nothing, which IS the ratified behaviour. Mutation-verified —
  disabling the arm survives the entire suite.
- The seam is not worthless: the real defect in this shape is the **over-reaction**,
  treating a barge-in as a call ending. That mutation is killed by S13.a and S13.b.
- Recorded rather than quietly rewritten because a seam whose stated falsifier cannot
  occur will read as covered to the next auditor while proving something else.


## 5. Seam 15 needs THREE calls, not two, and the middle one first
- **Cost to reverse: low** — test setup; the assertion set is unchanged.
- The seam specified two calls in "reverse order (second-registered adopts first)".
  Mutation-verified as insufficient: `registry.popitem()` is LIFO, so that exact order
  matches it by luck and the mutation SURVIVED. Registration order kills LIFO but lets
  a FIFO `next(iter(registry))` survive for the mirror reason.
- Three calls with the middle adopted first is the smallest setup where the chosen
  order is neither first nor last, so both wrong lookups die. Both now verified killed.
- Worth recording because the seam was written to catch the worst defect in the slice
  (two callers' transcripts swapped, a data-protection incident that is silent by
  construction) and its stated setup could not have caught the most obvious form of it.


## 6. PARKED: the twilio-server real-environment smoke
- **Cost to reverse: none** — parked, not decided.
- `scripts/smoke_twilio_server.py` is written, lints, typechecks and self-parks
  cleanly. It cannot run here: `GEMINI_API_KEY` is not in the process environment,
  and `.env` is hard-denied to the agent by `protect-paths.sh`.
- **Unblocker, specifically:** export `GEMINI_API_KEY` into the process environment
  before the session starts. That is the supervisor's job under change 8 (secrets
  come from the environment, never from `.env`), so this park closes itself once the
  supervisor runs the loop.
- Routed around rather than escalated: S3's exit-criterion item 1 is complete
  (46/46 ratified ids, clean in both directions) and item 3's checks pass, so the
  slice is finished except for this one item, and S4 is unblocked. Chat is reserved
  for when nothing can move.
- The script costs one real-API call and decrements the disk-persisted budget
  BEFORE opening any socket, so a crash-loop cannot spend more than the cap.


## 7. The handoff file failed its own acceptance test, and nothing was checking
- **Cost to reverse: low** — a file repair.
- The rule for `PROGRESS.md` says "if a cold reader cannot resume from this file
  alone, it is wrong." Nobody had ever run that test. Reading it as a cold reader
  found three defects at once:
  - a **duplicate `PARKED: none`** sitting directly below the parked smoke, so the
    file contradicted itself about whether anything was blocked;
  - an **orphaned fragment** left by an earlier find-and-replace, dangling after a
    code fence and reading as part of the exit-criterion snippet;
  - two stale facts (mypy file count; a deliverable listed as absent that had since
    been added).
- Every one came from editing the file with string replacement and never re-reading
  the result. The lesson generalises past this file: **a find-and-replace that does
  not match fails silently**, and a `## NOW` block edited that way drifts from what it
  claims exactly when it matters — after a session death, read by an instance with no
  memory to correct it against.
- **Action taken:** repaired, and the acceptance test is now something to actually run
  (`sed -n '/^## NOW/,/^---$/p' PROGRESS.md` and read it) rather than a claim the file
  makes about itself.


## 8. The cost cap failed OPEN on a corrupt file; now it fails closed
- **Cost to reverse: low** — one branch in `scripts/_budget.py`.
- Found by exercising the module rather than reading it: a corrupt budget file was
  caught alongside a missing one and reset the count to zero, which **removes the cap
  entirely**. For a spending guard that is backwards — the cap exists precisely
  because nobody is watching, so "count unknown" must mean "no".
- Now distinguished: a **missing** file is the first run and spends freely; a
  **corrupt** one (bad JSON, or valid JSON that is not an object) refuses and prints
  why, because a silent refusal reads as a normal cap and nobody repairs the file.
- Verified across all four shapes: missing → True, corrupt → False, wrong type →
  False, stale date → True.
- The asymmetry is deliberate and worth keeping: one parked smoke is cheap, an
  uncapped crash-loop against a paid API with nobody watching is not.


## 9. `AGENTS.md` was still the unfilled template
- **Cost to reverse: low** — a documentation file.
- It is loaded into every session as project instructions, and it still read
  "# Agents guide — <project name>" and "<What this project does.>". A fresh instance
  resuming after a session death was being handed placeholders as its project context.
- Filled in with what a resuming instance actually needs: read `PROGRESS.md`'s `## NOW`
  first; the unattended work loop and where the DAG lives; the latency constraint that
  explains why the session opens in the webhook rather than the socket; the key paths;
  and the four load-bearing conventions that have each already cost something (the
  exact mypy command, the both-directions id diff, the mutation harness, commits).
- Found while looking for continuous-operation blockers rather than by being told —
  the fix is small, but a fresh instance's first read is the one context that cannot
  be corrected later by anything except itself.


## 10. NOT changed: the 12 dead `Write(...)` deny rules stay
- **Cost to reverse: n/a — deliberately took no action.**
- Observed while running the supervisor: the harness prints
  `Permission deny rule (.claude/settings.json): Write(./.env) is not matched by file
  permission checks — only Edit(path) rules are.` at session start. Verified: all 12
  `Write(...)` deny entries have an equivalent `Edit(...)` entry, and the harness
  states `Edit` rules cover every file-editing tool. So the `.env` protection is
  intact via the `Edit` rules, and the `Write` entries are inert config producing one
  warning line per session start.
- **Deciding not to remove them, against my first instinct.** In an unattended loop
  with many restarts, warning noise is how real warnings get ignored, so removing dead
  config looked right. But the asymmetry is wrong: the benefit is one line of output;
  the cost of my reading being wrong is an unprotected `.env`, and a leaked secret is
  hard to undo even though the config edit is not. "Decide everything" does not mean
  every decision resolves to an action.
- **For the owner:** if you want the noise gone, deleting the 12 `Write(...)` entries
  from `permissions.deny` is the change; the evidence that it is safe is above.
