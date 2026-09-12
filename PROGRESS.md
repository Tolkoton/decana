# Build progress

One `## NOW` block at the top, live. Then one entry per completed slice, newest
first. Planning artifacts live in `.claude/overseer/slice/`.

**`## NOW` is written for a fresh instance with no memory of the session that
wrote it.** If you cannot resume from it alone, it is wrong — fix it rather than
guessing.

---

## NOW — S5 `dispatch` BUILT: 54/54 ids green, smoke tier 1 passed (updated 2026-09-12)

- **Ids green: 54 of 54.** `scripts/check_ids.py` reports `dispatch OK 54 ids, 54 covered`,
  clean in BOTH directions. **Suite: 314 passed** (was 260).
- **Mutation evidence: 42 mutations, 42 KILLED.** Three survived on the first pass and every
  one was a hole in the TEST, not the code — see the ledger entry
  `2026-09-12T03:00:00Z — dispatch (S5) — SLICE_TESTS_COMPLETE` for each.
- **Smoke: `scripts/smoke_dispatch.py` TIER 1 PASSED, 13/13** — for **BOTH** shipped
  profiles (`mortgage-broker` and `eco-consultant`), env var only, no code change. It reads
  `DECANA_PROFILE` and DERIVES an outcome that has an SMS template rather than naming one.
  That is A4's property demonstrated for S5 ahead of S7. No human oracle; runs in seconds.
- **Cross-slice vocabulary check: CLEAN, no mismatch.** `src/` hardcodes zero shipped
  category names; S3 never mentions `outcome`; S4 builds its enum from `profile.outcomes`
  and downgrades anything outside it; S5 reads `profile.sms.get(...)`. Both `analysis.md`
  prompts enumerate exactly their own `outcomes.allowed` plus `unclassified`. Full result:
  ledger `2026-09-12T04:00:00Z — CROSS_SLICE_VOCABULARY_CHECK`.
- **Checks:** `ruff check`, `ruff format --check`, `uv run mypy --strict src scripts tests`
  all clean (46 files).
- **Next unblocked item: NOTHING in S5.** The remaining feature nodes are **S6 deploy** and
  **S7 real calls**, both marked HUMAN-REQUIRED in the queue below. Per the work loop, that
  is the terminal condition: the DAG has no node left that can run without a human.
- **PARKED, each on a named unblocker:**
  - `scripts/smoke_dispatch.py` TIER 2 — needs `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/
    `SMTP_PASSWORD`/`SMTP_FROM`. Until it runs, `SmtpEmailSender` is verified only by a fake
    it implements.
  - `scripts/smoke_dispatch.py` TIER 3 — needs `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` and
    `DECANA_SMOKE_SMS_TO`. Costs money; spends the `_budget` cap before opening a socket.
    This is the only check that P2's `Optional[str]` narrowing is right about a REAL response.
  - `scripts/smoke_twilio_server.py`, `scripts/smoke_analysis.py` — `GEMINI_API_KEY`.
  - **S6** — cloud credentials. **S7** — a provisioned number and a human with a phone.
- **Staged, uncommitted:** everything. The owner commits; the hook allows commits only on an
  `unattended/<date>` branch.

**S5 changed files OUTSIDE `src/decana/dispatch/`** (Q24's authoritative list):
`src/decana/settings.py` (+7 optional fields, +`has_twilio`/`has_smtp`),
`src/decana/twilio/server.py` (`build_on_call_end` REMOVED — it moved to
`dispatch/wiring.py` so S3 never imports S4/S5), `src/decana/__main__.py` (import + call site,
now `build_on_call_end(settings, profile)`), `src/decana/analysis/analyse.py` (`__all__`
+`render_transcript`), `pyproject.toml` (+twilio, +scoped mypy override), `scripts/check_ids.py`
(+the `dispatch` row).

## Superseded — S5 planned, `brief.py` built (2026-09-12, earlier in the same session)

- **Ids green: 14 of 54** — `D3.a` `D3.b` `D8.a` `D19.a` `D19.b` `D19.c` `D20.a` `D20.b`
  `D20.c` `D20.d` `D21.a` `D21.b` `D21.c` `D21.d`. **Suite: 277 passed** (was 260).
- **Built so far:** `src/decana/dispatch/{__init__,errors,model,brief}.py`. `render_brief`
  is complete against the ratified Q21 template; **10 mutations run, 10 killed**, including
  the prefix-parsing renderer and the two-line-difference mutant.
- ~~Next unblocked item: `senders.py` …~~ **ALL DONE — superseded by the live `## NOW`
  block at the top of this file. Do not act on this line.**
