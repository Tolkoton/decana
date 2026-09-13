# Slice dispatch — planning artifact

Feature `vertical-profile-bridge`, slice S5. Ratified contract: "Edge S5 <- S3, S4" in
`.claude/architecture/feature/vertical-profile-bridge.md`.

Planned 2026-09-12. Converged after **9 critic rounds on Phase 2, 5 on Phase 3, 6 on Phase 4,
4 on Phase 5**, two owner escalations, and a cold read. Every round found a real defect; the
count is recorded because five of them were INCOMPLETE REPAIRS — a fix that left a stale
sibling site — which is this artifact's dominant failure mode and the reason the mutation
table is indexed by id rather than by seam.

## Goal

Turn one finished call into operator-visible output. S3 hands a `CallRecord` to an injected
`on_call_end`; S5 supplies the real one — analyse the transcript (S4), write the evidence
files, send at most one SMS to the caller, send one email to the operator, and write a brief.

**Measurable target:** given a `CallRecord` and a fake sender pair, the ratified file set
appears in `artifact_dir` in the ratified order, the brief states the SMS and email outcomes,
and `scripts/check_ids.py` reports `dispatch OK` with all 54 ratified ids covered in both
directions.

## Premise verified

Spike: `.claude/artifacts/spikes/dispatch-sdk-surfaces-2026-09-12.json` — 2026-09-12,
offline (no network, no credentials). `twilio` was **not a dependency at all** before this
slice; `uv add twilio` -> 9.11.1.

| id | premise | verdict | evidence |
|---|---|---|---|
| P1 | `twilio.rest.Client(sid, token).messages.create(to=, from_=, body=)` exists and returns `MessageInstance` | CONFIRMED | `inspect.signature`; return annotation |
| P2 | `MessageInstance.sid` is `str`, as the ratified contract types `SmsSender.send -> str` | **FALSIFIED** | SDK source `message/__init__.py:119` — `self.sid: Optional[str] = payload.get("sid")`. Set in `__init__` from the payload, so absent from `dir(MessageInstance)` and `None`-able at runtime. Adapter must narrow (Q2, Seam 9) |
| P3 | `twilio` is importable under this repo's ratified `mypy --strict` | **FALSIFIED** | No `py.typed`. `mypy --strict` gives TWO errors: `import-untyped` AND `no-any-return`. `ignore_missing_imports` alone fixes only the first — the value stays `Any`. Fix verified: scoped override + `isinstance` narrowing -> clean (Q1) |
| P4 | top-level `twilio` does not collide with the local `src/decana/twilio/` | CONFIRMED | `find_spec` on both; distinct origins |
| P5 | `Path.open("x")` is create-or-fail, usable as the at-most-once marker | CONFIRMED | second open raises `FileExistsError` |
| P6 | `smtplib` offers `SMTP_SSL` (465) and `SMTP`+`starttls`, `send_message` | CONFIRMED (**surfaces only**) | `hasattr`; `SMTP_SSL_PORT == 465`. **The real-server half is UNVERIFIED and PARKED** on `SMTP_*` |

**Parked on credentials, named as the unblocker** (`.env` is hard-denied to the agent;
`scripts/supervise.sh` or the owner must export):
- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` — the network half of P1, and the only check
  that P2's narrowing is right about a REAL response rather than a constructed one.
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` — the network half
  of P6. Until it runs, `SmtpEmailSender` is verified only by a fake it implements, which
  this project has recorded as no evidence at all.

## Out of scope (deliberately)

- **Retry / backoff on a failed send** — ratified scope is one attempt each; a retry also
  collides with Q4's at-most-once marker and needs its own ruling.
- **Any queue or scheduler** — `post_call` runs inline on S3's teardown path.
- **Cloud/DB storage of transcripts** — cut at feature level ("What is NOT a slice").
- **HTML email / attachments** — the brief points at the transcript rather than replacing it.
- **More than one SMS per call** — the at-most-once marker is the mechanism (Q4, owner-ratified).
- **Changing S3's socket or teardown code** — S5 REMOVES `build_on_call_end` from
  `server.py` (it moves to `dispatch/wiring.py`, Q24) and touches nothing else there. The
  socket, the event pump and `_teardown` are untouched. Full touched-file list: Q24.
- **Real network verification of Twilio/SMTP** — parked, above. Tier 1 of the smoke runs
  credential-free against the real filesystem; tiers 2 and 3 park.

## Seam (contract)

```python
# src/decana/dispatch/model.py
@dataclass(frozen=True)
class StageOutcome:
    status: Literal["ok", "skipped", "failed"]   # THE discriminant -- never parse `detail`
    detail: str
    # detail by status (Q19). One type for all five stages, not just the two senders:
    #   ok      + sms    -> the message sid
    #   ok      + others -> ""            (the status IS the outcome)
    #   skipped          -> "<why>"       (sms ONLY -- no other stage is ever skipped)
    #   failed           -> "<ExceptionType>: <msg>"

@dataclass(frozen=True)
class DispatchReport:
    transcript_path: Path
    brief_path: Path
    sms_sid: str | None          # set ONLY on a real send; None for all four not-sent causes
    # no analysis_path: Edge S7 "what it reads" lists .jsonl/.transcript.txt/.brief.md only.
    # analysis.json is written for a human debugging a bad outcome, not consumed by S7.
    email_sent: bool             # == (email outcome.status == "ok"), asserted by D23.a.
                                 # Named by the ratified DispatchReport, so it stays.
    errors: tuple[str, ...]      # one "<stage>: <ExceptionType>: <msg>" per FAILED effect.
                                 # stage in {"transcript","analysis","sms","email","brief"} -- ALL FIVE (Q10).
                                 # A deliberate skip is NOT an error.

# src/decana/dispatch/brief.py
def render_brief(record: CallRecord, analysis: Analysis, profile: Profile, *,
                 transcript: StageOutcome, analysis_file: StageOutcome,
                 sms: StageOutcome, email: StageOutcome | None) -> str
    # email=None  -> the email-outcome line is OMITTED; this exact string is the email body
    # email=<oc>  -> the full brief, written last
    # transcript/analysis_file are ALWAYS known before the email is sent, so they render
    # identically in both -- which is what keeps the difference at exactly one line (Q19).

# src/decana/dispatch/senders.py
class SmsSender(Protocol):
    def send(self, *, to: str, sender_id: str, body: str) -> str: ...   # returns message sid
class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...

class TwilioSmsSender:
    def __init__(self, account_sid: str, auth_token: str) -> None: ...
    def send(self, *, to: str, sender_id: str, body: str) -> str: ...
class SmtpEmailSender:
    def __init__(self, host: str, port: int, user: str, password: str, from_addr: str) -> None: ...
    def send(self, *, to: str, subject: str, body: str) -> None: ...

# src/decana/dispatch/dispatch.py
async def dispatch(record: CallRecord, analysis: Analysis, profile: Profile, *,
                   sms: SmsSender, email: EmailSender, artifact_dir: Path) -> DispatchReport
async def post_call(record: CallRecord, *, profile: Profile, analysis_client: AnalysisClient,
                    sms: SmsSender, email: EmailSender, artifact_dir: Path) -> None

# src/decana/dispatch/errors.py
class DispatchError(RuntimeError): ...
    # ONE class, three raisers: a sid-less Twilio response (Q2), and each Unconfigured sender.

# src/decana/dispatch/senders.py — the credential-absent pair (Q23)
class UnconfiguredSmsSender:     # satisfies SmsSender
    def send(self, **_: object) -> str:   # raises DispatchError("no Twilio credentials configured")
class UnconfiguredEmailSender:   # satisfies EmailSender
    def send(self, **_: object) -> None:  # raises DispatchError("no SMTP credentials configured")

# src/decana/dispatch/wiring.py — MOVED here from twilio/server.py, see Q24
def build_on_call_end(settings: Settings, profile: Profile) -> OnCallEnd
```

- **Errors:** `dispatch` never raises for ANY of the five effects; each failure lands in
  `errors` as `"<stage>: <ExceptionType>: <msg>"` (Q10, owner-ratified). `post_call` never
  raises either (Q17), but must not swallow `CancelledError`.
- **Dependencies (injected):** `sms`, `email`, `analysis_client`, `artifact_dir`, `profile`.
  Nothing reads the environment; that is the composition root's job.
- **Does NOT do:** retry, queue, schedule, cloud storage, HTML email, >1 SMS per call.

### Ordering (ratified guarantee (a)+(b))
1. `{call_sid}.transcript.txt`
2. `{call_sid}.analysis.json` (= `analysis.raw`)
3. SMS (conditional) — marker `{call_sid}.sms-sent` created FIRST
4. email (always attempted) — body = `render_brief(..., email=None)`
5. `{call_sid}.brief.md` = `render_brief(..., email=<outcome>)` — LAST

## Decisions (with WHY)

- **Q1: `twilio` gets a narrowly-scoped `[[tool.mypy.overrides]]`; the adapter narrows explicitly.**
  twilio 9.11.1 ships no `py.typed` (spike P3), so `mypy --strict` emits BOTH
  `import-untyped` and `no-any-return`; `ignore_missing_imports` alone fixes only the
  first, because the value stays `Any`. Chosen because `pyproject.toml:63-68` already
  does exactly this, scoped, for `soxr`, rationale in-comment — this extends a ratified
  precedent by one module.
  *Rejected: global `ignore_missing_imports`.* Best case for it: one line, and never
  breaks again on a new untyped dep. Rejected because that is precisely the property the
  soxr comment calls out as unwanted — it would silently un-type every future dependency.
  *Rejected: hand-written stubs.* Best case: real types, no `Any` at the boundary.
  Rejected because stubs for a 9.x SDK rot silently against the next `uv sync`, and
  nothing in CI would notice.

