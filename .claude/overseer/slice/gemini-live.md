# Slice gemini-live — planning artifact

Feature `vertical-profile-bridge`, slice **S2**. Planned 2026-08-26 (night),
unattended: the owner was away with the escalate list suspended for the session,
so gates that normally require owner ratification were decided by the planner and
logged in `.claude/overseer/unattended-decisions.md`. Every such decision is named
in this artifact where it applies.

Consumes: S1 `Profile` (shipped). Consumed by: S3 (`LiveSession` Protocol, event
stream). Ratified inter-slice contract:
`.claude/architecture/feature/vertical-profile-bridge.md` § "Edge S2 → S3".

## Goal

Deliver `src/decana/gemini/live.py`: an async Gemini Live client that S3 drives
for the whole life of one call. It opens a Live session configured from a
`Profile`, makes the model open the conversation unprompted, accepts caller audio
through a **sync** `send_audio` that never raises, and exposes ONE event stream of
`AudioChunk | Transcript | Interrupted | Closed` in arrival order — with
transcript fragments accumulated into whole turns, and exactly one `Closed` last.

**Measurable target.**
1. Unit suite green against a fake transport that reproduces the real SDK's
   per-turn `receive()` break; `pytest`, `ruff check`, `ruff format --check`,
   `mypy --strict` all clean.
2. `scripts/smoke_gemini_live.py` against the REAL Live API, on
   `profiles/mortgage-broker/conversation.md`, prints and asserts:
   - ≥ 1 `AudioChunk`, total bytes > 0, every chunk even-length;
   - exactly one `Transcript(role="model")` for the greeting turn, whose text is a
     WHOLE utterance — ≥ 5 words, ending in sentence punctuation — not a fragment
     like `' buy to'`;
   - exactly one `Closed`, it is the last event, and `reason == "local"`;
   - ≥ 1 `Transcript(role="caller")` after feeding audio back;
   - elapsed ms to first `AudioChunk`, recorded for S3's concurrency constraint.

   The Exit criterion below is authoritative and states each of these as a lettered
   assertion with its rationale; this list is the summary, not a second source.

Why that second bullet is the load-bearing one: fragment-vs-turn is the single
behaviour this slice adds on top of the SDK, and it is invisible to a test that
only counts events.


## Premise verified

| # | Premise | Status | Evidence |
|---|---|---|---|
| P1 | One client text turn after setup makes the model speak first, unprompted, with no audio input. | **verified** | Spike `.claude/artifacts/spikes/gemini-live-2026-08-26.json` C1 (5 consecutive runs); reproduced 2026-08-26 night by `scripts/spike_gemini_live_turns.py` (model spoke the intake opener from `conversation.md`). |
| P2 | With both transcription configs enabled, `input_` and `output_transcription` events arrive for both directions. | **verified** | Spike C3; reproduced tonight — 13 output fragments (phase A), 23 input fragments (phase B). |
| P3 | Transcripts arrive as FRAGMENTS, not whole utterances. | **verified** | Spike C3 granularity (`' I'`, `' CAN'`, `' HELP'`); tonight `' buy to'`, `' let?'`, `' Mo'`, `'ve'`. |
| P4 | **`Transcription.finished` is never set**; the model turn ends on `server_content.turn_complete`; the caller direction has **no terminator at all**. | **verified** | Tonight's probe: 0 of 36 fragments carried `finished`; `generation_complete` ×1 @7841 ms; `turn_complete` ×1 @9448 ms; caller-side drain held 45 s with no terminator. Raw: `.claude/artifacts/spikes/gemini-live-turn-boundaries-2026-08-26.json`; re-runnable via `scripts/spike_gemini_live_turns.py`. |
| P5 | Output audio is raw PCM16LE mono 24 kHz, always even-length. | **verified** | Spike C2 (`audio/pcm;rate=24000`, `even_length: true`); tonight every audio part was 1920 bytes. |
| P6 | A **sync** callable can feed the async session through a queue + drain task. | **verified** | Spike C4 — 424 frames sent this way. |
| P7 | Caller audio is delivered by `send_realtime_input(audio=Blob(data=…, mime_type="audio/pcm;rate=16000"))`. | **verified** | SDK source + docs; tonight phase B fed 16 kHz this way and `input_transcription` came back, so the server accepted it. |
| P8 | **`AsyncSession.receive()` terminates after ONE turn** (`break` on `turn_complete`, `live.py:455-459`); continuing a session requires calling `receive()` again. | **verified** | Source read + tonight's phase B: a re-entered iterator delivered 23 further events on the same open session. Full write-up and its consequences: `unattended-decisions.md`, FALSIFIED_PREMISE entry. |
| P9 | When the remote closes the socket, `_receive()` raises `google.genai.errors.APIError` (via `APIError.raise_error` on `ConnectionClosed`), it does not end the iterator cleanly. | **verified by source** | `live.py:540-547`. This is the `Closed(reason="remote")` path. |
| P10 | A real barge-in (caller speaking over the model) sets `server_content.interrupted` and interleaves the two transcription directions. | **UNVERIFIED — accepted as risk** | `interrupted` fired 0 times in tonight's probe and the spike's single occurrence came from feeding synthetic audio. Owner away; planner accepts. **Failure direction:** a barge-in would split one caller turn into two `Transcript` events (role switch fires early). That is *more* turns of the *same* text, never lost text — S4 reads a slightly choppier transcript. It cannot produce a false conversation. Revisit trigger: the first tracer call with a real human voice (feature step 4). |

**Gate.** P1-P9 carry fresh empirical or direct-source backing. P10 is the single
unverified premise, accepted in writing here by the planner under the owner's
standing suspension of the escalate list, with its failure direction stated and a
revisit trigger named.

## Out of scope (deliberately)

- **The Twilio leg and the WebSocket server** — S3. This slice has no socket, no
  FastAPI, no `streamSid`.
- **`BridgeSession` wiring** — already shipped; unchanged by this slice.
- **Audio resampling / mu-law** — `decana.bridge.resampler` / `.codec`, shipped.
  S2 sends whatever 16 kHz PCM16 bytes it is handed and emits 24 kHz untouched.
- **Barge-in handling** — S2 surfaces `Interrupted` and nothing more; Q4's no-op
  stays a no-op. No cancellation of queued audio on interrupt.
- **Reconnect / session resumption / context-window compression** — a dropped
  session becomes `Closed`; recovering from it is not this slice's job and is not
  in the feature's acceptance set.
- **Post-call analysis** — S4 consumes the accumulated transcript; S2 only emits it.
- **A real conversational round-trip** (caller speaks → model answers) — the
  tracer's job (feature step 4) with a real human voice. S2 proves the event
  contract, not the conversation.


## Seam (contract)

Module: `src/decana/gemini/live.py` (plus `src/decana/gemini/__init__.py`).

### Event types (frozen dataclasses — project convention for internal value objects)

```python
@dataclass(frozen=True)
class AudioChunk:   pcm24k: bytes                      # raw PCM16LE mono 24 kHz, even length
@dataclass(frozen=True)
class Transcript:   role: Literal["caller", "model"]; text: str    # ONE WHOLE TURN, not a fragment
@dataclass(frozen=True)
class Interrupted:  pass
@dataclass(frozen=True)
class Closed:       reason: str

LiveEvent = AudioChunk | Transcript | Interrupted | Closed
GREETING_TRIGGER: str = "[call connected - the disclosure has been played; open the conversation]"
```

