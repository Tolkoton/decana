# Slice twilio-server — planning artifact

Feature `vertical-profile-bridge`, slice S3. Planned 2026-08-27 via `/plan-slice`.
Critic rounds: Phase 2 = 3, Phase 3 = 9 (closed by owner ruling), Phase 4 = 3,
Phase 5 = 3. 15 distinct blocking findings, none reversed.


## Goal
Deliver `src/decana/twilio/server.py`: the FastAPI app that terminates the Twilio
leg and composes every existing piece into a working call. Four concerns, kept
separately testable per the feature's own instruction:

1. `POST /voice` → TwiML: `<Say>{profile.disclosure}</Say>` then `<Connect><Stream>`.
2. `WS /media` → Twilio `connected`/`start`/`media`/`stop`; one `BridgeSession` per
   `start`; routes S2's `LiveEvent` stream by type.
3. `CallRecord` / `TranscriptTurn` types + the injected `on_call_end` hook.
4. Composition root: `create_app(...)` (fake-injectable) + `__main__.py` (wiring only).

**Measurable target.** Not a real call — that is the tracer (feature step 4) and S7.
For this slice: `create_app` driven by fakes for both the Twilio socket and the S2
`LiveSession` completes a full simulated call — TwiML rendered and parsed, `start` →
`media`×N → `stop` pumped through a real `BridgeSession`, `on_call_end` awaited
exactly once with a `CallRecord` carrying a non-empty ordered transcript and a
`{call_sid}.jsonl` on disk containing `call_answered` and ≥1 `chunk_forwarded_to_twilio`.


## Out of scope (deliberately)
- **Deployment** (Dockerfile, Cloud Run, `min-instances=1`) — S6.
- **Post-call analysis and dispatch** — S4/S5. `on_call_end` is injected; this slice
  ships only the log-only no-op the tracer uses.
- **Any real PSTN call.** Blocked on provisioning and on S6; the tracer is step 4.
- **Retry / reconnection / backpressure policy.** Q22 part 3 of `voice-intake-demo`
  stands: a drop is a measurement result, not a bug to engineer around before the
  first measurement.
- **Barge-in handling.** `Interrupted` stays the ratified log-only no-op (feature Q4).
- **Caller-type routing, compliance guardrail, Calendly, UK-region storage** — all
  already deferred at feature level.


## Premise verified
### P1 — `<Connect><Stream>` is terminal and opens the socket only AFTER `<Say>` ends

**VERIFIED 2026-08-27 via docs** (twilio.com/docs/voice/twiml/stream, fetched this
session). Exact wording: *"When you use `<Connect><Stream>`, Twilio doesn't execute
subsequent TwiML instructions. Twilio executes the remaining TwiML instructions only
after your server closes the WebSocket connection."* TwiML verbs run sequentially, so
in `<Say>…</Say><Connect><Stream/></Connect>` the `<Say>` completes first and the
WebSocket upgrade to `/media` is only then issued.

**This is the slice's most consequential fact, and it falsifies the mechanism —
though not the requirement — assumed in the feature artifact.** The feature's S3 note
and `PR-gemini-live-greeting-on-connect` both require S3 to "open the Live session
concurrently with the Twilio `<Say>`" so that Gemini's 3.2–4.0 s connect+greeting cost
hides behind the disclosure. **The WebSocket handler cannot do that: it does not exist
while `<Say>` is playing.** The only place in S3 that runs during `<Say>` is
`POST /voice`, which is a plain HTTP request handled before Twilio begins playback.

Consequence carried into Phase 2, not resolved here: the Live session must be opened
in `POST /voice`, keyed by `CallSid`, and adopted by the WS handler when it connects
— which introduces a registry with a lifetime, an orphan path (caller hangs up during
the disclosure and the WS never arrives), and a question about where the model's
greeting audio goes if it is produced before the socket exists.

### P2 — Twilio media-stream message shapes

**VERIFIED 2026-08-27 via docs** (twilio.com/docs/voice/media-streams/websocket-messages,
fetched this session). Inbound `connected` / `start` / `media` / `stop` / `mark` /
`dtmf`; `start.customParameters` carries the `<Parameter>` children; `streamSid` is at
message root on every event. Outbound play-audio message is
`{"event":"media","streamSid":…,"media":{"payload":…}}` with `streamSid` **required**
at root.

**Marked ASSUMED, not verified, for the wire behaviour behind the shapes.** The shapes
are documented and were read; what is *not* checkable without a real call is whether
the live stream matches the documentation in the details that bite — e.g. whether
`customParameters` values arrive as strings, whether `sequenceNumber` is contiguous,
whether `mark` is echoed. **There is no source to read here** — this is a wire
protocol, not an installed SDK, so the `google-genai` mitigation ("read the source,
not the signature", `.claude/overseer/MEMORY.md`) is unavailable by construction.
Falsification: the tracer call (feature step 4). This is the third slice in a row
whose third-party surface is the recorded failure mode, and the first where reading
source is not an option — noted so the implementer does not go looking for one.

### P3 — `PR-bridgesession-composes-with-async-io` — still `unverified`

The synchronous `BridgeSession` plugs into an asyncio WebSocket server and the async
Live session without changing its ratified contract. **This slice is what builds the
composition, and its fake-driven exit criterion is the first real evidence for it**
— short of a live call. Falsification re-opens Seam 4's ratified 16-behavior contract
(Article 8). Existing row in `.claude/premises/premise-log.md`.

### P4 — S2's `LiveSession` guarantees, consumed as given

`send_audio` sync/never-raises; `events()` yields `AudioChunk`/`Transcript` in arrival
order and ends after **exactly one** `Closed`; `close()` idempotent; `Transcript` is a
whole turn. **VERIFIED 2026-08-27** — S2 is merged (`ad0b104`), 178 tests green, smoke
passed against the real API. S3 consumes these; it does not re-test them.

### P5 — Cloud Run WebSocket sustain — NOT this slice's premise

`PR-cloud-run-sustains-media-stream` is S6's. Recorded here only to state that S3
does not depend on it: S3's exit criterion runs entirely against fakes and a local
`TestClient`.


### Hard-gate disposition

P1, P2, P4 verified this session. P3 is the integration premise this slice exists to
build toward and is already owner-accepted at feature level. P2's wire-behaviour half
is accepted as risk with the tracer named as its falsifier. **No premise is both
unverified and unaccepted → gate passes.** P1's consequence is a design fork routed
into Phase 2, not a premise failure.


## Seam (contract)

**Also modified — `pyproject.toml`, two changes, one of them owner-gated:**

1. `[project.scripts] decana = "decana.__main__:main"` — the console entry the ratified
   feature contract assigns to this slice (`vertical-profile-bridge.md:52`) and which
   its Phase-4 gate's `__main__` smoke depends on. The file has no `[project.scripts]`
   section today.
2. **`uv add fastapi uvicorn` — requires the owner.** This slice's `create_app(...)`
   returns a `FastAPI` and `__main__.py` runs uvicorn, yet **neither package is in
   `[project] dependencies` (only `google-genai`, `numpy`, `soxr`) nor in the installed
   environment** — verified 2026-08-27. No earlier slice added them. The feature frame
   pre-approves both (`vertical-profile-bridge.md:17`) but says so with an explicit
   caveat: *"(`uv add` still prompts)"*, and `uv add` is on this project's ask-list in
   `CLAUDE.md`.

> **Correction to the ratified Phase-4 gate table.** Its row 3 (S3 twilio-server) marks
> **"Owner needed? No."** That is wrong: this slice cannot begin without one ask-list
> approval for the dependency add. The artifact flags the deploy step's ask-list
> commands but had not applied the same discipline to its own install — noted here
> rather than silently worked around, since it changes when the owner is first needed
> from "not at all" to "before the first line of code."

3. **`httpx` and `websockets` should become explicit dependencies**, not inherited ones.
   §2's smoke needs an HTTP client (the webhook POST) and a WebSocket client (the media
   stream). Both are installed today — but `uv pip show` reports each as
   `Required-by: google-genai`, i.e. **transitive only**. A dependency this slice's own
   verification relies on should not be one another package happens to pull in: if
   `google-genai` drops or repins either, the smoke breaks for a reason unrelated to
   anything this slice did. Same `uv add` prompt, so no extra owner interruption.

4. **`uv add python-multipart` — found during implementation, 2026-08-27, and NOT on
   the feature's pre-approved list.** Twilio posts the voice webhook as
   `application/x-www-form-urlencoded`, and Starlette raises
   `AssertionError: The 'python-multipart' library must be installed to use form
   parsing` on `await request.form()` without it. Discovered by the first GREEN
   attempt on `S6.a` failing on exactly that. Added rather than worked around: the
   alternative is hand-parsing the body with `urllib.parse.parse_qs`, which
   reimplements form decoding to avoid a dependency FastAPI treats as standard for
   this. Reversible with one `uv remove`, and the add is visible in the staged diff.

*(Items 2 and 3 came from auditing this enumeration after two consecutive cold reads
found omissions in it — first `[project.scripts]`, then `fastapi`/`uvicorn`. Item 4 came
from running the code. **The enumeration was audited three times and still missed a
dependency that the first executed line of the slice demanded** — which is the sharpest
available statement of this artifact's own recurring lesson: reading finds what you
thought to look for, running finds what is true. The list is where this artifact was
weakest, and it was weak in the same way four times.)*

Modules: `src/decana/twilio/records.py` (types), `src/decana/twilio/server.py` (app),
`src/decana/settings.py` (env), `src/decana/__main__.py` (wiring). Module paths are
fixed by the ratified feature contract, not chosen here.

### Types — `src/decana/twilio/records.py`

```python
@dataclass(frozen=True)
class TranscriptTurn:  role: Literal["caller", "model"]; text: str

@dataclass(frozen=True)
class CallRecord:
    call_sid: str
    caller_number: str                      # normalised; see S3-Q6
    profile_name: str
    started_at: datetime                    # UTC wall clock at Twilio `start`
    ended_at: datetime
    transcript: tuple[TranscriptTurn, ...]  # arrival order; may be empty
    timing_path: Path
    ended_reason: str

OnCallEnd = Callable[[CallRecord], Awaitable[None]]
```
All eight fields are the ratified set (feature contract, Edge S3 → S4,S5), copied
field-for-field rather than re-derived. `TranscriptTurn` is separate from S2's
`Transcript` so S4/S5 never import `decana.gemini`.

### Composition root — `src/decana/twilio/server.py`

```python
def create_app(
    profile: Profile,
    live_factory: LiveSessionFactory,
    on_call_end: OnCallEnd,
    *,
    public_wss_url: str,
    artifact_dir: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),   # ADDITION, see S3-Q7
    pending_ttl_s: float = 60.0,                                  # ADDITION, see S3-Q4
) -> FastAPI
```
The first five parameters and their order are ratified. `clock` and `pending_ttl_s`
are **additions to a ratified signature**, keyword-only with defaults so every
ratified call site keeps working — flagged explicitly rather than slipped in, and
logged for the owner to overrule.

### Endpoints

- `POST /voice` — form-encoded webhook; reads `CallSid` and `From`. Opens the Live
  session (S3-Q1), registers it under `CallSid`, returns
  `<Response><Say>{profile.disclosure}</Say><Connect><Stream url="{public_wss_url}/media"><Parameter name="caller" value="{From}"/></Stream></Connect></Response>`,
  `disclosure` and `From` both XML-escaped.
