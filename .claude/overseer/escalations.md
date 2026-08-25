# Overseer escalations log

Records every PRODUCT_DECISION / BLOCKER_CLASSIFICATION / DESIGN_FORK /
ADR_RATIFICATION escalation and the human's resolution. Used in the
2-week audit to tune escalation thresholds.

## Entry format

```
## <ISO timestamp UTC> — <category> — <slice slug>
- Question: <text>
- Options offered: <list>
- Recommendation: <overseer's pick + one-line rationale>
- Human chose: <final decision>
- Latency to decision: <minutes/hours>
- Notes: <if human changed mind, if recommendation was wrong, etc.>
```

## Audit signal interpretation (re-read at the 2-week mark)

- **Human waved through immediately, picked recommendation as-is** → next
  time, this class of question can likely be handled without escalation.
  Propose change in audit.md.
- **Human reversed the recommendation** → overseer is over-confident on
  this class. Tune the check prompt; consider weakening the recommendation
  language.
- **Human deliberated long, chose other** → correct escalation, healthy
  use of human time.

---

## 2026-08-26T00:00:00Z — ADR_RATIFICATION — voice-intake-demo
- **Question:** An overseer #1 audit found the Exit criterion's unit-suite half names four literal test functions as its proof, and three do not exist: `test_audio_frame_error_resilience` in no form, `test_mulaw_codec_reference_table` and `test_timing_recorder_event_stream_integrity` only as five and four prefixed variants. Seam 4 as built (16 behaviors across `decode_base64_frame`, `start()`, both handlers, `close()`) is also far broader than its name. How should the criterion be reconciled with the 36-test suite?
- **Options offered:** A) Fold in — replace the four names with the seam labels plus their actual test-name prefixes. B) Rename the 36 tests in code to match the artifact's four names, collapsing each seam into one function. C) other.
- **Recommendation:** A, on the grounds that the four names were seam labels written before any test existed, while the per-behavior split was itself ratified (Seam 2's amendment, Seam 4's 16-behavior list) — collapsing them back under B would destroy ratified granularity to satisfy a naming convention the artifact never argued for.
- **Human chose:** **A, with one change that is the substantive part of this entry: do not write test-name prefixes into the criterion either.** Owner's reasoning, recorded because it generalizes: prefixes are "the same defect one degree weaker. Any future test rename or split breaks the criterion again, and we will be back here. The criterion should assert a property, not a string match." The criterion now asserts that every behavior in each seam's ratified behavior list has a passing test and that no seam has tests beyond its list — pointing at the behavior lists, which the owner did ratify, rather than at test names, which were never ratified at all. Prefixes retained as a convenience note, explicitly not as proof. Owner separately directed the Seam 4 rename (to `BridgeSession` orchestration) and that the fold-in note about shared private forwarders be moved from the Seam 4 behavior-list section into "Decisions (with WHY)", since "a decision recorded in the wrong section is findable by grep and invisible to someone reading the decisions list — which is the only place a future reader looks."
- **Latency to decision:** immediate.
- **Notes:** Folded in as Q20 (re-filed forwarder decision) and Q21 (criterion reformulation + seam rename); Exit criterion item 1 and "What proves DONE" rewritten. **Applying the amendment immediately produced its first finding, which is the strongest evidence for it:** only Seam 4's behavior list is written into the artifact, so the criterion is verifiable for Seam 4 alone, and `tests/test_resampler.py` numbers its behaviors B1-B5 and **B7** — no B6, no record of what it was or whether it was cut. That is unresolvable by the implementer (reconstructing a ratified list from the tests it is meant to check is the tautology Q8 rejected, and B6 is not recoverable from the code at all), and is logged under "Open items requiring human decision". The pre-amendment criterion could not have surfaced it.

## 2026-08-25T00:00:00Z — TOOLING_DECISION — voice-intake-demo

- **Question:** `verify-on-stop.sh` blocks any turn that ends on a failing test
  suite. A strict-TDD RED turn ends on a *deliberately* failing test, so the
  hook fired on Seam 4's T3 RED and forced RED and GREEN into a single turn —
  removing the checkpoint between "here is the test" and "here is the
  implementation", which is the point where redirecting is still cheap. Should
  the hook learn about RED turns, or should the checkpoint be given up?
- **Options offered:**
  (a) Leave it — accept RED+GREEN pairs per turn. The RED output is still shown
      in the transcript, just without a pause to redirect.
  (b) Teach the hook to skip the TEST step when the final message carries a
      RED sentinel, restoring the checkpoint.
