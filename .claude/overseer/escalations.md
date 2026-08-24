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