- **`scripts/check_ids.py` now registers `dispatch`** and correctly reports `DIRTY 54 ids,
  14 covered` with the missing list. Before that row existed it printed `SKIP` and exited 0.
- ~~PARKED: none.~~ **Superseded — the live `## NOW` block's PARKED list is authoritative.**
  (It was true while building: nothing in the slice needed a credential. The smoke's tiers
  2 and 3 now park, as predicted here.)
- **Staged, uncommitted:** everything — the S4 port from the reconciliation session AND
  this session's S5 planning + `brief.py`. The owner has the two suggested commit commands;
  the hook allows commits only on `unattended/<date>`.
- **Checks:** `ruff check` clean, `ruff format --check` clean, `uv run mypy --strict src
  scripts tests` clean (42 files), `pytest` 277 passed.

**Read the slice contract before continuing: `.claude/overseer/slice/dispatch.md`.** It is
the ratified behavior list; do not invent ids or change what one asserts without escalating.

### Known deviation, recorded rather than hidden

`render_brief` was implemented in full to satisfy its FIRST behavior (`D20.a`), which
over-shoots TDD's "minimal implementation". The other 13 brief tests therefore passed on
arrival. That is why the 10 mutation runs above are the evidence, not the green suite —
the same position `twilio-server` recorded. For the remaining modules, write the test first.

## Superseded — branch fork reconciled (2026-08-27, reconciliation session)

**What happened:** two independent unattended sessions both built S3
`twilio-server` starting from the same commit (`754394a`), diverging — one
landed on `main` (`11da8aa`), the other on `slice/s4-analysis` (`28c794e`, with
S4 `analysis` built on top of it, `8e28dc5`). Neither branch had the other's
work. `main`'s S3 was chosen as canonical over `slice/s4-analysis`'s, on three
verified, concrete points — not a coin flip:

1. `slice/s4-analysis`'s `POST /voice` parsed `CallSid`/`From` permissively
   (`form.get(..., "")`) instead of `main`'s required `Form(alias=...)` fields —
   the exact empty-string registry-key collision bug `main`'s own fix note
   describes.
2. `slice/s4-analysis`'s `_teardown` fired `task.cancel()` without awaiting the
   cancelled task before closing shared resources — a real race window `main`'s
   `_stop_task` helper (cancel-and-await) closes.
3. `slice/s4-analysis` never built `build_on_call_end()` at all — the ratified
   feature contract names this exact function ("S5 replaces this body with
   `post_call`"); `main` has it, matching the contract.

This branch (`slice/s5-dispatch`, from `main`) carries forward `main`'s S3 plus
`slice/s4-analysis`'s S4 (`analysis` — independent of S3's internals, ported
clean) and its tooling (`check_ids.py`, `mutate_check.py`, `_budget.py`,
`MEMORY.md`, `ledger.md`, `audit.md`, `unattended-decisions.md`, `AGENTS.md`,
`CLAUDE.md`, `plan-slice.md`, `slice-builder/SKILL.md` — all pure additions
`main` never touched). **Not ported:** `slice/s4-analysis`'s `.claude/hooks/`
changes (it independently rewrote the same commit-policy hook `main` did, in a
different, less anti-bypass-robust way) and its `.claude/unattended/`-adjacent
work — left as `main`'s version deliberately; this is a safety-policy choice,
not a technical one, and wasn't re-litigated here. Flag for the owner if the two
hook rewrites need reconciling too.

- **S3's 4 "pending ratification" items are still open** — see the S3 entry
  below; still owner sign-off before S3 is genuinely DONE. **Correction: S5 DOES
  touch `server.py`** — Q24 removed `build_on_call_end` from it. None of the four
  pending items concerns that function, so they are still independent, but the
  parenthetical as originally written is false.
- **Suite: 260 passed** (`uv run pytest`), `ruff check` / `ruff format --check`
  clean, `mypy --strict src scripts tests` clean.
- **S5 `dispatch` is PLANNED (2026-09-12), not yet built.** Contract:
  `.claude/overseer/slice/dispatch.md` — 24 decisions, 23 seams, 54 ratified ids, 54
  mutations, 4-part exit criterion. Converged after 25 round-anchored critic rounds and 9
  cold reads; 2 owner escalations, both resolved.