- **Recommendation:** (b), on the grounds that a checkpoint you cannot stop at
  is not a checkpoint, and the remaining 9 Seam-4 behaviors would each lose it.
- **Human chose:** (b), with two conditions attached — log this escalation, and
  write the bypass's missing counterparty into the hook comment as a known
  limit.
- **Latency to decision:** immediate, same turn.

- **Why this is logged at all (human's stated reason, recorded verbatim in
  substance):** this is a modification to *the enforcement mechanism that
  audits my own work*, made mid-slice, under time pressure from a turn the
  mechanism itself had blocked. That combination — self-modifying the auditor,
  while the auditor is inconveniencing you — is the highest-trust edit in the
  repo, and it must not exist only as a diff. The pressure to make the block go
  away is exactly the pressure that should not be the thing deciding.

- **WHAT THE SENTINEL CANNOT DO (the load-bearing half of this entry):**
  - It skips **the test step only**. `ruff check` and `mypy` still run and
    still block. A deliberately failing test must still be well-formed,
    correctly typed code.
  - It does **not** suppress the overseer audit hook, which is a separate hook
    with separate triggers.
  - It is scoped to one turn: the sentinel must be re-emitted each RED turn,
    and absence of the sentinel restores full enforcement.
  - Verified in both directions before being relied on (2026-08-25): with a
    deliberately broken test present, sentinel → `TESTS SKIPPED`, exit 0, lint
    and typecheck still executed; no sentinel → `{"decision":"block"}` carrying
    the pytest failure. The probe test was then removed and the suite returned
    to 57 passed.

- **KNOWN LIMIT — the bypass has no counterparty (human-flagged, deliberately
  not closed now):** nothing verifies that a turn claiming RED actually
  produced a *failing test*. A turn that wrote no test, wrote a passing one, or
  broke something unrelated receives the identical skip merely by emitting the
  line. The obvious fix is the two-signal trigger `overseer_stop.py` already
  uses (sentinel AND structural tool evidence in the same turn), and it was
  consciously not built here. Until it is, the gate rests on the developer's
  honesty about what kind of turn it is — an acceptable trade for one skipped
  step and no others, and **not** acceptable if the skip is ever widened.
  Recorded in the hook comment at the skip site in both copies so it is visible
  to whoever is next tempted to widen it.

- **Scope note:** two copies of this hook fire — `.claude/hooks/` (project,
  configured-command path plus Python auto-detect) and `~/.claude/hooks/`
  (user-level, auto-detect only). Both were edited; a gate in only one is no
  gate. The user-level copy is outside this repo and will not appear in the
  slice diff — flagged here because that is precisely the kind of change a
  reviewer reading only `git diff` would never see.

- **Implementation note:** the sentinel is read from the Stop envelope's
  `last_assistant_message`, not by parsing the transcript JSONL. The transcript
  is flushed asynchronously, so a hook parsing it races the writer
  (anthropics/claude-code#15813) — `overseer_stop.py` hit exactly that and made
  the same choice. The two hooks now agree on where turn text comes from.

- **Notes:** category is TOOLING_DECISION, which is not one of the four the
  format header lists. It is genuinely none of them — not a product decision,
  not a blocker classification, not a design fork, not an ADR ratification —
  and inventing a fifth label was preferred to filing it under a wrong one and
  making the 2-week audit's category counts lie.

## 2026-08-24T20:18:01Z — ADR_RATIFICATION — voice-intake-demo
- Question: The overseer's post-unit audit fired check #8 (chat-only design). Three interface contracts had entered the code with owner ratification given in chat but never written into the ratified artifact: (1) `InboundResampler`/`OutboundResampler` collapsed into one `Resampler(in_rate, out_rate)`; (2) `AudioFrameError` extended to cover `Resampler.push`; (3) `reject_partial_pcm16` promoted to public API of `codec.py`. The artifact described the old contract in four places (Seam signatures, Dependencies, Seam 2's test approach). Two questions: does this get folded in or does it justify the project's first ADR, and is it one decision or two?
- Options offered: A) Fold in as Q12, correcting all four artifact locations; do not create `docs/adr/`. B) Create `docs/adr/` and write ADR-0001 for the seam-shape change.
- Recommendation: overseer returned `OVERSEER_ADR_REQUIRED` with a draft body but explicitly declined to choose the vehicle, on the grounds that creating the project's first ADR directory is a structural choice not to be made unilaterally mid-slice.
- Human chose: **A (fold-in), and `docs/adr/` deliberately NOT created.** Reasoning, recorded because the question will recur: this is a seam-shape change inside one slice, not a project-level architectural decision. The session had already used fold-in three times for exactly this class (Q8 at 19:41Z, Q9-Q11 at 20:14Z). Introducing a second mechanism for the same class of change would leave the next reader unsure which to check. `docs/adr/` gets created when a genuine project-level decision arrives, as a real ADR-0001 rather than a retrofit.
- Latency to decision: immediate.
- Notes: Owner flagged that the audit conflated two changes of very different weight, and that **part 2 is the substantive one and was nearly missed**: with `AudioFrameError` scoped to the codec functions only, the bare `ValueError` from `np.frombuffer` on an odd-length chunk would propagate past `handle_gemini_chunk`'s catch and terminate the call — the exact failure Q6's catch-drop-continue rule exists to prevent, on the one path (Gemini → outbound resampler) where nothing upstream guarantees even-length input. The inbound leg was never exposed, because `mulaw_decode` always emits even-length output. The gap existed because Q6 was reasoned about at the codec boundary while the resampler boundary was never enumerated. Part 1 (the class collapse) is cosmetic and originated as a non-blocking critic note; Q12's WHY states the asymmetry explicitly so the two are not conflated when reading the diff. **Standing correction issued for the remainder of the slice:** chat ratification from the owner authorises writing the change into the artifact — it is not itself the record. Fold in during the same turn as the implementation, without waiting to be asked.