These four names, their fields and `LiveEvent` are fixed by the ratified feature
contract (§ "Edge S2 → S3"). This slice does not change them.

### Injected transport (the test seam)

```python
class LiveTransport(Protocol):
    async def send_realtime_input(self, *, audio: types.Blob) -> None: ...
    async def send_client_content(self, *, turns: types.Content, turn_complete: bool) -> None: ...
    def receive(self) -> AsyncIterator[types.LiveServerMessage]: ...
    async def close(self) -> None: ...
```

Structurally satisfied by `google.genai.live.AsyncSession`. Nothing in this module
imports a client or reads an env var; `open_live_session` is the only function that
touches `genai`, and it takes `api_key` as an argument.

### The session

```python
class GeminiLiveSession:
    def __init__(
        self,
        transport: LiveTransport,
        *,
        aclose: Callable[[], Awaitable[None]] | None = None,
    ) -> None: ...
    # `aclose` is the connect() context manager's exit, injected by
    # open_live_session (see Q6). None in tests, where the fake owns its own
    # teardown. close() awaits it LAST, after the transport is torn down.
    async def start(self, *, greeting_trigger: str = GREETING_TRIGGER) -> None
    def send_audio(self, pcm16k: bytes) -> None          # SYNC. enqueues. never raises.
    def events(self) -> AsyncIterator[LiveEvent]         # one stream, ends after exactly one Closed
    async def close(self) -> None                        # idempotent

async def open_live_session(
    profile: Profile, *, api_key: str, greeting_trigger: str = GREETING_TRIGGER
) -> GeminiLiveSession
```

- **Returns:** events by async iteration; `send_audio` and `close` return `None`.
- **Errors:** `events()` never raises for a transport failure — every failure is
  translated into the terminal `Closed(reason=…)`. `send_audio` never raises for
  any reason. `open_live_session` MAY raise (connect-time failure happens before a
  call exists, and S3 must see it).
- **Dependencies (injected):** `LiveTransport` and the optional `aclose` callable
  into `GeminiLiveSession`; `Profile` and `api_key` into `open_live_session`. No
  module-level client, no env read.
- **Does NOT do:** sockets, resampling, mu-law, reconnect, barge-in reaction,
  post-call analysis, transcript persistence.

### Internal structure (paranoid-SRP)

One flow, four single-responsibility helpers:

- `_reader()` — task. Outer loop over repeated `transport.receive()` calls (P8);
  hands each message to `_translate`; puts results on `self._inbox`.
  **It emits `Closed` from a `finally`, catching `Exception` — not `APIError`**
  (Q11). Every exit path, expected or not, therefore ends the stream.
  **Lifecycle on `close()` is explicit, not incidental:** the reader is cancelled
  and awaited BEFORE the transport is torn down, so it never observes the
  teardown. See Q4's ordering invariant — this is the difference between a
  deterministic `reason` and a raced one. `CancelledError` propagates after the
  `finally` runs; `_emit_closed` is already a no-op by then because `close()` set
  the flag first.
- `_translate(msg) -> list[LiveEvent]` — pure. One SDK message → zero or more
  events. No I/O, no state except the turn accumulator it delegates to.
- `_TurnAccumulator` — owns the P4 flush rule and nothing else.
- `_drain()` — task. Pops `self._outbox`, awaits `send_realtime_input`; on failure
  calls `_emit_closed(f"send_failed: {exc}")` and stops.
- `_emit_closed(reason)` — the ONLY place a `Closed` is created; idempotent via a
  flag, so "exactly one" is one line of code in one place rather than an invariant
  spread across three call sites.

## Decisions (with WHY)

**Q1: `events()` must loop over repeated `receive()` calls, not delegate to one.**
Chosen: `_reader` wraps `while not closed: async for msg in transport.receive(): …`.
WHY: `AsyncSession.receive()` `break`s after the first `turn_complete`
(`live.py:455-459`, P8). Delegating once yields a stream that ends after the
model's greeting; S3 would tear the call down one turn in, and every unit test
against a naive fake would still be green. This is the slice's central defect risk.
Rejected: treat `receive()` exhaustion as end-of-session. Steelman: it is what the
signature implies and the simplest wrapper. Rejected: produces a one-turn call.
Rejected: make `events()` per-turn and let S3 loop. Steelman: keeps S2 thin.
Rejected: pushes an SDK quirk across a ratified slice boundary into S3's
at-most-once teardown, which is already the most intricate logic in the feature.

**Q2: the fake transport used in tests MUST reproduce the per-turn break.**
Chosen: the test fake yields a scripted list of `types.LiveServerMessage` and
**terminates its iterator after any message carrying `turn_complete`**, exactly as
the SDK does; a second `receive()` call returns the next scripted turn.
WHY: a fake that streams every scripted message from one `receive()` call makes Q1
untestable — the naive implementation and the correct one both pass. The fake's
fidelity to this one behaviour is what makes the suite able to fail.
Rejected: a fake that yields everything in one pass. Rejected: as above — it is the
happy-path illusion this slice exists to avoid.
Rejected: integration-only against the real API. Steelman: perfect fidelity, and the
project's default is integration-first. Rejected: the failure modes under test
(remote close mid-turn, send failure, close during a turn) cannot be provoked on
demand against a real server, and each attempt costs money and ~10 s.

**Second fidelity requirement (added after critic round 1).** The fake's `close()`
must make an **in-flight `receive()` raise `APIError`**, exactly as the real socket
does. Without it, Q4's ordering invariant is untestable: a fake whose `close()`
merely stops yielding lets both the correct implementation and the raced one
report `reason="local"`, so the suite is green against a transport shape the real
one does not have — the same illusion as Q1, one level down. A fake is only
evidence for the behaviours it can actually get wrong.

**Q3: transcript turn boundaries — the flush rule.**
Chosen: model turn flushes on `server_content.turn_complete`; caller turn flushes on
**role switch** (first `output_transcription` fragment after ≥1 `input_transcription`
fragment); any open turn flushes at session close, before `Closed`.
WHY: measured, not assumed. `Transcription.finished` is never set (0 of 36 fragments),
and the caller direction has no terminator in the protocol at all (45 s drain, no
signal) — see P4. Role switch is the only structural boundary available, and it is
the real conversational one: the caller's turn ends when the model starts answering.
Rejected: `Transcription.finished`. Steelman: it is right there on the type and is
exactly what it sounds like. Rejected: **measured absent** — this is the premise that
would have been wrong if reasoned from the signature.
Rejected: flush both directions on `turn_complete`. Rejected: `turn_complete` marks
the MODEL's turn; a caller turn followed by a model turn would flush both at one
instant, emitting them in an order that does not match arrival.
Rejected: one `Transcript` per fragment, joined by S4. Rejected: the contract has S4
serialising turns as `CALLER: …` / `MODEL: …` lines; per-fragment events make every
token a line. The spike already recorded "S2 must ACCUMULATE".
Rejected: a silence timer on the caller side. Rejected: invents a VAD threshold this
slice has no basis to choose; Q10 of the bridge slice rejected silence-detection
reasoning for the same reason.

**Q4: exactly one `Closed`, produced in exactly one place — and its `reason` must
not be decided by a race.**
Chosen: `_emit_closed(reason)` guarded by a `self._closed` flag; every terminal path
(remote close, local `close()`, drain-task send failure, reader exception) calls it.
`events()` returns after yielding it.