- ~~Next unblocked item: BUILD S5 from that artifact.~~ **DONE — 54/54 ids green. See the
  live `## NOW` block at the top of this file, which supersedes this line.** The
  `scripts/check_ids.py` registration it called for has landed.
- **Two ratified-text amendments landed this session**, both owner-ratified and tagged in
  `.claude/architecture/feature/vertical-profile-bridge.md`: guarantee (d) now covers all
  five dispatch effects (not just SMS/email), and guarantee (b)'s SMS-marker question is
  marked RESOLVED. A third change is the plan's own (Q24, no owner gate needed): S5 MOVES
  `build_on_call_end` out of `twilio/server.py` into `dispatch/wiring.py`, because leaving it
  there would make S3 import S4/S5 — which Edge S3 forbids. `__main__.py`'s call site changes
  from `build_on_call_end()` to `build_on_call_end(settings, profile)`.
- **`twilio` was added as a dependency** (`uv add twilio` -> 9.11.1). It ships no `py.typed`,
  so the build must add a scoped `[[tool.mypy.overrides]]` AND narrow `Optional[str]` at the
  adapter — `ignore_missing_imports` alone leaves `no-any-return`.
- **S7 WILL DESTROY ITS OWN EVIDENCE unless sequenced.** Step 7b redeploys the same
  `max-instances=1` service twice, wiping the instance disk where S5's artifacts live, while
  Edge S7 requires reading `{call_sid}.transcript.txt` and `.brief.md` per call. The
  sequencing requirement is now written into row 7b and Edge S7 themselves.
- **PARKED on `GEMINI_API_KEY`:** `scripts/smoke_twilio_server.py`,
  `scripts/smoke_analysis.py`. `.env` is hard-denied to the agent, so the variable must be
  exported by whatever invokes them (the owner, via `!`).
- **`scripts/supervise.sh` IS NOT ON THIS BRANCH** (found 2026-09-12). `CLAUDE.md:163` and
  an earlier version of this line both name it as the layer that exports secrets, but it was
  never ported in the reconciliation — it exists only on `slice/s4-analysis` (`a80c16f`), and
  that version checks `GEMINI_API_KEY` only: it exports nothing and inherits whatever the
  invoking shell has. **Owner decision needed:** port it, or correct `CLAUDE.md`. Until one
  of those happens, the project's written parking story points at a file that is not here.

### How to check any slice's exit criterion

Run `scripts/check_ids.py`. Diffs the ratified id set against test docstrings in
both directions. Do not eyeball this.

**It covers only the slices REGISTERED in its `SLICES` dict** — today `twilio-server`
and `analysis`. `profile-loader` and `gemini-live` are NOT registered, so their id sets
are not mechanically checked by it despite the line above previously claiming "every
slice" (corrected 2026-09-12). A new slice must add its own row, or it is silently
uncovered.

**A green exit code is not the check.** An unregistered slice — or one whose test file
is missing — takes the `SKIP` branch, which `continue`s WITHOUT setting `dirty`, so the
script prints `SKIP` and still exits 0. Read the printed line per slice; `OK` with a
non-zero id count is the evidence, not `$?`.

### Work queue

| node | state | note |
|---|---|---|
| S1 profile | DONE | |
| S2 gemini-live | DONE | |
| S3 twilio-server | DONE, 4 items pending owner ratification | see entry below |
| S4 analysis | DONE | ported from `slice/s4-analysis`, unchanged |
| **S5 dispatch** | **PLANNED, next to BUILD** | artifact: `.claude/overseer/slice/dispatch.md`; fake-driven, no credentials needed |
| S6 deploy | HUMAN-REQUIRED | Cloud Run + cloud credentials |
| S7 real calls | HUMAN-REQUIRED | provisioned number + a human with a phone |

## Slice S5 — dispatch (DONE 2026-09-12)

Feature `vertical-profile-bridge`, slice S5. Contract:
`.claude/overseer/slice/dispatch.md`. Planned and built in one session.

- **Modules:** `src/decana/dispatch/{__init__,errors,model,brief,senders,dispatch,wiring}.py`
  (662 LOC). Outside the package: `settings.py` (+7 optional fields, +2 group predicates),
  `twilio/server.py` (`build_on_call_end` removed), `__main__.py` (call site),
  `analysis/analyse.py` (`__all__`), `pyproject.toml`, `scripts/check_ids.py`.
