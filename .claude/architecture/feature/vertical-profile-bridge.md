# Feature vertical-profile-bridge — decomposition

Status: PLANNED 2026-08-26 (feature-architect). Phase 1 owner-ratified; Phase 2 owner-accepted at round-4 cap (see escalations); Phases 3–4 feature-critic PASS. Nothing built yet beyond `src/decana/bridge/`.

## Goal
The bridge becomes a working phone line: a real Twilio number, a real Gemini Live session, one conversation per call, one post-call follow-up. Everything that makes it "for UK mortgage brokers" lives in a *vertical profile* — `profiles/<name>/` with `profile.toml` (phone number, SMS sender id, operator email, model names, allowed outcomes, SMS templates + links per outcome) and three prompt files (`disclosure.md`, `conversation.md`, `analysis.md`). Switching vertical = another profile directory selected by `DECANA_PROFILE`; zero Python changes. `src/decana/bridge/` (codec, resampler, timing, session — 66 tests green) is the vertical-agnostic audio pipe this feature wires to real clients. This demo is the base of the production system, not a throwaway.

## Acceptance criteria (owner-ratified 2026-08-26)
- **A1** A real call to the Twilio number is answered; the caller hears the profile's disclosure line first, then a conversation driven by the profile's conversation prompt.
- **A2** When post-call analysis classifies the call as `new_client`, exactly one SMS with the profile's links reaches the caller's phone (Twilio caller ID). Not two, not zero. Other outcomes get no SMS unless the profile defines a template.
- **A3** On these real calls the prior slice's latency criterion holds: audible answer ≤3000 ms, no mid-response gap >1500 ms, 3 calls, every turn (methodology: `.claude/overseer/slice/voice-intake-demo.md` Exit criterion).
- **A4** A second throwaway profile (`eco-consultant`) runs a call end-to-end; `git diff` between the two runs touches only `profiles/`, zero lines in `src/`.

## Build parameters (owner-authorized, Phase 1e)
- Budgets: answer ≤3000 ms audible; mid-response gap ≤1500 ms; SMS exactly one per CallSid (decide-later: within 60 s of call end); post-call analysis timeout 30 s → `unclassified`, no SMS, brief still sent.
- Policies: frame errors = Q6 catch-drop-continue (unchanged); call-level failure = log, guarded single teardown, still run post-call on whatever transcript exists; every side effect keyed by CallSid; timing JSONL per call; transcript/analysis/brief files beside it.
- Ratified decisions: **no mid-call intervention** (no guardrail regex, no tool calls) — guardrails live in `conversation.md`, compliance is judged post-call by `analysis.md`; **disclosure is non-generative** — Twilio `<Say>` speaks `disclosure.md` verbatim before the stream opens; config = TOML + separate `.md` prompts, secrets env-only; runtime = Google Cloud Run `min-instances=1`; email via stdlib `smtplib`; deps pre-approved: `google-genai`, `twilio`, `fastapi`, `uvicorn`, `websockets` (`uv add` still prompts).
- Risk tolerance: auto-run spikes against real Gemini = yes; proceed on PASS = yes; only FALSIFIED interrupts. Real PSTN calls are owner-dialled scheduled steps.
- Autonomy: plan+build all slices automatically; interrupt only for the critical set; batch questions.

## Premises (see `.claude/premises/premise-log.md`, rows tagged `feature:vertical-profile-bridge`)
| id | status | verified by |
|---|---|---|
| PR-gemini-live-greeting-on-connect | unverified | S2 spike (unprompted speech), tracer (real) |
| PR-gemini-live-transcription-events | unverified | S2 spike, S7 calls |
| PR-bridgesession-composes-with-async-io | unverified | S3 fakes, tracer (real) |
| PR-cloud-run-sustains-media-stream | unverified | tracer (composition), S7 (latency) |
| PR-profile-fully-determines-vertical | unverified | S7 step 7b (A4) |
| PR-sms-deliverability | unverified | S7 step 7a (A2) |

## Out of scope (deliberately)
CRM/case data; Calendly webhooks/analytics; automated transcript QA harness; multi-language; rate limiting; A/B prompts; retention/deletion tooling; UK-region cloud storage for transcripts (local file now — revisit before the first real client call); landing page (permanently cut); any mid-call intervention; barge-in logic beyond S2 surfacing `Interrupted`.