- `WS /media` — handles `connected`, `start`, `media`, `stop`; **ignores `mark` and
  `dtmf`** (ratified guarantee (d)). `connected` is matched and **deliberately a
  no-op**: per P2 it carries only `protocol` and `version`, no `streamSid` and no
  `CallSid`, so there is nothing to bind a call to yet. Stated rather than left
  implicit so the next reader knows it was considered, not forgotten — the `start`
  message is where a call begins.

### The LiveEvent routing table (ratified; restated here so it cannot be dropped)

| event | S3 does |
|---|---|
| `AudioChunk(pcm24k)` | `bridge.handle_gemini_chunk(ev.pcm24k)` |
| `Transcript(role, text)` | append `TranscriptTurn(role, text)` to this call's list |
| `Interrupted` | **log-only no-op** (feature Q4 — stays a no-op) |
| `Closed(reason)` | `_teardown(f"gemini_closed: {reason}")` |

### Errors

`POST /voice` never raises to Twilio. `open_live_session` raises on connect-time
failure *deliberately* (`live.py:352-354`), so S3 catches it, logs, registers
nothing, and answers `<Response><Say>{disclosure}</Say><Hangup/></Response>` — the
caller still hears the compliance line. `WS /media` funnels every ending into one
`_teardown(reason)`, with each ending mapped explicitly rather than by a catch-all:

| ending | `ended_reason` |
|---|---|
| Twilio `stop` message | `twilio_stop` |
| `WebSocketDisconnect` mid-call | `ws_disconnect` |
| S2 `Closed(reason)` observed on `events()` | `gemini_closed: <reason>` |
| outbound drain-task send failure | `twilio_send_failed` |
| any other exception in the handler | `error: <ExceptionType>` |

A second Twilio `stop`, or a `stop` followed by a disconnect, is absorbed by the
`done` flag — the first ending wins and sets the reason.

### Dependencies (injected, never imported)

`live_factory`, `on_call_end`, `profile`, `public_wss_url`, `artifact_dir`, `clock`.
`BridgeSession`, `TimingRecorder`, `inbound_resampler`, `outbound_resampler` are
this project's own modules; the feature contract fixes their construction.

### Does NOT do

Deployment; analysis; dispatch; retry/reconnect; barge-in beyond logging
`Interrupted`; any real PSTN call.

---

## Decisions (with WHY)

**S3-Q1: the Live session is opened in `POST /voice` by a single `await
live_factory(profile)`, and S3 never calls `.start()`.**

Chosen: `POST /voice` awaits `live_factory(profile)` **exactly once**. What comes
back is already started and has already sent its greeting trigger. S3 registers it
under `CallSid` and returns the TwiML. The WS handler adopts it on `start`.

WHY the webhook and not the socket: forced by P1. `<Connect><Stream>` is terminal and
TwiML verbs run in order, so **the WebSocket does not exist while `<Say>` is
playing** — the WS handler cannot open the session "concurrently with the `<Say>`"
because it has not been invoked yet. The only S3 code that runs during the disclosure
is the HTTP webhook. The feature artifact and `PR-gemini-live-greeting-on-connect`
both *require* that concurrency (Gemini's 3.2–4.0 s connect+greeting must hide behind
the disclosure or the post-`<Say>` silence breaches the ≤1500 ms gap carrying A3);
neither names the mechanism, and the obvious reading — do it in the WS handler — is
impossible.

WHY no `.start()`: **verified in source, and the first draft of this decision got it
wrong.** `open_live_session` calls `await session.start(greeting_trigger=…)` itself at
`live.py:370`, before returning at `live.py:371`; the ratified `LiveSession` Protocol
S3 consumes (Edge S2 → S3) exposes only `send_audio`, `events`, `close` and has no
`.start()` member at all. `GeminiLiveSession.start()` (`live.py:191-203`) carries **no
idempotency guard**: a second call re-sends the greeting-trigger turn and re-assigns
`self._reader`/`self._drain` to two new tasks without cancelling the pair it
overwrites, leaving two readers racing over one `_inbox` and one transport. The
audible result is a doubled, self-racing greeting — corrupting precisely the signal
this decision exists to land promptly. A fake `LiveSession` in this slice's own tests
has no reason to assert single-invocation, so it would have passed every test here and
surfaced first on the tracer's one real call.

`open_live_session`'s own docstring confirms this split was designed for S3: *"the
session must outlive this function — S3 opens one per call and drives it from
elsewhere"* (`live.py:348-349`).

Rejected: **open the session on WS connect.** Steelman: one lifecycle, no registry, no
orphan path, and it is what the feature text reads like on first pass. Rejected: it
puts the whole 3.2–4.0 s cost *after* the disclosure ends, which is exactly the
≤1500 ms gap A3 measures — failing the acceptance the feature exists to meet, and
failing it silently (every unit test passes; only a real call shows it).

Rejected: **drop `<Say>`; stream a pre-rendered disclosure file while Gemini
connects.** Steelman: socket opens at t0 so connect and disclosure genuinely overlap,
no registry at all, and compliance holds because the audio is fixed and
non-generative. Rejected: it replaces Twilio `<Say>`, which the MVP doc ratified
specifically as the non-generative disclosure path, and adds a per-profile audio
artifact plus a TTS step. Ratified-text territory, and larger than the problem needs.
**Kept as the named fallback if the tracer shows the disclosure is too short to cover
the connect cost** — see W-1.

**S3-Q2: S3 adds no buffer for greeting audio produced before the socket exists.**

Chosen: rely on S2's internal `_inbox`; S3 begins iterating `events()` only once the
WS is up, and the backlog drains in arrival order.

WHY: verified by reading S2's source. `start()` spawns `_read_loop` as an independent
task (`live.py:202`) which does `self._inbox.put_nowait(event)` (`live.py:284`) into
an **unbounded** `asyncio.Queue` (`live.py:183`), so the reader accumulates with no
consumer attached. S2's docstring states the intent directly: *"the model should start
speaking whether or not S3 has begun iterating yet — that is not a race S3 should have
to know about"* (`live.py:195-196`). A second buffer in S3 would duplicate an existing
mechanism and add a second place for ordering to go wrong.

**Recorded as a dependency S2 must not silently drop:** this rests on `_inbox` being
unbounded, which is a property of S2's *implementation*, not of its ratified contract.
If S2 ever bounds that queue, S3-Q2 breaks and the greeting is truncated. Falsification
condition, so the next reader has one.

Rejected: **an explicit `deque` in S3 filled by an early consumer task.** Steelman:
makes buffering visible at the layer that needs it, and does not depend on another
slice's internals. Rejected: it requires S3 to consume `events()` from webhook time,
splitting the `Closed`-terminates-the-stream contract across two consumers, and it
buffers what is already buffered.

**S3-Q3: greeting backlog is flushed through the normal path, not fast-forwarded.**

Chosen: the buffered `AudioChunk`s go through `handle_gemini_chunk` like any others —
resample, encode, enqueue — with no pacing and no skipping.

WHY: Twilio plays outbound media from its own buffer, so a burst is played in order
rather than dropped; and pacing would require S3 to model playback timing, which is
the sort of local cleverness that hides real latency. The burst is bounded: the spike
measured a whole greeting at ~311 KB / 139 chunks of 24 kHz PCM (~6.5 s), which is
~52 KB of μ-law after downsampling. Accepted risk recorded as W-2.

**S3-Q4: the pending-session registry is bounded by a TTL sweep over a snapshot.**

Chosen: `dict[str, _Pending]`, `_Pending` holding the session and the `clock()` stamp
at registration. On every `POST /voice` and every WS `start`, entries older than
`pending_ttl_s` (default 60 s) are closed and dropped. **The sweep iterates a
`list(registry.items())` snapshot and removes each entry with a guarded pop —
`registry.pop(call_sid, None)`, never `del registry[call_sid]`** — because it awaits
`session.close()` per entry and the dict can be mutated by a concurrent webhook or
socket across that await. Named as the concrete call rather than as "re-checks
membership" (round-1 wording) because the bare `del` is what an implementer writes by
default, and the difference between the two is a `KeyError` raised inside whichever
*unrelated* request happened to trigger the sweep.

**Adoption pops before it sweeps.** The WS `start` handler removes *its own*
`CallSid` from the registry first, and only then runs the sweep over what remains.
Without that ordering a call whose socket arrives later than `pending_ttl_s` after the
webhook would have its own live session closed by its own sweep pass, and would then
be routed into S3-Q5's fail-loudly path — a real caller dropped by a reaper meant for
orphans. Popping first also closes the cross-request variant for the adopting call:
once popped, no other request's sweep can see the entry. (Raised as a round-2
NON_BLOCKING note; fixed here rather than deferred because the fix is an ordering
constraint, not a mechanism, and the failure it prevents is a dropped real call.)

**Residual, stated not hidden:** a *different* concurrent request's sweep can still
close a pending entry the instant it crosses the TTL while its socket is mid-handshake.
That window is the difference between a 60 s TTL and a disclosure measured in seconds
— roughly an order of magnitude — so it is accepted rather than engineered against.
Recorded as W-3.

WHY: the orphan path is not hypothetical — hanging up during a compliance disclosure
is normal caller behaviour, and each orphan holds an open Gemini socket whose reader
keeps filling an unbounded queue. Sweeping on request arrival rather than from a
background timer keeps the app free of a task whose lifecycle every test would have to
manage, at the cost of an orphan surviving until the next call — stated rather than
assumed.

Rejected: **no reaper.** Steelman: at demo volume leaks do not matter and the process
restarts often. Rejected: the leak is a paid API socket held by a growing queue, and
"it gets restarted" is not a property the code guarantees.
Rejected: **a periodic sweeper task.** Steelman: bounded reclamation latency
regardless of traffic. Rejected: a background task in `create_app` must be started and
cancelled around the app lifespan — real complexity in every test, to reclaim a socket
a few seconds sooner.

**S3-Q5: a WS `start` with no registry entry fails the call loudly.**

Chosen: log, send no media, close the socket, open no replacement session, produce no
`CallRecord`.

WHY: a miss means the TTL fired (impossible in a normal call) or `POST /voice` never
ran for this `CallSid` — an unsolicited socket. Opening a fresh session would "work"
while delivering exactly the failure S3-Q1 exists to prevent (~3 s dead air after the
disclosure) and would make the one symptom that reveals a broken webhook path
invisible. Failing loudly keeps the diagnostic. Consistent with the ratified "a call
that never reached `start` produces no record".

Rejected: **open a session on the fly.** Steelman: the caller gets *a* conversation
rather than a dropped call. Rejected: it converts a wiring bug into a latency bug, and
latency is what this feature is judged on.

**S3-Q6: `caller_number` is normalised to E.164 or to the empty string.**

Chosen: if the `<Parameter name="caller">` value parses as E.164, keep it; otherwise
store `""`. The raw value is not propagated.