**Ordering invariant (added after critic round 1 — this is the substantive half).**
`close()` runs in exactly this order:

1. if already closed → return (idempotence);
2. `_emit_closed("local")` — set the flag and queue the one `Closed`;
3. cancel the reader and drain tasks and await both, suppressing `CancelledError`;
4. only then tear the transport down (`transport.close()`), and finally await
   `aclose` if one was injected — see Q6, which owns that trailing step.

WHY the order is load-bearing: **the SDK gives the reader no way to tell "we closed
it" from "they closed it."** `AsyncSession.close()` is `await self._ws.close()`
(`live.py:886-888`), and the whole `connect()` body runs inside
`async with ws_connect(...) as ws:` (`live.py:1102`) — so our own teardown closes
the identical socket, and the in-flight `_ws.recv()` raises `ConnectionClosed`,
which `_receive()` converts unconditionally to `APIError` (`live.py:540-547`): the
exact exception P9 documents for a genuine remote close. Without steps 2 and 3
preceding step 4, whichever coroutine resumes first decides whether the same call
is recorded `"gemini_closed: local"` or `"gemini_closed: remote"` in
`CallRecord.ended_reason` — a value the ratified feature contract makes
load-bearing for S4/S5. Cancelling the reader before teardown means it never
observes the close at all; the idempotent flag is then a backstop, not the primary
mechanism.
WHY one guarded function at all: four paths can end a call, and an invariant
enforced at four call sites is one refactor away from being violated at the fifth.
Rejected: rely on the idempotent flag alone, letting the reader race its own
`except APIError` handler. Steelman: `_emit_closed` is idempotent, so the second
call is a no-op and only one `Closed` is ever emitted — the *count* guarantee holds.
Rejected: the count holds and the **reason** does not, silently and
intermittently, which is worse than a crash because it corrupts a downstream record
while every test stays green.
Rejected: distinguish the two cases by inspecting the exception. Rejected: verified
impossible — both produce the same `APIError` from the same line.
Rejected: emit `Closed` from `events()`'s `finally`. Steelman: no flag, no queue.
Rejected: an async generator's `finally` runs on consumer `break` too, where yielding
raises `RuntimeError`; and it cannot express a reason discovered by the drain task.

**Q5: `send_audio` is sync, enqueues, and never raises — including after close.**
Chosen: `self._outbox.put_nowait(...)` guarded by the closed flag; after `Closed` it
is a silent no-op. Unbounded queue.
WHY: it is called from inside `BridgeSession._forward_to_twilio`'s twin on the Gemini
leg, under a catch scoped to `AudioFrameError` only (bridge Q20). Any other exception
from this call ends the call. Contract guarantee (e) already names the post-`Closed`
no-op. Unbounded because a bounded queue's only options on overflow are to block (in
a sync method — deadlock) or to raise (forbidden here).
Rejected: `async def send_audio`. Steelman: no queue, no drain task, no ordering
question. Rejected: `GeminiLiveSessionClient.send_audio` is a SYNC Protocol in the
shipped bridge (`session.py:44-46`); making it async re-opens ratified, shipped code.
Rejected: bounded queue with drop-oldest. Rejected: silently discarding caller audio
degrades the exact signal the feature's latency criterion measures, invisibly.

**Q6: `open_live_session` holds the connect context manager open manually.**
Chosen: `cm = client.aio.live.connect(...)`; `transport = await cm.__aenter__()`;
the CM is stored and `__aexit__`-ed in `close()`.
WHY: `connect()` is an async context manager, but the session must outlive the
function that opens it — S3 opens once per call and drives it from elsewhere. There
is no supported alternative in the SDK surface.

**How `close()` reaches the CM (added after the cold-reader audit).** `cm.__aenter__()`
returns the bare `AsyncSession`, and `AsyncSession.close()` is only
`await self._ws.close()` (`live.py:886-888`) — it never drives the `connect()`
generator to `__aexit__`. So closing the transport alone leaves the async generator
un-exited for the life of the process, which on this feature's `min-instances=1`
long-lived Cloud Run service means one leaked generator per call. The mechanism is
therefore explicit rather than implied: `open_live_session` passes
`aclose=lambda: cm.__aexit__(None, None, None)` into the constructor, and `close()`
awaits it as its LAST step, after step 4 of Q4's ordering. Tests pass `aclose=None`,
because a fake owns its own teardown and has no CM to exit.
Rejected: run the whole call inside `async with`. Steelman: idiomatic, no manual
`__aenter__`. Rejected: it inverts control — S2 would have to own the call's whole
lifetime and invoke S3, which is backwards across a ratified boundary.
Rejected: `contextlib.AsyncExitStack` held on the session. Steelman: tidier than a
raw `__aenter__`/`__aexit__` pair. Accepted as an implementation detail the builder
may choose; it changes no observable behaviour.

**Q7: `Closed.reason` vocabulary.**
Chosen: `"local"` (our `close()`), `"remote"` (transport ended or raised
`APIError`), `"send_failed: <exc>"` (drain task). Fixed by the feature contract.
WHY: S3 maps these into `CallRecord.ended_reason` as `"gemini_closed: <reason>"`;
the strings are already load-bearing downstream.
Rejected: an enum. Steelman: type-safe, no string typos. Rejected: the contract
specifies `reason: str` including an interpolated exception; an enum cannot carry it
without a second field, and would amend ratified text.

**Q8: the greeting trigger is sent by `start()`, not by `__init__` or `events()`.**
Chosen: `await start(greeting_trigger=…)` sends one client text turn, then
`open_live_session` starts the reader and drain tasks and returns.
WHY: contract guarantee (b) — the trigger goes "immediately after setup, before any
`send_audio`". `__init__` cannot await. Putting it in `events()` would tie "the model
starts speaking" to whether S3 has begun iterating yet, which is a race S3 should not
have to know about.
Rejected: send it inside `open_live_session` directly without a `start()` method.
Steelman: one fewer public method. Rejected: it would make the greeting untestable
without a real connect, since `open_live_session` is the one function that touches
`genai`.

**Q9: arrival order is preserved by construction, not by assertion.**
Chosen: one `asyncio.Queue` (`_inbox`) carries every inbound event; `events()` is a
pure drain of it.
WHY: contract guarantee (c) requires `AudioChunk` and `Transcript` interleaved as
received. One queue written by one reader task makes that true structurally; two
queues, or a merge, would make ordering an emergent property to be tested rather than
a fact.

**Q10: queued outbound audio is discarded on close, not flushed.**
Chosen: `close()` sets the flag, cancels the drain task, and drops whatever is still
in `_outbox`.
WHY: the queue holds caller audio destined for a session that is ending; pushing it
after the call has ended can only produce transcript for words spoken into a dead
call. The bridge's Q10 teardown flush is the opposite case for a good reason — there
the stranded bytes are the AI's final words to the *caller*, which would be audibly
clipped.
Rejected: drain the queue before closing. Rejected: unbounded wait on teardown, in the
path S3 must complete exactly once and quickly.

---


## Hardest seams (test-confidence points — distinct from the contract Seam above)

**Seam 1: the per-turn `receive()` break (P8).**
The real `AsyncSession.receive()` `break`s after the first `turn_complete`, so a
correct implementation loops over repeated `receive()` calls and a naive one does
not. Against a fake that streams every scripted message from a single `receive()`,
**both implementations pass every test** — this is the slice's central happy-path
illusion.

