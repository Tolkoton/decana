# Build progress

One entry per completed slice, newest first. Planning artifacts live in
`.claude/overseer/slice/`; this file is the short version — what shipped, what
surprised us, and what the next slice inherits.

## Slice S2 — gemini-live (DONE 2026-08-27)

Feature `vertical-profile-bridge`, slice S2. Contract:
`.claude/overseer/slice/gemini-live.md`. **Planned and built unattended** — owner
away, escalate list suspended; every owner-gated decision is logged in
`.claude/overseer/unattended-decisions.md`, ordered by cost to reverse.

- **Module:** `src/decana/gemini/live.py` (~330 LOC — `GeminiLiveSession`,
  `open_live_session`, `LiveTransport`, `_TurnAccumulator`, and the four event
  types fixed by the ratified contract).
- **Tests:** `tests/test_live.py`, 23 nodes, all green. The ratified id set and
  the test nodes diff clean in both directions — no id without a test, no test
  naming an id that is not ratified. Suite total 178 (was 155).
- **Mutation evidence: all 7 ratified mutations killed their id**, restores
  diff-verified byte-identical against a sha256 of the original.
- **Smoke:** `scripts/smoke_gemini_live.py` against the real Live API — PASSED on
  the first run, all 7 assertions, no human oracle needed. Model opened the
  conversation unprompted at **3229 ms**; one whole-utterance model turn; caller
  turn recovered from fed-back audio; exactly one `Closed(reason='local')` last.
- **Checks:** `ruff check`, `ruff format --check` clean; `mypy --strict` clean over
  `src`, `scripts` AND `tests` (21 files). Note `pyproject.toml` scopes mypy to
  `files = ["src", "scripts"]`, so a bare `uv run mypy` does NOT check the test
  suite — the Stop hook does, and caught two real errors there that the scoped
  run reported clean. Check `tests/` explicitly, or trust the hook, not the
  config default.

### Surprises

- **`AsyncSession.receive()` ends after ONE turn.** It `break`s on the first
  `turn_complete` (`live.py:455-459`), so it is a per-turn iterator, not a
  session one. A naive wrapper would have ended the event stream after the
  greeting and killed every real call one turn in — while passing every unit test
  written against a fake that streams everything in one pass. **This also
  falsifies the earlier spike's own conclusion:** its `OPEN_not_a_premise` block
  blamed the fixture for "the receive stream ended", and tried "draining past the
  first turn_complete". The fixture was weak, but the `break` is what ended the
  stream, and draining fails because the next turn needs a *new* `receive()` call.
- **A local close and a remote close are indistinguishable by exception.**
  `AsyncSession.close()` closes the same socket the reader is blocked on, and
  `_receive()` converts the resulting `ConnectionClosed` to `APIError`
  unconditionally — byte-identical to a genuine remote close. `Closed.reason`
  feeds `CallRecord.ended_reason`, so this was a race that would silently
  mislabel calls. Fixed by ordering `close()` (Q4), not by cleverness.
- **The SDK raises a bare `ValueError` too.** `_receive()` raises it on malformed
  JSON (`live.py:551-552`), unwrapped by `receive()`. A reader scoped to
  `except APIError` dies silently, no `Closed` is queued, and `events()` waits
  forever — a hang, not an error. The reader catches `Exception` and emits from a
  `finally`.
- **`Transcription.finished` is never populated** — 0 of 36 fragments across both
  directions. It is the obvious flush signal and it does not exist. The caller
  direction has no terminator at all (45 s drain, nothing), which is why a caller
  turn is closed by role switch.
- **Three defects were found by review, not by testing**, each verified in SDK
  source rather than reasoned about. A fourth — `Interrupted` having no test at
  all despite being in the ratified event union — was found only by the
  cold-reader pass, after ten round-anchored critic rounds had missed it.
- **A mutation that appears to prove something can prove nothing**, again: the
  first `S2` mutation run inserted a comment inside a call's parens, producing a
  `SyntaxError`, so the suite never ran and the mutation "survived" for a reason
  that had nothing to do with the test. Re-run properly, it killed 4 nodes.
- `msg.data` logs `non-data parts in the response: ['text', 'thought']` on a real
  session. Harmless here — transcripts come from `output_transcription`, not from
  `model_turn` text parts — but worth knowing before anyone reaches for
  `msg.text`.

### Open for the next slice

- **S3 must open the Live session CONCURRENTLY with the Twilio `<Say>`.** First
  audio measured at 3229 ms tonight (3.2–4.0 s across runs). The disclosure takes
  longer than that to speak, so the connect cost hides behind it — but only if S3
  opens the session while `<Say>` is playing, not after.
