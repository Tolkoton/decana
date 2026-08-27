"""One Gemini Live session for the length of one call.

S3 drives this: it opens a session from a `Profile`, pushes caller audio in
through a SYNC `send_audio` that never raises, and consumes ONE event stream of
`AudioChunk | Transcript | Interrupted | Closed` that ends with exactly one
`Closed`.

Three things about the SDK shape this module exists to absorb, each verified
against the installed source rather than reasoned about (slice artifact P8, P9,
Q11):

  * `AsyncSession.receive()` is a PER-TURN iterator -- it breaks after the first
    `turn_complete` (live.py:455-459). Delegating to it once would end the
    stream after the model's greeting and kill every real call one turn in, with
    every unit test still green. `_read_loop` therefore loops over repeated
    `receive()` calls.
  * A local close and a remote close are INDISTINGUISHABLE by exception:
    `AsyncSession.close()` closes the same socket the reader is blocked on, and
    `_receive()` converts the resulting `ConnectionClosed` to `APIError`
    unconditionally. `close()` therefore orders itself (Q4) rather than letting
    the reader guess.
  * `_receive()` also raises a BARE `ValueError` on a malformed frame
    (live.py:551-552), unwrapped by `receive()`. The reader catches `Exception`,
    not `APIError`, and emits `Closed` from a `finally` -- a narrower catch dies
    silently and hangs `events()` forever.

Transcripts arrive as fragments (`' buy to'`, `' let?'`), never whole utterances,
and `Transcription.finished` is never populated. `_TurnAccumulator` owns the
measured flush rule and nothing else.

What this module does NOT do: sockets or WebSockets, resampling, mu-law,
reconnect, reacting to barge-in (it surfaces `Interrupted` and stops there),
post-call analysis, or transcript persistence.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from google import genai
from google.genai import types

from decana.profile.model import Profile

GREETING_TRIGGER = (
    "[call connected - the disclosure has been played; open the conversation]"
)
"""Sent as one client text turn right after setup, so the model speaks first.