*Test approach:* the fake transport is scripted as a LIST OF TURNS, and its
`receive()` yields one turn's messages then terminates, exactly as the SDK does;
the next `receive()` call serves the next turn. A test drives a 3-turn script
through ONE `events()` stream and asserts events from turns 2 and 3 arrive.
*Anti-pattern ruled out:* delegating to a single `receive()` call — which is the
implementation the type signature invites.
*Mutation check the implementer must run:* replace the outer loop with a single
`async for` and confirm this test — and ideally only this one — fails. If the
suite stays green, the fake is not reproducing the break and Seam 1 is not tested.

---

**Seam 2: fragments are joined into a turn, with the right text.**
`Transcript` events are the sole input to S4. A test asserting "a `Transcript`
arrives" passes on per-fragment emission, which would hand S4 one line per token.

*Test approach:* script a model turn as the exact fragments measured tonight
(`'Hello, thanks'`, `' for calling.'`, … `' buy to'`, `' let?'`) and assert
**exactly one** `Transcript(role="model", text=…)` whose text equals the
concatenation. Concatenation is `"".join`, NOT `" ".join`: the API's fragments
carry their own leading spaces, so a separator-joining implementation produces
`'Hello, thanks  for calling.'` with a double space.
*Anti-pattern ruled out:* counting events instead of asserting their text; and the
plausible-looking `" ".join` that only a text assertion catches.
*Mutation check:* change the join from `"".join` to `" ".join` and confirm `S2`
fails. If it passes, the test is asserting the event count rather than the text.

---

**Seam 3: exactly one `Closed`, whichever of four paths ends the call.**
Contract guarantee (d). Four terminal paths exist and an invariant enforced at
four call sites is one edit away from a fifth path that violates it.

*Test approach:* one test per path. Each asserts exactly one `Closed` in the whole
stream, that it is the LAST event, and the exact `reason` per Q11's mapping —
spelled out here rather than left as "the expected string", because a builder who
guesses will guess bare `"remote"` and quietly undo Q11:

| case | scenario | asserted `reason` |
|---|---|---|
| (a) | local `close()` | `== "local"` |
| (b) | remote raises `APIError` mid-turn | `.startswith("remote: APIError")` |
| (c) | remote ends its iterator cleanly, no further turns | `== "remote"` (the only bare-`"remote"` case) |
| (d) | drain task's `send_realtime_input` raises | `.startswith("send_failed: ")` |
| (e) | `close()` called twice | `== "local"`, still exactly one `Closed` |
| (f) | `close()` while a MODEL turn is mid-flight | `== "local"` — see Seam 8, same setup — **and** the partial model turn is emitted as `Transcript(role="model", …)` BEFORE the `Closed` |

*Anti-pattern ruled out:* asserting `any(isinstance(e, Closed) …)`, which passes
on two `Closed`s and on a `Closed` emitted mid-stream.
*Cross-reference:* case (f) and Seam 8's primary scenario are the same physical
setup — start a turn, close mid-turn — checked for different properties (count and
the model-side close-flush here, reason there). Update them together.

**Why case (f) carries the model-side flush assertion.** Q3's invariant is that
*any* open turn flushes at close, before `Closed` — both roles. Seam 6 tests it for
the caller. Nothing tested it for the model, and the gap is not academic: a
minimal wrong implementation that flushes only the caller branch at close is
*tempting*, because the caller side is the one flagged throughout this plan as
needing special handling (no protocol terminator, P4). That implementation passes
every other test here — Seam 2 only exercises the `turn_complete`-triggered flush,
Seam 6 only the caller-open-at-close case, and Seam 3(f)/Seam 8 previously asserted
nothing about transcript content. In production it silently drops the tail of any
call that ends while the model is mid-sentence: a remote drop, a local hang-up, or
a malformed frame. That is a corrupted transcript handed to S4, with a green suite —
the same failure class as the `reason` defect Q4 exists to prevent, one field over.
*Mutation check:* make the close-time flush caller-only and confirm case (f) fails.

---

**Seam 4: a dead reader task must not become a hung `events()`.**
If `_translate` raises on an unexpected message shape, the reader task dies. With
no `finally`, no `Closed` is ever queued, `events()` awaits an empty queue
forever, and S3's teardown — which the feature contract requires to run exactly
once per call — never fires. The call hangs instead of ending. Nothing about this
is visible in a happy-path test.

**This is not hypothetical, and it is not only about our own code.** The SDK's own
`_receive()` raises a **bare `ValueError`** on a malformed server frame
(`live.py:551-552`), and `receive()` does not wrap it (`live.py:455-459`). A reader
scoped to `except APIError` dies silently on that path — so the defect is reachable
without any bug of ours at all.

*Test approach:* two tests. (a) the fake yields a message crafted to make
`_translate` raise; (b) the fake's `receive()` raises a bare `ValueError`, exactly
as the SDK does on malformed JSON. Both assert `events()` terminates with exactly
one `Closed` **within a timeout** (a hang is the failure mode, so the test must be
able to fail by timing out rather than by hanging the suite), and that `reason`
names the failure rather than claiming a clean remote close.
*Anti-pattern ruled out:* trusting that the reader can only exit through paths the
author thought of — the same class of defect as the bridge slice's three
successive "the catch is narrower than it looks" findings, and now a fourth
instance of it in this very slice.
*Mutation check:* narrow the reader's catch from `Exception` to `APIError` and
confirm test (b) fails. If it passes, the fake is not reproducing the SDK's raise.

---

**Seam 5: `send_audio` never raises, in every state.**
It is called from inside the shipped `BridgeSession`'s Gemini leg under a catch
scoped to `AudioFrameError` only (bridge Q20). Any other exception escaping it
ends the call.

*Test approach:* call it (a) before `start()`; (b) after `Closed`; (c) after
`close()`; (d) when the drain task has already died from a send failure; (e) with
`b""`. Assert no exception in every case, and that (b)-(d) enqueue nothing.
*Anti-pattern ruled out:* testing only the happy enqueue, where "never raises" is
trivially true and the guarantee is untested exactly where it matters.

---

**Seam 6: caller-turn flush on role switch, in the right order.**
The model direction has `turn_complete` and is easy; the caller direction has no
terminator at all (P4) and is where the rule can silently be wrong.

*Test approach:* script input fragments, then an output fragment, then
`turn_complete`. Assert the emitted sequence is exactly
`[Transcript(caller, …), Transcript(model, …), …]` — the caller turn flushed
BEFORE the model turn, in arrival order, with the model's own fragments still
accumulated into one event. Also assert a caller turn still open at close is
flushed before `Closed`, so no fragment is ever dropped.
*Anti-pattern ruled out:* testing only the model direction, and asserting on a set
of events rather than their order.
*Coverage note:* text-join correctness for the caller direction is **Seam 2's**
job, not this one — `_TurnAccumulator` is one class holding the flush rule for
both roles, so Seam 2's `"".join` assertion exercises the shared code path. Stated
so the omission here reads as delegation rather than as a gap, the same way the
`_inbox`/`_outbox` bounds are recorded in Phase 2.
*The close-flush invariant is NOT symmetric here.* This seam covers the caller side
only; the **model** side of "any open turn flushes at close" is Seam 3 case (f).
Do not read this seam as covering both directions — that assumption is exactly what
left the model side untested through two review rounds.

---

**Seam 7: arrival order of audio against transcript.**
Contract guarantee (c) requires them interleaved as received. S3 feeds
`AudioChunk` straight into the latency-critical path while `Transcript` is
post-call data, so a reordering here is invisible until the timing artifact is
read.