- **S3 owns the teardown ordering between two `close()`s.** `BridgeSession.close()`
  is sync and does NOT call `gemini.close()`; S3 calls both, and this slice does
  not define the order. Read Q4's ordering invariant before writing that teardown.
- **Three decisions want the owner's eye**, all in `unattended-decisions.md`:
  `Closed.reason` carrying exception detail (the one place ratified contract text
  was stretched); P10 barge-in accepted as risk; the smoke's whole-utterance
  threshold.
- **P10 revisit trigger:** the first tracer call with a real human voice. Read
  that transcript for split caller turns — a barge-in would split one caller turn
  into two, which is the accepted failure direction.

## Slice S1 — profile-loader (DONE 2026-08-26)

Feature `vertical-profile-bridge`, slice S1. Contract:
`.claude/overseer/slice/profile-loader.md`.

- **Modules:** `src/decana/profile/model.py` (~111 LOC — `Profile`, `SmsTemplate`),
  `src/decana/profile/load.py` (~466 LOC — `load_profile`, `ProfileError`, `SCHEMA`).
  Data: `profiles/mortgage-broker/`, `profiles/eco-consultant/`, each `profile.toml`
  plus three DRAFT-marked prompt files.
- **Tests:** `tests/test_profile.py`, 89 nodes, all green. Integration-only —
  every one goes through `load_profile` against a directory on disk; no bare-helper
  tests. Node ids diff clean against the artifact's ratified list in both
  directions (no missing row, no unratified extra). Suite total 155.
- **Smoke:** `scripts/smoke_profile.py` — passed, owner reported DONE 2026-08-26.
  Both shipped profiles load with no `root` argument from the repo root (the one
  path the unit tests deliberately never take, Q7), and `../x` is rejected with a
  `ProfileError` naming the argument, exit 1.
- **Checks:** `ruff check`, `ruff format --check`, `mypy --strict` clean.

### Surprises

- **The DRAFT marker was a latent production defect, not a cosmetic one.**
  Q11 and P5 required every prompt file to *open* with
  `<!-- DRAFT — owner to review before S7 -->`, while the S3 contract feeds
  `profile.disclosure` verbatim into TwiML `<Say>`. The marker would have been
  read aloud to the caller — and because P5 pinned it, it would have outlived the
  draft text it was written for and reached real client calls. Escalated rather
  than patched (it amends ratified text and adds exit-criterion ids); owner chose
  to strip the comment at load. Recorded as Q15, risk as W-2.
- **Two assertions were only proven by breaking the code on purpose.** Seam 4
  (V1/V4) and the strip rule (W7/W8) both passed on arrival, which is not the
  same as being right. Mutation-checked: the aliasing bug leaves 73 of 75 tests
  green and is caught only by V1 and V4; an unanchored strip pattern is caught
  only by W8; a *greedy* strip pattern survived the entire suite until W7's
  fixture was given a second comment to protect. All restores diff-verified
  byte-identical.
- **A mutation run that appears to prove something can prove nothing.** The first
  Seam-5 attempt was shell-escaped wrong, the guard `assert` failed, and the
  suite ran against unmutated code showing a meaningless pass. Worth re-reading
  any mutation result for evidence the mutation actually landed.
- The planning artifact's "no toolchain on PATH" blocker was stale — the project
  runs through `uv run`, where 3.13.15 / ruff / mypy / pytest are all present.

### Open for the next slice

- **S3 owns the consequence of Q15.** `profile.disclosure` is now guaranteed free
  of a leading HTML comment, so the TwiML `<Say>` body is safe to interpolate
  directly. Nothing else needs to re-check it.
- **The prompt text is DRAFT.** The tracer may run on it; S7 step 7a may not. The
  owner authors the real wording before S7 — the `<!-- DRAFT -->` markers stay on
  disk (P5) and no longer reach the caller or the model.
- **Deferred, with triggers** (full list in the artifact): error aggregation — a
  second *real* vertical, or a non-developer editing profiles; `profile.toml`
  schema versioning — the first backward-incompatible field change after a
  profile is in production; per-outcome email templates and per-profile model
  parameters — a real vertical needing one.
- **W-1 still stands:** Q7's `profiles_root` default assumes an editable install.
  If S6's Dockerfile installs non-editable, set `DECANA_PROFILES_ROOT` explicitly
  and record it in `docs/deploy.md`.