- **Q2: `TwilioSmsSender.send` raises when the SDK returns no sid.** `MessageInstance.sid`
  is `Optional[str]` (spike P2, SDK source `message/__init__.py:119`), but the ratified
  Protocol is `-> str`. The raise is caught by `dispatch`'s per-effect wrapper and lands
  in `errors`, so a sid-less send is *reported* rather than silently recorded as
  `sms_sid=None` — the same value that means "deliberately not sent". Conflating those
  two would make the brief lie to the operator.
  *Rejected: widen the Protocol to `-> str | None`.* Best case: honest about the SDK.
  Rejected because it changes ratified feature-contract text and pushes the same
  ambiguity into every call site.
  *Rejected: return `""`.* Best case: total, no exception. Rejected because a falsy sid
  reads as "not sent" everywhere it is used.

- **Q3: SMTP transport chosen by port — 465 → `SMTP_SSL`, else `SMTP` + `starttls()`.**
  Needs no new config key. Rests on the VERIFIED half: the stdlib pins
  `SMTP_SSL_PORT = 465` (spike P6). The "465 is implicit-TLS everywhere" half is ASSUMED,
  not measured — falsified by any provider this is pointed at that wants STARTTLS on 465,
  which S6's deploy doc is where it would surface.
  *Rejected: an `SMTP_TLS_MODE` variable.* Best case: explicit, no inference. Rejected
  because it is a fourth SMTP variable for a value derivable from the third, and one more
  thing S6's deploy doc must get right.
  *Rejected: always STARTTLS.* Best case: one code path. Rejected because it fails closed
  against a 465-only provider with a confusing timeout rather than an auth error.

- **Q4: the SMS marker is created with `Path.open("x")` BEFORE the send. OWNER-RATIFIED 2026-09-12.**
  At-most-once. `open("x")` is create-or-fail (spike P5), so two concurrent dispatches for
  one CallSid cannot both pass the guard. A crash between marker and send yields zero SMS,
  never two; the miss is visible because both the email (step 4) and the brief (step 5)
  carry the SMS outcome.
  *Rejected (by the owner, explicitly): send-then-mark.* Best case: the message always
  goes out. Rejected because its failure mode is a duplicate SMS to a real prospect,
  which cannot be recalled.

- **Q5: the real senders are sync and are awaited via `asyncio.to_thread`.** `smtplib` and
  `twilio.rest` both block, and `post_call` runs on the event loop that is forwarding audio
  for every other live call; a blocking `sendmail` is dead air on a stranger's call. This
  is the `analysis` slice's recorded failure (sync/async facades interchangeable to mypy,
  not to the loop) in its second form.
  *Rejected: an async SMTP/HTTP client.* Best case: no thread pool. Rejected because it is
  a new dependency for a once-per-call effect that is not on the latency-critical path.

- **Q6: `dispatch` does `artifact_dir.mkdir(parents=True, exist_ok=True)` before writing.**
  S3 normally created it already, but `dispatch` is independently callable (tests, smoke),
  and an evidence-first contract that dies on a missing directory writes no evidence at all.

- **Q7: each of the FIVE effects is wrapped in its OWN `try/except Exception`** — transcript,
  analysis, SMS, email, brief (guarantee (d) as amended by Q10-A; this Q was originally
  written when the wrap spanned only SMS and email). A shared wrapper would let an SMS
  failure skip the email — the one output the operator always gets — and, after Q10-A, would
  let a transcript-write failure skip everything.

- **Q8: ONE `render_brief`, called twice, with `email: StageOutcome | None`.** The ratified
  text says the email body is "the same brief text minus the email-outcome line", and the
  email is sent at step 4, before its own outcome exists. Passing `email=None` omits that
  one line, so the email body and the final brief are the *same function of the same
  inputs* and cannot drift. `render_brief` is pure, so the operator-facing text is
  assertable without touching the filesystem.
  *Rejected: two functions (`render_email_body` + `render_brief`).* Best case: each reads
  straightforwardly, no flag parameter. Rejected because it makes "the same text minus one
  line" a discipline rather than a mechanism — two bodies restating the same content is
  the transcription failure this project has already recorded (three assertions died that
  way in `twilio-server`), and nothing would fail if they diverged.
  *Rejected: render the full brief, then string-slice the email line out.* Best case: one
  call. Rejected because it makes the email body depend on matching a formatted line by
  content — a silent break the first time the brief's wording changes.

- **Q9: `Settings` gains `twilio_account_sid`, `twilio_auth_token`, `smtp_host`, `smtp_port`,
  `smtp_user`, `smtp_password`, `smtp_from`, all optional-until-present**; **The predicate over those seven fields is Q23's, not a single `all(...)` gate** —
  and Q9's original "returns log-only when they are absent" is superseded there. Ratified: "so the tracer build never requires secrets it does not use" — a
  credential-less run still starts and still records calls.

- **Q10 (OWNER-RATIFIED 2026-09-12): ALL FIVE effects are wrapped independently — the three file writes as well as SMS
  and email — and `dispatch` does not raise for any of them.** Evidence-first is preserved
  as an *ordering* property: transcript and analysis.json are still attempted before any
  network effect, which is what ratified guarantee (a) actually requires. What changes is
  what happens when one fails.
  **Correction — the earlier justification for this misquoted ratified text.** Guarantee (d)
  reads in full: "each of SMS/email is wrapped independently; failures land in `errors`,
  nothing raises". "Nothing raises" is the TAIL OF A CLAUSE SCOPED TO SMS/EMAIL, not a
  standalone universal promise, and an earlier draft of this decision quoted the tail alone
  to justify widening the wrapping to five effects. That argument is withdrawn.
  What (d) actually does is say nothing either way about the file writes: it is silent on
  them, so whether it is a FLOOR (these two must be wrapped) or a CEILING (only these two
  may be wrapped) is genuinely undetermined by the ratified text. This was escalated as
  ratified artifact text and **OWNER-RATIFIED 2026-09-12 as Q10-A**; guarantee (d) in
  `vertical-profile-bridge.md` is amended to name all five effects, so the feature doc no
  longer under-describes what `dispatch` does.
  The argument that survives the correction rests on Q14, not on (d): a failed
  transcript write would abort before the email and take the operator's only notification
  channel with it. The failure mode is the worst available: a real call happened, the
  operator is never told, and the single record is a log line on a Cloud Run instance
  nobody is reading. Wrapping the writes instead turns a disk failure into an email that
  *says* the transcript could not be written.
  **Q10-A (recommended): wrap all five.** **Q10-B: the literal reading — file writes raise.**
  *Q10-B steelmanned, since it is the literal ratified reading.* Best case: the
  strongest possible reading of evidence-first — if we cannot record the call, do nothing
  else. Rejected because "do nothing else" includes "do not tell anyone", and the brief
  and email are the only things a human ever sees.
  *Rejected: raise only if BOTH evidence writes fail.* Best case: keeps a hard floor under
  guarantee (a). Rejected because it makes the abort condition depend on a partial
  failure combination that no test would naturally cover, for no operator-visible gain
  over reporting both in `errors`.

- **Q11: the SMS is gated by THREE independent suppressions, each with its own reason string.**
  `analysis.outcome in profile.sms`; `record.caller_number` non-empty; no marker present.
  Each produces a distinct `StageOutcome(status="skipped", detail="<why>")` — `detail` carries
  the bare reason and NO prefix, because `status` is the discriminant (Q19). The brief renders
  it as `- SMS: not sent — <detail>`, so a prefix here would read
  "not sent — skipped: ...". `sms_sid` stays `None` for all three.
  *Rejected: treat an empty `caller_number` as an error.* Best case: a withheld number is
  visible in `errors` rather than passing quietly. Rejected because S3 documents that
  Twilio sends withheld caller IDs as `"anonymous"`/`"+266696687"` and normalises them to
  `""` — a withheld number is an ordinary, expected call, not a fault, and putting it in
  `errors` would train the operator to ignore that field.

- **Q12: a send failure AFTER the marker is recorded in all three places** — `errors`, the
  brief, and the email body. That call gets zero SMS by design (Q4); the operator finds out
  because the email arrives at step 4 carrying the SMS outcome, and the brief repeats it.

- **Q13: the SMS body is `template.text.format(**template.links)`**, per ratified text. S1
  already guarantees every `{placeholder}` in `text` has a matching `links` key and rejects
  positional/attribute/index placeholders, so this cannot raise `KeyError`/`IndexError` on a
  loaded profile — but it is still inside Q7's wrapper, because the guarantee belongs to S1
  and S5 must not assume it silently.

- **Q14: the email is ALWAYS attempted**, to `profile.operator_email`, regardless of outcome,
  of whether an SMS went out, or of whether the transcript is empty. It is the only output
  the operator is guaranteed to receive.

- **Q15: the subject is `f"[{profile.display_name}] {analysis.outcome} — {record.caller_number}"`.**
  Ratified verbatim, including `display_name` (not `name` — amended by profile-loader Q12)
  and the em dash.

- **Q16: `sms_sid` is set ONLY on a real send.** Its `None` has four causes (three Q11 skips
  plus a failure); `errors` and the brief's SMS line are what distinguish them. `errors`
  records failures only — a deliberate skip is not an error.

- **Q17: `post_call` wraps its whole body in `try/except Exception` and logs.** Guarantee (e).
  Under Q10 `dispatch` no longer raises for any of the five effects, and `analyse` never
  raises (S4) — so this catch guards only what is genuinely outside them: a failure of
  `artifact_dir.mkdir` (Q6, which runs before any stage), and anything future.
  **A bug in `render_brief` is NOT in this residual set** — Q18 places both of its call
  sites inside their own stage's wrapper, because `render_brief` is how the email and brief
  stages produce their content, and Q10-A commits `dispatch` to not raising for either.
  (An earlier revision of this Q listed `render_brief` here; that was written against the
  pre-amendment two-effect split and did not survive Q10-A.) It must NOT
  swallow `asyncio.CancelledError`: `post_call` runs inside S3's teardown path, and S4
  already established that catching `BaseException` there costs the ability to cancel at
  all (`except Exception`, never bare).
  S3's guarantee (b) then becomes a second line of defence that never fires in normal
  operation, which is what the ratified text says it should be.