*Test approach:* script one turn interleaving audio parts and transcription
fragments in a known order; assert the `AudioChunk`s appear in the emitted stream
in the same relative order they were scripted, and that no `AudioChunk` is
withheld while a turn accumulates.
*Anti-pattern ruled out:* buffering audio behind the turn accumulator — an easy
mistake once `_translate` returns a list, and one that would add turn-length
latency to every response while every count-based test stays green.

---

**Seam 8: a locally-ended call must not be recorded as a remote close.**
*(Added after Phase-2 critic round 1 — the objection that blocked it.)*
The SDK gives the reader no way to distinguish the two: `AsyncSession.close()` is
`await self._ws.close()` (`live.py:886-888`), the whole `connect()` body runs
inside `async with ws_connect(...) as ws:` (`live.py:1102`), and `_receive()`
converts the resulting `ConnectionClosed` to `APIError` unconditionally
(`live.py:540-547`) — byte-identical to a genuine remote close. So `reason` is
decided by whichever coroutine resumes first unless `close()` orders itself
explicitly (Q4). The corrupted value lands in `CallRecord.ended_reason`, which the
ratified contract makes load-bearing for S4/S5.

*Test approach:* the fake's `close()` must make an **in-flight `receive()` raise
`APIError`**, mirroring the real socket. Then: start a turn, call `close()`
mid-turn, assert exactly one `Closed` and `reason == "local"` — never `"remote"`.
A companion test drives the genuine remote path (fake raises `APIError` on its
own, unprompted) and asserts `reason.startswith("remote: APIError")` — **not**
bare `"remote"`, which is Q11's mapping for a clean iterator end only. Asserting
bare `"remote"` here would contradict Q11 and, far more likely, would be "fixed"
during implementation by loosening the exception path back to bare `"remote"` —
silently undoing the diagnosability Q11 exists to protect, with the suite green
the whole way. The two tests together show local and remote are distinguished by
the implementation rather than by luck.
*Anti-pattern ruled out:* a fake whose `close()` merely stops yielding. Against
that fake the raced implementation and the correct one both report `"local"`, and
the suite proves nothing — the Seam-1 illusion one level down.
*Mutation check:* move `_emit_closed("local")` to AFTER the transport teardown in
`close()` and confirm this test fails. If it still passes, the fake is not
provoking the in-flight raise and Seam 8 is untested.

---

---

**Seam 9: `Interrupted` must actually be emitted, and the truncated turn kept.**
*(Added after the cold-reader audit — the objection that blocked it.)*
`Interrupted` is a member of the ratified `LiveEvent` union and surfacing it is this
slice's job. It had no seam, no id and no mutation check through ten critic rounds,
because every round was anchored on the parts of the design that had already been
contested. A `_translate` that never reads `server_content.interrupted` would have
passed all twenty ids, all five mutation checks and the entire exit criterion.

*Test approach:* script a model turn that emits a few output fragments, then a message
with `server_content.interrupted = True`, then `turn_complete` — the SDK's own
documented sequencing (`interrupted > turn_complete`, per the `generation_complete`
field docs). Assert two things: an `Interrupted()` appears in the stream, and the
partial model text still arrives as exactly one `Transcript(role="model", …)` emitted
AFTER it, carrying the fragments accumulated before the cut.
*Anti-pattern ruled out:* asserting only that `Interrupted` appears. That passes on an
implementation that emits the event but silently drops the truncated turn — losing
words the caller actually heard, from the one artifact S4 classifies on.
*Mutation check:* delete the `interrupted` branch from `_translate` and confirm `S9a`
fails; separately, make the interrupted turn discard its accumulator and confirm `S9b`
fails.

---

### Reachability pass (Phase-2 critic round 3, non-blocking note)

This project has a precedent for stating which branches are inert and why —
bridge Q14 (`event` key, unreachable as a matter of Python's argument binding) and
Q18's correction (two of five stage/direction combinations unreachable as a matter
of pipeline order). Same pass, applied here:

- **`Closed(reason="remote")` from a CLEAN iterator end appears unreachable
  against the concrete SDK.** Every session-level end found in `live.py` is either
  the per-turn `break` — which Q1's outer loop treats as non-terminal, not as an
  end — or an exception. Notably `_receive()` converts `ConnectionClosed` to
  `APIError` for BOTH `ConnectionClosedOK` and `ConnectionClosedError`
  (`live.py:540-547`), so even a graceful remote hang-up arrives as an exception;
  there is no quiet close path.
- **Kept, not pruned, and the reason matters.** Unlike Q14's `event` key, this is
  not a guarantee of the language — it is a property of one SDK version's control
  flow, and of the `LiveTransport` Protocol having implementations other than
  `AsyncSession` (every test fake is one, and a fake may legitimately just stop
  yielding). The branch is live for fakes today and could become live for the real
  transport on any SDK upgrade.
- **Test consequence:** the clean-end branch is exercised through a FAKE only
  (hardest Seam 3, case (c)), and the smoke does not attempt to provoke it. No test
  asserts that the real SDK can produce it, because on the evidence it cannot.

### Known ambiguity, recorded rather than designed away

A remote-initiated failure can be observed by the reader (`"remote: …"`) and by the
drain task (`"send_failed: …"`) at nearly the same moment; whichever calls
`_emit_closed` first wins. **This is not the round-1 defect.** There, a local close
could be labelled remote — a false statement about the call. Here both labels are
true characterisations of the same real remote failure, and the choice between them
is a diagnostic nuance, not a corrupted record. Deliberately not resolved: ordering
these two would mean holding one path back to see whether the other fires, which
buys nothing and adds a wait to teardown.

---

### What the fake transport must provide (prerequisite for the seams above)

Three requirements. The first two are Phase 2 decisions (Q2); the third comes from
the Phase-3 critic and exists to stop these tests being flaky.

1. **Per-turn `receive()` break.** Scripted as a list of TURNS; `receive()` yields
   one turn's messages then terminates; the next call serves the next turn.
   Without it, Seam 1 is untestable.
2. **`close()` provokes an in-flight `receive()` to raise `APIError`,** as the real
   socket does. Without it, Seam 8 is untestable.
3. **Deterministic mid-turn positioning — an explicit gate, never a sleep.**
   Seam 3(f) and Seam 8 both need `close()` to land *while a turn is in flight*.
   The fake must expose a step/gate primitive — it advances past a scripted message
   only when the test releases an `asyncio.Event` (or calls `.step()`) — so "mid-
   turn" is a state the test establishes, not a moment it hopes to hit.
   **`asyncio.sleep(0)` scheduling tricks are forbidden here:** they make the test
   pass on an idle machine and fail under load, and a flaky test on a
   concurrency seam is worse than no test — it trains the reader to re-run rather
   than to look.

**Timeout rule — stated as a scope, deliberately not as a list.** *Every seam-test
that awaits on `events()` runs under an explicit timeout.* That is Seams 1, 2, 3,
4, 6, 7 and 8 today; Seam 5 is exempt only because `send_audio` is synchronous and
its tests never consume the stream. A future Seam 9 is covered by the rule without
anyone having to remember to update a list in two places.

An earlier draft of this paragraph enumerated "Seams 1, 3, 4, 7 and 8" and silently
dropped 2 and 6 — which are, if anything, the **most** hang-prone in the set. A
flush-rule bug does not produce a wrong `Transcript`; it produces **no**
`Transcript`, and a test awaiting the expected event blocks forever. The caller
direction has no protocol terminator at all (P4), so Seam 6 is precisely where that
happens. The failure mode being ruled out is a HANG, and a test that hangs instead
of failing takes the suite with it and reports nothing.

