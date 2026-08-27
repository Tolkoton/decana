# Build progress

One `## NOW` block at the top, live. Then one entry per completed slice, newest
first. Planning artifacts live in `.claude/overseer/slice/`.

**`## NOW` is written for a fresh instance with no memory of the session that
wrote it.** If you cannot resume from it alone, it is wrong — fix it rather than
guessing. It is updated at every unit, not at session end, so a session killed by
a context limit or a crash still leaves it accurate. Its timestamp is the liveness
signal: chat is reserved for interrupts, so nothing else reports that the machine
is still moving.

---

## NOW — S3 and S4 tests DONE; S5 `dispatch` is next (updated 2026-08-27T21:45:00Z)

- **Suite: 260 passed.** `ruff check src tests scripts` clean.
  `mypy --strict src scripts tests` clean (37 files).
  **Use that exact mypy command** — `pyproject.toml` scopes mypy to `src`/`scripts`,
  so a bare `uv run mypy` silently skips the test suite and reports clean.

- **S3 `twilio-server`** — all 46 ratified ids green. Contract:
  `.claude/overseer/slice/twilio-server.md`.
- **S4 `analysis`** — all 22 ratified ids green, 7 mutations killed. Contract:
  `.claude/overseer/slice/analysis.md` (RATIFIED; 8 defects removed across 2 critic
  rounds and 6 cold-read passes).

- **Next unblocked item: plan and build S5 `dispatch`.** Run `/plan-slice dispatch`.
  It consumes `Analysis` from S4 and `CallRecord` from S3 — both exist and are tested.
  Its ratified contract is the "Edge S5 ← S3, S4" block in
  `.claude/architecture/feature/vertical-profile-bridge.md`. **S5 needs no credentials
  to build** — the SMTP and Twilio senders are injected, so the whole slice is
  fake-driven; the secrets are runtime-only.

- **PARKED, both on the same unblocker:**
  - `scripts/smoke_twilio_server.py` (S3 exit criterion item 2)
  - `scripts/smoke_analysis.py` (S4 exit criterion item 2)

  **Both need `GEMINI_API_KEY` exported into the process environment.** `.env` is
  hard-denied to the agent, so `scripts/supervise.sh` must export it. Each spends one
  unit of `.claude/overseer/.api-budget.json` before opening any socket, and each
  parks cleanly rather than failing when the key or the budget is absent.

### How to check either slice's exit criterion

Run `scripts/check_ids.py`. It diffs the ratified id set against the test docstrings
in both directions for every slice, and exits non-zero if either direction is dirty.
Do not eyeball this.

### Work queue

| node | state | note |
|---|---|---|
| S1 profile | DONE | |
| S2 gemini-live | DONE | |
| S3 twilio-server | **tests DONE** | 46/46 ids; smoke PARKED |
| S4 analysis | **tests DONE** | 22/22 ids; smoke PARKED |
| **S5 dispatch** | **NEXT** | fake-driven; needs no credentials to build |
| S6 deploy | **HUMAN-REQUIRED** | Cloud Run + cloud credentials. Park on sight. |
| S7 real calls | **HUMAN-REQUIRED** | provisioned number + a human with a phone |

**After S5, every remaining node is HUMAN-REQUIRED.** That is the point at which the
loop has genuinely run out of work and should say so in chat.

### Live risks — decided, do not re-litigate

- **`_sweep_expired` claims before it closes** (S3). `registry.pop(...)` is the claim;
  whoever pops owns the entry and closes it. S8.c found a real double-close here.
- **Every teardown path passes the websocket** (S3), or a call ends with the socket
  open forever. That is a hang, not an error; it cost three attempts to find.
- **`analyse` catches `Exception`, never `BaseException`** (S4-Q7). One word wider
  passes every node except `A4.f` and silently costs teardown its cancellation.
- **`GeminiAnalysisClient` must use `client.aio.models.generate_content`** and must
  forward `api_key`. The sync facade blocks the loop; a dropped key is masked by the
  SDK's own env fallback and passes CI, smoke and production alike.
- **A non-string `outcome` is a wrong SHAPE, not a wrong value** (S4). Found during the
  build; the diagnosis differs a week later, when the record is all there is.
- **Use `scripts/mutate_check.py` for every mutation check.** It asserts the mutation
  applied, restores in a `finally` and on signals, and verifies the restore. Ad-hoc
  runners are forbidden: one died mid-mutation and left the tree corrupted.
- **Maintain this block with `Edit`, never a script doing `str.replace`** — a
  no-match fails silently, and this file has drifted that way twice.
---

## Slice S4 — analysis (DONE 2026-08-27)

Feature `vertical-profile-bridge`, slice S4. Contract:
`.claude/overseer/slice/analysis.md`. Planned and built unattended.

- **Modules:** `src/decana/analysis/{model,analyse,gemini_client}.py`.
- **Tests:** `tests/test_analysis.py`, 25 nodes covering all 22 ratified ids, clean in
  both directions (`scripts/check_ids.py`). Suite 235 -> 260.
- **Mutation evidence: 7 of 7 killed**, each via `scripts/mutate_check.py`.
- **Smoke:** `scripts/smoke_analysis.py` — PARKED on `GEMINI_API_KEY`.

### Surprises

- **Eight defects in planning, every one the same shape** — a ratified thing with fewer
  than all three of (a decision naming the mechanism, a seam naming the wrong
  implementation, an id naming the node). None was found by re-reading; every one came
  from an enumeration walked row by row.
- **`except BaseException` is one word from correct and silent forever.** It passes
  every node except `A4.f`, `ruff` and `mypy`, and costs teardown the ability to cancel
  the analysis at all.
- **A dropped `api_key` is masked by the SDK itself.** `google-genai` falls back to
  `os.environ['GEMINI_API_KEY']`, which is exactly what the deploy injects — so
  `genai.Client()` passes CI, the smoke AND production. The usual reassurance that a
  real call would catch it is false here.
- **The sync and async facades are interchangeable to mypy and not to the event loop.**
  `client.models.generate_content` is a blocking `def`; wrapping it in an `async def`
  defeats `wait_for` and stalls audio for every other live call.
- **A repair can introduce the defect it is repairing.** The `summary`-content fix was
  applied to four of Seam 4's five failure modes and skipped the fifth.

### Open for the next slice

- **S5 consumes `Analysis` and `CallRecord`**, both tested. It needs no credentials to
  build; SMTP and Twilio senders are injected.
- **`raw` is what S5 writes** to `{call_sid}.analysis.json`, and it is populated on the
  failure paths too — deliberately, because a parse failure is when someone needs to
  see what the model actually said.
- **W-1:** truncation can end a summary mid-sentence. Accepted — the brief points at
  the transcript rather than replacing it.

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