- **Q18: the stage boundary INCLUDES content production, not just the I/O call.** Each of the
  five wrappers opens before the work that produces the thing and closes after the effect:
  - `transcript` — rendering the turn list AND writing the file;
  - `analysis` — writing `analysis.raw`;
  - `sms` — the gate checks, the marker create, `template.text.format(...)`, and the send;
  - `email` — `render_brief(..., email=None)` AND the send;
  - `brief` — `render_brief(..., email=<outcome>)` AND the write.
  So a `render_brief` bug raised while building the email body is an `email:` entry in
  `errors` and the email is not sent; the same bug raised while building the final file is a
  `brief:` entry and the file is not written. Two call sites, two distinct stages, two
  distinct assertions — which is what lets a test pin down which one broke.
  *Rejected: wrap only the I/O call, produce content outside.* Best case: the wrapper reads
  narrowly and every `errors` entry is unambiguously an I/O fault. Rejected because it puts
  `render_brief` back outside all five stages, which is precisely what Q10-A ratified
  against — `dispatch` would raise while composing the brief, and the operator would get
  the silence the amendment exists to prevent.

- **Q19: `StageOutcome` carries a STRUCTURAL `status`, covers ALL FIVE stages, and the
  brief's fixed lines are ratified here rather than invented at implementation time.**
  **`status` is the discriminant. `render_brief` branches on it and NEVER on `detail`'s text.**
  An earlier revision encoded skip-vs-fail as a `"skipped: "` / `"failed: "` prefix inside
  `detail`, which would have made the operator-facing wording depend on a string convention
  shared across two modules and enforced by nothing — the "two representations that can
  silently diverge" failure Q8 rejects, reintroduced one decision later.
  **The type spans all five stages, not just the two senders.** An earlier revision passed
  only `sms` and `email` to `render_brief` — which meant a failed transcript or analysis
  write had NO channel to the operator at all, and the email for a disk failure would have
  been byte-identical to full success. That is precisely the silence Q10-A was escalated and
  owner-ratified to prevent, so the mechanism was widened rather than the claim narrowed.
  The lines, verbatim — operator-facing text, one per stage, `<detail>` interpolated:
  ```
  - Transcript file: written
  - Transcript file: FAILED — <detail>
  - Analysis file: written
  - Analysis file: FAILED — <detail>
  - SMS: sent (<detail>)
  - SMS: not sent — <detail>
  - SMS: FAILED — <detail>
  - Email: sent to <operator_email>
  - Email: FAILED — <detail>
  ```
  The **`Email:` line is the one and only line omitted when `email=None`** (Q8). The
  transcript and analysis lines are known before the email is sent, so they render
  identically in both — which is what keeps "the email body is the brief minus the
  email-outcome line" a difference of exactly one line, and what Seam 3 asserts.
  **The `brief` stage has no line of its own**, deliberately: a brief that failed to write
  cannot report its own failure, and the email has already gone by then. That failure is
  visible only in `DispatchReport.errors` and the log — stated here so it is a known limit
  rather than a discovered one.
  *Rejected: a free-form "problems" list rendering `DispatchReport.errors`.* Best case: one
  line of code, covers every stage including future ones. Rejected because the email-stage
  error would then appear in the brief's list AND in the `Email:` line, making the brief
  differ from the email body by TWO lines and destroying Seam 3's mechanical property.
  *Rejected: a separate `EmailOutcome` type.* Best case: no impossible states. Rejected
  because `render_brief` would take several unrelated types for one job, and the impossible
  state it removes (`email` + `"skipped"`) is not one any code path constructs (Q14).
  *Rejected: keeping `ok: bool` alongside `status`.* Rejected as two sources of truth for
  one fact; `ok` is exactly `status == "ok"`.

- **Q21: the brief renders the CALL, not just the dispatch. The content block is ratified here.**
  Q19 fixed nine status lines and nothing else, which meant the operator's email would have
  read "Transcript file: written. SMS: sent." and never said what the caller wanted. That is
  not a wording gap: `Analysis.summary` is ratified in the feature contract
  (`vertical-profile-bridge.md`) with the comment **"for the brief"**, and
  `compliance_notes` is the feature's ONLY post-call compliance channel — the design
  explicitly rejects mid-call intervention in its favour. Both had zero decisions, zero seams
  and zero ids until the cold read.
  The brief is, verbatim and in this order:
  ```
  # Call brief — <call_sid>

  Caller:  <caller_number, or "withheld" when empty>
  When:    <started_at> – <ended_at> (UTC)
  Profile: <profile.display_name>
  Ended:   <ended_reason>

  ## Outcome
  <analysis.outcome>

  ## Summary
  <analysis.summary>

  ## Compliance notes
  - <note>            one line per note, in order
  none                the literal, when compliance_notes is empty

  ## Transcript
  <n> turns — full text in <call_sid>.transcript.txt

  ## Dispatch
  - Transcript file: ...
  - Analysis file: ...
  - SMS: ...
  - Email: ...            <- LAST LINE; the one omitted when email=None
  ```
  **The `Email:` line is last**, which is what keeps Q8's "the email body is the brief minus
  exactly one line" a trailing-line removal rather than a splice.
  *Rejected: point at the transcript and omit the summary.* Best case: the brief cannot be
  wrong about the call, because it says nothing about it. Rejected because the ratified
  contract annotates `summary` "for the brief", and an operator who must open a transcript
  to learn what a call was about has not been given operator-visible output.
  *Rejected: render `compliance_notes` only when non-empty.* Best case: a shorter brief on the
  ordinary call. Rejected because "no compliance notes section" and "a compliance section that
  says none" are indistinguishable to an operator scanning for risk — and the first is also
  what a DROPPED `compliance_notes` looks like.

- **Q22: `transcript.txt` is `render_transcript`'s output, reused — not a second renderer — and
  every text file is written `encoding="utf-8"` explicitly.**
  The file's CONTENT was undecided until the third cold read: Q18 said only "rendering the turn
  list AND writing the file", which never says what the bytes are. `str(record.transcript)` — a
  Python tuple repr — satisfied every id in this artifact and ships unreadable noise to the human
  S7 asks to read it out. Edge S7 names this file as one of exactly three a human reads per call,
  and Q21's brief points the operator straight at it.
  `decana.analysis.analyse.render_transcript` already produces the ratified `CALLER: …` /
  `MODEL: …` lines (S4-Q2, and the feature contract pins that shape). S5 reuses it.
  **Scope note:** `render_transcript` is not in `analyse.py`'s `__all__` today, so this slice
  adds it there. That is an export widening with no behaviour change. **Q24 carries the single
  authoritative touched-file list** — do not maintain a second one here; an earlier revision of
  this note did, and went stale the moment Q24 moved `build_on_call_end` into
  `src/decana/dispatch/`.
  *Rejected: S5 defines its own renderer.* Best case: no edit to another slice's module, and S5
  owns a format tuned for a human rather than for a prompt. Rejected because two renderers of
  the same turn list is the divergence Q8 already rejects, and the operator-facing file would
  then silently differ from what the model was actually shown — which is the first thing anyone
  debugging a bad outcome compares.
  **Encoding:** `Path.write_text` defaults to the locale encoding. A caller name like "Siobhán"
  in a transcript is ordinary on this line, and on a non-UTF-8 locale a bare `write_text` either
  raises or mangles it — a per-environment failure that no test on a UTF-8 dev box would catch.
  All three text files pass `encoding="utf-8"` explicitly. `ruff`'s default rule set does not
  flag this (`pyproject.toml` configures no `select`), so nothing catches it automatically.

- **Q23: the two credential groups gate INDEPENDENTLY, and `build_on_call_end` no longer falls
  back to log-only at all.**
  Q9 said only "present" / "not present" over seven fields, and Seam 15 tested just the two
  extremes. The obvious implementation of that prose is `if all(seven): real else: log_only` —
  under which **a missing or rotated-out Twilio credential silently disables the operator's
  email**, which has nothing to do with Twilio. That contradicts Q14 and ratified guarantee (c),
  and partial states are not hypothetical: this artifact's own smoke parks Tier 2 on the SMTP
  five and Tier 3 on the Twilio two independently, because secrets land in Secret Manager one
  at a time.
  The predicate:
  - **SMS** is wired iff `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` are both present.
  - **Email** is wired iff all five `SMTP_*` are present.
  - **Neither gates the other, and neither gates `post_call`.** `GEMINI_API_KEY` is already
    required, so analysis, the two evidence files and the brief need no optional credential —
    they are written on every call regardless.
  A missing group yields a sender that raises `DispatchError("no Twilio credentials
  configured")` / `("no SMTP credentials configured")`. That records the stage as `failed` with
  that exact detail, in `errors` and in the brief — **not** as `skipped`, which preserves Q19's
  invariant that the email stage is never skipped, and is the honest label: the attempt could
  not be made. Note the SMS gate (Q11) runs first, so a call whose outcome has no template
  never reaches the raising sender and records an ordinary skip, not a spurious failure.
  *Rejected: one monolithic `all(seven)` gate.* Best case: one predicate, one branch, nothing to
  get subtly wrong, and "half-configured" arguably deserves to fail loudly rather than half-work.
  Rejected because the loud failure lands on the wrong service — the operator loses email
  because an SMS credential is missing — and because the half that still works is the half the
  ratified contract calls the guaranteed channel.
  *Rejected: keeping the log-only fallback for the no-credentials case.* Best case: a
  credential-less run behaves exactly as the tracer did, which is a known-good shape. Rejected
  because it throws away work that needs no credentials at all: the transcript, the analysis
  JSON and the brief would not be written, so a local or misconfigured run leaves no evidence
  of a real call — for no gain, since the senders already report their own absence.