---

### Ratified test-id set (the closed list the exit criterion diffs against)

Granularity is **one id ↔ one test node**, matching the `profile-loader` Q21
precedent exactly. An earlier draft keyed coverage to the eight seam *names*, which
one test for Seam 3 case (a) would have satisfied while (b)-(f) silently vanished —
the same drift as before, one level down.

| id | what it asserts | seam |
|---|---|---|
| `S1` | 3-turn script through one `events()`; turns 2 and 3 arrive | 1 |
| `S2` | exactly one model `Transcript`; text == `"".join(fragments)`, no double space | 2 |
| `S3a` | local `close()` → one `Closed`, last, `reason == "local"` | 3 |
| `S3b` | remote raises `APIError` mid-turn → `.startswith("remote: APIError")` | 3 |
| `S3c` | remote iterator ends cleanly → `reason == "remote"` (only bare case) | 3 |
| `S3d` | drain `send_realtime_input` raises → `.startswith("send_failed: ")` | 3 |
| `S3e` | `close()` twice → still exactly one `Closed`, `reason == "local"` | 3 |
| `S3f` | `close()` mid-MODEL-turn → partial `Transcript(role="model")` emitted BEFORE `Closed` | 3 |
| `S4a` | `_translate` raises → one `Closed` within a timeout, reason names the failure | 4 |
| `S4b` | `receive()` raises bare `ValueError` (SDK's malformed-JSON path) → same | 4 |
| `S5a` | `send_audio` before `start()` → no raise | 5 |
| `S5b` | `send_audio` after `Closed` → no raise, nothing enqueued | 5 |
| `S5c` | `send_audio` after `close()` → no raise, nothing enqueued | 5 |
| `S5d` | `send_audio` after drain task died → no raise, nothing enqueued | 5 |
| `S5e` | `send_audio(b"")` → no raise | 5 |
| `S6a` | caller fragments then output fragment → caller `Transcript` emitted BEFORE model's, in arrival order | 6 |
| `S6b` | caller turn still open at close → flushed before `Closed` | 6 |
| `S7` | audio and transcript interleaved as scripted; no `AudioChunk` withheld behind the accumulator | 7 |
| `S8-local` | `close()` mid-turn against a fake whose `close()` raises in-flight → `reason == "local"`, never `"remote"` | 8 |
| `S8-remote` | fake raises `APIError` unprompted → `.startswith("remote: APIError")` | 8 |
| `S9a` | message with `server_content.interrupted` → `Interrupted()` emitted | 9 |
| `S9b` | interrupted turn → truncated model text still emitted as one `Transcript`, AFTER the `Interrupted` | 9 |
| `S10` | `start()` sends exactly one greeting-trigger text turn, and no audio precedes it | contract guarantee (b) |

**23 ids. This list is closed.** Adding, removing, or changing what an id asserts is
a behavior-list change — the one thing that stays escalate even with the escalate
list suspended, because it is what overseer check #11 diffs against.

## Exit criterion

### 1. Unit suite — the Phase-3 seams, against a faithful fake

Every behavior id from the ratified behavior list is green, run as
`uv run pytest tests/test_live.py`, and the whole suite (`uv run pytest`) is green
with no pre-existing test broken — baseline before this slice: **155 passed**.

**Coverage is a property over the ratified TEST-ID set, at one-id-to-one-test-node
granularity.** *Every id in the "Ratified test-id set" table — all 23 — has exactly
one test node naming it, and every test node in `tests/test_live.py` names an id
from that table.* The diff runs in both directions and must come back clean.

Two earlier drafts of this line were wrong, in the same way at two different
granularities, and both are worth recording because the failure keeps recurring:

- The first said "S1-S7" — a hand-typed range that silently dropped Seam 8, added
  later, the one Phase 2 fought hardest for.
- The second keyed the property to the eight seam *names*. That is satisfiable by a
  single test for Seam 3 case (a) while (b)-(f) vanish — including `S3f`, the
  model-side flush gap that took three review rounds to surface.

Only id-level granularity actually closes it, and that is precisely what the
`profile-loader` Q21 precedent uses (one ratified row id ↔ one test node). Citing
that precedent while implementing something coarser was the defect.

The fake transport **must** terminate its `receive()` iterator on `turn_complete`
(Seam 1) **and** its `close()` must provoke an in-flight `receive()` to raise
(Seam 8). An implementation lacking either fidelity is not evidence, and `S1` and
`S8-local` respectively are the ids that would silently pass without it.

**Mutation evidence is part of this criterion, not optional polish.** Several
assertions here are of the kind that pass on arrival, and the prior slice
established that passing-on-arrival is not the same as being right. All seven
mutation checks named in the Hardest-seams section must be run:

| mutation | id that must fail |
|---|---|
| outer `receive()` loop → a single `async for` | `S1` |
| fragment join `"".join` → `" ".join` | `S2` |
| close-time flush made caller-only | `S3f` |
| reader's catch narrowed `Exception` → `APIError` | `S4b` |
| `_emit_closed("local")` moved to AFTER transport teardown | `S8-local` |
| `interrupted` branch deleted from `_translate` | `S9a` |
| interrupted turn made to discard its accumulator | `S9b` |

Each must be shown failing, and the restore diff-verified byte-identical, exactly
as `profile-loader` did for its aliasing (V1/V4) and strip-rule (W7/W8) seams —
that slice, not `voice-intake-demo`, is where those two precedents live. A mutation that
does NOT fail its id is itself the finding: it means the fake lacks the fidelity
that id depends on, and the id is not actually tested.

### 2. Real-environment smoke — `scripts/smoke_gemini_live.py`

Runs against the REAL Gemini Live API with `GEMINI_API_KEY` loaded from `.env`,
on `profiles/mortgage-broker/`. It opens a session via `open_live_session`,
iterates `events()` until `Closed`, prints every event's kind and size, and
asserts:

| # | Assertion | Threshold and why |
|---|---|---|
| A | ≥ 1 `AudioChunk`, total bytes > 0, every `pcm24k` even-length | evenness is P5; an odd length would break the shipped resampler's `reject_partial_pcm16` on the S3 leg |
| B | **exactly one** `Transcript(role="model")` for the greeting turn | the whole point of the slice — per-fragment emission produces ~13 |
| C | that transcript's text has ≥ 5 words AND ends in `.`, `?` or `!` | a whole utterance, not a fragment. Measured basis: tonight's greeting was 19 words ending in `?`; the longest single fragment was 3 words with no terminal punctuation. The threshold sits well clear of both. |
| D | exactly one `Closed`, it is the LAST event, **and `reason == "local"`** | contract guarantee (d), plus Seam 8 against the REAL socket. The smoke ends the session by calling `close()`, so `"local"` is the only correct answer; a raced implementation reports `"remote: APIError"` here and the smoke catches it. Asserting count and position alone — as an earlier draft did — is the same "a fake whose `close()` merely stops yielding proves nothing" anti-pattern, recurring in the real-environment gate |
| E | ≥ 1 `Transcript(role="caller")` after feeding audio back | closes the feature Order table's S2 gate ("transcript events for **both** roles appear") against the real API, and exercises the caller-side flush — the rule with no protocol terminator (P4), which is the riskiest thing this slice invents. Audio source: the model's own greeting, resampled 24k→16k with the shipped `Resampler`, exactly as tonight's probe did. If the model does not reply, this turn flushes at close, which tests that path too |
| F | elapsed ms to first `AudioChunk` printed and recorded | not a pass/fail gate here — it is the input to S3's concurrency constraint (open the Live session *concurrently* with Twilio `<Say>`; measured 3.2-4.0 s) |

The smoke has **no human-only oracle** — every assertion is machine-checkable — so
per the slice-builder's Step-5 split it is run by the implementer, with full
output in the transcript, and the slice continues to Step 6 without waiting.

**Reconciliation with the feature's S2 gate.** The Order table names a spike doing
"16 kHz WAV in → 24 kHz audio + transcript out … transcript events for both roles
appear". Assertion E is how this slice meets that, with one difference recorded
rather than glossed: the caller audio is the model's own greeting fed back rather
than a WAV fixture, because that is what tonight's probe established works and it
needs no new asset. The half of that gate about the greeting arriving unprompted is
already carried by P1, verified on 5 consecutive runs plus tonight.

**Cost discipline:** one session, one greeting turn, one audio feed-back, then
`close()` — a single run, bounded by an outer `timeout`. Not a loop, not repeated
for convenience.

### 3. Static gates

`uv run ruff check`, `uv run ruff format --check`, `uv run mypy` (strict, per
`pyproject.toml`) all clean, with `src/decana/gemini/` and `scripts/` inside
mypy's `files` list.

### What does NOT prove this slice done

- A real conversational round-trip (caller speaks, model answers). That needs a
  human voice and is the tracer's job — feature step 4. Tonight's probe and the
  original spike both failed to draw a reply from synthetic audio, and neither is
  evidence against the seam.
- Latency of the model's first audio. Recorded, not gated. A3 is judged in S7.

---

### Note on script naming

`scripts/smoke_gemini_live.py` (this slice's real-API smoke, closing this exit
criterion) is a **different artifact** from `scripts/spike_gemini_live.py`, which
the feature's Order table names as S2's premise spike. The spike's job was to
answer "does the greeting arrive unprompted, and do transcription events exist" —
already answered and recorded in
`.claude/artifacts/spikes/gemini-live-2026-08-26.json` plus tonight's probe. The
smoke's job is to prove *this module's* seam against the real API. Two scripts,
two purposes; not a rename and not a duplicate.

## Deferred to later slices

- **Reconnect / session resumption after a dropped Live session.** Why later: the
  feature's acceptance set has no availability requirement, and `Closed` already
  gives S3 a clean, tested teardown path. Revisit trigger: the first tracer or S7
  call that ends early with `Closed(reason="remote")` before the caller hung up.
- **Barge-in reaction.** S2 surfaces `Interrupted`; nothing consumes it. Why later:
  Q4 of the bridge slice ratified log-only, and reacting means cancelling queued
  audio — a policy no slice owns yet. Revisit trigger: a scripted S7 call where the
  caller talks over the model and the transcript is unreadable as a result.
- **Bounded outbound queue / backpressure.** Q5 chose unbounded deliberately. Why
  later: at 20 ms frames a call would have to stall for minutes to matter. Revisit
  trigger: a call whose memory grows, or the first deployment that is not
  one-process-per-number.
- **Per-profile Live model parameters** (temperature, voice, `enable_affective_dialog`).
  Why later: `Profile` carries `live_model` only, and inventing config a real
  vertical has not asked for is the premature generality this project's slices
  refuse. Revisit trigger: a second real vertical needing a different voice.
- **`interim_input_transcription`.** The SDK exposes it; it fired 0 times tonight
  and nothing consumes partial caller text. Revisit trigger: a product need for
  live mid-call display.
- **Verifying the role-switch flush rule against a real barge-in** (P10). Why
  later: needs a human voice. Revisit trigger: feature step 4, the first tracer
  call — the transcript is read for split caller turns.

## Open items requiring human decision

Three items. None blocks implementation; all three are recorded because the owner
was away and the escalate list was suspended when they were decided.

1. **`Closed.reason` carries exception detail** — `f"remote: {type(exc).__name__}: {exc}"`
   for a caught exception, bare `"remote"` only for a clean iterator end (Q11 part 2).
   The ratified contract enumerates three reason values and this is a fourth shape.
   *Recommended: keep it.* `reason` is typed `str` not `Literal`, the contract's own
   `"send_failed: <exc>"` already interpolates an exception, nothing downstream parses
   the value, and bridge Q18 (owner-ratified) established that a terminal record which
   cannot distinguish failure modes is "provably not diagnosable". The blind critic,
   asked directly whether this amends ratified text, declined to escalate. **Cheapest
   item to overrule:** one line and one assertion, and no other slice is built on it yet.
2. **P10, barge-in behaviour, accepted as risk** — `interrupted` fired 0 times in
   measurement, so the role-switch flush rule is unverified against a caller talking
   over the model. *Recommended: accept.* The failure direction is turn *splitting* —
   more turns of the same text, never lost or invented text. Revisit trigger: the first
   tracer call with a real human voice (feature step 4), reading that transcript for
   split caller turns.
3. **Exit-criterion threshold** — the smoke's "whole utterance" check (≥ 5 words, ends
   in terminal punctuation) is a threshold that would normally need owner ratification.
   *Recommended: keep.* It is a backstop behind the assertion that actually gates
   (exactly one `Transcript` for the greeting turn, versus ~13 on per-fragment
   emission), and it is anchored to measurement: the observed greeting was 19 words
   ending in `?`, the longest observed fragment 3 words with no terminal punctuation.