- **Tests:** `tests/test_dispatch.py`, **54 ids, 54 covered, clean both directions**
  (`scripts/check_ids.py`). Suite 260 -> 314.
- **Mutation evidence: 42 of 42 killed.** Tree verified free of residue after every run.
- **Smoke:** `scripts/smoke_dispatch.py` TIER 1 **PASSED** (13/13) against the real
  filesystem and the real shipped profile. Tiers 2 (SMTP) and 3 (Twilio) **PARKED** on
  credentials — see `## NOW`.
- **Checks:** `ruff check`, `ruff format --check`, `mypy --strict src scripts tests` clean.

### Surprises

- **Every mutation that survived was a hole in the TEST, not the code.** Three of them.
  `D1.a` asserted `ticks > 0`, which held under a direct call too because the ticker gets one
  tick in before the block starts. `D22.c` passed on any UTF-8 dev box whether or not the code
  named its encoding. `D8.a` drove the renderer with hand-built outcomes and so never
  exercised `dispatch`'s own conversion — "a fake cannot be evidence for the contract the fake
  implements", in the most literal form yet.
- **A patch written to expose a defect can hide it instead.** The first `io.text_encoding`
  patch ignored its argument, so it overrode the explicit `encoding="utf-8"` as well as the
  default — making the test fail for a reason unrelated to the property. `write_text` calls
  `io.text_encoding(encoding)` unconditionally; only a patch that honours the argument
  emulates "the process default is ascii".
- **Two planning decisions predicted defects I then committed.** Q18 says the stage boundary
  spans content production, not just the I/O call — I computed the email body outside the
  wrapper, and `D14.a` caught it. Q17 requires `post_call` to guard what is left — I omitted
  the `try/except` entirely, and `D10.a` caught it. The artifact was right and the
  implementation was wrong, which is the direction that check exists to catch.
- **314 unit tests never meet the shipped profile's vocabulary.** The suite's profile is
  fabricated; the real one is `new_client`/`not_qualified`/`callback_requested`/
  `existing_client` with one SMS template. The smoke's first run used `qualified_lead` and the
  gate correctly skipped. The smoke is the only place the two touch.
- **`ruff format` reflowed a line between my writing a replacement and running it**, so a
  `str.replace` silently matched nothing and the assertion stayed stale. Caught by re-running
  the smoke, not by reading. This is the argument for `Edit` over scripted replacement.

### Open for the next slice

- **S6 inherits the seven new env vars.** `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` and the
  five `SMTP_*` must reach the Cloud Run service from Secret Manager. They gate
  INDEPENDENTLY (Q23): a missing Twilio secret costs only the SMS, never the email or the
  evidence files.
- **`build_on_call_end` now lives in `decana.dispatch.wiring`**, not `twilio/server.py`, and
  takes `(settings, profile)`. `D24.a` asserts by AST that `server.py` imports nothing from
  `decana.dispatch`/`decana.analysis` — that constraint is now mechanical, not conventional.
- **S7 must capture 7a's artifacts BEFORE 7b's first redeploy.** Written into the feature
  doc's row 7b and Edge S7. S5's artifacts live on instance disk and a redeploy destroys them.
- **The brief's wording is ratified text** (Q19/Q21, nine status lines plus the content
  blocks). Changing it changes what `D3.a`/`D19.c`/`D20.*`/`D21.*` assert — escalate rather
  than edit.

## Slice S3 — twilio-server (DONE 2026-08-27, pending 4 ratifications)

Feature `vertical-profile-bridge`, slice S3. Contract:
`.claude/overseer/slice/twilio-server.md`. **All three exit criteria hold** — §1
the id-set property, §2 the real-API smoke, §3 the checks. **Four items changed
or strengthened ratified text or project config and need the owner's sign-off**
— listed under "Pending ratification".

- **Modules:** `src/decana/twilio/server.py` (~530 LOC — `create_app`,
  `build_on_call_end`, `LiveSession`, `_SocketSender`, the event pump, the drain
  task and `_teardown`), `records.py` (47 LOC, unchanged), `settings.py` (~90
  LOC), `__main__.py` (~43 LOC). `pyproject.toml` gains
  `[project.scripts] decana`.
- **Tests:** `tests/test_twilio_server.py`, **57 nodes across 46 ids, all green**.
  The ratified id set and the collected nodes diff clean in both directions,
  checked mechanically against the artifact's table rather than by eye: no
  ratified id without a node, no node whose docstring id is unratified, no
  node-count mismatch. Suite total **235** (was 178) — exactly the number the
  artifact projected.