## 2026-08-24T20:14:00Z — ADR_RATIFICATION — voice-intake-demo
- Question: A runtime probe of soxr 1.1.0 (`scripts/verify_soxr_premise.py`), run before writing any resampler code, falsified an assumption implicit in the ratified Seam: that each `push()` returns bytes for the frame it was given. soxr batches internally — 41 of 50 real-sized inbound frames and 34 of 50 outbound chunks return zero samples — and strands its tail until flushed (1060 samples inbound, 170 outbound). The Seam's handlers forward the push result and record `frame_forwarded_to_gemini` / `chunk_forwarded_to_twilio` unconditionally, and the Exit criterion computes mid-response gaps between consecutive `chunk_forwarded_to_twilio` events. Three sub-questions: (1) on an empty push, suppress the forward, the timing event, or both? (2) what triggers `push(..., last=True)`? (3) does the gap methodology survive?
- Options offered: (1a) suppress both forward and event; (1b) suppress the forward, keep the event as a per-frame heartbeat; (1c) forward the empty payload and record it. (2a) `last=True` once per direction at session teardown; (2b) `last=True` on every chunk; (2c) flush on silence detection. (3a) methodology unchanged, quantization floor recorded explicitly; (3b) revise the gap methodology.
- Recommendation: implementer escalated without recommending, since the fix touches both the ratified seam contract and the exit criterion's measurement basis.
- Human chose: **1a, 2a, 3a.** (1) Both suppressed — "the event name states a forward happened; it must not fire when one didn't." Keeping the event records a lie, and phantom events shrink apparent gaps, so a genuine multi-second stall would be fragmented into sub-threshold pieces, never become a large gap, never reach the corroboration rule, and pass silently — the false-PASS direction this slice exists to catch. Forwarding an empty payload sends nothing while claiming a forward, and wastes a call. (2) Teardown flush only — not per chunk (which would finalize the stream and destroy the filter history Q1 exists to preserve) and not on silence detection (needs a VAD that does not exist in this slice). (3) Methodology unchanged, but its premise base made explicit: with empty pushes suppressed, every recorded event is a real forward again, so gaps are genuine — but bursts are ~61ms outbound rather than continuous, so a genuine stall shorter than one burst interval is invisible to the method. At a 1500ms threshold against ~61ms quantization that is a ~24x margin, comfortably within tolerance — "but it must be written down, not assumed."
- Latency to decision: immediate.
- Notes: Applied as a fold-in per the 2026-08-23T16:27Z precedent — no critic-loop rerun. Artifact changes: Seam handlers made conditional on non-empty bytes; `close()` added for the teardown flush; Q9 (empty-push contract), Q10 (flush trigger) and Q11 (quantization floor, folded into the Exit criterion's gap note) added; Critic note 1 struck as resolved by Q10. The Exit criterion's earlier claim that local processing adds "single-digit milliseconds per chunk" was factually falsified by the probe and corrected in place. Owner separately directed that Seam 2's test — written before this behaviour was known — must now assert the empty-return case explicitly, because a fresh-instance-per-chunk bug returns empty on *every* push, and with empty pushes suppressed at the handler, a fully broken bridge forwards nothing while emitting no events at all, which is indistinguishable from a healthy idle line by the timing artifact alone. Premise handling: `PR-resampler-emits-per-chunk` stays `falsified` with the probe as evidence; replacement premise `PR-resampler-empty-push-is-noop` added stating what is now true; the quantization finding folded into `PR-gemini-chunk-cadence` rather than a new row, per owner direction; review flags on the depended-on-by items cleared as of this fold-in.

## 2026-08-24T19:41:13Z — ADR_RATIFICATION — voice-intake-demo
- Question: Implementation start-up found the ratified artifact rests on a false environment claim. Q2's WHY cited "`import audioop` on this repo's 3.12.3 interpreter emits a DeprecationWarning", and Seam 1 cited reference values "verified via `audioop.ulaw2lin` reference decode". Neither is true on this machine: the interpreter is Python 3.14.4, `audioop` was removed outright in 3.13 (PEP 594), and `import audioop` raises ModuleNotFoundError. Separately, the source of the test's μ-law reference values was never stated as a decision, leaving the constants at risk of being "cleaned up" by a later reader. Should the correction be a fold-in, or does it require re-running the planner–critic loop?
- Options offered: A) Fold-in — correct the false basis in Q2 and Seam 1 in place, add Q8 recording the reference-value source with its WHY, log here as ADR_RATIFICATION. B) Reopen Phase 2's critic loop, since Q2's stated rationale is being edited.
- Recommendation: A. The *decision* in Q2 is untouched — hardcoded ITU-T constants beat audioop-derived ones on either interpreter, because the standard is the standard; only the rationale shifts from "expiring premise" to "already removed". Correcting a false premise under a decision is not reopening the decision. Precedent: the 2026-08-23T16:27Z entry folded an amendment into an already-finalized Phase 2 rather than re-running its critic loop, for the same reason.
- Human chose: A (fold-in), and directed that Q8 be added using the text drafted during implementation, the Q2/Seam-1 citation corrected, and both changes logged here.
- Latency to decision: immediate.
- Notes: Owner also caught that the premise log was missing its load-bearing rows — most importantly `PR-audio-bridge-latency`, the very premise this slice exists to test. Without it, a failed exit criterion has no `depended-on-by` chain to propagate to `feature:conversation`, defeating the mechanism's whole purpose. Added in the same pass: `PR-audio-bridge-latency`, `PR-sms-deliverability`, `PR-advice-boundary-enforcement`, plus `PR-gemini-chunk-cadence` (slice Premise 5, added by the implementer under the same argument and flagged for owner review). `PR-audioop-unavailable` was restated as interpreter-conditional (holds on ≥3.13, falsified by pinning back to ≤3.12) with the Article 8 propagation trigger written into the row.