## Critic notes (non-blocking)

Surfaced across 10 critic rounds (Phase 2: 3, Phase 3: 4, Phases 4-5: 3). Kept for
the implementer's awareness; none blocks.

### From Phase 2, (critic round 1)

- **S3 must order its two teardowns, and this slice does not do it for them.**
  The shipped `BridgeSession.close()` is sync and does NOT call `gemini.close()`;
  S3 therefore calls both, and the ordering between them is undefined by this
  slice. Correctly out of S2's scope (it is an "Edge existing bridge → S3"
  concern), but S2's `close()` semantics — Q4's ordering invariant and Q10's
  discard-don't-flush — are exactly what S3 will be invoking. Flagged for the S3
  plan; also listed under Deferred.

- **The `_outbox` bound is call-duration-bounded, not size-bounded.** Q5 chose
  unbounded deliberately, and the reasoning there stands. Recorded explicitly so a
  later reader does not mistake the omission for an oversight: if the drain task
  ever stalls *without* raising — awaiting a `send_realtime_input` through a
  network stall that never surfaces as an exception — the queue grows for the rest
  of the call with no ceiling. At 20 ms frames and call lengths measured in
  minutes this is small, and the alternatives (block in a sync method, or drop
  caller audio silently) are both worse. Revisit trigger is in Deferred.

---

**Q11: what the reader catches, and how a non-`APIError` failure gets a `reason`.**
*(Added after critic round 2 — the objection that blocked it.)*

Chosen, in two parts:
1. `_reader`'s outer loop catches **`Exception`**, and emits `Closed` from a
   **`finally`**, so no exit path can leave the stream unterminated.
2. Reason mapping: a clean iterator end → `"remote"`; any caught exception →
   `f"remote: {type(exc).__name__}: {exc}"`.