- **Q24: `build_on_call_end` MOVES from `twilio/server.py` to `dispatch/wiring.py`, and
  `__main__.py`'s call site changes with it.**
  The cold read found the Seam block silent on this function even though Q23 makes it
  load-bearing. Pinning its signature exposed a harder conflict: under Q23 it must construct
  `post_call`, `GeminiAnalysisClient` and the two senders — so leaving it in `server.py` makes
  **S3 import S4 and S5**, which the ratified Edge S3 text forbids in terms
  (`"S3 does not import S4/S5 — same DI convention as TwilioMediaStreamClient/…"`). Verified:
  `server.py` imports nothing from `analysis` or `dispatch` today.
  The competing statement is S3's own "`build_on_call_end()` lives in `server.py`, not
  `__main__.py`", which `PROGRESS.md` records under **"Decided alone (one line each, overrule
  if wrong)"** — explicitly overrulable, and the weaker of the two. So the function moves to
  S5, whose job the wiring now is. `server.py` keeps nothing of it; `__main__.py` imports from
  `decana.dispatch.wiring` and stays wiring-only, which is what that decision was protecting.
  **Signature change:** `build_on_call_end()` -> `build_on_call_end(settings, profile)`.
  `__main__.py:35` currently calls it with ZERO arguments and cannot compile against any
  signature this plan implies.
  *Rejected: keep it in `server.py` and let S3 import S5.* Best case: no file moves, and the
  import is only in a factory the socket code never calls. Rejected because the ratified
  convention is what keeps S3 independently testable with fakes, and "only one import" is how
  that erodes.
  *Rejected: put the wiring in `__main__.py`.* Best case: the composition root does composition,
  and nothing moves between slices. Rejected because `__main__` is ratified as wiring-only with
  no logic, and the credential branching in Q23 is logic that needs tests (`D15.a`, `D15.c`-`e`)
  — tests that would then have to drive `main()`.

  **Scope correction:** this slice therefore touches `src/decana/dispatch/*` (new),
  `src/decana/settings.py`, `src/decana/twilio/server.py` (remove `build_on_call_end`),
  `src/decana/__main__.py` (import + call site) and `analyse.py`'s `__all__` (Q22).
  `__main__.py` was named in neither the in-scope nor the out-of-scope list until now.

- **Q20: the marker check IS the atomic create, not a separate `exists()` pre-check.** Q11
  calls the marker one of three suppressions; it is discovered by `Path.open("x")` raising
  `FileExistsError`, which is the same operation that claims the marker. A separate
  `exists()` test followed by a create would be a time-of-check/time-of-use gap — two
  dispatches could both see "no marker" and both send, which is exactly the duplicate Q4 was
  ratified to make impossible. S3's guarantee (a) awaits `on_call_end` exactly once per call,
  so the race is not reachable in normal operation; the atomic form costs nothing and does not
  depend on that guarantee holding.

## Hardest seams (test-confidence points — distinct from the contract Seam above)

Each seam names the WRONG IMPLEMENTATION it must kill. A seam whose wrong
implementation passes the proposed test is not a seam, it is decoration.

- **Seam 1: `asyncio.to_thread` is invisible to every fast fake.**
  Wrong implementation: `sms.send(...)` / `email.send(...)` called directly on the loop.
  Every test using an instant fake passes identically — this is the `analysis` slice's
  recorded sync/async defect in its second form, and the fake is *actively reassuring*
  about the exact property that is broken.
  Test approach: a fake sender whose `send` blocks on a `threading.Event` until released.
  Run `dispatch` as a task alongside a sentinel coroutine that increments a counter every
  1 ms; release the event; assert the counter advanced **while the send was in flight**.
  Under a direct call the loop is blocked and the counter cannot advance.
  Rules out: "we proved `to_thread` by asserting the return value came back."

- **Seam 2: marker-before-send is invisible on the happy path.**
  Wrong implementation: send-then-mark (the alternative the owner explicitly rejected).
  Every success-path assertion — marker exists, sid returned — holds for BOTH orders.
  Test approach: a fake SMS sender that RAISES. Assert (i) the marker exists afterwards,
  (ii) a second `dispatch` for the same CallSid does **not** call `send` again, and (iii) that
  second dispatch STILL sends the email and writes the brief — a marker-suppressed call is
  the third skip branch, and Seam 4's wrong implementation B reaches it too.
  Under send-then-mark the marker is absent and the second dispatch re-sends — which is
  exactly the duplicate-to-a-prospect the owner ratified against.
  Rules out: asserting only "marker exists after a successful dispatch."

- **Seam 3: "email body = brief minus the email-outcome line" is a property, not a string.**
  Wrong implementation: two renderers (or a flag branch) whose texts drift. Nothing fails
  when they diverge; this is the transcription failure that silently killed three
  assertions in `twilio-server`.
  Test approach: assert `render_brief(..., email=None)` equals the full brief with
  **exactly one** line removed, by line-list difference — for BOTH a successful and a failed
  email outcome, AND with the transcript/analysis stages in both `ok` and `failed` states.
  That last combination is the one that matters: those two lines are rendered in both passes,
  so an implementation that derived them from post-email state would make the difference two
  lines instead of one.
  **Fixture requirement:** both cases pin `sms=StageOutcome(status="ok", detail="<sid>")`.
  `render_brief` picks one of three SMS templates by `status`, so a fixture built with
  `skipped` or `failed` would never render the `sent` line — and a mutation aimed at that
  line would then survive while reporting as applied.
  Rules out: asserting the email body merely "contains the same text". (This line once read
  "contains the summary", which reads as if it covered `Analysis.summary` — it never did.
  Seam 19 covers that; the ambiguity is one reason fifteen rounds passed over the gap.)

- **Seam 4: the three-way SMS gate is one test masquerading as three — and a SKIP must not
  end the dispatch.**
  Wrong implementation A: dropping any one conjunct — e.g. `if outcome in profile.sms and
  caller_number:` with the marker check gone. A single "no SMS was sent" test passes.
  **Wrong implementation B (the one no other seam reaches): `return` early on a skip.**
  ```python
  if analysis.outcome not in profile.sms:
      errors/outcome recorded...
      return DispatchReport(...)      # email and brief never happen
  ```
  A skip is a BRANCH, not an exception, so Seam 13's short-circuit family — which mutates an
  `except` body — never fires on it. Q14 says the email is attempted "regardless of outcome",
  and this silences the operator on every call whose outcome simply is not in `profile.sms`,
  or whose caller ID was withheld, or that is dispatched twice. It is Seam 13's wrong
  implementation B transplanted onto the skip path.
  Test approach: three ids, each satisfying the OTHER two conditions so it isolates one
  suppression, each asserting its own distinct `detail` reason string **AND that the email
  was still sent and the brief still written**. That last clause is what kills B; the reason
  string alone does not.
  Rules out: one test that suppresses on all three conditions at once, and any test that
  checks only why the SMS did not go.

- **Seam 5: evidence-first ordering is invisible when everything succeeds.**
  Wrong implementation: write the files after the network calls.
  Test approach: the fake senders assert **at call time** that `transcript.txt` and
  `analysis.json` already exist on disk; plus a test where both senders raise, asserting
  both files exist anyway.
  Rules out: asserting file existence at the end of `dispatch`, which both orders satisfy.

- **Seam 6: brief-last is invisible for the same reason.**
  Wrong implementation: write the brief before sending the email — which would make the
  email's own outcome unstatable, the thing the ratified ordering exists to permit.
  Test approach: the fake email sender records `brief_path.exists()` at call time — must
  be `False`; assert `True` after `dispatch` returns.
  Rules out: asserting only that the brief exists at the end, which a brief written FIRST
  satisfies equally well.

- **Seam 7: an assertion on a hardcoded `errors` value proves nothing.**
  Wrong implementation: `errors` hardcoded to `()`. Asserting `report.errors == ()` on the
  happy path passes for every implementation — the exact `compliance_notes` defect the
  cold read caught in `analysis`.
  Test approach: assert on the path where `errors` is **computed**, in BOTH directions —
  (i) SMS fails, assert exactly one entry naming stage `sms`, and the email was still sent;
  (ii) email fails, assert exactly one entry naming stage `email`, and the SMS still went.
  One direction alone leaves the other wrapper free to be missing.

- **Seam 8: a failed send and a deliberate skip must not render the same.**
  Wrong implementation: `render_brief` treats every non-`sent` SMS outcome as "not sent" —
  which is what an earlier draft of the contract invited, because it encoded the difference
  as a `"skipped: "` / `"failed: "` text prefix inside `detail` rather than as a field. A
  genuine send FAILURE then reads to the operator as a routine non-send, and nobody ever
  sends that message by hand.
  Test approach: assert the exact ratified line text per `status` — `- SMS: sent (<sid>)`,
  `- SMS: not sent — <why>`, `- SMS: FAILED — <ExcType>: <msg>` — and assert `render_brief`
  never branches on `detail`'s content by giving a *skipped* outcome a `detail` that begins
  with the literal text `"failed: "`; it must still render as "not sent".
  That last assertion is the one that kills the prefix-parsing implementation, and nothing
  else in the suite would. The `"failed: "`-prefixed skip detail is a **deliberately
  adversarial fixture**, not a realistic value — Q11's real skip reasons are plain strings;
  the fixture exists only to prove the renderer ignores `detail`'s text.
  Rules out: asserting only that the brief "mentions the SMS".

- **Seam 9: the twilio adapter's `Optional[str]` narrowing (premise P2, locked in).**
  Wrong implementation: `return msg.sid`. It type-checks only because the module is `Any`,
  and it returns `None` as a "sid" the brief then reports as success.
  Test approach: a fake twilio client whose `messages.create` returns an object with
  `sid=None`; assert `TwilioSmsSender.send` raises, and that `dispatch` converts it into
  one `errors` entry with `sms_sid is None`.
  Rules out: testing the adapter only against a well-formed response.

- **Seam 10: `post_call` must swallow what is LEFT, and must not swallow cancellation.**
  Wrong implementation A: no `try/except` in `post_call` — but under Q10 `dispatch` no
  longer raises for the five effects, so an ordinary test cannot reach this. The reachable
  raise is `artifact_dir.mkdir` itself (Q6) or a bug in `render_brief`.
  Wrong implementation B (the dangerous one): `except BaseException`. It passes every
  test above, satisfies "post_call never raises" literally, and silently costs S3's
  teardown the ability to cancel the task — the exact one-word defect recorded in the
  `analysis` slice.
  Test approach: (i) point `artifact_dir` at an existing *file* so `mkdir` raises; assert
  `post_call` returns `None` and logs. (ii) Cancel the `post_call` task while a fake
  sender is blocked; assert `CancelledError` **propagates** and the task ends cancelled.
  Rules out: proving "never raises" with a catch that is one word too wide.

