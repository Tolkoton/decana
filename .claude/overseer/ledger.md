# Overseer ledger — append-only

Append one entry per overseer invocation. Newest at the top below this
header. Older entries below.

## Entry format

```
## <ISO timestamp UTC> — <slice slug> — <verdict>
- Trigger: <which check #N, or "none">
- Evidence: <transcript turn N / SHA abc1234 / file:line>
- Action: <one-line description>
- Category: strategy | recovery | optimization | none
```

Categories follow Trajectory-Informed Memory Generation (arXiv 2603.10600):
- **strategy** — developer pattern that worked, worth recording
- **recovery** — developer near-miss with successful course-correction
- **optimization** — inefficient pattern worth flagging next time
- **none** — routine entry, no pattern of note

## 2026-08-24T20:18:01Z — voice-intake-demo — OVERSEER_ADR_REQUIRED
- Trigger: #8 chat-only design (three interface contracts agreed in chat, never written to the slice artifact or an ADR). #2 partially noted but not fired — see Action.
- Evidence: `.claude/overseer/slice/voice-intake-demo.md` lines 27, 28, 40, 104 name `InboundResampler`/`OutboundResampler` as the Seam contract and as Seam 2's test approach; `src/decana/bridge/resampler.py:39,66,71` implements a single `Resampler(in_rate, out_rate)` plus `inbound_resampler()`/`outbound_resampler()`. Artifact line 37 scopes `AudioFrameError` to `mulaw_decode`/`mulaw_encode` only; `src/decana/bridge/resampler.py:59` extends it to `Resampler.push` via `reject_partial_pcm16`. `src/decana/bridge/codec.py` promoted `_reject_partial_sample` to public `reject_partial_pcm16`. Owner ratified the first two in chat this session ("1. do 1 class", "2. up to you"); neither reached the artifact's "Decisions (with WHY)" section, and `docs/adr/` does not exist.
- Action: BLOCKED on writing the three interface changes into the ratified contract before Seam 3 begins. Not a correctness finding — 43 tests green, `ruff`/`mypy` clean, RED shown before GREEN for codec B1/B2/B3-B5 and resampler B1/B7, and the resampler's four no-RED tests (B2-B5) were mutation-verified by hand (8 of 13 fail when the stateless bug is reintroduced, restore diff-verified identical). The defect is that the artifact now describes a contract the code does not implement, in four places, while the same session used the fold-in mechanism three times (Q8 at 19:41Z, Q9-Q11 at 20:14Z) for exactly this situation.
- Category: recovery

## 2026-08-24T11:35:00Z — voice-intake-demo — PLANNING_COMPLETE
- Trigger: /plan-slice command
- Evidence: .claude/overseer/slice/voice-intake-demo.md, .claude/overseer/escalations.md (7 owner-ratified decisions: Phase-2 circuit-breaker Q6, Phase-3 circuit-breaker Q7, Phase-4 circuit-breaker corroboration rule + evidence-source swap + ±1000ms tolerance, cold-reader Premise-5 accepted risk)
- Action: planning artifact written after Phase 1 (interactive framing, 2 premises verified via live docs fetch), Phases 2-5 (automated planner-critic loop: Phase 2 four rounds to a circuit breaker, Phase 3 seven rounds, Phase 4 twelve rounds across two owner escalations plus one PRODUCT_DECISION, Phase 5 three rounds), and two cold-reader final-audit passes on the assembled artifact — the second found and resolved a genuine cross-section contradiction (event `gemini_chunk_received` renamed `chunk_forwarded_to_twilio` to match its actual post-processing recording point) plus one premise-probe (Gemini intra-response chunk cadence, accepted as open risk). 7 decisions logged with WHY, 4 hardest seams named with concrete test approaches, 1 exit criterion with owner-ratified thresholds, 6 items deferred with revisit triggers, 1 permanent cut corrected from an earlier imprecise "deferred" label.
- Category: strategy