## 2026-08-23T16:08:00Z — DESIGN_FORK — voice-intake-demo
- Question: Phase 2 hit the 4-round circuit breaker. Open issue: when a malformed/undersized audio frame arrives mid-call, does the bridge catch AudioFrameError and continue, or let it propagate? Directly affects whether one bad frame can fail an entire real-PSTN test call.
- Options offered: A) Catch, drop, log via TimingRecorder, continue the session. B) Catch, log, terminate the call as a hard failure.
- Recommendation: A because it matches Q4's already-established "never crash the session on a recoverable event" principle, and keeps any resulting timing gap diagnosable after the fact instead of a mystery.
- Human chose: A (catch, drop, log, continue).
- Latency to decision: immediate.
- Notes: This was the 4th consecutive round on Phase 2's seam/decisions section, each round finding a genuinely distinct defect (stateless resampler → numpy dtype mismatch → wrong constructor kwarg → this catch-point gap), not repeated oscillation on the same point. Circuit breaker fired correctly per protocol regardless.

## 2026-08-23T16:27:00Z — DESIGN_FORK — voice-intake-demo
- Question: Phase 3 (built on top of the already-finalized Phase 2) hit its own round-4 circuit breaker. Root cause traced back into Phase 2: the TimingRecorder description was self-contradictory — "record(event, timestamp) -> None" (caller supplies timestamp) stated alongside "takes an injected clock" (implies the recorder derives timestamp internally). These can't both be true of the same method.
- Options offered: A) BridgeSession owns the one clock, computes every timestamp itself, passes it explicitly into record(event, timestamp); TimingRecorder has no clock of its own. B) TimingRecorder owns the injected clock; record(event) takes only the event name and stamps time internally via self._clock().
- Recommendation: A because it centralizes all "what time is it" logic in one place (BridgeSession, which already receives received_at-shaped data from the wire) and keeps TimingRecorder as a pure write-sink with zero time logic to get wrong.
- Human chose: B (TimingRecorder owns the clock).
- Latency to decision: immediate.
- Notes: This required amending the already-finalized Phase 2 seam text (handle_gemini_chunk's signature dropped its separate `received_at` parameter; TimingRecorder.record() is now single-argument-plus-detail) rather than reopening Phase 2's full critic loop — same fold-in pattern used for Phase 2's own Q6 circuit-breaker resolution. Phase 3's Seam 3 was rewritten to match the corrected contract.

## 2026-08-24T10:33:00Z — DESIGN_FORK — voice-intake-demo
- Question: Phase 4 hit its own round-4 circuit breaker. The T-largest-gaps exclusion rule (itself already revised twice this session — vacuous automated rule → manual magnitude+ordinal rule → off-by-one fix) had no check that an excluded gap is actually a caller turn rather than a real stall: a genuine mid-response freeze that happens to be the single largest gap in the call would be waved through as "largest = must be a caller turn," producing a false PASS on exactly the failure mode this slice exists to catch.
- Options offered: A) Any of the T excluded gaps that individually exceeds the 1500ms threshold must be corroborated against the call's audio/transcript before being excluded; uncorroborated → NOT PASSED. Smaller excluded gaps need no corroboration since they couldn't have failed the threshold regardless. B) Corroborate all T excluded gaps, always, regardless of size.
- Recommendation: A because it only adds verification burden where misclassification is actually consequential (a gap that couldn't fail the threshold anyway needs no check), keeping the manual review proportionate rather than uniformly heavier.
- Human chose: A (corroborate only excluded gaps >1.5s).
- Latency to decision: immediate.
- Notes: Fourth distinct real defect found across Phase 4's gap-classification mechanism (vacuous signal → no mapping rule → off-by-one → no corroboration check), each round finding something genuinely different, not oscillation on the same point.

## 2026-08-24T10:47:00Z — PRODUCT_DECISION — voice-intake-demo
- Question: The corroboration check for an excluded gap >1500ms read "corroborated if its start offset roughly aligns with the tester's logged start-time." What numeric tolerance defines "roughly aligns"?
- Options offered: A) ±2000ms tolerance (accounts for stopwatch reaction time + manual note-writing lag). B) ±1000ms tolerance (tighter — reduces risk of rubber-stamping a real stall as corroborated).
- Recommendation: B because the point of corroboration is to catch a genuine AI stall masquerading as caller think-time; a tolerance loose enough to absorb manual stopwatch imprecision but tight enough that it can't swallow a real >1500ms stall preserves the purpose of the already-ratified corroboration gate.
- Human chose: B (±1000ms).
- Latency to decision: immediate.
- Notes: This surfaced as a genuinely new undefined qualitative term ("roughly aligns") introduced by the corroboration-mechanism swap (Twilio recording → tester manual log) in the prior round — a normal CRITIC_ESCALATE, not the round-4 circuit breaker (Phase 4's mechanical round count had reset after its own prior circuit-breaker escalation).

## 2026-08-24T11:29:00Z — PREMISE_PROBE — voice-intake-demo
- Question: The second cold-reader final audit found the Exit criterion's "take the T largest gaps as caller-turn boundaries" methodology rests on an unverified assumption — that Gemini Live's intra-response audio-chunk delivery cadence is small (~single-digit ms), never rivaling genuine caller-turn-boundary gaps in size. Gemini's docs don't document chunk cadence; this was never empirically spiked. If false, the failure mode is a false NOT-PASSED (a genuine caller-turn gap could get miscounted against the 1500ms threshold) — the critic separately confirmed the more dangerous direction (a real AI stall sneaking into the excluded set) is already closed by the existing corroboration rule.
- Options offered: A) Accept as an open/accepted risk, proceed to finalize the artifact — if wrong, it surfaces as an occasional false NOT-PASSED during the actual 3 test calls, resolved via the already-built-in Ambiguity/Corroboration rules. B) Run a ~15-minute standalone spike (bare Gemini Live WebSocket session, a few test prompts, log real inter-chunk gaps within single responses) to empirically confirm the cadence assumption before finalizing.
- Recommendation: A because the failure direction is the safe one (over-strict, not under-strict) and this MVP's own design already accepts Premise 3 itself as an open risk under the same "the real test calls are the actual spike" philosophy.
- Human chose: A (accept as open risk, proceed).
- Latency to decision: immediate.
- Notes: Folded into the artifact as Premise 5 (OPEN/ACCEPTED RISK), same treatment as Premise 3. This was the second cold-reader pass's only finding; the first cold-read's cross-section contradiction (Seam↔Exit-criterion event-timing mismatch) was independently re-verified fixed and did not recur.