- **Mutation evidence: 12 mutations, all 12 killed by their named id**, restores
  sha256-verified byte-identical after every one. Most of this slice's tests were
  written after the machinery they cover and so passed on arrival; the mutation
  run is what makes them evidence rather than decoration.
- **Smoke:** `scripts/smoke_twilio_server.py` against the **real Live API** —
  **PASSED on the first run**, all 9 assertions, no human oracle needed. Real
  `create_app`, real `open_live_session`, real uvicorn, real webhook POST, real
  WebSocket client; only Twilio simulated. Webhook answered in **559 ms**; **93
  outbound frames**, every one carrying the root `streamSid`; outbound **RMS
  0.134** of full scale against a 0.005 floor (~27x); timing JSONL carried
  `call_answered` and **94 `chunk_forwarded_to_twilio`** of 115 events;
  `on_call_end` fired once with `ended_reason="twilio_stop"` and the model's
  unprompted greeting turn in the transcript.
- **Checks:** `ruff check`, `ruff format --check`, `mypy --strict` clean over
  `src`, `scripts` **and `tests`** (27 files).

### Pending ratification — do not treat this slice as DONE until these are ruled on

1. **The TTL sweep now pops BEFORE closing**, not after. S3-Q4's prose describes
   close-then-pop ("the dict can be mutated ... across that await"), but Seam
   8(c) asserts "no session is closed twice" — and those cannot both hold: two
   overlapping sweeps each snapshot the same entry and each await its `close()`.
   Verified by test, not reasoned about. Pop-before-close satisfies both, and is
   strictly better in two further ways: an entry adopted across the await is now
   never closed at all (shrinking W-3), and a `close()` that raises no longer
   leaves its entry in the dict forever. One line; reverts in one line.
2. **Seam 15's prescribed technique does not work, and was replaced.** The
   artifact says two concurrent calls in *reversed* connect order defeat
   `registry.popitem()`. It does not: `popitem()` is LIFO, so reversed order is
   exactly the order it gets right. **The mutation survived** the two-call
   version. Replaced with three calls in a rotated connect order (register one,
   two, three; connect three, one, two), which kills it on the second connect.
   The ids' assertions are unchanged — each record still traces to its own
   session; only the arrangement that makes them discriminating changed.
3. **`hook-checks/` is excluded from `ruff` and `mypy`.** It arrived in the
   outside commit `7343c06 .claude upgrade` carrying **41 ruff and 23 mypy
   findings**, none of them in `src`/`scripts`/`tests`, and it blocked the Stop
   hook — which runs bare `ruff check .` / `mypy .` — on code no slice wrote.
   `pyproject.toml` already excludes `.claude/` for this exact reason, in the
   same rule codes (`PLW1510`, `BLE001`), with the rationale written in the
   file; this extends that precedent one directory. Excluded rather than fixed
   because `hook-checks/` is the test suite for the hooks that audit this
   agent's own work, which is Article 7 territory and the owner's to change.
   One line reverses it.
4. **`POST /voice` now declares `CallSid` and `From` as required form fields**
   (`Form(alias=...)`), so a malformed webhook is a 422. Seam 17(a)'s ratified
   technique depends on that 422, and the permissive read it replaced would have
   registered a session under the empty string — where two malformed webhooks
   collide on one key and the second closes the first.

### Decided alone (one line each, overrule if wrong)

- **`BridgeSession` is monkeypatched in tests, not injected.** `create_app`'s
  parameter list is ratified; adding a `bridge_factory` only so tests can reach
  in would widen a ratified seam for test convenience. Seam 9 uses the real one.
- **Seam 3(f)'s drain-stop is observed via the sender's public `closed` flag**,
  read by the fake bridge inside its `close()`. That flag *is* the drain-stop, so
  the ordered list gets a real fourth entry without the server reporting on
  itself.
- **`build_on_call_end()` lives in `server.py`, not `__main__.py`**, keeping
  `__main__` wiring-only. It is the function S5 replaces.
- **The smoke synthesises its caller audio** instead of reading a WAV, because
  the repo ships no WAV fixture. Twilio's wire shape is preserved (100 frames,
  160 bytes, 20 ms cadence) and no assertion depends on intelligible caller
  speech — the transcript assertion rides on the model's own greeting turn.

### The A3 number, recorded and NOT gated

