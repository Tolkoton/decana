"""Tests for `decana.gemini.live`, one node per ratified test id (23 of them).

The fake transport carries three fidelities the real SDK has and a careless fake
would not. Each exists because a test depends on it, and without it that test
passes against both the correct implementation and the broken one:

  1. `receive()` serves ONE turn and terminates (`S1`).
  2. `close()` makes an in-flight `receive()` raise `APIError` (`S8-local`).
  3. An explicit gate, never a sleep, positions a close mid-turn (`S3f`).

Async tests run through `asyncio.run` inside ordinary sync test functions, so no
pytest plugin is needed. Every test that consumes `events()` runs under a
timeout: the failure mode being ruled out is a HANG, and a test that hangs takes
the suite with it and reports nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Sequence

from google.genai import types

from decana.gemini.live import (
    AudioChunk,
    Closed,
    GeminiLiveSession,
    Interrupted,
    LiveEvent,
    Transcript,
)

TIMEOUT = 5.0


def run[T](coro: Awaitable[T]) -> T:
    """Run one coroutine to completion under a hard timeout."""

    async def _bounded() -> T:
        return await asyncio.wait_for(coro, TIMEOUT)

    return asyncio.run(_bounded())


# --------------------------------------------------------------------------
# message builders -- real `types.LiveServerMessage`, so translation is tested
# against the type the SDK actually delivers, not a stand-in for it.
# --------------------------------------------------------------------------


def _msg(**content_kwargs: object) -> types.LiveServerMessage:
    return types.LiveServerMessage(
        server_content=types.LiveServerContent(**content_kwargs)  # type: ignore[arg-type]
    )


def out_frag(text: str) -> types.LiveServerMessage:
    return _msg(output_transcription=types.Transcription(text=text))


def in_frag(text: str) -> types.LiveServerMessage:
    return _msg(input_transcription=types.Transcription(text=text))


def audio(payload: bytes) -> types.LiveServerMessage:
    return _msg(
        model_turn=types.Content(
            parts=[
                types.Part(
                    inline_data=types.Blob(
                        data=payload, mime_type="audio/pcm;rate=24000"
                    )
                )
            ]
        )
    )


def turn_done() -> types.LiveServerMessage:
    return _msg(turn_complete=True)


def interrupted() -> types.LiveServerMessage:
    return _msg(interrupted=True)


def api_error() -> Exception:
    """The exception the real `_receive()` raises when the socket closes."""
    from google.genai import errors

    return errors.APIError(503, {"message": "socket closed"})


# --------------------------------------------------------------------------
# the fake transport
# --------------------------------------------------------------------------


class FakeTransport:
    """A `LiveTransport` that reproduces the three SDK behaviours that bite."""

    def __init__(
        self,
        turns: Sequence[Sequence[types.LiveServerMessage]] = (),
        *,
        end_cleanly: bool = False,
    ) -> None:
        self._turns = [list(t) for t in turns]
        self._end_cleanly = end_cleanly
        self.sent: list[bytes] = []
        self.greetings: list[str] = []
        self.close_calls = 0
        self.send_error: Exception | None = None
        self.receive_error: Exception | None = None
        self._shut = asyncio.Event()
        # gate: when set, receive() pauses before the message at this index
        self.pause_before: int | None = None
        self.at_gate = asyncio.Event()
        self.release = asyncio.Event()

    async def send_realtime_input(self, *, audio: types.Blob) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(bytes(audio.data or b""))

    async def send_client_content(
        self, *, turns: types.Content, turn_complete: bool
    ) -> None:
        parts = turns.parts or []
        self.greetings.append(parts[0].text or "" if parts else "")

    async def receive(self) -> AsyncIterator[types.LiveServerMessage]:
        """One call serves ONE turn, then stops -- exactly like the SDK."""
        if self.receive_error is not None:
            raise self.receive_error
        if not self._turns:
            if self._end_cleanly:
                return
            await self._shut.wait()
            raise api_error()
        for index, message in enumerate(self._turns.pop(0)):
            if self.pause_before is not None and index == self.pause_before:
                await self._gate()
            yield message
            if message.server_content and message.server_content.turn_complete:
                return

    async def _gate(self) -> None:
        """Block until the test releases, or raise if the socket closed first."""
        self.at_gate.set()
        waiters = {
            asyncio.ensure_future(self.release.wait()),
            asyncio.ensure_future(self._shut.wait()),
        }
        _done, pending = await asyncio.wait(
            waiters, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if self._shut.is_set():
            raise api_error()

    async def close(self) -> None:
        self.close_calls += 1
        self._shut.set()


async def collect(session: GeminiLiveSession) -> list[LiveEvent]:
    """Drain the whole stream to its terminal `Closed`."""
    return [event async for event in session.events()]


async def drive(
    turns: Sequence[Sequence[types.LiveServerMessage]],
    *,
    end_cleanly: bool = False,
) -> list[LiveEvent]:
    """Start a session over a scripted fake and collect every event."""
    transport = FakeTransport(turns, end_cleanly=end_cleanly)
    session = GeminiLiveSession(transport)
    await session.start()
    return await collect(session)


def only[T](events: Sequence[LiveEvent], kind: type[T]) -> list[T]:
    return [e for e in events if isinstance(e, kind)]


# --------------------------------------------------------------------------
# S1 -- the per-turn receive() break
# --------------------------------------------------------------------------


def test_s1_events_span_multiple_receive_calls() -> None:
    """S1: a 3-turn script arrives on ONE events() stream.

    The real receive() breaks after each turn_complete. An implementation that
    delegates to a single receive() ends the stream after turn 1 -- and would
    kill every real call one turn in while looking correct.
    """
    script = [
        [out_frag("one."), turn_done()],
        [out_frag("two."), turn_done()],
        [out_frag("three."), turn_done()],
    ]
    events = run(drive(script, end_cleanly=True))
    texts = [t.text for t in only(events, Transcript)]
    assert texts == ["one.", "two.", "three."]


# --------------------------------------------------------------------------
# S2 -- fragments joined into one turn, with the right text
# --------------------------------------------------------------------------


def test_s2_fragments_join_into_one_turn() -> None:
    """S2: measured fragments become exactly one Transcript, joined with "".

    Fragments carry their own leading spaces, so " ".join doubles them. Only a
    text assertion catches that; counting events does not.
    """
    fragments = ["Hello, thanks", " for calling.", " Are you", " buy to", " let?"]
    script = [[out_frag(f) for f in fragments] + [turn_done()]]
    events = run(drive(script, end_cleanly=True))
    transcripts = only(events, Transcript)
    assert len(transcripts) == 1
    assert transcripts[0].text == "Hello, thanks for calling. Are you buy to let?"
    assert transcripts[0].role == "model"


# --------------------------------------------------------------------------
# S3 -- exactly one Closed, and the exact reason, on every terminal path
# --------------------------------------------------------------------------


def _assert_one_closed_last(events: Sequence[LiveEvent]) -> Closed:
    closed = only(events, Closed)
    assert len(closed) == 1, f"expected exactly one Closed, got {len(closed)}"
    assert isinstance(events[-1], Closed), "Closed must be the last event"
    return closed[0]


def test_s3a_local_close_reason_is_local() -> None:
    """S3a: close() we initiated is reported as "local"."""

    async def scenario() -> list[LiveEvent]:
        transport = FakeTransport([[out_frag("hi."), turn_done()]])
        session = GeminiLiveSession(transport)
        await session.start()
        await asyncio.sleep(0)
        await session.close()
        return await collect(session)

    events = run(scenario())
    assert _assert_one_closed_last(events).reason == "local"


def test_s3b_remote_api_error_names_the_exception() -> None:
    """S3b: a receive-side APIError is reported WITH its type, not bare."""

    async def scenario() -> list[LiveEvent]:
        transport = FakeTransport()
        transport.receive_error = api_error()
        session = GeminiLiveSession(transport)
        await session.start()
        return await collect(session)

    events = run(scenario())
    assert _assert_one_closed_last(events).reason.startswith("remote: APIError")


def test_s3c_clean_iterator_end_is_bare_remote() -> None:
    """S3c: a clean end of the session iterator -- the ONLY bare "remote"."""
    events = run(drive([[out_frag("bye."), turn_done()]], end_cleanly=True))
    assert _assert_one_closed_last(events).reason == "remote"


def test_s3d_send_failure_is_send_failed() -> None:
    """S3d: a drain-task send failure surfaces as Closed, never as a raise."""

    async def scenario() -> list[LiveEvent]:
        transport = FakeTransport()
        transport.send_error = RuntimeError("socket gone")
        session = GeminiLiveSession(transport)
        await session.start()
        session.send_audio(b"\x00\x01")
        return await collect(session)

    events = run(scenario())
    assert _assert_one_closed_last(events).reason.startswith("send_failed: ")


def test_s3e_close_twice_still_one_closed() -> None:
    """S3e: idempotent close -- two calls, still exactly one Closed."""

    async def scenario() -> list[LiveEvent]:
        transport = FakeTransport([[out_frag("hi."), turn_done()]])
        session = GeminiLiveSession(transport)
        await session.start()
        await session.close()
        await session.close()
        assert transport.close_calls == 1, "transport must be torn down once"
        return await collect(session)

    events = run(scenario())
    assert _assert_one_closed_last(events).reason == "local"


def test_s3f_close_mid_model_turn_flushes_partial_transcript() -> None:
    """S3f: a call ending mid-utterance still reports what the caller heard.

    A flush that handles only the caller branch passes every other test here
    and silently drops the tail of any call ending mid-model-turn.
    """

    async def scenario() -> list[LiveEvent]:
        script = [[out_frag("Hello, thanks"), out_frag(" for calling."), turn_done()]]
        transport = FakeTransport(script)
        transport.pause_before = 2  # pause before turn_complete
        session = GeminiLiveSession(transport)
        await session.start()
        await asyncio.wait_for(transport.at_gate.wait(), TIMEOUT)
        await session.close()
        return await collect(session)

    events = run(scenario())
    closed = _assert_one_closed_last(events)
    assert closed.reason == "local"
    transcripts = only(events, Transcript)
    assert len(transcripts) == 1
    assert transcripts[0] == Transcript(role="model", text="Hello, thanks for calling.")
    assert events.index(transcripts[0]) < events.index(closed)


# --------------------------------------------------------------------------
# S4 -- a dead reader must not become a hung events()
# --------------------------------------------------------------------------


class TranslateExplodes(GeminiLiveSession):
    """A session whose translation step fails, as an unforeseen shape would.

    Subclassed rather than monkey-patched: the override keeps the real
    signature, so this stays honest under `mypy --strict` instead of needing an
    ignore that would also hide a genuine mismatch.
    """

    def _translate(self, message: types.LiveServerMessage) -> list[LiveEvent]:
        raise ValueError("unexpected message shape")


def test_s4a_translate_failure_still_closes_the_stream() -> None:
    """S4a: an unexpected message shape ends the stream instead of hanging it."""

    async def scenario() -> list[LiveEvent]:
        session = TranslateExplodes(FakeTransport([[out_frag("hi.")]]))
        await session.start()
        return await collect(session)

    events = run(scenario())
    reason = _assert_one_closed_last(events).reason
    assert reason.startswith("remote: "), reason
    assert reason != "remote", "a translate failure must not look like a clean close"


def test_s4b_bare_valueerror_from_receive_still_closes_the_stream() -> None:
    """S4b: the SDK's own malformed-JSON ValueError must not kill us silently.

    `_receive()` raises a BARE ValueError (live.py:551-552) and `receive()` does
    not wrap it. A reader scoped to `except APIError` dies here with no Closed
    queued, and events() then waits forever.
    """

    async def scenario() -> list[LiveEvent]:
        transport = FakeTransport()
        transport.receive_error = ValueError("Failed to parse response: b'{'")
        session = GeminiLiveSession(transport)
        await session.start()
        return await collect(session)

    events = run(scenario())
    assert _assert_one_closed_last(events).reason.startswith("remote: ValueError")


# --------------------------------------------------------------------------
# S5 -- send_audio never raises, in every state
# --------------------------------------------------------------------------


def test_s5a_send_audio_before_start_does_not_raise() -> None:
    """S5a: queued before the tasks exist -- still no raise."""
    session = GeminiLiveSession(FakeTransport())
    session.send_audio(b"\x00\x01")


def test_s5b_send_audio_after_closed_event_is_a_noop() -> None:
    """S5b: after the terminal Closed, sending is silently dropped."""

    async def scenario() -> FakeTransport:
        transport = FakeTransport()
        transport.receive_error = api_error()
        session = GeminiLiveSession(transport)
        await session.start()
        await collect(session)
        session.send_audio(b"\x00\x01")
        await asyncio.sleep(0)
        return transport

    transport = run(scenario())
    assert transport.sent == []


def test_s5c_send_audio_after_close_is_a_noop() -> None:
    """S5c: after close(), sending is silently dropped."""

    async def scenario() -> FakeTransport:
        transport = FakeTransport()
        session = GeminiLiveSession(transport)
        await session.start()
        await session.close()
        session.send_audio(b"\x00\x01")
        return transport

    transport = run(scenario())
    assert transport.sent == []


def test_s5d_send_audio_after_drain_died_is_a_noop() -> None:
    """S5d: a dead drain task must not turn the next send into a raise."""

    async def scenario() -> FakeTransport:
        transport = FakeTransport()
        transport.send_error = RuntimeError("gone")
        session = GeminiLiveSession(transport)
        await session.start()
        session.send_audio(b"\x00\x01")
        await collect(session)
        session.send_audio(b"\x02\x03")
        await asyncio.sleep(0)
        return transport

    transport = run(scenario())
    assert transport.sent == []


def test_s5e_send_audio_empty_does_not_raise() -> None:
    """S5e: an empty frame is not an error at this boundary."""
    session = GeminiLiveSession(FakeTransport())
    session.send_audio(b"")


# --------------------------------------------------------------------------
# S6 -- caller-turn flush on role switch
# --------------------------------------------------------------------------


def test_s6a_caller_turn_flushes_on_role_switch_before_model_turn() -> None:
    """S6a: the caller's turn closes when the model starts answering.

    The caller direction has no protocol terminator at all, so this structural
    boundary is the only one available -- and the order matters, because S4
    reads these as an ordered conversation.
    """
    script = [
        [
            in_frag("I want"),
            in_frag(" to remortgage."),
            out_frag("Happy to help"),
            out_frag(" with that."),
            turn_done(),
        ]
    ]
    events = run(drive(script, end_cleanly=True))
    transcripts = only(events, Transcript)
    assert transcripts == [
        Transcript(role="caller", text="I want to remortgage."),
        Transcript(role="model", text="Happy to help with that."),
    ]


def test_s6b_open_caller_turn_flushes_before_closed() -> None:
    """S6b: a caller turn still open at close is not dropped."""

    async def scenario() -> list[LiveEvent]:
        transport = FakeTransport([[in_frag("Hello"), in_frag(" there.")]])
        session = GeminiLiveSession(transport)
        await session.start()
        await asyncio.sleep(0)
        await session.close()
        return await collect(session)

    events = run(scenario())
    closed = _assert_one_closed_last(events)
    transcripts = only(events, Transcript)
    assert transcripts == [Transcript(role="caller", text="Hello there.")]
    assert events.index(transcripts[0]) < events.index(closed)


# --------------------------------------------------------------------------
# S7 -- arrival order of audio against transcript
# --------------------------------------------------------------------------


def test_s7_audio_is_not_withheld_behind_the_accumulator() -> None:
    """S7: audio flows in arrival order, never buffered until the turn ends.

    Buffering audio behind the turn accumulator adds turn-length latency to
    every response while every count-based assertion stays green.
    """
    script = [
        [
            out_frag("Hello"),
            audio(b"\x01\x02"),
            out_frag(" there."),
            audio(b"\x03\x04"),
            turn_done(),
        ]
    ]
    events = run(drive(script, end_cleanly=True))
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["AudioChunk", "AudioChunk", "Transcript", "Closed"]
    assert [c.pcm24k for c in only(events, AudioChunk)] == [b"\x01\x02", b"\x03\x04"]


# --------------------------------------------------------------------------
# S8 -- local close must never be recorded as remote
# --------------------------------------------------------------------------


def test_s8_local_close_mid_turn_is_not_mislabelled_remote() -> None:
    """S8-local: our own close, against a socket that raises in-flight.

    The SDK cannot distinguish these: close() closes the same socket the reader
    is blocked on, and the resulting exception is the identical APIError a real
    remote close produces. Only close()'s ordering makes the answer definite.
    """

    async def scenario() -> list[LiveEvent]:
        transport = FakeTransport([[out_frag("hi"), turn_done()]])
        transport.pause_before = 1
        session = GeminiLiveSession(transport)
        await session.start()
        await asyncio.wait_for(transport.at_gate.wait(), TIMEOUT)
        await session.close()
        return await collect(session)

    events = run(scenario())
    assert _assert_one_closed_last(events).reason == "local"


def test_s8_genuine_remote_close_is_labelled_remote() -> None:
    """S8-remote: the twin, so the two are distinguished by design not by luck."""

    async def scenario() -> list[LiveEvent]:
        transport = FakeTransport()
        transport.receive_error = api_error()
        session = GeminiLiveSession(transport)
        await session.start()
        return await collect(session)

    events = run(scenario())
    assert _assert_one_closed_last(events).reason.startswith("remote: APIError")


# --------------------------------------------------------------------------
# S9 -- Interrupted is surfaced, and the truncated turn is kept
# --------------------------------------------------------------------------


def test_s9a_interrupted_is_emitted() -> None:
    """S9a: the event exists in the stream at all.

    It is a member of the ratified LiveEvent union; a _translate that never
    reads the field would otherwise pass every other test in this file.
    """
    script = [[out_frag("Let me expl"), interrupted(), turn_done()]]
    events = run(drive(script, end_cleanly=True))
    assert len(only(events, Interrupted)) == 1


def test_s9b_interrupted_turn_keeps_its_partial_transcript() -> None:
    """S9b: words the caller heard before the cut are still transcribed.

    The SDK documents that an interrupted turn still ends with turn_complete,
    so the ordinary flush covers it -- provided nobody adds a special case that
    discards it. Interrupted comes first: it is why the turn ended.
    """
    script = [[out_frag("Let me expl"), interrupted(), turn_done()]]
    events = run(drive(script, end_cleanly=True))
    transcripts = only(events, Transcript)
    assert transcripts == [Transcript(role="model", text="Let me expl")]
    assert events.index(only(events, Interrupted)[0]) < events.index(transcripts[0])


# --------------------------------------------------------------------------
# S10 -- the greeting trigger, which start() owes the contract
# --------------------------------------------------------------------------


def test_s10_start_sends_exactly_one_greeting_trigger() -> None:
    """S10: contract guarantee (b) -- one text turn on open, before any audio.

    This is what makes the model speak first; the Live API has no
    server-initiated greeting. Nothing else in this suite covers it, and a
    start() that skipped it would leave every real call silent until the caller
    spoke -- inverting the whole design.
    """

    async def scenario() -> FakeTransport:
        transport = FakeTransport()
        session = GeminiLiveSession(transport)
        await session.start()
        await session.close()
        return transport

    transport = run(scenario())
    assert len(transport.greetings) == 1
    assert "disclosure" in transport.greetings[0]
    assert transport.sent == [], "no audio may precede the greeting turn"