## Open items requiring human decision — RESOLVED 2026-08-26 (owner chose the recommended option for both; see escalations.md)
1. **SMS idempotency marker order.** Marker written before the send (at-most-once): a crash can never produce two SMS; a send failure after the marker leaves zero SMS, recorded in the brief/email for manual resend. Alternative: mark after send (at-least-once, duplicate possible). **Recommended: keep at-most-once** — a duplicate to a prospect is visible and embarrassing; a miss is caught by the brief.
2. **A4 on the same Twilio number.** Step 7b redeploys the same service + number with `DECANA_PROFILE=eco-consultant` for one call, then reverts. Alternative: provision a second number (another hard-to-undo act). **Recommended: same number.**


---

# Slices (Phase 2 — decompose, owner-accepted)


Feature: vertical-profile-bridge. Existing: `src/decana/bridge/{codec,resampler,timing,session}.py` — sync, dependency-injected, 66 tests green. `BridgeSession(twilio, gemini, timing, inbound, outbound)` with `start()`, `handle_twilio_frame(base64)`, `handle_gemini_chunk(pcm24k)`, `close()`. Protocols: `TwilioMediaStreamClient.send_media(base64)`, `GeminiLiveSessionClient.send_audio(pcm16k)`.

## Slices

- **S1 profile** — `src/decana/profile/`. Delivers: `load_profile(name, root=Path("profiles")) -> Profile` — frozen dataclass with the TOML fields + the three prompt texts; validates at load (required fields, prompt files exist, `[sms.<outcome>]` keys ⊆ `outcomes.allowed`, template placeholders resolvable). Ships `profiles/mortgage-broker/` and `profiles/eco-consultant/` (the A4 fixture) with valid, DRAFT-marked placeholder content — the owner authors the real prompt text before S7 (corrected 2026-08-26 to match §Sequence step 1; was "with real content"). Pure: no network. Depends on: —.