- **Seam 11: SMTP transport selection by port.**
  Wrong implementation: always `SMTP_SSL` (or always STARTTLS) — works against whichever
  provider the smoke happens to use, fails against the other with a timeout.
  Test approach: monkeypatch both `smtplib.SMTP_SSL` and `smtplib.SMTP`; assert which
  class is constructed for port 465 vs 587, and that `starttls()` was called in the
  second case and not the first.
  Rules out: testing one port only — which passes for a hardcoded transport.

- **Seam 12: a failed EVIDENCE write must still produce an email (Q10's reversal).**
  Wrong implementation: file writes raise out of `dispatch` (the rejected earlier draft).
  Every happy-path test passes; the defect appears only on a disk failure, where it
  silences the operator's only channel — and a disk failure is exactly when someone needs
  to be told.
  Test approach: make the transcript write fail (`artifact_dir` holding a *directory* named
  `{call_sid}.transcript.txt`, so the open fails); assert (i) the email sender WAS called,
  (ii) `errors` contains one entry with stage `transcript`, (iii) `dispatch` returned a
  report rather than raising, (iv) the email body names the failure, and **(v)
  `brief_path.exists()` is True and the brief text names the transcript failure.**
  Rules out: asserting only that `dispatch` "handles" a write failure without checking that
  the downstream effects still ran — and specifically rules out the short-circuit
  implementation below, which (i)-(iv) alone do NOT kill.

- **Seam 13: `dispatch` never raises, AND never short-circuits, for any of the five effects.**
  Wrong implementation A: any one of the five left unwrapped — the incomplete repair
  recorded in `analysis` (a fix applied to four of five failure modes). Q10 is a
  five-member family, so it is the shape most at risk.
  **Wrong implementation B (the one that survives the obvious test): catch, record, and
  `return` early.**
  ```python
  except Exception as e:
      errors.append(f"{stage}: {type(e).__name__}: {e}")
      return DispatchReport(..., errors=tuple(errors))   # never reaches render_brief
  ```
  This satisfies "never raises" and "`errors` names the failing stage" for every stage,
  while silently dropping every downstream effect — including the brief, whose whole
  purpose under guarantee (a) is to be written unconditionally and LAST so the operator is
  never left silent. It is the exact failure Q10-A was escalated to prevent, reintroduced
  one level down.
  Test approach: five ids, one per stage, each making ONLY that stage fail and asserting
  **all** of: `dispatch` returned; `errors` names that stage and only that stage; **every
  LATER stage still ran** (its fake was called, or its file exists); and **`brief_path.exists()`
  is True** — for all five, including when the failing stage IS `brief` (where the
  assertion inverts: the file does not exist, and `errors` names `brief`).
  Then **count the family**: exactly five such nodes, one per stage, no sibling skipped.
  Rules out: a per-stage test that checks only `errors`, which wrong implementation B
  passes five times out of five.

- **Seam 14: the two `render_brief` call sites belong to DIFFERENT stages (Q18).**
  Wrong implementation: one `try` spanning both, so a bug composing the email body is
  reported as a `brief:` failure (or vice versa) and the operator is pointed at the wrong
  thing. Both call sites take the same arguments except `email=`, so the two are easy to
  conflate and nothing distinguishes them at runtime.
  Test approach: make `render_brief` raise on its FIRST call only; assert the entry is
  `email:` and the brief file still exists (the second call succeeded). Then make it raise
  on the SECOND call only; assert the entry is `brief:` and the email WAS sent.
  Rules out: asserting merely that "a render_brief bug lands in errors" without pinning
  which stage owns it.

- **Seam 15: `build_on_call_end` is where the whole slice can be dead code in production.**
  Wrong implementation A: it keeps returning the tracer's `log_only` after S5 exists. Every
  `dispatch` test passes — `dispatch` is fine — and NOTHING is ever dispatched on a real
  call. The slice ships, the suite is green, and no operator ever gets an email.
  **Note on polarity:** an earlier revision of this seam called "returns the real handler
  unconditionally" the DEFECT, because it was written against Q9's superseded predicate. Q23
  reversed that — analysis, the evidence files and the brief need no optional credential, so
  a log-only fallback throws away work that would have succeeded. The credential-absent
  behaviour is Seam 22's, and the id that asserted the old polarity (`D15.b`) was retired
  rather than reworded, because it contradicted `D15.e` for the same input.
  Test approach: call `build_on_call_end` with a `Settings` carrying full Twilio/SMTP fields
  and assert the returned handler, when awaited on a `CallRecord`, actually invokes the
  analysis client and both senders. The credential-ABSENT cases belong to Seam 22 (`D15.c`-`e`),
  which assert what the operator receives rather than which handler was chosen. Assert on
  OBSERVED CALLS, never on the function's name or identity.
  Rules out: testing `dispatch` exhaustively and never testing that anything calls it —
  which is the entire delta between "S5 works" and "S5 runs".

- **Seam 16: the email subject is one attribute away from silently wrong.**
  Wrong implementation: `profile.name` instead of `profile.display_name`. Both exist, both
  are `str`, both render — the subject just says `mortgage-broker` instead of
  `UK mortgage broker intake`. `mypy` cannot see it and no assertion on "the subject contains
  the outcome" catches it. This is the `live_model`/`analysis_model` defect from `analysis`,
  one attribute apart, in a new place.
  Test approach: a fixture profile whose `name` and `display_name` DIFFER, asserting the
  exact subject string `f"[{display_name}] {outcome} — {caller_number}"`, em dash included.
  Rules out: a fixture where the two fields are equal, which cannot discriminate them.

- **Seam 17: an unrendered SMS template reaches the caller verbatim.**
  Wrong implementation: sending `template.text` instead of `template.text.format(**template.links)`.
  The send succeeds, a sid comes back, `errors` is empty, the brief reports success — and the
  prospect receives a message containing a literal `{booking_link}`. Every structural
  assertion passes; only the body content is wrong.
  Test approach: a fixture `SmsTemplate` whose `text` contains a placeholder and whose
  `links` supplies it; assert the body the fake sender received contains the URL and does
  NOT contain `{`.
  Rules out: asserting only that `send` was called with a non-empty body.

- **Seam 18: an empty transcript is a ratified input, not an edge case.**
  S3's guarantee (a) says `on_call_end` is awaited "regardless of how the call ended
  (partial transcript allowed — **S5 tolerates empty**)", and S4 short-circuits an empty
  transcript to `unclassified` without calling the model. So the commonest real failure —
  a caller who hangs up during the disclosure — arrives here as an empty tuple.
  Wrong implementation: anything that treats an empty transcript as nothing to do and
  returns early. The operator then never learns the call happened, which is the same
  silence Q10-A was escalated to prevent, arriving by a different route.
  Test approach: `dispatch` with `transcript=()` and `analysis.outcome == "unclassified"`;
  assert all three files exist and the email was sent.
  Rules out: only ever testing with a populated transcript fixture.

---

- **Seam 19: the brief reports the dispatch and forgets the call.**
  Wrong implementation: `render_brief` emits only Q19's status lines. **This is not
  hypothetical — it is exactly what this artifact specified for fifteen critic rounds**,
  and every seam, every id and every mutation passed against it, because nothing asserted
  that the brief says what happened on the call.
  Sub-case, and the one a careless fixture misses: `compliance_notes` rendered as
  `notes[0]` or `notes[:1]` — a truncation that a single-note fixture cannot distinguish
  from correct.
  Test approach: a fixture with `outcome="qualified_lead"`, a distinctive `summary`, and
  **at least TWO compliance notes**. Assert the summary appears verbatim in BOTH the brief
  and the email body; assert each note appears on its own line; assert the outcome appears
  in the BODY, not only in the subject. Separately, with `compliance_notes=()`, assert the
  section renders the literal `none`.
  That last assertion is deliberately paired: the empty case renders a hardcoded literal, so
  on its own it proves nothing — it is only evidence alongside the two-note case, where the
  value is actually computed.
  Rules out: asserting the brief is non-empty, or that it "mentions" the outcome — the
  subject line already carries the outcome, so a body that drops it still looks right.

- **Seam 20: the brief's HEADER block, and the sender arguments — every field one swap from wrong.**
  The header Q21 introduced (`Caller:` / `When:` / `Profile:` / `Ended:`) and the arguments
  handed to the two senders are all same-typed `str` reads that render plausibly when wrong.
  **This seam exists because Q21's own fix created it**: the fix added the header and covered
  only the Outcome/Summary/Compliance blocks beneath it.
  Wrong implementations, each of which passed every id before this seam existed:
  - `record.caller_number` rendered raw, so a withheld number shows as an empty field rather
    than `withheld` — and an empty field reads as a rendering bug, not as a real withheld ID;
  - the `When:` line dropping `ended_at` or the `(UTC)` label, leaving a bare `datetime` repr
    whose timezone the operator must guess;
  - `profile.name` in the BODY line while the subject correctly uses `display_name` — `D16.a`
    passes, because it only ever looks at the subject;
  - the `Ended:` line omitted, losing `ended_reason` — the one field that distinguishes a
    completed call from a dropped one;
  - `sender_id=profile.phone_number` instead of `profile.sms_sender_id`, or
    `to=record.caller_number` on the EMAIL — both send successfully and assert nothing wrong,
    because no test inspects the arguments the fake sender actually received.
  Test approach: a fixture whose `name`, `display_name`, `phone_number`, `sms_sender_id` and
  `operator_email` are ALL distinct strings, and a `CallRecord` with an empty `caller_number`
  in one case and a real one in another. Assert the rendered header line-for-line, and assert
  the exact kwargs each fake sender was called with.
  Rules out: asserting the brief "contains the caller number" — which an empty string trivially
  satisfies — and asserting a send happened without asserting who it went to.

**Mutation note for this seam:** `profile.display_name` appears TWICE in the implementation
(subject and body). `mutate_check.py` requires `old` to occur exactly once, so `D21.c`'s swap
must carry enough surrounding text to be unique — `Profile: {profile.display_name}` rather
than the bare attribute, which would abort as MUTATION AMBIGUOUS.

- **Seam 21: `transcript.txt`'s content, and `email_sent`'s truth.**
  Wrong implementation A: `str(record.transcript)` — the tuple repr. It passed `D5.a`, `D5.b`,
  `D18.a` and every `transcript`-touching mutation in this artifact, because all of them assert
  the file EXISTS and none assert what is in it.
  Wrong implementation B: `email_sent=True` hardcoded. `DispatchReport.email_sent` had no
  decision, no seam and no id — its own inline comment claimed "the smoke asserts on it", which
  Phase 4 §4's Tier-1 list does not.
  Wrong implementation C: a bare `Path.write_text(...)`, which uses the locale encoding.
  Test approach: a fixture with at least three turns, BOTH roles, non-consecutive role changes,
  and a non-ASCII character in one turn. Assert the file's text equals `render_transcript`'s
  output exactly; assert role labels and order (reversing the turns must fail); read the file
  back as UTF-8 and assert the non-ASCII character survives. Separately assert `email_sent` is
  False on a failed send and True on a successful one.
  Rules out: asserting the transcript file is non-empty, or that it "contains" a turn's text —
  both of which the tuple repr satisfies.

- **Seam 22: partial credentials — the state between "configured" and "not".**
  Wrong implementation: `if all(seven): post_call else: log_only`. Seam 15 tests only the
  all-present case (`D15.a`), so nothing there objects, and this silently disables the
  operator's email whenever a Twilio credential is missing — a green suite says nothing,
  because until `D15.c`-`e` no test occupied the middle.
  Test approach: three ids over the partial states, asserting what the operator ACTUALLY
  receives, not which factory was chosen — (i) Twilio absent, SMTP present: the email is still
  sent, and the SMS stage reads `failed` with `no Twilio credentials configured`; (ii) SMTP
  absent, Twilio present: the SMS still goes and the brief still records the email failure;
  (iii) both absent: all three files are still written and the brief names both failures.
  Rules out: asserting `build_on_call_end` "returns post_call" — an identity check that is
  satisfied by a handler which then does nothing useful.

- **Seam 23: the S3-does-not-import-S4/S5 constraint, made mechanical.**
  Wrong implementation: `dispatch/wiring.py` is created but `server.py` keeps importing from
  `decana.dispatch` or `decana.analysis` "just for the factory". Every test still passes —
  the import is harmless at runtime — and the ratified convention that keeps S3 independently
  testable with fakes has quietly gone, one import at a time. Nothing in a behaviour suite
  ever objects to an import.
  Test approach: parse `src/decana/twilio/server.py` with `ast` and assert no `Import` or
  `ImportFrom` node names `decana.dispatch` or `decana.analysis`. A static check, deliberately
  — the property IS static, and asserting it at runtime would prove only that one code path
  did not happen to touch it.
  Rules out: relying on a human to notice an import in review, which is how the convention
  would have been lost the first time.

### Planner's note on one downgrade (recorded, not silently accepted)

A critic pass rated Seam 15 (`build_on_call_end`) below the "fools naive tests" bar, on the
grounds that presence/absence branching is not deceptive the way a same-typed field swap is.
**Kept as a seam anyway.** The bar is not how subtle the branch is; it is what a green suite
would fail to tell you. Seam 15's wrong implementation A leaves every `dispatch` test passing
and the entire slice unreachable in production — the largest possible gap between "the suite
is green" and "the feature runs", and the ratified contract names this function as the one
piece of S3 that S5 replaces. It also has a recorded precedent one slice back: `analysis`'s
dropped `api_key` passed the unit suite, the real-API smoke AND production. Cheap to test,
catastrophic and silent if wrong.


### Before the first test lands — the seams are unreachable without this

`scripts/check_ids.py` iterates a hardcoded `SLICES` dict that today holds only
`twilio-server` and `analysis`. Until `dispatch` is registered there, the 54 ids these 23
seams map to are **not checked by anything** — the script says nothing about `dispatch`,
success or failure, and still exits 0.

**Action, to land before or alongside the first `dispatch` test:**
```python
"dispatch": ("tests/test_dispatch.py", r"D\d+\.\w"),
```
Stated here as well as in Phase 4 §1 deliberately: the whole id table can be orphaned from
its checker, which is a strictly worse failure than any single missing id, and it is
invisible from a green run.

## Ratified behavior ids

`scripts/check_ids.py` greps this table (`^| \`D<n>.<x>\` |`). 54 ids.

**`D15.b` was retired, not lost.** It asserted that a credential-less `build_on_call_end`
returns the log-only handler and touches no sender — the exact inverse of `D15.e`, for the
identical input, after Q23 reversed that predicate. Two ratified ids that no single
implementation can satisfy is worse than one fewer id, so it was removed rather than reworded.

| id | behavior | nodes |
|---|---|---|
| `D1.a` | the event loop stays responsive while a sender is blocked (`to_thread`, not a direct call) | 1 |
| `D2.a` | a send that RAISES still leaves the marker on disk | 1 |
| `D2.b` | a second `dispatch` for the same call_sid sends no second SMS, but STILL emails and writes the brief | 1 |
| `D3.a` | email body == brief minus exactly one line (email succeeded) | 1 |
| `D3.b` | email body == brief minus exactly one line (email failed) | 1 |
| `D4.a` | no SMS when `analysis.outcome` has no template; detail says so; email still sent, brief still written | 1 |
| `D4.b` | no SMS when `caller_number` is empty; detail says so; email still sent, brief still written | 1 |
| `D4.c` | no SMS when the marker already exists; detail says so; email still sent, brief still written | 1 |
| `D5.a` | transcript + analysis.json exist ON DISK at the moment a sender is called | 1 |
| `D5.b` | both evidence files exist even when both senders raise | 1 |
| `D6.a` | brief does NOT exist when the email is sent, and DOES after `dispatch` returns | 1 |
| `D7.a` | SMS fails -> one `sms:` error, email still sent | 1 |
| `D7.b` | email fails -> one `email:` error, SMS still sent | 1 |
| `D8.a` | a FAILED send is reported differently from a deliberate skip | 1 |
| `D8.b` | a real send sets `sms_sid` to the sid returned | 1 |
| `D9.a` | `TwilioSmsSender.send` raises when the SDK returns `sid=None` | 1 |
| `D9.b` | `dispatch` turns that into one `sms:` error with `sms_sid is None` | 1 |
| `D10.a` | `post_call` returns None (does not raise) when `artifact_dir` cannot be created | 1 |
| `D10.b` | `post_call` lets `CancelledError` PROPAGATE | 1 |
| `D11.a` | port 465 -> `SMTP_SSL`, `starttls` not called | 1 |
| `D11.b` | port 587 -> `SMTP` + `starttls` called | 1 |
| `D12.a` | a failed transcript write still sends the email, writes the brief, and carries `- Transcript file: FAILED — <detail>` in both | 1 |
| `D13.a` | transcript stage fails -> report returned, later stages ran, brief written | 1 |
| `D13.b` | analysis stage fails -> report returned, later stages ran, brief written | 1 |
| `D13.c` | sms stage fails -> report returned, later stages ran, brief written | 1 |
| `D13.d` | email stage fails -> report returned, later stages ran, brief written | 1 |
| `D13.e` | brief stage fails -> report returned, `errors` names `brief`, file absent | 1 |
| `D14.a` | `render_brief` raising on the FIRST call is an `email:` error; brief still written | 1 |
| `D14.b` | `render_brief` raising on the SECOND call is a `brief:` error; email still sent | 1 |
| `D15.a` | `build_on_call_end` returns a handler that actually invokes the analysis client and BOTH senders (observed calls, not identity) | 1 |
| `D16.a` | subject is exactly `[{display_name}] {outcome} — {caller_number}` (fixture where name != display_name) | 1 |
| `D17.a` | SMS body has links substituted and contains no `{` | 1 |
| `D18.a` | an empty transcript still produces all three files and an email | 1 |
| `D19.a` | a failed transcript write renders the ratified `- Transcript file: FAILED — <detail>` line in the EMAIL BODY, not only the brief | 1 |
| `D19.b` | a failed analysis-json write renders `- Analysis file: FAILED — <detail>` in both | 1 |
| `D19.c` | the transcript and analysis lines are byte-identical between the email body and the brief, so the difference stays exactly the `Email:` line | 1 |
| `D20.a` | `analysis.summary` appears verbatim in the brief AND in the email body | 1 |
| `D20.b` | EVERY compliance note renders, one line each (fixture has >= 2, so truncation dies) | 1 |
| `D20.c` | empty `compliance_notes` renders the literal `none`, not an absent section | 1 |
| `D20.d` | `analysis.outcome` appears in the brief BODY, not only in the email subject | 1 |
| `D21.a` | an empty `caller_number` renders the literal `withheld`, not an empty field | 1 |
| `D21.b` | the `When:` line carries `started_at`, `ended_at` AND the `(UTC)` label | 1 |
| `D21.c` | the BODY `Profile:` line uses `display_name` (fixture has `name != display_name`) | 1 |
| `D21.d` | the `Ended:` line carries `record.ended_reason` | 1 |
| `D21.e` | the SMS sender is called with `to=record.caller_number` and `sender_id=profile.sms_sender_id` | 1 |
| `D21.f` | the email sender is called with `to=profile.operator_email` | 1 |
| `D22.a` | `transcript.txt` equals `render_transcript(record.transcript)` exactly, for a 3-turn mixed-role fixture | 1 |
| `D22.b` | role labels and turn ORDER are preserved (a reversed transcript fails) | 1 |
| `D22.c` | a non-ASCII transcript round-trips: the file reads back as UTF-8 unmangled | 1 |
| `D23.a` | `email_sent` is True only on a real send, False when the email raised | 1 |
| `D15.c` | Twilio absent / SMTP present: the email is STILL sent; sms stage `failed` naming the missing credentials | 1 |
| `D15.d` | SMTP absent / Twilio present: the SMS still goes; the brief records the email failure | 1 |
| `D15.e` | both credential groups absent: all three files are still written and the brief names both failures | 1 |
| `D24.a` | `decana.twilio.server` imports nothing from `decana.dispatch` or `decana.analysis` (AST check) | 1 |

## Exit criterion

Four parts. All four must hold. None is satisfied by a green suite alone.

### §1 — The id-set property (mechanical, not eyeballed)
`scripts/check_ids.py` diffs the ratified behavior-id set for `dispatch` against the id in
every test docstring in `tests/test_dispatch.py`, **in both directions**: no ratified id
without a node, no node naming an unratified id, no count mismatch.

This asserts a property over the ratified artifact rather than string-matching test names —
the reformulation the project adopted after an exit criterion named four test functions of
which three did not exist.

**Two prerequisites, because without them this criterion passes VACUOUSLY** (verified by
reading `scripts/check_ids.py` and running it, 2026-09-12):

1. **`dispatch` must be REGISTERED** in the harness's `SLICES` dict:
   `"dispatch": ("tests/test_dispatch.py", r"D\d+\.\w")`. Today it holds only
   `twilio-server` and `analysis`.
2. **This artifact must carry the id table in the exact shape the harness greps** —
   `^| \`D1.a\` |` rows under an `| id | behavior | nodes |` header, matching
   `analysis.md:651`. Ids are `D<seam>.<letter>`.

**The criterion is "the `dispatch` line prints `OK` with a non-zero id count", NOT "the
script exits 0".** An unregistered or test-file-less slice hits the `SKIP` branch, which
`continue`s **without setting `dirty`** — so the script exits 0 having checked nothing.
A green exit code is not evidence here; the printed line is.

### §2 — Mutation evidence (what makes the tests evidence rather than decoration)
Every seam in Phase 3 names a **wrong implementation**. Each one is applied with
`scripts/mutate_check.py` — the only sanctioned harness — and must be **killed by the id
that claims to cover it**, not merely by "some test somewhere".

**Required: one per RATIFIED ID, all 54** — not one per seam. §2's own standard is "a
ratified id without a mutation behind it is not covered", and a one-per-seam bar contradicts
it: it would have left `D4.a`, `D4.b`, `D5.b`, `D8.b`, `D10.a` and `D11.a` with no mutation
anywhere, passing on id-string presence alone. Each entry is a literal old->new swap, the
shape `mutate_check.py` handles (verified against its source: asserts the mutation applied,
restores in a `finally`, verifies by SHA-256, and requires `old` to appear exactly once).

| id | mutation (old -> new) |
|---|---|
| `D1.a` | `await asyncio.to_thread(sms.send, ...)` -> `sms.send(...)` |
| `D2.a` | the marker create moved to AFTER the send |
| `D2.b` | drop the marker conjunct from the SMS gate (same swap as `D4.c`) |
| `D3.a` | make the SMS line conditional on the pass — `f"- SMS: sent ({sms.detail})"` -> `f"- SMS: sent ({sms.detail})" if email is not None else f"- SMS sent ({sms.detail})"` — so the two passes differ in a SECOND line. **Requires the fixture's `sms` outcome to be `status="ok"`** (see below) |
| `D3.b` | the `Email:` line omitted unconditionally, so the two renders no longer differ by one line |
| `D4.a` | drop the `analysis.outcome in profile.sms` conjunct |
| `D4.a`(2) | **`return` early on the outcome-not-in-`profile.sms` skip branch** (skips email+brief) |
| `D4.b` | drop the `record.caller_number` conjunct |
| `D4.b`(2) | **`return` early on the empty-`caller_number` skip branch** |
| `D4.c` | drop the marker conjunct (same swap as `D2.b`) |
| `D4.c`(2) | **`return` early on the marker-present skip branch** (also kills `D2.b`) |
| `D5.a` | the two evidence writes moved after the senders |
| `D5.b` | the two evidence writes moved INSIDE the `sms` stage's `try`, so a sender raise skips them |
| `D6.a` | the brief write moved before the email send |
| `D7.a` | remove the `sms` stage's wrapper |
| `D7.b` | remove the `email` stage's wrapper |
| `D8.a` | the failure branch constructs `status="skipped"` |
| `D8.b` | `sms_sid=<sid>` -> `sms_sid=None` on the success path |
| `D9.a` | `if not isinstance(sid, str): raise` -> `return sid` |
| `D9.b` | same swap as `D9.a`; no exception reaches `dispatch`, so the `errors` entry vanishes |
| `D10.a` | remove `post_call`'s `try/except` entirely |
| `D10.b` | `except Exception` -> `except BaseException` in `post_call` |
| `D11.a` | the port test -> unconditional `SMTP` + `starttls()` |
| `D11.b` | the port test -> unconditional `SMTP_SSL` |
| `D12.a` | the `transcript` stage's `except` -> `raise` |
| `D13.a`..`D13.e` | that stage's `except` body -> `return` (short-circuit). **Run five times, once per stage** |
| `D14.a` | merge BOTH `render_brief` call sites under ONE `try`, labelled `"brief: "` |
| `D14.b` | merge BOTH `render_brief` call sites under ONE `try`, labelled `"email: "` |
| `D15.a` | `build_on_call_end` -> return `_log_only` unconditionally |
| `D16.a` | `profile.display_name` -> `profile.name` |
| `D17.a` | `template.text.format(**template.links)` -> `template.text` |
| `D18.a` | insert `if not record.transcript: return ...` at the top of `dispatch` |
| `D19.a` | delete the `- Transcript file: ...` line from `render_brief` |
| `D19.b` | delete the `- Analysis file: ...` line from `render_brief` |
| `D19.c` | render the transcript/analysis lines only when `email is not None` (so they appear in the brief but not the email body) |
| `D20.a` | delete the `## Summary` block from `render_brief` |
| `D20.b` | `for note in analysis.compliance_notes` -> `for note in analysis.compliance_notes[:1]` |
| `D20.c` | the empty-notes branch renders `""` instead of `none` |
| `D20.d` | delete the `## Outcome` block from `render_brief` |
| `D21.a` | drop the `or "withheld"` fallback on `caller_number` |
| `D21.b` | delete ` (UTC)` from the `When:` line |
| `D21.c` | `Profile: {profile.display_name}` -> `Profile: {profile.name}` (carry the `Profile: ` prefix — the bare attribute occurs twice) |
| `D21.d` | delete the `Ended:` line |
| `D21.e` | `sender_id=profile.sms_sender_id` -> `sender_id=profile.phone_number` |
| `D21.f` | `to=profile.operator_email` -> `to=record.caller_number` |
| `D22.a` | `render_transcript(record.transcript)` -> `str(record.transcript)` |
| `D22.b` | `record.transcript` -> `tuple(reversed(record.transcript))` at the transcript-render call site |
| `D22.c` | drop `encoding="utf-8"` from the transcript write |
| `D23.a` | `email_sent=<computed>` -> `email_sent=True` |
| `D15.c` | the two independent gates -> one `if all(seven fields)` gate |
| `D15.d` | the email gate reads the TWILIO fields instead of the SMTP ones |
| `D15.e` | `build_on_call_end` -> return `_log_only` when any optional credential is missing |
| `D24.a` | add `from decana.dispatch.wiring import build_on_call_end` to `server.py` |

**`D3.a` must DIVERGE OUTPUT, not just restructure.** An earlier draft wrote this mutation as
"the second `render_brief` call -> a separate renderer". That names a structure, not a content
change: a separate renderer that happens to produce identical text leaves the one-line
difference intact and the mutation SURVIVES, which would be recorded as evidence that the
property is discriminating when it is not. The swap must alter the text at the exact point
`D3.a` diffs.

**`D12.a` and `D19.a`/`D19.b` are NOT duplicates.** They share a scenario (an evidence write
fails) and assert different properties: `D12.a` is about the effect chain — `dispatch` does not
abort, the email still goes, the brief still gets written; `D19.a`/`D19.b` are about content —
the ratified `- Transcript file: FAILED — <detail>` line actually renders, in the EMAIL
specifically. A reader skimming `ids.md` alone could mistake them for one check.

**A mutation is only evidence if the FIXTURE reaches it.** `D3.a`/`D3.b` call `render_brief`
directly with hand-built `StageOutcome` values, and the `D3.a` swap edits only the
`status == "ok"` SMS template. A fixture built with `status="skipped"` never renders that
line, so the mutation would be *applied* — `mutate_check.py` would confirm it — and still
SURVIVE, which is indistinguishable from a covered id until somebody reads the fixture.
**So `D3.a` and `D3.b` both pin `sms=StageOutcome(status="ok", detail="<sid>")`.**
The same question, asked of every other row that mutates one branch of a status switch:
- `D8.a` mutates `dispatch`'s exception->`StageOutcome` conversion, so its test must drive a
  REAL sender failure through `dispatch` rather than construct the outcome by hand —
  otherwise the mutated line is never executed. Stated here because Seam 8 does not say it.
- `D11.a`/`D11.b` each pin a port (465 / 587); neither is reachable from the other's fixture.
- `D19.a`/`D19.b` pin `status="failed"` on the transcript / analysis stage respectively.

**`D5.b` needs its own mutation, not `D5.a`'s.** An earlier draft had `D5.a`'s reordering
"also kill `D5.b`". It does not: under Q7 each of the five stages is independently wrapped
and runs regardless of a sibling's exception, so moving the writes later still writes them —
`D5.b` ("both evidence files exist even when both senders raise") passes against that mutant.
Only a mutation that makes the writes share fate with a sender kills it.

**`D14.a`/`D14.b` are the structural mutation, not a label swap.** Seam 14's wrong
implementation is "one `try` spanning both `render_brief` call sites" — merging their
exception handling. An earlier draft of this table instead swapped the brief stage's error
label `"brief: "` -> `"email: "`, which kills `D14.b` while proving nothing about whether the
two call sites have independent handling at all. A merged `try` with a fixed label kills only
one direction, which is why both rows exist.

**Seam 15's mutation is the one to run first.** Its wrong implementation leaves every
`dispatch` test passing and the slice unreachable in production — and §1 is constitutionally
blind to it: the id-set check compares docstring LABELS against this artifact's table, so it
cannot distinguish a test that genuinely asserts the behaviour from one that merely cites the
right id. That is the whole reason §2 exists. A ratified id without a mutation behind it is
not covered; "a decision, a seam, and an id" is the standard, and the mutation is what makes
the id evidence rather than a name.

Per the harness rules, each run asserts the mutation **applied**, restores in a `finally`,
and verifies the restore by checksum. A "survived" verdict from a mutation that never
landed is worse than no check, because it gets written down as evidence.

**S13 additionally requires counting the family**: five stages, five nodes. The recorded
failure mode is a repair applied to four of five siblings — and an earlier revision of THIS
section reproduced it exactly, claiming "every seam" while listing 13 of 18, because the
list was written before Seams 14-18 existed and never recounted.

### §3 — Checks
`ruff check` · `ruff format --check` · `uv run mypy --strict src scripts tests` — that
exact mypy invocation, including `tests`, because `pyproject.toml` scopes `files` to
`src`/`scripts` and a bare run silently skips the suite and reports clean.

Must be clean WITH the new `[[tool.mypy.overrides]]` for `twilio` in place and NOT with a
global `ignore_missing_imports` (Q1).

### §4 — The smoke: `scripts/smoke_dispatch.py`
Three tiers. Tier 1 always runs; tiers 2 and 3 **park** rather than fail when their
credential is absent, following `scripts/smoke_analysis.py`'s established shape. Every
assertion is machine-checkable — **no human oracle** — so the script runs to completion
and its output goes in the transcript.

**Tier 1 — always runs, no credentials.** The environment S5 actually touches is the
filesystem, and this exercises the real one: a real temp `artifact_dir`, the real
`dispatch`, real `Path.open("x")`, real `asyncio.to_thread`, with fake senders.
Asserts: all three files exist with the ratified names; transcript and analysis.json
existed at the moment the senders were called; the brief did not; the brief is the email
body plus exactly one line; the marker exists; a second `dispatch` sends no second SMS;
a forced transcript-write failure still produces an email naming the failure.

**Tier 2 — PARKS on `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM`.**
The real `SmtpEmailSender` against the real server: one email to `profile.operator_email`.
Asserts the send returns without raising and that the chosen transport matches the port.
This is the ONLY place the SMTP adapter meets a real server; until it runs, `SmtpEmailSender`
is verified by a fake it implements — which the project has recorded as no evidence at all.

**Tier 3 — PARKS on `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`.** The real `TwilioSmsSender`:
one SMS to a number given by `DECANA_SMOKE_SMS_TO`. Asserts a non-empty sid comes back —
the network half of premise P1, and the only check that P2's narrowing is right about a
REAL response rather than a constructed one. **Costs money**: spends the `_budget.py` cap
BEFORE opening the socket, so a crash-loop cannot exceed it.

### No threshold is being ratified here
This criterion contains no number, latency, rate or qualitative term requiring an owner
ruling. Every assertion above is an exact equality, an existence check, or an ordering —
deliberately, because the one place a threshold could have crept in (what makes a brief
"good") is instead expressed as the mechanical property in Seam 3: the email body and the
brief are the same function of the same inputs, differing by exactly one line.

## Deferred to later slices

- **Retry / backoff on a failed SMS or email** — why later: the ratified scope says one
  attempt each, and a retry interacts with Q4's at-most-once marker in a way that needs its
  own ruling (a retry that re-reads the marker sends zero; one that ignores it sends two —
  the thing the owner ratified against). Revisit trigger: the first real call where the
  operator reports a lost notification, or S7 producing a send failure.

- **A real SMTP/Twilio verification gate** — why later: both need credentials the agent
  cannot read (`.env` is hard-denied), so tiers 2 and 3 of `scripts/smoke_dispatch.py` park.
  **Revisit trigger: those tiers RUNNING instead of parking** — i.e. `SMTP_HOST`/`SMTP_PORT`/
  `SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM` and `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` being
  present in whatever environment invokes the smoke. Phase 4 §4 already defines that
  park/run boundary mechanically, so the trigger is a printed line in the smoke's output,
  not a judgement.
  *An earlier draft named `scripts/supervise.sh` exporting those variables as the trigger.
  That was wrong twice over and is recorded here because the same claim is still live
  elsewhere in the repo:* the script **does not exist on this branch** (it is only on
  `slice/s4-analysis`, commit `a80c16f`), and the version that does exist checks
  `GEMINI_API_KEY` only — it exports nothing and inherits whatever the invoking shell
  already has. The trigger also wrongly implied S6's deploy depends on it; S6 takes its
  secrets from GCP Secret Manager via `gcloud --set-secrets`, an unrelated owner-run path.

- **Per-outcome email templates** — why later: S1 deferred this on the same ground; today
  every outcome gets the same brief with the outcome in the subject.
  **Revisit trigger: the operator asking for different content per outcome, or S7 step 7b's
  read-out finding an eco-consultant email the generic brief cannot express.**
  *An earlier draft used "a second real vertical" as the trigger. That is exactly backwards:
  7b IS the scheduled second vertical, and its ratified acceptance bar is an env-only
  redeploy whose `git diff --stat` shows `profiles/` only — so 7b PASSING is evidence the
  generic brief already handles a second vertical, not a signal to build per-outcome
  templates. The trigger would have fired on schedule while meaning the opposite.*

- **Structured/HTML email and attachments** — why later: cut in THIS SLICE'S FRAME (the
  feature doc says nothing about HTML email — grepped, zero hits; the earlier wording
  miscredited the cut to it); the brief
  points at the transcript rather than replacing it. Revisit trigger: an operator who
  cannot act from the plain-text brief.