WHY: **checked against Twilio docs, as the ratified contract instructed S3 to do.**
`From` is not always E.164 — Twilio documents that on a withheld or unnormalisable
caller ID it reports *"a string that contains `anonymous`, `unknown`, or other
descriptions"*, and that *"there are occasionally cases where Twilio cannot normalize
an incoming caller ID to E.164, [where] Twilio will report the raw caller ID string."*
`caller_number` feeds S5's SMS send; a non-E.164 string reaching that path is an SMS
to a non-number. Collapsing to `""` makes "no usable number" a single testable state
instead of an open set of vendor strings. **Honest note:** the contract's example
`+266696687` is not documented by Twilio as a sentinel; `anonymous` and `unknown` are.
The rule is written against the documented behaviour (parse-or-empty), which covers
the example without depending on it.

**S3-Q7: `started_at`/`ended_at` come from the injected `clock`, not `datetime.now`.**

Chosen: `create_app` takes `clock`, defaulted to `lambda: datetime.now(UTC)`; the two
record timestamps and the TTL sweep read it.

WHY: same reason `TimingRecorder` takes one (voice-intake-demo Q7) — a test that
asserts `ended_at >= started_at`, or that the TTL fired, cannot do so against a real
clock without sleeping. This is an addition to a ratified signature, keyword-only with
a default, flagged as such.

**S3-Q8: teardown order is drain-stop → bridge → Gemini → record.**

Chosen: one `_teardown(reason)` per call, guarded by an `asyncio.Lock` + `done` flag:
stop the outbound drain task → `BridgeSession.close()` (sync; flushes both
resamplers) → `await live_session.close()` → build `CallRecord` → `await
on_call_end(record)`.

WHY: `BridgeSession.close()` flushes soxr's stranded tail (~66 ms inbound, ~21 ms
outbound) and forwards it, so it must run while the Twilio send path can still accept
the flush, but after the drain stops taking new work or the flush races the queue.
`live_session.close()` runs last because S2's Q4 makes it emit `Closed("local")` and
tear down in a fixed order; closing Gemini first would make S3's event loop observe a
`Closed` mid-teardown and re-enter `_teardown`. The feature fixes the exactly-once
property (guarantee (a)); it explicitly leaves the *order* to S3 (PROGRESS.md, S2
entry: "S3 owns the teardown ordering between two `close()`s").

Rejected: **`await live_session.close()` first.** Steelman: stop the audio source
first so the bridge flushes into a quiet system. Rejected: triggers the re-entrancy
above and discards whatever Gemini had already queued.

**S3-Q9: `BridgeSession.close()` raising does not abort the record.**

Chosen: `_teardown` wraps it, logs, sets `ended_reason="error: <ExceptionType>"`, and
still awaits `on_call_end` exactly once with the record as it stands.

WHY: ratified guarantee (a), load-bearing because a second `close()` raises
`RuntimeError("Input after last input")` **by design** (`voice-intake-demo` Q19 — the
bridge slice, not S2) — the guard must make that unreachable rather than swallow it.
A partial transcript still has value; S5 tolerates an empty one.

**S3-Q10: `send_media` is a sync enqueue onto a per-call FIFO drained by one task.**

Chosen: the mirror of S2's adapter. Sync, enqueues, **never raises**; one drain task
per call writes `{"event":"media","streamSid":…,"media":{"payload":…}}` in FIFO order;
a failed send triggers `_teardown("twilio_send_failed")`; after teardown it is a
silent no-op.

WHY: `BridgeSession._forward_to_twilio` calls it under a catch scoped to
`AudioFrameError` only (`voice-intake-demo` Q20 — the bridge slice, not S2), so **any
other exception from `send_media` ends the call**. Never-raising is a hard
requirement, not defensive style. Ratified as guarantee (e).

**S3-Q12: `on_call_end` raising is caught, logged, and changes nothing else.**

Chosen: `await on_call_end(record)` is the **last** statement of `_teardown`, wrapped
in `try/except Exception`. On a raise: log `call_sid`, the exception type and message;
swallow. Do not retry, do not re-invoke, do not alter `ended_reason`, do not
re-enter `_teardown`.

WHY: ratified guarantee (b) — *"an exception from `on_call_end` is logged and does not
affect the socket or other calls"* — and **round 2 caught that no decision covered it**:
S3-Q8 ended `_teardown` with a bare `await on_call_end(record)`, and S3-Q9's wrapping
is scoped explicitly to `BridgeSession.close()`. That is the same shape of omission
that cost S2 ten critic rounds on `Interrupted` — a member of a ratified list that no
decision ever names.

Three properties make the catch safe rather than merely quiet:

1. **Ordering.** Both `close()` calls, the drain-task stop, the registry removal and
   the `done` flag are all settled *before* this line (S3-Q8's order). A raise here
   therefore cannot leave the call half-torn-down — there is nothing left to tear.
2. **No retry.** `on_call_end` is ratified as awaited **exactly once per `start`**.
   Retrying to "recover" would break the stronger guarantee to protect the weaker one;
   S5's own idempotency marker is written before its Twilio send precisely so a
   duplicate is never the recovery path.
3. **Isolation.** The record and the callback are per-call, and the exception is
   swallowed inside the per-call `_teardown`, so it cannot reach the WS handler's
   exception path (which would otherwise trigger a second `_teardown`, blocked anyway
   by `done`) and cannot touch a concurrently-torn-down call.

**Named test, because the ratified Phase-4 gate does not cover this either** (it tests
`on_call_end` exactly-once *including when `close()` raises*, never `on_call_end`
itself raising): a fake `on_call_end` that raises → the call still tears down, the
exception is logged, `close()` was still called exactly once, and a second concurrent
call completes normally. Carried into Phase 3 as its own seam so it cannot fall
through again.

**S3-Q15 (decided during implementation 2026-08-27, derivable from ratified text —
overrule if wrong): S3 defines the `LiveSession` Protocol consumer-side.**

Chosen: `LiveSession(Protocol)` — exactly `send_audio`, `events`, `close` — is declared
in `src/decana/twilio/server.py`, not imported from S2.

WHY: the ratified feature contract's Edge S2 → S3 specifies this Protocol as "what S3
consumes", but **S2 never shipped it.** `live.py`'s `__all__` exports `GeminiLiveSession`
(concrete), `LiveTransport` (S2's own *inbound* test seam), and the four event types —
no `LiveSession`. Verified against `src/decana/gemini/live.py:374-384`. So it has to be
declared somewhere, and the choice is S2's module or S3's.

Declared consumer-side because `GeminiLiveSession` satisfies it structurally, so nothing
in the shipped S2 changes — and because a consumer-defined Protocol is what lets this
slice's fakes implement *exactly* the ratified surface, which is the standing constraint
the whole seam list rests on. Editing a merged slice's module to add a type only its
consumer needs would be the larger change and the more coupled one.

Rejected: **add the Protocol to `src/decana/gemini/live.py`.** Steelman: it is where the
feature contract's code block shows it, so a reader following the contract looks there
first. Rejected: it modifies a slice that is merged, green and smoke-verified, to add a
type S2 itself does not use, and it makes S3 import a Protocol rather than own the shape
it depends on. The contract's code block is grouped by *edge*, not by file ownership —
the same block also lists `LiveSessionFactory`, which is plainly S3's.

**S3-Q14: re-registering a `CallSid` closes the superseded session first.**

Chosen: registration is not a bare `registry[call_sid] = _Pending(...)`. If the key is
already present, the existing session's `close()` is awaited **before** the new entry
replaces it, **and the supersede is logged with the `CallSid`**. One live entry per
`CallSid`, always.

The log line is part of the decision, not incidental: it is the only observable that a
webhook retry actually happened in a given deployment, and Phase 5's deferral of the
`I-Twilio-Idempotency-Token` optimisation names exactly that line as its revisit
trigger. Without it the deferral would have a trigger nothing produces — which is what
an earlier draft had.

WHY: **Twilio retries the voice webhook** — on timeout or 5xx it re-requests, then falls
back — and it ships an `I-Twilio-Idempotency-Token` header precisely because, without
it, a retried request is indistinguishable from a fresh one at the server. So a second
`POST /voice` for a `CallSid` already pending is a documented condition, not a
hypothetical.

The consequence of the bare write is worse than a duplicate: it silently overwrites the
`_Pending` holding the first `GeminiLiveSession`, whose `_reader`/`_drain` tasks
(`live.py:202-203`) are referenced only from the now-orphaned object. The event loop
keeps them running, and the sweep never sees them again because **the sweep only
inspects what is in the dict**. That is not a leak bounded by `pending_ttl_s` — it is
unbounded: an open, billed Gemini socket accumulating into an unbounded `_inbox`
(`live.py:183`) for the life of the process. The TTL reaper of S3-Q4 gives no protection
here, which is exactly why this needs its own decision rather than an assumption that
S3-Q4 covers the registry.

Rejected: **read `I-Twilio-Idempotency-Token` and skip the duplicate registration.**
Steelman: it is Twilio's own purpose-built mechanism, and skipping is cheaper than
opening a second session at all. Rejected: it makes correctness depend on a
vendor-specific header being present and correctly propagated, when close-then-replace
is right whether the second request is a retry, a genuinely new call reusing a
`CallSid`, or anything else. The header could be an optimisation later; it is not the
invariant.

Rejected: **keep the first session and discard the second.** Steelman: the first is
older and its greeting has had longer to generate, so keeping it preserves the latency
S3-Q1 works to protect. Rejected: the returning TwiML belongs to the second request,
and the caller will be connected on the strength of *that* response — keeping a session
the surviving request never learned about reintroduces the orphan from the other end.

**S3-Q13: `streamSid` is captured from the `start` message and threaded into every
outbound media message.**

Chosen: the WS handler reads `msg["streamSid"]` from the `start` message, stores it on
the per-call state alongside the `BridgeSession`, and the socket adapter puts it at the
**root** of every outbound frame: `{"event":"media","streamSid":<captured>,"media":
{"payload":…}}`. It is captured once, at `start`, and never re-read from later messages.

WHY: P2 records that Twilio requires `streamSid` at message root on outbound media, and
ratified guarantee (e) states the literal shape — but **no decision said where the value
comes from**, and round 5 found that no seam asserted it either. That combination is the
dangerous one: the shape appears verbatim in three places (P2, guarantee (e), S3-Q10)
and looks thoroughly specified, while nothing in the plan produces the value or checks
it. An adapter that omits the field or hardcodes `""` satisfies every other stated
property — FIFO order, never-raises, failure mapping, correct payload bytes — and
Twilio discards the frames. The caller hears **dead air after the greeting**, on exactly
the latency path A3 measures, discoverable only on the tracer call.

Captured at `start` rather than echoed per-message because `start` is the only inbound
message guaranteed to precede all outbound audio, and because the greeting backlog
(S3-Q2) is flushed immediately on adoption — there may be no inbound `media` message to
echo from before the first outbound frame is sent.

Rejected: **echo `streamSid` from the most recent inbound `media` message.** Steelman:
no per-call state to hold, and every `media` carries it. Rejected: the greeting backlog
is sent before any inbound `media` necessarily arrives, so the first — and most
latency-critical — frames would have no value to echo.

**S3-Q11: `Settings.from_env()` lives in `src/decana/settings.py` and exits 2.**

Chosen: frozen dataclass; a missing required variable exits 2 naming the variable.
`__main__.py` is wiring only — no logic, no branching beyond what the ratified
`main()` sketch contains.

WHY: ratified module path and behaviour (feature contract, env table preamble).
Keeping the env read in exactly one place is what lets `create_app` be driven entirely
by fakes, which is this slice's whole exit criterion.

---

### Appendix — Phase 2 non-blocking notes

**Round 1** (blocking: double `session.start()` — fixed in S3-Q1)
- Note 2 (`CallRecord` dropped 3 ratified fields) — **resolved**: all 8 fields, copied
  field-for-field from the ratified contract.
- Note 3 (LiveEvent routing table absent) — **resolved**: table now in the Seam.
- Note 4 (mutate-during-iterate in the TTL sweep) — **resolved**: S3-Q4 snapshots and
  re-checks membership.
- Note 5 (`Q4` label collision with the feature's own Q4) — **resolved**: decisions
  renumbered `S3-Q<n>`.

**Round 2** (blocking: ratified guarantee (b) uncovered — fixed as S3-Q12)
- Note 2 (TTL sweep can race adoption, incl. a call closing its own session) —
  **resolved**: S3-Q4 pops before sweeping; the residual cross-request window is
  disclosed as W-3.
- Note 3 (`create_app`'s two signature additions) — affirmation, no defect; flagging
  judged sufficient, no ADR needed.
- Note 4 (`ws_disconnect` mapping unnamed) — **resolved**: the Errors section now maps
  every ending explicitly.

**Round 3** (CRITIC_PASS)
- Note 1 (`connected` listed as handled with no stated behavior) — **resolved**: named
  as a deliberate no-op with the reason.
- Note 2 (`Q19` miscited as S2's) — **resolved**, and the sibling citation `Q20` was
  wrong the same way and is fixed too; `Q4` was checked and is correctly gemini-live's.
  Both belong to `voice-intake-demo`, the bridge slice.
- Note 3 (appendix tracked only round-1 notes) — **resolved**: this appendix.


## Hardest seams (test-confidence points — distinct from the contract Seam above)

Distinct from the contract Seam. Each entry names the naive test that would pass while
the code is wrong, and the concrete approach that discriminates.

### Decision → seam coverage map

Every Phase-2 decision maps to at least one seam, or is explicitly recorded as needing
none. **This table is the instrument, not decoration.** Three separate rounds of this
slice's planning were blocked by the same defect — a mechanism named in a decision's
prose that no test would force to exist (guarantee (b) in Phase 2 round 2; S3-Q4's
guarded removal in Phase 3 round 1; S3-Q9 and S3-Q5 in Phase 3 round 2). Prose coverage
is not coverage. A reader checking this artifact should walk this table, not the seam
list.

| Decision | Seam(s) | |
|---|---|---|
| S3-Q1 open in webhook, adopt, never `.start()` | 1 | |
| S3-Q2 no S3-side buffer | 2 | |
| S3-Q3 backlog flushed through the normal path | 2 | |
| S3-Q4 guarded-pop TTL sweep, pop-before-sweep | 8 (a)(b)(c) | |
| S3-Q5 WS `start` with no registry entry fails loudly | **11** | added round 3 |
| S3-Q6 `caller_number` → E.164 or `""` | 7 | |
| S3-Q7 timestamps come from the injected `clock` | 3 (g), and 8 (a)(b) for the sweep's own clock reads | citation widened round 7 |
| S3-Q8 teardown order drain→bridge→gemini→record | **3 (e)** | added round 3 |
| S3-Q9 `close()` raising does not abort the record | **10** | added round 3 |
| S3-Q10 `send_media` never raises | 5 | |
| S3-Q11 `Settings.from_env()` + the `decana` entry point | **17 (a)(b)** | added by the cold read: the parent gate names a `__main__` smoke, and no seam executed `main()` |
| S3-Q12 `on_call_end` raising | 4 | |
| P3 integration premise | 9 | |
| Guarantee (a) at-most-once teardown + always-completes | 3 (a)–(e); 10 for the close-raises clause; 11 for "never reached `start` produces no record" | citation widened round 7 |
| Guarantee (b) `on_call_end` isolation | 4 | |
| Guarantee (c) TwiML shape | 6 | |
| Guarantee (d) WS message handling incl. ignore set | **12** | added round 4 |
| Guarantee (e) — property 1: FIFO, never raises, maps failure | 5 (a) | |
| Guarantee (e) — property 2: message content incl. root `streamSid` | **5 (b)** | added round 6 |
| S3-Q13 `streamSid` captured at `start`, threaded outbound | **5 (b)** | added round 6 |

### Fourth axis — the Seam contract's own sections

The three axes above enumerate *decisions*, *guarantees* and *type members*. The Seam
contract has sections that are none of those, and round 7's finding lived in one.

| Seam-contract section | Covered by |
|---|---|
| Types + their members | see the type-member table above |
| Composition root — every `create_app` parameter | 6, 1, 9, 4, 10, 12, 3 (g), 8 |
| Endpoint `POST /voice` — success path | 1, 6 |
| **Endpoint `POST /voice` — `live_factory` raises** | **14** — added round 7 |
| Endpoint `WS /media` — message handling | 12, and 1/2/3/9 for the handled set |
| LiveEvent routing table | 1, 2, 9, 13, 3 |
| Errors — the five endings table | 3 (a)–(e) |
| Dependencies (injected, never imported) | 9 — real bridge, fakes only at the two externals |

**Why the map enumerates Phase 2's structure, and what that still does not close.**
Rounds 4-7 each found a member of an enumerable set the map had no row for — guarantees,
then type members, then AND-split properties, then endpoint error paths. Adding a fifth
ad-hoc axis after each finding is chasing, not closing. The map therefore enumerates
**the Phase 2 artifact's own structure**: every section of the Seam contract, every
decision, every guarantee, every premise. That set is finite and checkable by reading
the Phase 2 headings rather than by intuition.

**But it is closed only over Phase 2's *text*, and that is a real limit, not a caveat.**
Round 8 found a load-bearing property with no row on any axis: two concurrent calls must
be routed to their own sessions. It is never written down as a decision, guarantee or
type member — it is implicit in the *key type of a dict*, `dict[str, _Pending]`. No
enumeration of a document finds it, because it is not a property of the document; it is
an **emergent property of running two instances of what the document describes**.

### Fifth axis — properties that emerge from N instances, not from the text

| Property | Seam |
|---|---|
| Two concurrent calls route to their own sessions (read side) | **15** — added round 8 |
| One `CallSid` registered twice does not orphan a session (write side) | **16** — added round 9 |
| Two concurrent calls each tear down independently | 4 (e), 10 (d) |
| A sweep in one request does not corrupt another's adoption | 8 (c) |
| Two calls' `TimingRecorder`s do not collide | non-issue: `sink_path` is `artifact_dir / f"{call_sid}.jsonl"`, distinct by key; each `record()` opens, appends and closes independently |
| Logs distinguish concurrent calls | every log site in S3-Q5/Q12/Q14 and Seams 11(e)/14(d) carries `call_sid` |
| Real `BridgeSession`/`Resampler` under two-call concurrency | **deliberately not tested here.** Seam 9 drives the real collaborators single-call; Seam 15 drives concurrency with Protocol fakes. A real-collaborator concurrent test is the tracer's territory (P3's named falsifier), and the standing fake constraint makes it costly here. Recorded as W-4 rather than assumed away. |

The general rule this slice earns: **enumerating an artifact finds what it says; it does
not find what happens when two of the thing it describes run at once.** For a per-call
server that dimension is not exotic — it is the normal operating condition, and it is
where the worst failure in this seam list lives.

**Multi-property guarantees get one row per property, not one row per guarantee.**
Round 6's finding was `streamSid`: guarantee (e) had a single row reading "5", which
*claimed* coverage — and a map that claims coverage it does not have is worse than no
map, because it stops the next reader looking. Guarantee (e) asserts two independently
checkable things (how sending fails, and what is sent); Seam 5 tested only the first.
The same split is what R1 found inside S3-Q4. Where a decision or guarantee has an
"and" in it, it needs a row on each side of the "and".

### Third axis — members of ratified types

| `LiveEvent` member | Seam |
|---|---|
| `AudioChunk` | 1, 2 |
| `Transcript` | 9 (both roles, role-fidelity asserted) |
| `Interrupted` | **13** — added round 5 |
| `Closed` | 3 (a)–(e) |

| `CallRecord` field | Seam |
|---|---|
| `call_sid` | 9, 11 |
| `caller_number` | 7 |
| `profile_name` | — deliberately none: a pass-through of the injected `profile`, same standing as S3-Q11 |
| `started_at`, `ended_at` | 3 (g) |
| `transcript` | 9 |
| `timing_path` | 9 |
| `ended_reason` | 3 (a)–(e), 10 |

**Three axes, because each new axis has produced a finding.** Round 4's gap was
guarantee (d): the map enumerated *decisions* only, so inherited ratified text had no
row. Round 5's gap was `Interrupted`: the map enumerated decisions *and* guarantees, so
a **member of a ratified type** — which is neither — had no row either. It appears only
in Phase 2's routing-table prose.

That `Interrupted` is the member that went missing is not a coincidence worth passing
over. It is the same member S2 lost through ten round-anchored critic rounds, in a
slice whose own preamble cites that history, in a draft that lists it in the routing
table. **Knowing about a failure mode does not confer coverage against it; only an
enumeration does.** A coverage map is a map of the territory you already thought about
until every axis of the ratified surface is enumerated in it.

**Standing constraint for this slice's fakes.** The two fakes (`LiveSession`, the
Twilio WebSocket) implement **exactly** the ratified Protocol surface and nothing more.
No convenience `.start()`, no extra attributes. This is not tidiness: round 1 of Phase 2
had S3 calling `.start()` on a session the factory had already started, and the reason
it survived drafting is that a hand-written fake would cheerfully have grown a `start`
stub to match. A fake that mirrors the Protocol exactly turns that class of drift into
an `AttributeError` at test time instead of a doubled greeting on a real call. Recorded
because `.claude/overseer/MEMORY.md` now carries the general form — *a fake cannot be
evidence for the contract the fake implements* — and this is the one legitimate
inverse: the fake is evidence for **our** code honouring a contract, never for the
vendor's behaviour.

---

**Seam 1: the Live session is created during `POST /voice` and *adopted* — not
recreated — by the socket.**

Wrong implementations that a naive test passes: (i) opening the session on WS connect,
which is the whole latency defect S3-Q1 exists to prevent; (ii) opening one in the
webhook and a *second* one on connect, leaving the first orphaned; (iii) calling
`.start()` again on adoption.

Test approach — three assertions, none of which a call-count alone gives you:
- **Timing:** the fake factory records `clock()` when invoked. Assert it was invoked
  during the `POST /voice` request and **before** the WS connect. A bare
  `factory.call_count == 1` passes for the WS-connect implementation too, which is why
  the ordering assertion is the load-bearing one.
- **Identity:** the object the bridge is driving is the *same object* the factory
  returned (`is`, not `==`). This is what rules out (ii); a second factory call would
  bump the count, but only identity proves the *first* session is the one being used.
- **Protocol purity:** the fake exposes only `send_audio`/`events`/`close`. Any
  `.start()` reach is an `AttributeError`, which rules out (iii) structurally rather
  than by assertion.

**Seam 2: greeting audio produced before the socket exists arrives first, and in
order.**

Wrong implementation a naive test passes: consuming `events()` only from WS-connect
time onward and dropping the backlog, or draining it out of order. Every test that
emits its events *after* connecting is blind to this — and that is the shape every
test naturally takes.

Test approach: the fake `LiveSession` emits N `AudioChunk`s **before** the test opens
the WebSocket (mirroring S2's real reader, which fills `_inbox` with no consumer), then
M more after. Assert the outbound `send_media` payload sequence has exactly N+M entries
and that decoding them back through `mulaw_decode` recovers the chunks in emission
order — first byte of outbound media traces to chunk 1, not chunk N+1. Rules out: a
consumer that starts at connect and silently discards the greeting, which on a real
call is the caller hearing the AI mid-sentence.

**Seam 3: teardown is exactly-once across all five endings, including two racing.**

Wrong implementation a naive test passes: a `done` flag checked without a lock. Any
single-ending test is green; the defect needs two endings arriving concurrently, which
is exactly what a Twilio `stop` immediately followed by a socket disconnect produces.

Test approach:
- **(a) the five endings, parametrised (5 nodes)** — assert `BridgeSession.close()` was
  called **exactly once**, `on_call_end` awaited **exactly once**, and `ended_reason`
  matches the table.
- **(e) the race** — fire `stop` and `WebSocketDisconnect` concurrently via
  `asyncio.gather`; assert still exactly one of each and that `ended_reason` is
  whichever ending won, not a corrupted mix. Rules out the flag-only guard, which
  double-flushes into `RuntimeError("Input after last input")` — the failure
  `voice-intake-demo` Q19 built deliberately into `close()`.
- **(f) the order (S3-Q8)** — every injected collaborator appends its name to one
  shared list: drain-stop, `bridge.close`, `gemini.close`, `on_call_end`. Assert the
  list equals exactly that sequence. **Exactly-once does not imply in-order:** the
  reversed implementation S3-Q8 explicitly rejects still shows one `close()` and one
  `on_call_end`, so (a)–(e) all pass against it while the flushed tail is discarded.
  Order needs its own assertion or it has none.
- **(g) clock provenance (S3-Q7)** — inject a clock returning a fixed sentinel far from
  now (`2000-01-01T00:00:00Z`, then a later fixed value). Assert `CallRecord.started_at`
  and `ended_at` equal those exact values. An implementation calling `datetime.now(UTC)`
  internally passes every other assertion in this seam and fails only this one.

**Seam 4: `on_call_end` raising leaves the call and its neighbours intact (S3-Q12).**

Wrong implementation a naive test passes: no wrapping at all — with a fake
`on_call_end` that never raises, an unwrapped `await` is indistinguishable from a
wrapped one. Note the ratified Phase-4 gate does **not** cover this, so nothing
downstream forces it either.

Test approach: fake `on_call_end` raises. Assert (a) the exception does not escape the
WS handler, (b) it is logged with `call_sid` and exception type, (c) `close()` was
still called exactly once, (d) `on_call_end` is **not** retried, and (e) a second call
running concurrently completes normally and gets its own record. Rules out: both the
unwrapped await and a "helpful" retry that would violate the ratified exactly-once.

**Seam 5: `send_media` never raises, and a send failure ends the call the right way.**

Wrong implementation a naive test passes: letting the socket's exception propagate.
`BridgeSession._forward_to_twilio` catches only `AudioFrameError`
(`voice-intake-demo` Q20), so anything else ends the call — but a happy-path fake
socket never raises, so the defect is invisible.

Guarantee (e) has **two independent properties**, and until round 6 only one had a test.

- **(a) failure behaviour.** Fake socket whose `send_text` raises on the k-th send.
  Assert `send_media` itself returns normally (never propagates), that `_teardown` runs
  with `ended_reason="twilio_send_failed"`, and that `send_media` calls *after* teardown
  are silent no-ops rather than errors. Rules out a drain task that dies silently,
  leaving the call alive but mute.
- **(b) message content (S3-Q13).** The fake socket captures every frame it is sent as
  parsed JSON. Assert each has `streamSid` at the **root**, equal to the value from the
  `start` message — not absent, not `""`, not nested inside `media`. Include a frame
  from the **greeting backlog**, which is flushed on adoption before any inbound `media`
  arrives; that is the case an echo-from-last-media implementation gets wrong and the
  reason S3-Q13 captures at `start`.

Why (b) is not pedantry: the shape appears verbatim in P2, in ratified guarantee (e) and
in S3-Q10, which makes it *look* thoroughly specified. Nothing produced the value and
nothing checked it. An adapter omitting the field passes every assertion in (a) —
ordering, never-raises, failure mapping, correct decoded payload bytes — and Twilio
discards the frames, so the caller hears dead air after the greeting on precisely the
path A3 measures.

**Seam 6: the TwiML is valid XML for hostile disclosure and caller values.**

Wrong implementation a naive test passes: building the TwiML by f-string and asserting
`"<Say>" in body`. A disclosure containing `&` (entirely legal English prose — "Smith
& Co") or a caller value containing `<` produces malformed XML that still satisfies the
substring assertion, and Twilio rejects or mis-parses it on a real call.

Test approach: **parse** the response with `xml.etree.ElementTree`, not substring-match
it. Assert the element structure (`Response/Say`, `Response/Connect/Stream`, the
`Parameter` child), assert `Say`'s text equals the profile disclosure **exactly** after
parsing, and assert `Stream/@url` is `{public_wss_url}/media`. Then the hostile case: a
profile whose disclosure contains `&`, `<`, `>` and a quote, and a `From` of
`+44 "x" & <y>` — assert the document still parses and the round-tripped text is
byte-identical to the input. Rules out: the f-string implementation, which is what
anyone writes first.

**Seam 7: `caller_number` normalisation collapses every non-E.164 value to `""`.**

Wrong implementation a naive test passes: passing `From` through unchanged. A test
using a well-formed `+447700900123` is green either way.

Test approach: parametrised over the documented set — a valid E.164 (kept verbatim),
`anonymous`, `unknown`, the contract's `+266696687` example, an empty string, and a
raw non-normalised string. Assert the first is preserved and every other yields `""`.
Rules out: passthrough, whose consequence lands two slices away as S5 sending an SMS to
the literal string `anonymous`.

**Seam 8: the TTL reaper never closes a session that is being adopted.**

Wrong implementation a naive test passes: sweeping before popping. With a default
60 s TTL and a test that connects immediately, sweep-order is unobservable.

S3-Q4 rests on **two** safety properties, and they need two different tests. The first
draft of this seam tested only the first, and a sweep written with a bare
`del registry[call_sid]` passed all nine seams while carrying the exact defect S3-Q4's
prose claims to prevent.

Test approach — three cases:

- **(a) adoption beats the reaper.** Drive the injected `clock` forward past
  `pending_ttl_s` between the webhook and the WS connect, then connect. Assert the call
  **succeeds** — its session is adopted, not reaped — proving the handler popped its own
  entry before sweeping. Rules out sweep-then-lookup ordering, which drops a real caller
  whose socket was merely slow.
- **(b) the orphan is actually reclaimed.** A webhook with no socket at all, followed by
  a second webhook past the TTL; assert the first session's `close()` was called and its
  registry entry is gone. Rules out: no reaper at all.
- **(c) the sweep survives the registry changing under it — concurrently.** Two
  sweep-eligible entries, X and Y, both past the TTL. The interleaving must be *forced*,
  not hoped for: the fake session for **Y** has a `close()` that awaits an
  `asyncio.Event` the test controls. Sequence: start the unrelated request whose sweep
  snapshots both X and Y and blocks inside `Y.close()`; the test waits until it is
  observably blocked (a second Event the fake sets on entry); adopt X via a WS `start`,
  which pops X; then set the gate so the sweep resumes and reaches X. Assert the
  unrelated request **completes without raising**, no session is closed twice, and the
  registry ends consistent. Rules out the bare `del`, which raises `KeyError` inside a
  request with nothing to do with the call being reaped.

  **Why not plain `asyncio.gather`.** Seam 3(e)'s race is order-*insensitive* — either
  winner is a correct outcome — so `gather` suffices there. This one needs a specific
  interleaving, and `gather` alone does not guarantee it: without the gate the test
  passes whether or not the race was ever exercised, which is precisely the
  passes-for-the-wrong-reason gap that blocked round 1. Spelled out rather than left to
  "the technique Seam 3 uses", which was the round-2 draft's wording and was wrong.

**Distinct from W-3, deliberately.** W-3 accepts that a concurrent sweep may close a
live session too early — a timing risk, disclosed. Case (c) is not that: it is the
sweep's own bookkeeping crashing on a stale snapshot, which S3-Q4 claims to have solved
and which is accepted nowhere. Cases (a) and (b) are both sequential and cannot
distinguish the two.

**Seam 10: `BridgeSession.close()` raising still produces a record (S3-Q9).**

Wrong implementation a naive test passes: `self._bridge.close()` unwrapped inside
`_teardown` (`BridgeSession.close()` is **sync** — `session.py` — so the wrong
implementation is a bare call, not an `await`). **All nine earlier seams pass it** — none of them ever makes `close()`
raise. Seam 3's five endings are all about *how the call ended*, not about the teardown
step itself failing; Seam 4 raises from `on_call_end` with a `close()` that succeeds;
Seam 9 is a happy-path pump.

Why it matters more than its obscurity suggests: this is ratified feature-contract text,
a promise made to S4 and S5 — *"If `close()` raises anyway, `_teardown` catches it at
the call site, logs it, sets `ended_reason="error: <ExceptionType>"`, and still awaits
`on_call_end` exactly once."* Unwrapped, a raising `close()` takes the whole `_teardown`
down with it: **no `CallRecord`, no `on_call_end`, no diagnostic trail for a call that
really happened.** That is a worse silent failure than the one Seam 4 exists to close.

Test approach — the structural mirror of Seam 4: a fake `BridgeSession` whose `close()`
raises an exception *distinct* from the guarded double-invocation `RuntimeError` (which
the `done` flag already makes unreachable). Assert (a) the exception escapes neither
`_teardown` nor the WS handler, (b) `ended_reason == "error: <ExceptionType>"` naming
the actual type, (c) `on_call_end` is still awaited **exactly once** with the record as
it stands, partial transcript included, and (d) a concurrently running second call
completes normally with its own record.

**Seam 11: a WS `start` with no registry entry fails loudly and creates nothing
(S3-Q5).**

Wrong implementation a naive test passes: opening a session on the fly — the alternative
S3-Q5 explicitly rejects. Every other seam connects a socket whose webhook already ran,
so none of them ever reaches this branch, and the on-the-fly implementation looks
*better* under casual testing because the call "works".

Test approach: connect a WS and send `start` for a `CallSid` the registry has never
seen. Assert (a) `live_factory` was **not** called, (b) no media was sent, (c) the
socket was closed, (d) `on_call_end` was **not** awaited and no `CallRecord` produced —
matching the ratified "a call that never reached `start` produces no record", and
(e) the miss was logged with the `CallSid`. Rules out the on-the-fly fallback, which
converts a broken-webhook wiring bug into a ~3 s-dead-air latency bug — invisible to
tests, and landing on exactly the metric A3 judges.

**Seam 12: `connected`, `mark` and `dtmf` are absorbed without incident (guarantee (d)).**

Wrong implementation a naive test passes: a dispatch table —
`HANDLERS[msg["event"]](msg)` — which is the natural refactor once there are four event
types, and which raises `KeyError` on any message not in it. **All eleven other seams
pass it**: every one of them drives only `start` / `media` / `stop`, including Seam 9's
composed pump.

Why this is not a theoretical branch: **`dtmf` is caller-initiated.** Any caller who
presses a key during the disclosure or mid-conversation — a reflex on a phone call —
sends one. The `KeyError` surfaces inside the message-handling loop, outside
`_teardown`, so it is not even routed to the ratified `error: <type>` ending: it is an
uncontrolled crash mid-call. `connected` is worse in a quieter way — it is the **first**
message Twilio ever sends, so a dispatch-table implementation fails every call
immediately, and would be caught on the first tracer dial rather than in production.
`mark` only arrives if S3 sends one, which it does not, so it is the genuinely inert
member of the three and is covered for completeness.

Test approach: send each of `connected`, `mark`, and `dtmf` — `connected` first (its
real position), `dtmf` and `mark` interleaved *between* `media` frames mid-call. Assert
(a) no exception escapes the handler, (b) the socket stays open and subsequent `media`
frames are still forwarded, (c) `_teardown` did **not** run, (d) the transcript and the
`CallRecord` are unchanged by them, and (e) the call still ends normally on `stop` with
`ended_reason="twilio_stop"`. Rules out both the dispatch-table `KeyError` and the
lazier failure of treating an unknown event as a call-ending condition.

**Seam 13: `Interrupted` is a logged no-op that does not disturb the stream.**

Wrong implementation a naive test passes: a `match ev:` with arms for `AudioChunk`,
`Transcript` and `Closed` but none for `Interrupted` — or a dict dispatch keyed by type.
Either raises mid-call, outside `_teardown`, the first time Gemini surfaces a barge-in.
**All twelve other seams pass it**, because none of their fakes ever emits `Interrupted`.

Not hypothetical: `Interrupted` is a real emitted variant (`live.py:317`), surfaced
whenever the caller talks over the model — which on a phone call is ordinary, not
exceptional. The feature contract puts it on the same footing as the other three
branches, as a log-only no-op (feature Q4), and that no-op status is exactly what makes
it easy to omit: there is nothing to *do*, so there is nothing that visibly breaks in
review.

Test approach: the fake `LiveSession` interleaves `Interrupted()` between `AudioChunk`
and `Transcript` events mid-call. Assert (a) no exception escapes the event-consumption
path, (b) it is logged and otherwise a no-op, (c) `_teardown` did **not** run, (d) the
`AudioChunk`s and `Transcript`s that follow it still flow normally — the stream is not
truncated — and (e) the call still ends on `stop` with `ended_reason="twilio_stop"`.
Rules out both the missing dispatch arm and the over-reaction of treating a barge-in as
a call-ending condition.

**Seam 14: `POST /voice` survives a `live_factory` that raises, and registers nothing.**

Wrong implementations a naive test passes: (i) letting the exception propagate, so
FastAPI returns a raw 500 to Twilio and the caller hears a Twilio error message instead
of the compliance disclosure; (ii) catching it but still registering a `_Pending` entry,
so a later WS `start` for that `CallSid` adopts a session that was never opened.
**All thirteen other seams pass both**, because every one of them drives a fake factory
that succeeds.

This path is real and deliberate, not defensive padding: `open_live_session` raises on
connect-time failure *by design* — *"that happens before a call exists, and S3 needs to
see it rather than receive a `Closed` for a session that never opened"*
(`live.py:352-354`). A Gemini outage, a bad API key, or a network blip during the
webhook all land here, and the compliance disclosure must still be spoken.

Test approach: a fake `live_factory` that raises. Assert (a) no exception reaches the
client — the response is 200, not 500; (b) the body **parses** (ElementTree, Seam 6's
technique) as `Response/Say` + `Response/Hangup`, with the `Say` text equal to the
profile disclosure — the caller hears the compliance line even on the failure path;
(c) nothing was registered for that `CallSid`, proven by then connecting a WS `start`
for it and asserting Seam 11's fail-loudly path, not an adoption; (d) the failure is
logged with the `CallSid`.

**Seam 15: two concurrent calls are routed to their own sessions, never swapped.**

Wrong implementations a naive test passes: a WS handler that takes the most recently
registered entry instead of looking up by the `start` message's `CallSid` —
`registry.popitem()` rather than `registry.pop(call_sid)` — or a registry that is
accidentally a single mutable slot rather than genuinely keyed.

**All fourteen other seams pass both.** Seam 1 tests session identity for *one* call.
Seam 9 is a single-call pump. Seams 4(e) and 10(d) are the only places two concurrent
calls appear at all, and both assert only that the second call "completes normally and
gets its own record" — the *existence* of a record, never that its **content** traces to
its own session. With Protocol-only fakes, which by this slice's own standard are
interchangeable and carry no distinguishing behaviour, two calls would each complete and
each produce a record while their transcripts were silently exchanged.

**Why this outranks the other fourteen in consequence.** Every other seam here guards
against a call that fails, stalls, or crashes. This one guards against two calls that
both appear to *succeed* while one caller's mortgage details are written into the other
caller's `CallRecord` — which is then sent to the operator by S5. That is a
data-protection incident, not an outage, and it is silent by construction: nothing in
the logs, the timing JSONL, or the record itself looks wrong.

Test approach: two **distinguishable** fake sessions — each emits a transcript naming
its own `CallSid` — registered via two `POST /voice` calls with distinct `CallSid`s,
then two WS connections opened concurrently via `asyncio.gather` in the *reverse* order
(second-registered adopts first), which is what defeats a most-recent-entry
implementation. Assert each `CallRecord.call_sid` matches the transcript content that
belongs to it, and that each adopted session `is` the object its own factory call
returned. Rules out both wrong implementations, and the reversed connect order is what
makes the assertion sharp rather than accidentally satisfied.

**Seam 16: a repeated `POST /voice` for one `CallSid` closes the superseded session
(S3-Q14).**

Wrong implementation a naive test passes: `registry[call_sid] = _Pending(...)`, the
plain dict write. **All fifteen other seams pass it** — every one registers each
`CallSid` exactly once, including Seams 8 and 15, whose concurrency uses *distinct*
`CallSid`s.

Not hypothetical: Twilio retries the voice webhook on timeout or 5xx and then falls back
to the fallback URL, and its `I-Twilio-Idempotency-Token` header exists because a retry
is otherwise indistinguishable from a new request. The failure is not a duplicate call —
it is an **unbounded** leak: the overwritten `GeminiLiveSession`'s `_reader`/`_drain`
tasks keep running with no external reference, filling an unbounded `_inbox`, and the
TTL sweep can never reclaim them because it only inspects entries still in the dict.

Test approach: two `POST /voice` requests for the same `CallSid`, the second well inside
`pending_ttl_s`. Assert (a) the first session's `close()` was awaited, (b) exactly one
entry exists for that key afterwards, (c) the surviving session is the one the *second*
request created, (d) a subsequent WS `start` adopts that surviving session — proving the
replacement is coherent end to end rather than merely tidy — and (e) **the supersede is
logged with the `CallSid`**, because Phase 5 defers the idempotency-token optimisation
on the strength of that log line being the observable that retries are real here. Rules out both the bare
write and the "keep the first, discard the second" variant, which orphans from the other
direction.

**Seam 17: the `decana` console entry point starts under the tracer's env profile.**

Wrong implementations a naive test passes: a `main()` that mis-wires the composition
root — passes `live_factory` without its `api_key` partial, forgets `root=` on
`load_profile` (profile-loader Q7, whose W-1 says the default assumes an editable
install), or builds `create_app` with arguments in the wrong order. **All sixteen other
seams pass every one of these**, because each drives `create_app` *directly* and
§2's smoke does the same. Nothing in this plan ever executes `main()`.

**This is a named requirement of the ratified parent gate, not an extra.**
`vertical-profile-bridge.md:233` lists, for this slice: *"`__main__` smoke: `decana`
starts with the tracer's optional env."* The `[project.scripts] decana =
"decana.__main__:main"` entry that gate depends on
(`vertical-profile-bridge.md:52`) **does not exist in `pyproject.toml` today** — the
file has no `[project.scripts]` section at all — so adding it is part of this slice's
deliverable, not an assumption about the environment.

Test approach — two cases, both subprocess-level:
- **(a) it starts, and the route is registered.** Spawn the `decana` entry point with the
  tracer's env profile: `DECANA_PROFILE`, `GEMINI_API_KEY` and `PUBLIC_WSS_URL` set,
  **Twilio and SMTP vars deliberately absent** (the feature's env table marks exactly
  those "tracer: optional, unused", so a `Settings` demanding them would break the
  tracer). Assert the process comes up and that `POST /voice` is **registered** — by
  POSTing a body missing the required fields and asserting FastAPI's 422, **not** by
  driving a successful webhook. Then terminate.

  **Why not a successful POST — correcting an earlier draft of this seam.** S3-Q1 makes
  `POST /voice` call `live_factory(profile)` unconditionally on every well-formed
  webhook, and `open_live_session` opens a real socket at `live.py:363-364`. So a
  successful POST *would* hit the network, and the earlier claim here that "no Gemini
  request is made" was wrong. Worse, with a placeholder key a successful POST is
  **non-discriminating**: a wrongly-wired factory and a correctly-wired one with a fake
  key both produce Seam 14's graceful `<Hangup/>`, so the test could not tell them
  apart.

  **What this seam does and does not catch, stated rather than implied.** Startup
  catches every composition error that raises when `main()` builds the app — wrong
  argument order, a missing required argument, a bad `load_profile(root=…)` call. It
  does **not** catch a factory wired without its `api_key` partial, which only fails
  when the factory is invoked; that is covered by §2's smoke, which runs against the
  real API with a real key.
- **(b) it fails loudly on a missing required var.** Unset `DECANA_PROFILE`; assert
  **exit code 2** and that the message **names the variable**, which is S3-Q11's ratified
  behaviour and otherwise has no test anywhere in this slice.

Rules out: the whole class of composition-root wiring errors that unit tests structurally
cannot see, because every unit test constructs the app itself rather than letting the
process do it. On the tracer this failure mode is a container that will not boot.

**Seam 9: the real `BridgeSession` composes with the async server (premise P3).**

Wrong implementation a naive test passes: mocking `BridgeSession`. That proves the
server calls a mock and says **nothing** about `PR-bridgesession-composes-with-async-io`,
which is the whole integration risk this slice carries and whose falsification re-opens
Seam 4's ratified 16-behavior contract under Article 8.

Test approach: the composed test uses the **real** `BridgeSession`, the **real**
`inbound_resampler()`/`outbound_resampler()`, the real `mulaw_*` codec and a real
`TimingRecorder` writing to `tmp_path`. Fakes exist at exactly two points — the Twilio
socket and the `LiveSession` — because those are the only true externals. Assert an
end-to-end pump: `start` → 50 `media` frames → several `AudioChunk`s **and at least one
`Transcript` of each role** → `stop` yields a `{call_sid}.jsonl` containing
`call_answered` and ≥1 `chunk_forwarded_to_twilio`, and a `CallRecord` whose
`timing_path` points at that file.

**Transcript fidelity, asserted not assumed.** The fake emits
`Transcript("caller", "A")`, `Transcript("model", "B")`, `Transcript("caller", "C")` in
that order; assert `record.transcript` is exactly
`(TranscriptTurn("caller","A"), TranscriptTurn("model","B"), TranscriptTurn("caller","C"))`.
Round 4's draft asserted a "non-empty and ordered" transcript while its stated fake
emitted only `AudioChunk`s — setup and assertion did not agree, and neither pinned
`role`. A mapper that tags every turn `"model"` regardless of source, or that reverses
order, passes "non-empty and ordered" and corrupts the one artifact S4's analysis
consumes. Rules out: the mock-shaped
suite that is green while the sync/async composition is broken — the failure that would
otherwise first appear on the tracer call.


## Exit criterion

The slice is done when all three hold.

---

### 1. Unit suite — a property over the ratified behavior ids, not over test names

> For each seam, **every behavior id below has a passing test node, and
> `tests/test_twilio_server.py` contains no test node that does not trace to an id in
> this list.** Both directions are required: the first catches a dropped behavior, the
> second catches a test that drifted in without ratification.

This is `profile-loader` Q21's formulation, adopted deliberately rather than
re-derived. Test names are not the criterion — they broke that slice's criterion when
three of four named tests turned out not to exist. Each test's docstring opens with its
id, so the mapping is checkable by reading the file.

**A parametrised id expands to one node per parameter**, and the parameter names are
part of the id (e.g. `S3.a[twilio_stop]`). The count below is nodes, not functions.

### The closed id set

| id | behavior | nodes |
|---|---|---|
| `S1.a` | `live_factory` invoked during `POST /voice`, before the WS connect | 1 |
| `S1.b` | the adopted session `is` the object the factory returned | 1 |
| `S1.c` | the fake exposes no `.start()`; S3 never reaches for one | 1 |
| `S2.a` | N chunks emitted pre-connect + M post arrive as N+M in emission order | 1 |
| `S3.a` | five endings, each: `close()` once, `on_call_end` once, correct `ended_reason` | 5 |
| `S3.b` | `stop` + disconnect raced: still exactly one of each, reason is the winner | 1 |
| `S3.c` | teardown order is drain-stop → bridge → gemini → record | 1 |
| `S3.d` | `started_at`/`ended_at` equal the injected clock's exact values | 1 |
| `S4.a` | `on_call_end` raising does not escape the handler | 1 |
| `S4.b` | it is logged with `call_sid` and exception type | 1 |
| `S4.c` | `close()` still called exactly once; `on_call_end` not retried | 1 |
| `S4.d` | a concurrent second call completes normally with its own record | 1 |
| `S5.a` | `send_media` never propagates; failure maps to `twilio_send_failed` | 1 |
| `S5.b` | post-teardown `send_media` is a silent no-op | 1 |
| `S5.c` | every outbound frame carries root `streamSid` from `start`, backlog frames included | 1 |
| `S6.a` | TwiML parses as `Response/Say` + `Response/Connect/Stream/Parameter` | 1 |
| `S6.b` | `Say` text equals the disclosure exactly; `Stream/@url` is `{public_wss_url}/media` | 1 |
| `S6.c` | hostile disclosure and `From` (`&`, `<`, `>`, quote) still parse; text round-trips | 1 |
| `S7.a` | `caller_number` normalisation, parametrised over the documented value set | 6 |
| `S8.a` | a call whose socket arrives past the TTL is adopted, not reaped | 1 |
| `S8.b` | a true orphan is closed and dropped | 1 |
| `S8.c` | Event-gated: a concurrent sweep does not raise when an entry is popped under it | 1 |
| `S9.a` | composed pump with the real bridge writes `call_answered` + ≥1 `chunk_forwarded_to_twilio` | 1 |
| `S9.b` | `record.transcript` equals the exact expected `TranscriptTurn` tuple, both roles | 1 |
| `S9.c` | `record.timing_path` points at the written JSONL | 1 |
| `S10.a` | `BridgeSession.close()` raising: no escape, `ended_reason="error: <type>"` | 1 |
| `S10.b` | `on_call_end` still awaited exactly once with the partial record | 1 |
| `S10.c` | a concurrent second call is unaffected | 1 |
| `S11.a` | unknown `CallSid` on `start`: `live_factory` not called, socket closed | 1 |
| `S11.b` | no `CallRecord`, `on_call_end` not awaited, miss logged | 1 |
| `S11.c` | **no outbound media frame is sent** before the socket closes | 1 |
| `S12.a` | `connected` / `mark` / `dtmf` absorbed; no exception, no teardown | 3 |
| `S12.b` | `media` after them still forwarded; call ends normally on `stop` | 1 |
| `S12.c` | the transcript and the `CallRecord` are unchanged by the absorbed messages | 1 |
| `S13.a` | `Interrupted` mid-stream: no exception, logged, no teardown | 1 |
| `S13.b` | events after it still flow; call ends on `stop` | 1 |
| `S14.a` | `live_factory` raising: 200 not 500; body parses as `Say` + `Hangup`, `Say` text equals the disclosure | 1 |
| `S14.b` | nothing registered — a later `start` for that `CallSid` hits `S11`'s path | 1 |
| `S14.c` | the factory failure is logged with the `CallSid` | 1 |
| `S15.a` | two concurrent calls, reversed connect order: each record's content traces to its own session | 1 |
| `S15.b` | each adopted session `is` the object its own `live_factory` call returned | 1 |
| `S16.a` | re-registering a `CallSid` awaits the superseded session's `close()` | 1 |
| `S16.b` | exactly one entry survives, it is the second request's, and a later `start` adopts it | 1 |
| `S16.c` | the supersede is logged with the `CallSid` (Phase 5 item 4's revisit trigger) | 1 |
| `S17.a` | the `decana` entry point starts under the tracer env profile and serves `POST /voice` | 1 |
| `S17.b` | a missing required env var exits 2 and names the variable | 1 |

**46 ids, 57 nodes.** Suite total after this slice: 178 + 57 = **235**.

Counted mechanically by summing the nodes column, not by hand: an earlier draft of this
table claimed 47 by hand-count and was wrong, which is the same defect `profile-loader`
Phase 4 hit twice ("wrong hand-typed totals ×2"). The number in this row is reproduced
by regex-summing the table, and the implementer should re-derive it from
`pytest --collect-only` rather than trusting it.

---

### 2. Real-environment smoke — executable, no human oracle

`scripts/smoke_twilio_server.py`. **Everything except the Twilio leg is real**: the real
`create_app`, the real `open_live_session` against the live Gemini API, a real uvicorn
server, a real HTTP webhook POST, and a real WebSocket client. Only Twilio itself is
simulated — which is exactly the leg that is blocked on provisioning, and exactly the
leg the tracer (feature step 4) exists to prove.

Sequence:
1. Start the app on a local port with the real profile and the real Gemini factory.
2. `POST /voice` with a form-encoded body mimicking Twilio (`CallSid`, `From`).
3. Parse the returned TwiML; extract the `<Stream url>`.
4. Open a real WebSocket to `/media`; send `connected`, then `start` carrying the
   `CallSid` and `customParameters.caller`.
5. Send ~100 real μ-law frames (a WAV read from disk, chunked to 160 bytes at 20 ms
   cadence, the real Twilio shape).
6. Read outbound frames until **either** ≥1 frame has arrived and 2 s have passed with
   no new frame (the greeting finished), **or** a hard cap of **20 s** elapses. Then
   send `stop` and wait for teardown.

   Both numbers are anchored, not chosen: S2's smoke measured first greeting audio at
   3229 ms, and the premise log records 3.5–4.0 s across runs, so a 20 s cap is ~5×
   the observed worst case and a 2 s quiet-gap is ~33× the ~61 ms soxr burst interval
   measured for the outbound direction. **A too-short window is a false negative in the
   smoke's own ≥1-frame assertion**, which is why it gets a stated value rather than
   being left to the implementer.

Assertions, all machine-checkable:
- the TwiML parsed, and `Say` carried the profile disclosure;
- **≥1 outbound media frame arrived**, each with root `streamSid` equal to the one sent
  in `start` — the greeting reached the socket;
- decoding the outbound payloads through `mulaw_decode` yields **non-silent** audio —
  **RMS ≥ 0.005 of full scale (≥ 164 on the int16 scale)** — so the path carried real
  audio rather than zeros;

  **The floor is measured, not chosen.** Round-tripping through this repo's own
  `mulaw_encode`/`mulaw_decode` (1 s at 8 kHz, measured 2026-08-27):

  | signal | round-trip RMS | fraction of full scale |
  |---|---|---|
  | digital silence | **0.00** | 0.000000 |
  | line noise ~−60 dBFS | 34.22 | 0.001044 |
  | speech level ~−18 dBFS | 1450.43 | 0.044264 |

  μ-law round-trips digital zero to exactly zero, so the failure this assertion guards —
  a path that emits silence — has a hard floor of 0.00, and any threshold above the
  noise row discriminates it by orders of magnitude. 0.005 sits ~5× above a −60 dBFS
  line-noise floor and ~9× below speech level.

  **Honest limit on the anchor:** the silence end is exact and is the actual failure
  mode; the speech end is a synthetic formant-like tone, not real Gemini TTS, so it
  bounds the threshold from above only approximately. If a real greeting ever measures
  below 0.005 the assertion is wrong and the number moves — recorded as the
  falsification condition rather than left implicit. Logged as an Open Item for owner
  ratification, following `gemini-live`'s treatment of its own "≥5 words" threshold,
  which was measured, kept, and still surfaced.
- `{call_sid}.jsonl` exists, containing `call_answered` and ≥1
  `chunk_forwarded_to_twilio`;
- `on_call_end` fired exactly once with a `CallRecord` whose transcript is non-empty and
  whose `ended_reason` is `twilio_stop`.

**Recorded but NOT gated: time from `start` to the first outbound frame.** This is the
number that predicts whether the tracer meets A3, and it is the first end-to-end
measurement of it — but the ratified threshold is measured on a real PSTN call with the
disclosure playing, so asserting a locally-measured proxy against it would be inventing
a threshold the feature did not ratify. Printed, logged into the smoke's output, and
carried into the artifact's handoff notes for S6/S7 to use.

**No human oracle is required**, so per the slice-builder's split-by-oracle rule this
runs to completion and its full output goes in the transcript; it is not a stop.

---

### 3. Checks

`ruff check`, `ruff format --check`, and `mypy --strict` clean over `src`, `scripts`
**and `tests`**. Note `pyproject.toml` scopes mypy to `files = ["src", "scripts"]`, so a
bare `uv run mypy` does **not** check the test suite — S2's slice found two real errors
there that the scoped run reported clean. Check `tests/` explicitly.

---

### What proves DONE

The id-set property in §1 shown to hold in both directions with the suite run visible in
the transcript; the smoke in §2 run to completion with its full output and its recorded
time-to-first-frame; §3 clean. Not a generic "the server works".


## Deferred to later slices

### Deferred, each with a revisit trigger

1. **The real PSTN call.** This slice proves composition against everything except the
   Twilio leg. — why later: the tracer is feature step 4 and needs S6 deployed plus a
   provisioned number and public URL; neither exists. — **trigger:** S6 deployed and the
   Twilio number's voice webhook pointed at `POST /voice`.

2. **Retry, reconnection and backpressure policy.** — why later: `voice-intake-demo`
   Q22 part 3 is ratified and still governs — *a dropped call is a measurement result,
   not a bug to engineer around before the first measurement*. Engineering resilience
   now would mask the signal the tracer exists to produce, in the direction that hides
   failure. — **trigger:** a dropped or degraded call during the tracer or S7 that the
   measurement does **not** explain.

3. **A real-collaborator concurrency test (W-4).** No seam drives the real
   `BridgeSession`/`Resampler` pair under two simultaneous calls; Seam 9 is real but
   single-call, Seam 15 is concurrent but uses Protocol fakes. — why later: P3's named
   falsifier is the tracer, and a real-collaborator concurrent harness is disproportionate
   at slice scope. — **trigger:** the first two overlapping real calls, or any evidence of
   cross-call interference in a tracer/S7 transcript.

4. **`I-Twilio-Idempotency-Token` as a registration optimisation.** S3-Q14 closes the
   correctness hole without it. — why later: it would make behaviour depend on a
   vendor-specific header being present and propagated, for a saving (not opening a
   second session at all) that only matters at volume. — **trigger:** S3-Q14's
   supersede path logs at all. That path closes a superseded session and logs it, so a
   single occurrence in the logs is the observable signal that retries are real in this
   deployment; frequency is then judged from the same log line. (An earlier draft said
   "often enough… to make it a real cost", which named no observable — a trigger nobody
   can detect is a deferral with no revisit.)

5. **`sequenceNumber` gap and reorder detection.** Twilio numbers its messages; S3
   ignores the field. — why later: no loss- or reorder-handling behaviour is claimed
   anywhere, so there is nothing to enforce, and inventing it before a measurement is
   the same error as item 2. — **trigger:** audible gaps or ordering artifacts in a real
   call that the timing JSONL does not otherwise explain.

6. **Deployment (S6), post-call analysis (S4), dispatch (S5).** — why later: separate
   ratified slices in the feature DAG. — **trigger:** their own place in the build order,
   `S1 → S2 → S3 → S6 → S4 → S5 → S7`.

6b. **UK-region cloud storage for transcripts.** — why later: only scripted and test
   callers until the first prospect. — **trigger, carried verbatim from the feature
   artifact:** *before the first real client's transcript is written.*

   Split out of item 6 rather than bundled with it. UK storage is a **feature-level
   deferral** (`vertical-profile-bridge.md:262`), not a slice in the DAG — it has no slot
   in `S1→S7` to reach, so the build-order trigger that is correct for S4/S5/S6 is
   **structurally inert** for it: the stated event can never occur, and the deferral could
   never be revisited by watching the build order. This slice writes the timing JSONL to
   a local `artifact_dir`, so it is one of the places that decision lands.

7. **Barge-in / interruption handling beyond logging `Interrupted`.** — why later: no
   mid-call intervention is ratified. — **trigger, carried verbatim from the feature
   artifact:** *a demo caller reports being talked over.*

   **Two different things must not be conflated here, and an earlier draft of this item
   conflated them.** Feature Q4 ratifies that S3 treats the `Interrupted` event as a
   log-only no-op *for the calls this feature builds* — that is in scope, decided, and
   tested by Seam 13. The **barge-in feature question** is separate and is **deferred,
   not cut**: `vertical-profile-bridge.md:263` lists it under "Deferred to later
   features" with the live trigger above. That artifact marks genuine cuts explicitly —
   "landing page (permanently cut)" at line 32 — and barge-in carries no such mark.

   The earlier draft called it "permanently cut", which is the harmful direction of the
   error: a reader holding only this slice artifact would have found no trigger to
   revisit, so a caller reporting being talked over during S7 would be logged correctly
   by Q4's mechanism and acted on by nobody. Recorded rather than silently corrected,
   because the item was written to warn against exactly this confusion and then made the
   opposite version of it.

## Watching (standing concerns)

- **W-1 (inherited from `profile-loader`).** Q7's `profiles_root` default assumes an
  editable install. If S6's Dockerfile installs non-editable, `DECANA_PROFILES_ROOT` must
  be set explicitly. **Action if triggered:** set it in the deploy config and record in
  `docs/deploy.md`. This slice's `__main__.py` is where it is read, so S6 inherits it
  directly.

- **W-2. The greeting backlog is flushed to Twilio as one burst.** S3-Q3 sends it through
  the normal path with no pacing; the measured greeting is ~311 KB of 24 kHz PCM (~6.5 s),
  ~52 KB of μ-law after downsampling. Twilio buffers and plays in order, so this is
  accepted rather than engineered around. **Watch for:** audible clipping or truncation at
  the start of the AI's first utterance on a real call. **Action:** pace the backlog flush
  at the 20 ms cadence Twilio expects, rather than emitting it as fast as the socket takes it.

- **W-3. The TTL sweep can still close a live session in one narrow window.** S3-Q4's
  pop-before-sweep closes the self-race; a *different* concurrent request's sweep can
  still close a pending entry the instant it crosses the TTL while its socket is
  mid-handshake. The window is ~60 s of TTL against a disclosure measured in seconds —
  about an order of magnitude. **Watch for:** a caller reaching Seam 11's fail-loudly path
  with a webhook that demonstrably ran. **Action:** mark entries as adopting before the
  await, and have the sweep skip marked entries.

- **W-4. Real collaborators are never driven concurrently** — see deferred item 3. The
  reason it is a watch item and not only a deferral: P3's falsification re-opens Seam 4's
  ratified 16-behavior contract under Article 8, so this is the failure with the widest
  blast radius in the slice.

- **W-5. The smoke's RMS floor rests on a synthetic speech anchor.** The silence end is
  exact (digital zero round-trips to 0.00 through this repo's codec, hand-verified); the
  speech end is a formant-like tone, not Gemini TTS. **Watch for:** the first smoke run
  against the real API measuring below 0.005 of full scale. **Action:** re-anchor the
  floor to the measured real greeting and record the new number — the threshold moves, the
  assertion does not.

## New premise-log rows this slice adds

Written with the log's full schema — `level`, `checked` and `depended-on-by` included,
which an earlier draft omitted.

| id | statement | level | status | evidence | checked | depended-on-by |
|---|---|---|---|---|---|---|
| `PR-twiml-say-precedes-stream` | `<Connect><Stream>` is terminal and TwiML verbs run in order, so the media WebSocket opens only after `<Say>` finishes. | `slice` | `verified` | twilio.com/docs/voice/twiml/stream, fetched 2026-08-27; quoted verbatim in P1. **Falsification:** a Twilio change making `<Connect>` non-terminal, or observing the socket open during `<Say>` on a real call. | 2026-08-27 | `slice:twilio-server` S3-Q1 and Seam 1; `feature:vertical-profile-bridge` A3 via `PR-gemini-live-greeting-on-connect` |
| `PR-twilio-webhook-retries` | Twilio may invoke `POST /voice` more than once for one `CallSid` (timeout/5xx retry, fallback URL). | `slice` | `verified` | Twilio voice webhook docs + the existence of `I-Twilio-Idempotency-Token`, 2026-08-27. **Falsification:** documented removal of webhook retries. | 2026-08-27 | `slice:twilio-server` S3-Q14 and Seam 16 |
| `PR-twilio-wire-shapes` | The documented `connected`/`start`/`media`/`stop`/`mark`/`dtmf` shapes and the outbound root-`streamSid` shape match what a live stream actually sends. | `slice` | `accepted-as-risk` | Docs read 2026-08-27; **no source to read** — a wire protocol, not an installed SDK, so the "read the source" mitigation that caught three defects in S2 is unavailable by construction. **Falsifier: the tracer call (feature step 4).** | | `slice:twilio-server` S3-Q13, Seams 5(b), 12; `feature:vertical-profile-bridge` tracer |
| `PR-caller-id-not-always-e164` | Twilio's `From` is not always E.164; withheld or unnormalisable IDs arrive as `anonymous`, `unknown`, or a raw string. | `slice` | `verified` | twilio.com/docs/voice/twiml request-parameters, 2026-08-27. **Falsification:** a `From` that is neither E.164 nor a documented sentinel reaching S5's SMS path. | 2026-08-27 | `slice:twilio-server` S3-Q6, Seam 7; `slice:post-call-dispatcher` SMS send |

## Open items requiring human decision

1. **The smoke's RMS floor, 0.005 of full scale.** Measured, not chosen — digital
   silence round-trips to exactly 0.00 through this repo's own μ-law codec
   (hand-verified), a −60 dBFS line-noise floor measures 0.001044, and speech level
   measures 0.044264. **Recommended: keep 0.005** because it discriminates the actual
   failure (a path emitting zeros) by orders of magnitude while sitting ~9× below
   measured speech. Surfaced anyway because it is a numeric threshold in an exit
   criterion, following `gemini-live`'s treatment of its own measured-and-kept "≥5
   words". **Limitation stated in the criterion:** the speech anchor is a synthetic
   formant-like tone, not Gemini TTS. Falsification: a real greeting measuring below
   0.005 on the first smoke run (W-5).

2. **Two additions to the ratified `create_app` signature** — `clock` and
   `pending_ttl_s`, both keyword-only with defaults, so every ratified call site keeps
   working. **Recommended: keep both.** `clock` is required to test S3-Q7's timestamp
   provenance and S8's TTL behaviour without sleeping; `pending_ttl_s` is the bound on
   S3-Q4's orphan reaper. Flagged rather than slipped in because the five-parameter
   signature is ratified feature text.

3. **Phase 3 ran to 9 rounds, past the round-4 circuit breaker.** Surfaced mid-run and
   answered by the owner 2026-08-27: *one scoped round on the newly-opened emergent
   axis, then proceed to Phase 4 regardless of verdict.* Recorded here because the
   circuit breaker exists to catch oscillation and was deliberately overridden on the
   grounds that the rounds were converging monotonically — 9 distinct findings, none
   reversed, each smaller in blast radius than the last.

## Critic notes (non-blocking)

- **`connected` is a deliberate no-op**, not an oversight — it carries only `protocol`
  and `version`, no `streamSid`, no `CallSid`, so there is nothing to bind a call to
  yet. `start` is where a call begins.
- **`CallRecord.profile_name` has no seam**, deliberately: a pass-through of the
  injected `profile`, same standing as S3-Q11's env mapper.
- **Cross-slice citation hazard.** `Q19` and `Q20` belong to `voice-intake-demo` (the
  bridge slice), not to S2 `gemini-live`; `Q4` belongs to `gemini-live`. An earlier
  draft of this artifact miscited two of the three. A wrong citation sends the next
  reader to a decision that does not exist.
- **The node count has been wrong every time a human produced it** — 45, 47, 52 were all
  hand-counts, and `profile-loader`'s Phase 4 hit the same defect twice. The figure in
  the Exit criterion is regex-summed; the implementer should re-derive it from
  `pytest --collect-only` rather than trust it.