- **S2 gemini-live** — `src/decana/gemini/live.py`. Delivers: an async client over `google-genai` Live that (a) opens a session with `system_instruction=profile.conversation` + input/output transcription enabled (the disclosure is NOT the model's job — S3 plays it via Twilio `<Say>` before the stream opens; `conversation.md` states the disclosure has already been given), (b) sends the greeting trigger text turn on open so the model opens the conversation right after the `<Say>` ends, (b′) the sync `send_audio` Protocol is satisfied by an adapter: sync call enqueues, a background task drains the queue into the async Live session; a failed async send is surfaced as a `Closed` event rather than lost — (c) implements `GeminiLiveSessionClient.send_audio`, (d) exposes an async iterator of events: `AudioChunk(pcm24k: bytes)`, `Transcript(role: caller|model, text)`, `Interrupted`, `Closed`. Accumulates transcript in order. Verified by a spike: WAV in → audio + transcript out, timings logged. Depends on: S1 (for the prompt text only; can be spiked with a literal).

- **S3 twilio-server** — `src/decana/twilio/server.py`. Delivers: FastAPI app with (a) `POST /voice` returning TwiML `<Say>{profile.disclosure}</Say><Connect><Stream url=wss://.../media><Parameter name="caller" value="{From}"/></Stream></Connect>` — **the disclosure is spoken by Twilio's TTS, verbatim from `disclosure.md`, before the Gemini stream opens.** This is the MVP doc's ratified "hardcoded, non-generative disclosure line … so disclosure can't be skipped by model behaviour", and it is the only path that guarantees the compliance text verbatim; the model is never asked to say it. `conversation.md` tells the model the disclosure has already been given. The `From` number rides in as a `<Parameter>` because Twilio's `start` message does not carry the caller number natively. Measurement consequence for A3: the caller hears speech within ~1 s (Twilio `<Say>`), so the ≤3000 ms audible-answer check measures to the START of `<Say>`; the silence between the end of `<Say>` and the model's first utterance is a **mid-response gap** under the ≤1500 ms rule, which is where Gemini connect + greeting latency now shows up. (b) `WS /media` handling Twilio `connected/start/media/stop`, constructing one `BridgeSession` per `start` (CallSid, caller number from `customParameters`/start), pumping `media` → `handle_twilio_frame`, and routing S2's event stream by type: `AudioChunk.pcm24k` → `handle_gemini_chunk`; `Transcript` → appended to the call's transcript list; `Interrupted` → log-only no-op (Q4); `Closed` → teardown. On Twilio `stop` (or `Closed`) → `close()`, then calls an **injected** `on_call_end: Callable[[CallRecord], Awaitable[None]]` with `CallRecord(call_sid, caller_number, transcript, timing_path)`. S3 does not import S4/S5 — same DI convention as `TwilioMediaStreamClient`/`GeminiLiveSessionClient`; the tracer passes a no-op that logs the record, and the composition root wires the real handler once S4/S5 exist. Implements `TwilioMediaStreamClient.send_media` via the mirror of S2's adapter: the sync call enqueues the base64 frame onto an ordered `asyncio.Queue`; one background task per call drains it into `websocket.send_text(media message)` in FIFO order; a failed send closes the queue and triggers the same teardown path as Twilio `stop`, so the failure reaches `close()` + `on_call_end` rather than being lost. **S3 also owns the composition root:** `create_app(profile: Profile, gemini_factory, on_call_end) -> FastAPI` (testable with fakes) and `src/decana/__main__.py` + `[project.scripts] decana = "decana.__main__:main"` which reads `DECANA_PROFILE` and secrets from env, calls `load_profile`, builds the real S2 client factory, wires `on_call_end` (a log-only no-op until S5 exists; then `S5.post_call`), and runs uvicorn. This is the process the Dockerfile's `CMD` starts. Depends on: S2 (event shape), S1 (profile), existing bridge. Defines `CallRecord(call_sid: str, caller_number: str, transcript: list[TranscriptTurn(role: Literal["caller","model"], text: str)], timing_path: Path)`, which S4/S5 consume; S4 serializes the turn list into the analysis prompt as `CALLER: …\nMODEL: …` lines.

- **S4 post-call-analysis** — `src/decana/analysis/`. Delivers: `analyse(transcript, profile) -> Analysis(outcome: str, compliance_notes: list[str], summary: str)` via one `google-genai` text call with `profile.analysis` as system instruction and structured JSON output constrained to `outcomes.allowed` (+ `unclassified`). 30 s timeout → `unclassified`. Depends on: S1, S3 (`TranscriptTurn` / `CallRecord.transcript` shape).

- **S5 dispatcher** — `src/decana/dispatch/`. Delivers: `dispatch(record: CallRecord, analysis: Analysis, profile) -> None`: writes `transcript` + `brief` files next to the timing JSONL; sends ≤1 SMS via `twilio` if `profile.sms[outcome]` exists (idempotent per CallSid via a marker file); sends one email via `smtplib` to `profile.operator.email`. Every side effect independently try/except-logged so one failure doesn't block the others. Depends on: S1, S4 (Analysis shape), S3 (CallRecord shape). S5 also delivers `async post_call(record: CallRecord) -> None`: `analysis = await analyse(record.transcript, profile)`; `await dispatch(record, analysis, profile)` — the real `on_call_end` implementation; S5 replaces the body of `build_on_call_end` in the composition root and adds the Twilio/SMTP fields to `Settings` — the only S3-owned code S5 touches (corrected from "one line" in contracts round 1: the real factories need their secrets read).

- **S6 deploy** — `Dockerfile`, `cloudrun.yaml`/deploy script, `docs/deploy.md`. Delivers: the service running on Cloud Run with `min-instances=1`, `DECANA_PROFILE` + secrets from env, public wss URL wired into the Twilio number's voice webhook. Depends on: S3.

- **S7 real-call-verification** — human-executed, no code; **not routed through slice-planner/slice-builder** — handled as the prior slice's exit criterion was (owner dials, artifacts filed, architect reads them out). Delivers: the 3 scripted PSTN calls (A1, A3 artifacts: JSONL + turnlog), the A2 SMS receipt, and the A4 profile-swap call with `git diff` evidence. Depends on: S5, S6.

## Tracer bullet
**S1(min) → S2 → S3 → S6, one real call, caller hears the disclosure line from `profiles/mortgage-broker/disclosure.md` through Cloud Run.** This is the thinnest path that exercises the latency-critical integration premises: profile → prompt, existing BridgeSession ↔ async loop (PR-bridgesession-composes-with-async-io), greeting trigger (PR-gemini-live-greeting-on-connect), Cloud Run WebSocket + latency (PR-cloud-run-sustains-media-stream). PR-gemini-live-transcription-events (multi-turn ordering/completeness) is verified by S2's WAV-in spike and confirmed by S7's full calls, not by the tracer. S3 note for the contracts phase: S3 carries four concerns (TwiML endpoint, WS router, `CallRecord` types, composition root) — its behavior list must keep them as separately testable units (`create_app` with fakes; `__main__` is wiring only, no logic). S4/S5 are post-call and sit outside the latency-critical path; they compose against a `CallRecord` that the tracer already produces.

Order: S1 → S2 → S3 → S6 (tracer, owner dials once) → S4 → S5 → S7.

## What is NOT a slice
Guardrail regex (cut), tool calling (cut — no mid-call intervention), barge-in handling beyond S2 surfacing `Interrupted` (Q4's no-op stays a no-op), cloud transcript storage (deferred).

---

# Inter-slice contracts (Phase 3 — critic PASS)


Feature: vertical-profile-bridge. Decompose (converged, owner-accepted 2026-08-26): S1 profile · S2 gemini-live · S3 twilio-server+composition root · S4 analysis · S5 dispatch · S6 deploy · S7 real calls. All types are frozen dataclasses unless stated; all modules `mypy --strict` clean per `pyproject.toml`. Existing bridge contract is unchanged: `BridgeSession(twilio, gemini, timing, inbound, outbound)`, `TwilioMediaStreamClient.send_media(base64_mulaw: str) -> None`, `GeminiLiveSessionClient.send_audio(pcm16k: bytes) -> None` (`src/decana/bridge/session.py:37-46`).

## Edge S1 → S2, S3, S4, S5 — `Profile`

```python
# src/decana/profile/model.py
@dataclass(frozen=True)
class SmsTemplate:
    text: str                     # may contain {placeholders}
    links: Mapping[str, str]      # placeholder name -> URL; every {x} in text must be a key

@dataclass(frozen=True)
class Profile:
    name: str                     # directory name, e.g. "mortgage-broker" — identity (from the load_profile argument)
    display_name: str             # [vertical] name — human label, e.g. "UK mortgage broker intake" (added 2026-08-26, profile-loader Q12)
    live_model: str               # e.g. "gemini-2.5-flash-native-audio-preview-12-2025"
    analysis_model: str           # e.g. "gemini-2.5-flash"
    phone_number: str             # E.164, the Twilio number this profile answers on
    sms_sender_id: str            # alphanumeric sender id
    operator_email: str
    outcomes: tuple[str, ...]     # allowed outcome labels; "unclassified" is implicit and never in this tuple
    sms: Mapping[str, SmsTemplate]  # keys ⊆ outcomes
    disclosure: str               # disclosure.md, stripped
    conversation: str             # conversation.md
    analysis: str                 # analysis.md

# src/decana/profile/load.py
class ProfileError(ValueError): ...
def load_profile(name: str, root: Path = Path("profiles")) -> Profile
```
`load_profile` raises `ProfileError` (never a bare `KeyError`/`FileNotFoundError`/`tomllib.TOMLDecodeError`) with the offending field or file named, for: missing/extra top-level table, missing required key, missing prompt file, empty prompt file, `sms` key not in `outcomes`, a `{placeholder}` in `SmsTemplate.text` with no matching `links` key, `outcomes` containing `"unclassified"`. **Extended 2026-08-26 by the profile-loader slice plan (ratified there, threaded up here):** also for a non-bare `name` (path traversal), wrong-typed values, duplicate outcomes, unknown keys inside the fixed tables (strict schema; `[sms.<outcome>]` stays open beyond `text` for link keys), positional/attribute/index placeholders, and a link key never referenced in `text` (dead link). Full enumeration: `.claude/overseer/slice/profile-loader.md` § Seam. TOML layout is the frame's (`[vertical] name`, `[gemini] live_model analysis_model`, `[twilio] phone_number sms_sender_id`, `[operator] email`, `[outcomes] allowed`, `[sms.<outcome>] text + one key per link`).

## Edge S2 → S3 — Live client factory, events, sync adapter

```python
# src/decana/gemini/live.py
@dataclass(frozen=True)
class AudioChunk:      pcm24k: bytes          # raw PCM16LE mono 24 kHz, even length
@dataclass(frozen=True)
class Transcript:      role: Literal["caller", "model"]; text: str
@dataclass(frozen=True)
class Interrupted:     pass
@dataclass(frozen=True)
class Closed:          reason: str            # "remote" | "send_failed: <exc>" | "local"
LiveEvent = AudioChunk | Transcript | Interrupted | Closed

class LiveSession(Protocol):                   # what S3 consumes
    def send_audio(self, pcm16k: bytes) -> None: ...        # satisfies GeminiLiveSessionClient; sync, enqueues, never raises
    def events(self) -> AsyncIterator[LiveEvent]: ...       # yields until Closed, then stops
    async def close(self) -> None: ...                      # idempotent

LiveSessionFactory = Callable[[Profile], Awaitable[LiveSession]]   # what S3's create_app takes
async def open_live_session(profile: Profile, *, api_key: str, greeting_trigger: str = GREETING_TRIGGER) -> LiveSession   # the real factory
```
Guarantees S3 relies on: (a) session is configured with `system_instruction=profile.conversation`, `response_modalities=["AUDIO"]`, input and output transcription enabled; (b) `greeting_trigger` is sent as one text turn immediately after setup, before any `send_audio`; (c) `events()` yields `AudioChunk` in arrival order and `Transcript` in arrival order, interleaved as received; (d) exactly one `Closed` is the last event, whether the remote closed, `close()` was called, or a queued `send_audio` failed (reason `send_failed: …`); (e) `send_audio` after `Closed` is a silent no-op.

## Edge existing bridge → S3 — unchanged

S3 constructs `BridgeSession(twilio=<S3 socket adapter>, gemini=<LiveSession>, timing=TimingRecorder(clock=partial(datetime.now, UTC), sink_path=artifact_dir / f"{call_sid}.jsonl"), inbound=inbound_resampler(), outbound=outbound_resampler())`, calls `start()` on Twilio `start`, `handle_twilio_frame(media.payload)` per `media`, `handle_gemini_chunk(ev.pcm24k)` per `AudioChunk`, and `close()` exactly once from the guarded `_teardown` (see S3 guarantee (a)). No changes to `src/decana/bridge/`.

## Edge S3 → S4, S5 — `CallRecord`, `on_call_end`

```python
# src/decana/twilio/records.py
@dataclass(frozen=True)
class TranscriptTurn:  role: Literal["caller", "model"]; text: str        # same values as S2.Transcript; separate type so S4/S5 don't import S2
@dataclass(frozen=True)
class CallRecord:
    call_sid: str
    caller_number: str            # from TwiML <Parameter name="caller">; normalised: E.164 if it parses as one, else "" (Twilio sends e.g. "anonymous"/"+266696687" for withheld IDs — S3 checks against Twilio docs when built)
    profile_name: str
    started_at: datetime          # UTC, wall clock at Twilio `start`
    ended_at: datetime
    transcript: tuple[TranscriptTurn, ...]     # arrival order; may be empty
    timing_path: Path             # the JSONL this call's TimingRecorder wrote
    ended_reason: str             # "twilio_stop" | "ws_disconnect" | "gemini_closed: <reason>" | "twilio_send_failed" | "error: <type>"

OnCallEnd = Callable[[CallRecord], Awaitable[None]]

# src/decana/twilio/server.py
def create_app(profile: Profile, live_factory: LiveSessionFactory, on_call_end: OnCallEnd, *, public_wss_url: str, artifact_dir: Path) -> FastAPI
```
Guarantees: (a) **teardown is at-most-once and always completes.** Every path that ends a call — Twilio `stop`, WebSocket disconnect, S2 `Closed`, drain-task send failure, any unexpected exception in the handler — funnels into one `_teardown(reason)` coroutine guarded by a per-call `asyncio.Lock` + `done` flag, so `BridgeSession.close()` is called **exactly once** (Q19 names the double-invocation as the live risk: a second flush raises `RuntimeError("Input after last input")` by design and must not be swallowed inside `close()`). If `close()` raises anyway, `_teardown` catches it at the call site, logs it, sets `ended_reason="error: <ExceptionType>"`, and still awaits `on_call_end` exactly once with the `CallRecord` as it stands (partial transcript allowed — S5 tolerates empty). `on_call_end` is therefore awaited exactly once per `start`, after `close()` was attempted, regardless of how the call ended; a call that never reached `start` produces no record. `ended_reason` values: `"twilio_stop"`, `"ws_disconnect"`, `"gemini_closed: <Closed.reason>"`, `"twilio_send_failed"`, `"error: <type>"` — Twilio-side and Gemini-side send failures use distinct prefixes; (b) an exception from `on_call_end` is logged and does not affect the socket or other calls; (c) `POST /voice` returns `<Response><Say>{profile.disclosure}</Say><Connect><Stream url="{public_wss_url}/media"><Parameter name="caller" value="{From}"/></Stream></Connect></Response>` with `From` XML-escaped; (d) `WS /media` handles `connected`, `start`, `media`, `stop`, ignores `mark`/`dtmf`; (e) send side: sync `send_media` enqueues onto a per-call unbounded FIFO queue and **never raises** (after teardown it is a silent no-op) — it is called inside `BridgeSession._forward_to_twilio` under a catch scoped to `AudioFrameError` only (Q20), so any exception here would end the call; one task drains the queue into `{"event":"media","streamSid":…,"media":{"payload":…}}`; a failed send ends the call via `_teardown("twilio_send_failed")`.

Composition root (`src/decana/__main__.py`, script `decana`). Env contract, read in one place (`Settings.from_env()` in `src/decana/settings.py`, frozen dataclass; missing required → exit 2 naming the variable):

| var | required | used by |
|---|---|---|
| `DECANA_PROFILE` | yes | S1 `load_profile` |
| `DECANA_PROFILES_ROOT` | no (default: `<repo root>/profiles`, resolved from `decana.__file__`, never CWD) | S1 `load_profile(root=…)` — added 2026-08-26 by profile-loader Q7: `main()` must pass `root` explicitly |
| `GEMINI_API_KEY` | yes | S2 `open_live_session`, S4 `GeminiAnalysisClient` |
| `PUBLIC_WSS_URL` | yes | S3 TwiML |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | yes once S5 exists (tracer: optional, unused) | S5 `TwilioSmsSender` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | yes once S5 exists (tracer: optional, unused) | S5 `SmtpEmailSender` |
| `DECANA_ARTIFACT_DIR` | no (default `.claude/artifacts/calls`) | S3 timing, S5 files |
| `PORT` | no (default 8080) | uvicorn |

`main()` = `settings = Settings.from_env()`; `profile = load_profile(settings.profile, root=settings.profiles_root)`; `app = create_app(profile, live_factory=partial(open_live_session, api_key=settings.gemini_api_key), on_call_end=build_on_call_end(settings, profile), public_wss_url=…, artifact_dir=…)`; run uvicorn. `build_on_call_end` is the ONE function S5 changes: in the tracer it returns `log_only` (logs the `CallRecord` summary); after S5 it returns `partial(post_call, profile=profile, analysis_client=GeminiAnalysisClient(api_key=settings.gemini_api_key),   # model is per-call: analyse() passes profile.analysis_model sms=TwilioSmsSender(sid, token), email=SmtpEmailSender(host, port, user, password, from_addr), artifact_dir=…)`. Real factories are S4/S5 deliverables (below); `Settings` grows the Twilio/SMTP fields in S5 as optional-until-present so the tracer build never requires secrets it does not use.

## Edge S4 → S5 — `Analysis`

```python
# src/decana/analysis/model.py
@dataclass(frozen=True)
class Analysis:
    outcome: str                         # ∈ profile.outcomes | "unclassified"
    compliance_notes: tuple[str, ...]    # empty = nothing flagged
    summary: str                         # ≤ 600 chars, for the brief
    raw: str                             # model's raw JSON text; S5 writes it to {call_sid}.analysis.json
# src/decana/analysis/analyse.py
async def analyse(transcript: Sequence[TranscriptTurn], profile: Profile, *, client: AnalysisClient, timeout_s: float = 30.0) -> Analysis
class AnalysisClient(Protocol):
    async def generate_json(self, *, model: str, system: str, user: str, schema: Mapping[str, Any]) -> str: ...
# src/decana/analysis/gemini_client.py — the real one (S4 deliverable)
class GeminiAnalysisClient:
    def __init__(self, *, api_key: str) -> None: ...
    async def generate_json(...) -> str   # google-genai generate_content with response_mime_type="application/json", response_schema=schema
```
Guarantees: transcript is rendered as `CALLER: …` / `MODEL: …` lines in order; the JSON schema passed constrains `outcome` to `profile.outcomes + ("unclassified",)`; an empty transcript, timeout, API error, or unparsable/invalid-outcome response all yield `Analysis(outcome="unclassified", compliance_notes=(), summary="<reason>", raw=…)` — `analyse` never raises.

## Edge S5 ← S3, S4 — `dispatch`, `post_call`

```python
# src/decana/dispatch/dispatch.py
class SmsSender(Protocol):     def send(self, *, to: str, sender_id: str, body: str) -> str: ...   # returns message sid
class EmailSender(Protocol):   def send(self, *, to: str, subject: str, body: str) -> None: ...
# real implementations (S5 deliverables)
class TwilioSmsSender:   def __init__(self, account_sid: str, auth_token: str) -> None   # twilio.rest.Client.messages.create(to=, from_=sender_id, body=)
class SmtpEmailSender:   def __init__(self, host: str, port: int, user: str, password: str, from_addr: str) -> None   # smtplib.SMTP_SSL/starttls, one message
# both sync; dispatch awaits them via asyncio.to_thread so the event loop (and the next call's audio) is never blocked
async def dispatch(record: CallRecord, analysis: Analysis, profile: Profile, *, sms: SmsSender, email: EmailSender, artifact_dir: Path) -> DispatchReport
@dataclass(frozen=True)
class DispatchReport:  transcript_path: Path; brief_path: Path; sms_sid: str | None; email_sent: bool; errors: tuple[str, ...]
async def post_call(record: CallRecord, *, profile: Profile, analysis_client: AnalysisClient, sms: SmsSender, email: EmailSender, artifact_dir: Path) -> None   # analyse → dispatch; the real OnCallEnd after functools.partial
```
Guarantees: (a) evidence files first — `{artifact_dir}/{call_sid}.transcript.txt` and `{call_sid}.analysis.json` (= `analysis.raw`) are written before any network side effect; `{call_sid}.brief.md` is written once, LAST, after SMS and email have been attempted, so it can state their outcome (sid or error) — the email body is the same brief text minus the email-outcome line; (b) SMS sent iff `analysis.outcome in profile.sms` AND `record.caller_number` non-empty AND no `{artifact_dir}/{call_sid}.sms-sent` marker exists; marker written *before* the send call — at-most-once: a crash between send and marker can never produce a second SMS; a send failure after the marker leaves that call with zero SMS, which is recorded in `DispatchReport.errors` AND in the brief/email so the operator can send it by hand. **Open item for the owner (batched, not blocking):** this favours A2's "not two" over its "not zero"; the alternative (mark after send) flips that. Recommended: keep at-most-once — a duplicate SMS to a prospect is visible and embarrassing, a missed one is caught by the brief; body = `template.text.format(**template.links)`; (c) email always attempted to `profile.operator_email`, subject `[{profile.display_name}] {outcome} — {caller_number}` (was `profile.name`; amended by profile-loader Q12); (d) each of SMS/email is wrapped independently; failures land in `errors`, nothing raises; (e) `post_call` catches and logs every exception itself, so under normal operation S3's guarantee (b) — log and continue if `on_call_end` raises — is a second line of defence that never fires.

## Edge S3 → S6 — runtime contract

`Dockerfile` runs `decana` (the script entry) with `PORT` honoured; Cloud Run service: `min-instances=1`, `max-instances=1` (one process per number, Twilio stream affinity), `--session-affinity`, timeout ≥ 3600 s (WebSocket lifetime), secrets `GEMINI_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `SMTP_*` from Secret Manager into env; `PUBLIC_WSS_URL = wss://<service-url>`; Twilio number voice webhook → `https://<service-url>/voice`. `docs/deploy.md` records the exact `gcloud` commands (owner runs them — ask-list).

## Edge S7 — what it reads

Per call: `{call_sid}.jsonl` (timing), `{call_sid}.transcript.txt`, `{call_sid}.brief.md`, the tester's `.turnlog.txt` as in the prior slice's Exit criterion, the SMS on the tester's phone, the email in the operator inbox. A4: `git diff --stat` between the broker run and the eco run.

---

# Sequence and gates (Phase 4 — critic PASS)


Feature: vertical-profile-bridge. Decompose + contracts converged (critic PASS on contracts round 4). This phase fixes build order, the tracer gate, what each step must show before the next starts, and where the owner is needed.

## Order

| # | Slice | Gate to proceed | Owner needed? |
|---|---|---|---|
| 1 | **S1 profile** | `load_profile("mortgage-broker")` and `("eco-consultant")` both load; every `ProfileError` case has a test; `ruff`/`mypy --strict`/`pytest` green. | No. Profile *content* (real prompts, real links) is owner-authored — S1 ships with placeholder-but-valid text; owner fills `profiles/mortgage-broker/*.md` and links any time before S7. |
| 2 | **S2 gemini-live** | Unit tests with a fake Live transport for event ordering / `Closed`-exactly-once / `send_audio` never-raises; **spike** (`scripts/spike_gemini_live.py`): real API, `conversation.md` as system prompt, greeting trigger, 16 kHz WAV in → 24 kHz audio + transcript out, prints time-to-first-audio and inter-chunk gaps. PASS = greeting audio arrives unprompted and transcript events for both roles appear. Verifies `PR-gemini-live-greeting-on-connect` (half: unprompted speech) and `PR-gemini-live-transcription-events`. | No (needs `GEMINI_API_KEY` in env — owner sets once). |
| 3 | **S3 twilio-server** | `create_app` tests with fake `LiveSessionFactory` + fake `on_call_end`: TwiML shape, `<Parameter>` extraction, at-most-once `_teardown` across stop/disconnect/Closed/send-failure, `on_call_end` exactly once incl. when `close()` raises, drain-task FIFO. `__main__` smoke: `decana` starts with the tracer's optional env. Verifies `PR-bridgesession-composes-with-async-io` locally (fakes) — real verification is step 4. | No. |
| 4 | **S6 deploy → TRACER GATE** | Dockerfile builds; owner runs the `gcloud` commands from `docs/deploy.md` (ask-list); Twilio number webhook pointed at `/voice`. **Owner dials once.** PASS = hears whatever `disclosure.md` currently contains via `<Say>` (placeholder text is fine — the tracer verifies composition and timing, not compliance wording; the real disclosure is judged in 7a), then the model opens the conversation; `{call_sid}.jsonl` exists with `call_answered` and ≥1 `chunk_forwarded_to_twilio`; `on_call_end` log line shows a non-empty transcript. Verifies `PR-cloud-run-sustains-media-stream` (composition half), `PR-bridgesession-composes-with-async-io` (real), `PR-gemini-live-greeting-on-connect` (real). Latency numbers are recorded but A3 is NOT judged here — that is S7 with the turnlog. | **Yes** — deploy commands + one call. Twilio number provisioning is hard-to-undo (MVP doc); owner does it. |
| 5 | **S4 analysis** | Tests with fake `AnalysisClient`: transcript rendering, schema constrains outcome, every failure → `unclassified`, never raises, timeout honoured. One real-API check against a fixture transcript (cheap, auto-run). | No. |
| 6 | **S5 dispatch** | Tests with fake senders + tmp `artifact_dir`: file order (transcript+analysis before network, brief last), marker-before-send, no SMS when no template / empty number / marker present, per-side-effect isolation, `post_call` never raises. `build_on_call_end` + `Settings` extended. Redeploy = rebuilt image (S4+S5 code) + Twilio/SMTP secrets added to the service (owner runs `gcloud` again). | Deploy only. |
| 7a | **S7 — broker calls** | 3 scripted calls on `DECANA_PROFILE=mortgage-broker` (A1, A3 per the prior slice's Exit criterion incl. turnlog + corroboration), SMS receipt (A2). Read-out per call, not "it worked". | **Yes** — all calls. |
| 7b | **A4 profile switch** | Owner redeploys the SAME Cloud Run service and SAME Twilio number with `DECANA_PROFILE=eco-consultant` (env-only change, no image rebuild); one call: hears the eco disclosure, gets the eco SMS/email; `git diff --stat` between the broker and eco states shows `profiles/` only. Owner then redeploys back to `mortgage-broker`. **Owner decision, batched (recommended: reuse the same number):** reusing the number means the real line briefly runs the eco profile — fine while only test callers know the number; provisioning a second number is another hard-to-undo act (MVP doc) and buys nothing for a throwaway profile. | **Yes** — two redeploys + one call. |

## Tracer bullet
Chain **S1 → S2 → S3 → S6, one real call** (step 4). Built through the normal slice flow (`/plan-slice` → slice-builder) for S1, S2, S3, S6. Nothing after step 4 is planned until the tracer passes: if it fails to compose, the failing premise is marked `falsified`, dependents flagged (Art. 8), and Phase 2 re-opens. Owner may instead accept the integration risk in writing (not the default).

## Why this order and not another
- S2 before S3: S3's tests need S2's event types; S2's spike is the cheapest real-API check and de-risks the greeting premise before any server code exists.
- S6 before S4/S5: the latency question (A3) is the feature's riskiest premise and needs only S1–S3 + deploy; post-call work cannot change its answer. Building S4/S5 first would spend effort ahead of the one result that could send us back to Phase 2.
- S4 before S5: S5's `post_call` composes `analyse`; S5 tests use a fake `AnalysisClient` but its `Analysis` type must exist.
- Two deploys (step 4, step 6): unavoidable — the tracer must run before S5 exists. Both are owner-run `gcloud` commands.

## Interrupt map (what pauses the run)
- Step 2 spike: greeting never arrives unprompted → `PR-gemini-live-greeting-on-connect` falsified → owner (also re-opens the prior slice's proactive-greeting assumption).
- Step 4: tracer fails to compose → owner, with the falsified premise named.
- Step 4/6: deploy commands — owner runs them (ask-list), not an interrupt in the design sense.
- Any step: a product/threshold question Phase 1 did not answer → batched to the owner. Currently batched: (1) SMS marker order (at-most-once, recommended keep); (2) A4 on the same Twilio number vs a second number (recommended same).
- Everything else: autonomous.

---

## Integration exit criterion
The tracer (S1→S2→S3→S6, one real call: `<Say>` disclosure audible, model opens the conversation, `{call_sid}.jsonl` has `call_answered` + ≥1 `chunk_forwarded_to_twilio`, `on_call_end` logged a non-empty transcript) composes end-to-end, AND A1–A4 are met per S7's read-out (3 broker calls with turnlog + corroboration, SMS receipt, eco-profile call + `git diff --stat`).

## Deferred to later features
- Cloud transcript storage in a UK region — why later: only scripted/test callers until the first prospect; revisit trigger: before the first real client's transcript is written.
- Barge-in / interruption handling — why later: no mid-call intervention ratified; revisit trigger: a demo caller reports being talked over.
- Tool-call driven outcomes mid-call — why later: post-call classification chosen; revisit trigger: post-call analysis proves too slow or inaccurate for A2.
- Multi-number / multi-profile per process — why later: one number per vertical is the MVP shape; revisit trigger: second real vertical.