- **Cloud/DB storage of transcripts and briefs** — why later: cut at feature level
  ("cloud transcript storage — deferred"). Today the artifacts are files next to the timing
  JSONL on the instance's disk, which on Cloud Run does not survive a redeploy.
  **Revisit trigger — NOT speculative, and already on the schedule: S7 step 7b.** The
  ratified Order table has the owner redeploy the SAME Cloud Run service to
  `DECANA_PROFILE=eco-consultant`, make a call, then "redeploy back to `mortgage-broker`" —
  two redeploys — while Edge S7 "what it reads" requires, per call,
  `{call_sid}.transcript.txt` and `{call_sid}.brief.md`, which are exactly the files this
  slice writes to that disk. So 7a's three broker calls produce evidence that 7b then
  destroys, unless it is captured first.
  **The handoff was PLACED, not asserted** (2026-09-12): `vertical-profile-bridge.md`'s
  Order-table row 7b and its "Edge S7 — what it reads" section now both carry the sequencing
  requirement — 7a's read-out must complete, or the artifacts be copied off the instance,
  BEFORE 7b's first redeploy. It had to go THERE: S7 is explicitly "not routed through
  slice-planner/slice-builder", so its human executor has no reason to open this artifact,
  and a risk recorded only here would have been recorded nowhere that anyone reads.
  S5 could make it moot by writing to a bucket, but that is the deferred item itself —
  building it here would be building the deferral rather than deferring it.