**`start` → first outbound frame = 3128 ms**, the first end-to-end measurement of
the latency this feature is judged on. Not asserted against a threshold: A3 is
ratified as measured on a real PSTN call with the disclosure playing, so gating
a local proxy would invent a threshold the feature never ratified.

What it implies, stated so S6/S7 can check it rather than rediscover it. Gemini
needed **~3.2 s from session open to first audio** (3128 ms measured from a WS
`start` sent ~50 ms after a 559 ms webhook), which is consistent with S2's
3229 ms. The disclosure is **36 words ≈ 13–15 s of `<Say>`** at 140–165 wpm. Since
S3-Q1 opens the session in `POST /voice`, the whole connect+greeting cost is
generated *while the disclosure plays*, with roughly **10 s of margin** — so the
greeting should already be buffered in S2's `_inbox` when the socket opens, and
the post-`<Say>` gap should be near zero rather than near the ≤1500 ms limit.

**This is an estimate, not a measurement.** The 13–15 s is a wpm calculation, not
Twilio TTS timed on a real call, and the margin is only as good as that rate.
The tracer measures it for real. If the disclosure is ever shortened, this margin
is what shrinks — W-1's named fallback (a pre-rendered disclosure streamed while
Gemini connects) is the answer if it goes negative.

Side effect of the margin, already accepted as W-2: a fully-buffered greeting
bursts on adoption. The smoke saw 93 frames arrive in one flush, which is the
expected shape of S3-Q3, not a defect.

### Surprises

- **The toolchain was gone at session start.** No `uv`, no Python 3.13, no venv,
  no uv cache — on a repo whose last three commits were made with them hours
  earlier. `brew install uv` + `uv sync` restored it. Worth knowing that a green
  suite in `PROGRESS.md` is not evidence the next session can run one.
- **A ratified seam's own technique was wrong, and only mutation found it.** Seam
  15 is the slice's most consequential seam by its own account — a silent
  cross-call transcript swap is a data-protection incident, not an outage — and
  its prescribed two-call reversed order is precisely the order the wrong
  implementation reproduces. Ten critic rounds and a cold read did not catch it;
  a mutation run did, in one line of output. This is the third slice in a row
  where the artifact's weakest point was an enumeration or arrangement that
  *looked* thorough.
- **Two ratified statements contradicted each other** (item 1 above). Neither is
  wrong in isolation; they cannot both hold under concurrency. Found by writing
  the test the artifact asked for and watching it fail for a reason the artifact
  did not predict.
- **The teardown lock is weaker evidence than the artifact implies.** Seam 3(e)
  says a `done` flag without a lock is the defect. In a single-threaded event
  loop, a check-then-set with no `await` between them is already atomic, so the
  flag alone would pass S3.a and S3.b. The lock is still correct — it guards the
  awaits *inside* teardown — but "raced stop + disconnect" does not discriminate
  flag-only from flag-plus-lock. Stated rather than claimed as proof.
- **`asyncio.Task` cancellation is load-bearing in teardown, not tidiness.**
  `_teardown` holds the lock for its whole body and is reachable *from* both the
  pump and the drain, so awaiting either to finish naturally deadlocks against a
  task parked on that same lock. Cancel-and-await, plus a `current_task()`
  self-check, is what makes it terminate.
- Two commits (`34f3fd1 stage`, `7343c06 .claude upgrade`) landed from outside
  this session while the slice was in flight. Nothing was lost.

### Open for the next slice

- **S6 inherits W-1 concretely.** `Settings.profiles_root` resolves
  `<repo root>/profiles` from `decana.__file__`, which assumes an editable
  install. A non-editable Docker image **must** set `DECANA_PROFILES_ROOT`, and
  `docs/deploy.md` must say so.
- **`PORT` is honoured** (`Settings.port`, default 8080) so Cloud Run's injected
  value works without a Dockerfile flag.
- **The A3 proxy now has a number (3128 ms) and ~10 s of headroom** — see above.
  The tracer replaces the estimated half of that with a measurement.
- **`msg.data` logs `non-data parts in the response: ['text', 'thought']`** on a
  real session, exactly as S2 recorded. Harmless here for the same reason —
  transcripts come from `output_transcription`, not `model_turn` text parts.
- **P2's wire half is still ASSUMED.** Whether `customParameters` values arrive
  as strings, whether `sequenceNumber` is contiguous, whether `mark` is echoed —
  none is checkable without a real call, and there is no SDK source to read.
  Falsified or confirmed by the tracer.

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