WHY part 1: the draft previously reasoned about exactly one exception type,
`APIError` (P9). The SDK has at least two. Verified in source: `_receive()` raises
a **bare `ValueError`** on a malformed server frame —
`except json.decoder.JSONDecodeError: raise ValueError(f'Failed to parse response: {raw_response!r}')`
(`live.py:551-552`) — and `receive()` wraps `_receive()` with **no try/except**
(`live.py:455-459`), so it propagates straight into our loop. `_LiveServerMessage_from_mldev`
and `APIError.raise_error` are further paths nobody has enumerated. An
`except APIError` reader therefore dies silently on a malformed frame: no `Closed`
is queued, `events()` awaits an empty queue forever, and S3's teardown — which the
ratified contract requires to run exactly once per call — never fires. The call
hangs rather than ends. This is the round-1 failure family (a corrupted terminal
signal) reached through exception coverage rather than ordering, and a fake that
only ever yields well-formed messages can never exercise it.

The `finally` matters as much as the width of the catch: it is what makes the
guarantee structural rather than a list of paths someone remembered.

WHY part 2: the `reason` must stay diagnosable. This project already settled the
identical question — bridge Q18 ratified that a `frame_error` carrying only
`detail=str(exc)` is "provably not diagnosable" and must name its stage. Collapsing
every receive-side failure to a bare `"remote"` repeats exactly that defect: a
malformed-frame kill and an ordinary hang-up would be indistinguishable in
`CallRecord.ended_reason`, in the one record that survives a call nobody can replay.
Interpolating the exception follows the contract's own established shape —
`"send_failed: <exc>"` already carries an interpolated exception — so this extends
a pattern the contract set rather than inventing one. Nothing downstream parses it:
S3 does `f"gemini_closed: {reason}"` and stores the string.

Rejected: `except APIError` only. Rejected: verified to miss a real raise path, and
the failure mode is a hang, not an error.
Rejected: catch `BaseException`. Steelman: nothing whatsoever escapes. Rejected: it
swallows `CancelledError`, breaking the Q4 cancellation the ordering invariant
depends on.
Rejected: map every exception to bare `"remote"`, unchanged vocabulary. Steelman:
touches no ratified text, and "the remote sent us garbage" IS semantically remote.
Rejected: throws away the only diagnosis available for a call that cannot be
replayed — the Q18 defect, in the same project, for the same reason.
Rejected: widen the vocabulary with a distinct fourth value (e.g. `"reader_error: …"`).
Steelman: most explicit, and does not overload `"remote"`. Rejected: a genuinely
new enumerated value in a ratified contract is a bigger unilateral step than
extending an existing one with detail, and I am unwilling to take the larger one
alone. **Flagged for the owner** in `unattended-decisions.md`.

---

**Q12: what `_translate` does with `server_content.interrupted`, and what happens to
the truncated model turn.**
*(Added after the cold-reader audit — the objection that blocked it.)*

Chosen, in three parts:
1. `_translate` emits `Interrupted()` whenever `server_content.interrupted` is truthy.
2. The truncated model turn is **kept, not discarded**: it flushes normally on the
   `turn_complete` that follows, becoming one `Transcript(role="model", …)` holding
   whatever text accumulated before the interruption.
3. Ordering: `Interrupted` precedes that `Transcript`. This falls out of arrival
   order, since the SDK sends them as separate messages. If a single message ever
   carries both flags, `Interrupted` is emitted first — the interruption is the
   cause of the turn ending, so it reads correctly before the turn's terminal record.

WHY part 1: `Interrupted` is a member of the ratified `LiveEvent` union and Out-of-scope
says in as many words that S2 "surfaces `Interrupted` and nothing more" — translating
the field is this slice's job; only *reacting* to it is deferred. It had no seam, no
test id and no mutation check until the cold read found it, which means a `_translate`
that ignored the field entirely would have passed the whole exit criterion. That is the
same happy-path illusion this artifact hunts everywhere else, sitting on the fourth
member of its own event union.

WHY part 2 is the substantive one. The caller **heard** the words the model got out
before being cut off. A transcript that silently drops them misrepresents what was said
on the call, and S4 classifies the outcome from exactly that transcript. Keeping the
partial turn is also what the existing flush rule already does — `turn_complete` still
arrives on an interrupted turn, so no special case is needed, only a decision not to
add one.

Grounded, not assumed: the SDK documents the sequencing on
`LiveServerContent.generation_complete` — *"When model is interrupted while generating
there will be no generation_complete message in interrupted turn, it will go through
interrupted > turn_complete."* So an interrupted turn is still terminated by
`turn_complete`, and Q3's rule covers it unchanged.

Rejected: discard the truncated turn. Steelman: the model never finished the sentence,
so it is arguably not a real turn. Rejected: the caller heard it; dropping it makes the
transcript disagree with the call, and it is the one artifact S4 has.
Rejected: do not emit `Interrupted` at all, since nothing consumes it today (S3 routes
it to a log-only no-op per bridge Q4). Rejected: it is in the ratified union. A member
that never arrives is a contract violation that stays invisible until someone relies on
it — and P10 already flags barge-in as the least-verified thing here, so the event that
reports it is exactly what a future reader will reach for.
Rejected: flush the truncated turn immediately on `interrupted` rather than waiting for
`turn_complete`. Steelman: emits the transcript at the true moment of truncation.
Rejected: it adds a second flush trigger for no gain — `turn_complete` follows anyway
per the SDK's documented sequencing — and a second trigger is a second thing that can
disagree with the first.

---

### From Phase 2, (critic round 2)

- **`start()` is internal, not part of the S3-facing surface.** The ratified
  `LiveSession` Protocol names `send_audio`, `events`, `close` — not `start`.
  `open_live_session` calls `start()` itself before returning, so S3 never sees it
  and never needs to. It is public only so a test can drive it without a real
  connect. Stated explicitly to avoid Hyrum's-Law creep beyond the ratified
  Protocol.

- **`_inbox` is unbounded, on the same reasoning as `_outbox`.** A slow or
  abandoned `events()` consumer plus a fast reader grows it for the duration of one
  call. Same shape as the `_outbox` note, same conclusion: call-duration-bounded,
  not size-bounded, and the alternatives (drop inbound events, or block the reader)
  are both worse than the bound. Recorded so the omission is not mistaken for an
  oversight.

- **An abandoned `events()` with no `close()` leaks the tasks and the socket.**
  Judged out of scope: S3's ratified guarantee (a) is that `_teardown` — and
  therefore `close()` — runs exactly once on every path that ends a call. S2 is
  entitled to rely on it. Noted for completeness, and listed in Deferred so it is
  not lost if that guarantee ever weakens.

### From Phases 4-5

- `scripts/smoke_gemini_live.py` (this slice's smoke) and the feature Order table's
  `scripts/spike_gemini_live.py` (S2's premise spike) are different artifacts with
  different jobs. See "Note on script naming" under Exit criterion.
- Seam 2's mutation check was inferred rather than labelled in an earlier draft; it is
  now labelled explicitly, so all five mutation checks are named where they belong.

### Standing note for whoever builds S3

The shipped `BridgeSession.close()` is sync and does NOT call `gemini.close()`. S3
therefore calls both, and the ordering between them is undefined by this slice —
correctly, since it is an "Edge existing bridge → S3" concern. But S2's `close()`
semantics (Q4's ordering invariant, Q10's discard-don't-flush) are exactly what S3
will be invoking, so read Q4 before writing that teardown.