The Live API has no server-initiated greeting; this is the documented
workaround, verified on 5 consecutive spike runs plus a re-run.
"""

_INPUT_MIME = "audio/pcm;rate=16000"

Role = Literal["caller", "model"]


@dataclass(frozen=True)
class AudioChunk:
    """Raw PCM16LE mono 24 kHz from the model. Always even-length."""

    pcm24k: bytes


@dataclass(frozen=True)
class Transcript:
    """ONE WHOLE TURN of speech -- never a fragment.

    Assembling fragments into turns is the single behaviour this module adds on
    top of the SDK, and the one S4 depends on: it serialises these as
    `CALLER: ...` / `MODEL: ...` lines.
    """

    role: Role
    text: str


@dataclass(frozen=True)
class Interrupted:
    """The model was cut off by client input.

    Surfaced, never acted on (bridge Q4 ratified log-only). The turn it
    interrupts is still terminated by `turn_complete`, so its partial text is
    still emitted -- the caller heard those words.
    """


@dataclass(frozen=True)
class Closed:
    """Terminal event. Exactly one, always last.

    `reason` is `"local"`, bare `"remote"` for a clean end,
    `"remote: <Type>: <msg>"` for a receive-side exception, or
    `"send_failed: <Type>: <msg>"`. S3 stores it as
    `CallRecord.ended_reason`, so it must name the failure, not just report one.
    """

    reason: str


LiveEvent = AudioChunk | Transcript | Interrupted | Closed


class LiveTransport(Protocol):
    """What this module needs from a Live session. `AsyncSession` satisfies it.

    Injected, never constructed here -- `open_live_session` is the only function
    in this module that touches `genai`, and it takes the key as an argument.
    """

    async def send_realtime_input(self, *, audio: types.Blob) -> None: ...

    async def send_client_content(
        self, *, turns: types.Content, turn_complete: bool
    ) -> None: ...

    def receive(self) -> AsyncIterator[types.LiveServerMessage]: ...

    async def close(self) -> None: ...


class _TurnAccumulator:
    """Fragments in, whole turns out. Owns the flush rule and nothing else.

    The rule is measured, not assumed (slice artifact P4, Q3):

      * `Transcription.finished` is NEVER populated -- 0 of 36 fragments. An
        accumulator keyed on it would never flush anything.
      * The model turn ends on `turn_complete`.
      * The caller direction has NO terminator in the protocol at all: a 45 s
        drain produced no signal of any kind. So a caller turn is closed by a
        ROLE SWITCH -- the caller stops talking when the model starts answering
        -- or by session close.

    Joining is `"".join`, not `" ".join`: fragments carry their own leading
    spaces (`'Hello, thanks'` + `' for calling.'`), so a separator doubles them.
    """

    def __init__(self) -> None:
        self._role: Role | None = None
        self._parts: list[str] = []

    def add(self, role: Role, text: str) -> list[Transcript]:
        """Take one fragment; emit the previous turn if this one switches role."""
        emitted = self.flush() if role != self._role else []
        self._role = role
        self._parts.append(text)
        return emitted

    def flush(self) -> list[Transcript]:
        """Close the open turn, if any. Safe to call when nothing is open."""
        if self._role is None or not self._parts:
            return []
        turn = Transcript(role=self._role, text="".join(self._parts))
        self._role = None
        self._parts = []
        return [turn]


class GeminiLiveSession:
    """One live call. `open_live_session` builds it; S3 drives it."""

    def __init__(
        self,
        transport: LiveTransport,
        *,
        aclose: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """`aclose` exits the `connect()` context manager (Q6).

        `AsyncSession.close()` only closes the websocket; it never drives the
        `connect()` async generator to `__aexit__`, so without this the
        generator leaks once per call on a long-lived process. Tests pass
        `None` -- a fake owns its own teardown and has no CM to exit.
        """
        self._transport = transport
        self._aclose = aclose
        self._inbox: asyncio.Queue[LiveEvent] = asyncio.Queue()
        self._outbox: asyncio.Queue[bytes] = asyncio.Queue()
        self._turns = _TurnAccumulator()
        self._closed = False
        self._torn_down = False
        self._reader: asyncio.Task[None] | None = None
        self._drain: asyncio.Task[None] | None = None

    async def start(self, *, greeting_trigger: str = GREETING_TRIGGER) -> None:
        """Send the greeting trigger, then start the reader and drain tasks.

        Separate from `__init__` because it must await, and separate from
        `events()` because the model should start speaking whether or not S3 has
        begun iterating yet -- that is not a race S3 should have to know about.
        """
        await self._transport.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=greeting_trigger)]),
            turn_complete=True,
        )
        self._reader = asyncio.create_task(self._read_loop())
        self._drain = asyncio.create_task(self._drain_loop())

    def send_audio(self, pcm16k: bytes) -> None:
        """Queue one caller frame. SYNC, and never raises -- for any reason.

        It is called inside the shipped `BridgeSession`'s Gemini leg under a
        catch scoped to `AudioFrameError` only, so any other exception escaping
        here ends the call. After `Closed` it is a silent no-op.
        """
        if self._closed:
            return
        self._outbox.put_nowait(pcm16k)

    async def events(self) -> AsyncIterator[LiveEvent]:
        """The one event stream, in arrival order, ending at the one `Closed`.

        A pure drain of a single queue written by a single reader: that is what
        makes "interleaved as received" true by construction rather than an
        emergent property some test has to defend.
        """
        while True:
            event = await self._inbox.get()
            yield event
            if isinstance(event, Closed):
                return

    async def close(self) -> None:
        """End the session. Idempotent, and ORDER-SENSITIVE (Q4).

        The order is the whole point. The SDK gives the reader no way to tell
        our close from the remote's -- both close the same socket and surface
        the same `APIError` -- so the reason is decided here, before the reader
        can observe anything, and the reader is stopped before the socket is
        touched at all. Reversing steps 2 and 4 reintroduces a race that
        mislabels a local hang-up as a remote failure in `CallRecord`, silently
        and intermittently, with the suite green.
        """
        if self._torn_down:
            return
        self._torn_down = True
        self._emit_closed("local")
        for task in (self._reader, self._drain):
            if task is not None:
                task.cancel()
        for task in (self._reader, self._drain):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await self._transport.close()
        if self._aclose is not None:
            await self._aclose()

    def _emit_closed(self, reason: str) -> None:
        """The ONLY place a `Closed` is created. Idempotent.

        Any turn still open is flushed FIRST, so a call that ends mid-utterance
        still reports the words the caller actually heard.
        """
        if self._closed:
            return
        self._closed = True
        for turn in self._turns.flush():
            self._inbox.put_nowait(turn)
        self._inbox.put_nowait(Closed(reason))

    async def _read_loop(self) -> None:
        """Repeatedly re-enter `receive()`, translating messages onto the inbox.

        The outer loop is load-bearing: one `receive()` is one TURN. `Closed` is
        emitted from `finally` and the catch is `Exception`, not `APIError`, so
        that no exit path -- including the SDK's bare `ValueError` on a
        malformed frame -- can leave `events()` awaiting a queue nothing will
        ever fill.
        """
        reason = "remote"
        try:
            while not self._closed:
                delivered = False
                async for message in self._transport.receive():
                    delivered = True
                    for event in self._translate(message):
                        self._inbox.put_nowait(event)
                    if self._closed:
                        break
                if not delivered:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- see docstring; narrower hangs the call
            reason = f"remote: {type(exc).__name__}: {exc}"
        finally:
            self._emit_closed(reason)

    def _translate(self, message: types.LiveServerMessage) -> list[LiveEvent]:
        """One SDK message to zero or more events. Pure apart from the accumulator.

        Audio is appended directly, never held behind the accumulator: a chunk
        buffered until its turn completes would add turn-length latency to every
        response while every count-based test stayed green.

        `Interrupted` precedes the `Transcript` that `turn_complete` flushes --
        the interruption is why the turn ended, so it reads correctly first.
        """
        content = message.server_content
        if content is None:
            return []
        events: list[LiveEvent] = []
        if content.input_transcription and content.input_transcription.text:
            events.extend(self._turns.add("caller", content.input_transcription.text))
        if content.output_transcription and content.output_transcription.text:
            events.extend(self._turns.add("model", content.output_transcription.text))
        if pcm := message.data:
            events.append(AudioChunk(pcm24k=pcm))
        if content.interrupted:
            events.append(Interrupted())
        if content.turn_complete:
            events.extend(self._turns.flush())
        return events

    async def _drain_loop(self) -> None:
        """Feed queued caller audio into the async session, in FIFO order.

        This is what lets `send_audio` be sync and never raise: a send failure
        becomes a `Closed`, not an exception thrown back at the bridge.
        """
        try:
            while True:
                pcm = await self._outbox.get()
                await self._transport.send_realtime_input(
                    audio=types.Blob(data=pcm, mime_type=_INPUT_MIME)
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- surfaced as Closed, never raised
            self._emit_closed(f"send_failed: {type(exc).__name__}: {exc}")


async def open_live_session(
    profile: Profile,
    *,
    api_key: str,
    greeting_trigger: str = GREETING_TRIGGER,
) -> GeminiLiveSession:
    """Connect, configure from the profile, greet, and hand back a live session.

    The `connect()` context manager is entered manually because the session must
    outlive this function -- S3 opens one per call and drives it from elsewhere.
    Its exit is handed to the session as `aclose` so `close()` can complete it.

    Raises on a connect-time failure, deliberately: that happens before a call
    exists, and S3 needs to see it rather than receive a `Closed` for a session
    that never opened.
    """
    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=profile.conversation,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    manager = client.aio.live.connect(model=profile.live_model, config=config)
    transport = await manager.__aenter__()

    async def _exit() -> None:
        await manager.__aexit__(None, None, None)

    session = GeminiLiveSession(transport, aclose=_exit)
    await session.start(greeting_trigger=greeting_trigger)
    return session


__all__ = [
    "GREETING_TRIGGER",
    "AudioChunk",
    "Closed",
    "GeminiLiveSession",
    "Interrupted",
    "LiveEvent",
    "LiveTransport",
    "Transcript",
    "open_live_session",
]