- **Idempotency for anything other than SMS** — why later: only the SMS is externally
  visible and irreversible, so only it got a marker. A re-dispatch overwrites the files and
  sends a second email. Revisit trigger: a retry mechanism existing at all (item 1), which
  is the only way a second dispatch happens today.

- **`DispatchReport` being consumed by anything** — why later: nothing reads the return
  value in this slice; `post_call` discards it and the operator-visible record is the brief.
  It exists so the tests and the smoke can assert on structured data rather than parsing
  Markdown. Revisit trigger: a caller that needs to branch on dispatch outcome.

## Open items requiring human decision

Both of this slice's escalations were resolved by the owner on 2026-09-12 and are recorded in
`.claude/overseer/escalations.md`. Nothing in this artifact is blocked on a decision.

- **RESOLVED — SMS marker order.** Mark before send (at-most-once). The feature doc's
  guarantee (b) and its batched-items list were updated to record the resolution.
- **RESOLVED — guarantee (d)'s silence on the file writes.** Read as a floor: `dispatch`
  wraps all five effects and never raises. Guarantee (d) amended in place and tagged.

Carried to the owner, not blocking this slice:

- **`scripts/supervise.sh` does not exist on this branch.** `CLAUDE.md:163` names it as the
  layer that exports secrets to a session, and `PROGRESS.md` did too. It exists only on
  `slice/s4-analysis` (`a80c16f`), and that version checks `GEMINI_API_KEY` only — it exports
  nothing and inherits whatever the invoking shell has. Port it, or correct `CLAUDE.md`.
  Flagged in `PROGRESS.md`; not fixed here, because the supervisor is harness tooling.
- **`CLAUDE.md`'s commit policy contradicts its own hook.** The autonomy section says "You may
  run `git commit` on a feature branch", but `block-dangerous.sh:116-129` permits commits only
  on `unattended/<date>`, and `AGENTS.md` still says commits are the human's. On
  `slice/s5-dispatch` the hook blocks. Not touched — Article 7.

## Critic notes (non-blocking)

- `DispatchReport` exposes `transcript_path`/`brief_path` but no `analysis_path`, because Edge
  S7's "what it reads" lists only `.jsonl`, `.transcript.txt` and `.brief.md`. `analysis.json`
  is written for a human debugging a bad outcome, not for S7.
- Q3's "465 means implicit TLS everywhere" half is ASSUMED, not measured. The stdlib's
  `SMTP_SSL_PORT == 465` is the verified half. Falsified by any provider pointed at this that
  wants STARTTLS on 465; S6's deploy doc is where that would surface.
- Q20's atomicity (the marker check IS the create) is deliberately untested: S3's guarantee (a)
  awaits `on_call_end` exactly once per call, so the race is unreachable in normal operation.
  The atomic form costs nothing and does not depend on that guarantee holding.
- `D8.b` has no seam paragraph of its own — it is a plain success-path assertion
  (`sms_sid == the returned sid`), not a seam that fools a naive test.
- Seam 8's adversarial fixture (a *skipped* outcome whose `detail` begins `"failed: "`) is
  deliberately unrealistic; it exists only to prove the renderer ignores `detail`'s text.
- The AND-gate reachability requirement (each SMS-gate test satisfies the other two conjuncts)
  is stated in Seam 4 and in each id's own definition, but not restated in the mutation table.
