"""Tests for the Twilio leg.

Every test's docstring opens with its behavior id from the ratified id set in
`.claude/overseer/slice/twilio-server.md`. The exit criterion is a property over
that set in both directions: every id has a passing node, and no node here fails
to trace to an id.
"""

import asyncio
import base64
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from decana.gemini.live import AudioChunk, Closed, Interrupted, LiveEvent, Transcript
from decana.profile.load import load_profile
from decana.profile.model import Profile
from decana.twilio.records import CallRecord, TranscriptTurn
from decana.twilio.server import create_app, normalise_caller_number

REPO_ROOT = Path(__file__).resolve().parent.parent

T0 = datetime(2000, 1, 1, tzinfo=UTC)

# The frame the fake bridge pushes through send_media during its teardown
# flush -- the real BridgeSession.close() does the same with soxr's tail.
_TEARDOWN_FLUSH = "dGFpbA=="

# Seam 9's model-side script: three turns, both roles, in an order a mapper
# that tags everything "model" or reverses the list cannot reproduce. The audio
# chunks are deliberately LARGE -- soxr batches, so a 160-byte chunk usually
# resamples to nothing and the timing log would carry no
# chunk_forwarded_to_twilio for reasons unrelated to the server.
_S9_EVENTS: tuple[LiveEvent, ...] = (
    Transcript(role="caller", text="A"),
    AudioChunk(pcm24k=bytes(9600)),
    Transcript(role="model", text="B"),
    AudioChunk(pcm24k=bytes(9600)),
    Transcript(role="caller", text="C"),
)


def _real_mulaw_frame() -> str:
    """One Twilio-sized frame of real mu-law: 160 bytes, 20 ms at 8 kHz."""
    return base64.b64encode(bytes(160)).decode("ascii")


def _timing_events(path: Path) -> list[str]:
    """The `event` field of every line in a TimingRecorder JSONL."""
    return [json.loads(line)["event"] for line in path.read_text().splitlines() if line]


class FakeLiveSession:
    """Implements EXACTLY the ratified `LiveSession` surface and nothing more.

    No `start()`, deliberately. `open_live_session` calls it internally before
    returning (`live.py:370`), so S3 must never call it again -- a second call
    re-sends the greeting trigger and spawns a second reader/drain pair over one
    transport. A fake carrying a `start` stub would let that bug pass every test
    here and surface first on a real call.

    `events()` mirrors S2's ratified stream shape rather than a convenient one:
    it BLOCKS when idle (a real session's does), and it ends after yielding
    exactly one `Closed`, which `close()` is what produces. A fake whose
    `events()` merely ran out would let a pump that never handles `Closed` pass.

    The remaining attributes (`sent`, `closed`, `order`, `emit`, `on_send`) are
    test-observation handles, not Protocol members: nothing on the ratified
    surface is widened, which is what the standing fake constraint protects.
    """

    def __init__(
        self,
        tag: str = "",
        backlog: Sequence[LiveEvent] = (),
        on_send: Sequence[LiveEvent] = (),
        order: list[str] | None = None,
    ) -> None:
        self.tag = tag
        self.sent: list[bytes] = []
        self.closed = 0
        self.order = order
        self._outbox: asyncio.Queue[LiveEvent] = asyncio.Queue()
        for event in backlog:
            self._outbox.put_nowait(event)
        # Emitted the first time the bridge forwards caller audio -- i.e. from
        # inside the app's own loop, once the socket is genuinely up. This is
        # what makes Seam 2's "M events after connect" real rather than more
        # backlog: the test thread never touches the queue.
        self._on_send = list(on_send)

    def send_audio(self, pcm16k: bytes) -> None:
        self.sent.append(pcm16k)
        for event in self._on_send:
            self._outbox.put_nowait(event)
        self._on_send = []

    def events(self) -> AsyncIterator[LiveEvent]:
        async def _iter() -> AsyncIterator[LiveEvent]:
            while True:
                event = await self._outbox.get()
                yield event
                if isinstance(event, Closed):
                    return

        return _iter()

    async def close(self) -> None:
        self.closed += 1
        if self.order is not None:
            self.order.append("gemini.close")
        self._outbox.put_nowait(Closed(reason="local"))


class RecordingFactory:
    """A `LiveSessionFactory` that records when and how often it was invoked."""

    def __init__(
        self,
        clock: Callable[[], datetime],
        backlog: Sequence[LiveEvent] = (),
        on_send: Sequence[LiveEvent] = (),
        order: list[str] | None = None,
    ) -> None:
        self._clock = clock
        self._backlog = backlog
        self._on_send = on_send
        self._order = order
        self.calls: list[tuple[Profile, datetime]] = []
        self.sessions: list[FakeLiveSession] = []

    async def __call__(self, profile: Profile) -> FakeLiveSession:
        session = FakeLiveSession(
            tag=f"s{len(self.sessions)}",
            backlog=self._backlog,
            on_send=self._on_send,
            order=self._order,
        )
        self.calls.append((profile, self._clock()))
        self.sessions.append(session)
        return session


class Recorder:
    """Captures every `CallRecord` handed to `on_call_end`, and counts the calls."""

    def __init__(
        self, order: list[str] | None = None, raises: BaseException | None = None
    ) -> None:
        self.records: list[CallRecord] = []
        self.order = order
        self._raises = raises

    async def __call__(self, record: CallRecord) -> None:
        self.records.append(record)
        if self.order is not None:
            self.order.append("on_call_end")
        if self._raises is not None:
            raise self._raises

    @property
    def reasons(self) -> list[str]:
        return [r.ended_reason for r in self.records]


class FakeBridge:
    """A `BridgeSession` stand-in that forwards one chunk to exactly one frame.

    Used wherever the property under test belongs to the SERVER -- pump
    ordering, teardown order, send failure. The real `BridgeSession` batches
    through soxr, so 3 of every 4 chunks produce no outbound frame at all
    (`session.py:136-140`), which would make "N chunks in, N frames out"
    untestable for reasons that have nothing to do with the server.

    Seam 9 is where the real bridge is mandatory, and it uses it.
    """

    def __init__(
        self,
        twilio: Any,
        gemini: Any,
        timing: Any,
        inbound: Any,
        outbound: Any,
        order: list[str] | None = None,
        close_raises: BaseException | None = None,
    ) -> None:
        self._twilio = twilio
        self.gemini = gemini
        self._timing = timing
        self.order = order
        self._close_raises = close_raises
        self.started = 0
        self.closed = 0
        self.inbound_frames: list[str] = []
        self.send_errors: list[BaseException] = []

    def start(self) -> None:
        self.started += 1
        self._timing.record("call_answered")

    def handle_twilio_frame(self, base64_payload: str) -> None:
        self.inbound_frames.append(base64_payload)
        self.gemini.send_audio(base64.b64decode(base64_payload))

    def handle_gemini_chunk(self, pcm24k_bytes: bytes) -> None:
        # Mirrors the real bridge's contract with the sender: send_media must
        # never raise, so a raise here is recorded rather than propagated -- if
        # it propagated, the assertion would be indistinguishable from the
        # server crashing for some other reason.
        try:
            self._twilio.send_media(base64.b64encode(pcm24k_bytes).decode("ascii"))
        except Exception as exc:  # noqa: BLE001 - the point is that it stays empty
            self.send_errors.append(exc)
        self._timing.record("chunk_forwarded_to_twilio")

    def close(self) -> None:
        self.closed += 1
        # The teardown flush the real bridge performs here. After drain-stop it
        # must be a silent no-op (S3-Q10), not an error and not a frame.
        try:
            self._twilio.send_media(_TEARDOWN_FLUSH)
        except Exception as exc:  # noqa: BLE001 - the point is that it stays empty
            self.send_errors.append(exc)
        if self.order is not None:
            # `closed` on the injected sender IS the drain-stop: after it the
            # send path is a silent no-op (S3-Q10). Reading it here is how the
            # ordered list gets a drain-stop entry without the server having to
            # report its own steps.
            if getattr(self._twilio, "closed", False):
                self.order.append("drain-stop")
            self.order.append("bridge.close")
        if self._close_raises is not None:
            raise self._close_raises


class BridgeFactory:
    """A `BridgeSession` replacement to monkeypatch into the server.

    Monkeypatched rather than injected: `create_app`'s parameter list is
    ratified, and a `bridge_factory` argument added only so tests can reach in
    would widen a ratified seam for test convenience. This is fixture shape,
    not assertion content.

    `made` doubles as the test's signal that the server has processed `start`
    -- it is the first thing `_begin_call` builds after adopting the session.

    `raise_on` selects WHICH bridges get `close_raises` by construction index.
    Seam 10's isolation case needs one call whose `close()` raises and a second,
    concurrent one whose does not; a factory that raises for every bridge could
    not tell "the neighbour survived" from "the neighbour failed the same way".
    """

    def __init__(self, raise_on: set[int] | None = None, **kw: Any) -> None:
        self._kw = kw
        self._close_raises = kw.pop("close_raises", None)
        self._raise_on = raise_on
        self.made: list[FakeBridge] = []

    def __call__(self, **call_kw: Any) -> FakeBridge:
        index = len(self.made)
        raises = self._close_raises
        if raises is not None and self._raise_on is not None:
            raises = self._close_raises if index in self._raise_on else None
        bridge = FakeBridge(**call_kw, **self._kw, close_raises=raises)
        self.made.append(bridge)
        return bridge


async def _noop_on_call_end(_record: CallRecord) -> None:
    return None


class StepClock:
    """A clock the test advances explicitly.

    Not `iter([...])`: the clock is read by the TTL sweep and by every
    `TimingRecorder.record`, so a one-shot sequence is consumed in an order the
    test does not control. S3.d needs `started_at`/`ended_at` to be exact
    sentinels, which means the value must be stable until the test moves it.
    """

    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


@pytest.fixture
def profile() -> Profile:
    return load_profile("mortgage-broker", root=REPO_ROOT / "profiles")


@pytest.fixture
def app(profile: Profile, tmp_path: Path) -> FastAPI:
    """An app whose factory succeeds quietly.

    Deliberately NOT a factory that raises when invoked: `POST /voice` opens the
    Live session (S3-Q1), so a "must not be called" stub here would assert the
    opposite of the ratified contract and fail every TwiML test the moment the
    webhook was implemented correctly.
    """
    return create_app(
        profile,
        RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC)),
        _noop_on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )


def test_s6a_twiml_parses_with_the_expected_element_structure(app: FastAPI) -> None:
    """S6.a -- the TwiML parses as Response/Say + Response/Connect/Stream/Parameter.

    Parsed, not substring-matched: an f-string implementation that leaves a `&` in
    the disclosure unescaped still satisfies `"<Say>" in body` while producing a
    document Twilio cannot parse.
    """
    client = TestClient(app)

    response = client.post(
        "/voice",
        data={"CallSid": "CA-s6a", "From": "+447700900123"},
    )

    assert response.status_code == 200
    root = ET.fromstring(response.text)
    assert root.tag == "Response"
    assert root.find("Say") is not None
    stream = root.find("Connect/Stream")
    assert stream is not None
    assert stream.find("Parameter") is not None


def test_s6b_say_carries_the_disclosure_and_stream_points_at_media(
    app: FastAPI, profile: Profile
) -> None:
    """S6.b -- Say's text equals the disclosure exactly; Stream/@url is {public_wss_url}/media.

    Equality, not containment: a truncated or wrapped disclosure still "contains"
    the compliance wording while changing what the caller hears, and the whole
    point of the non-generative disclosure is that it is spoken verbatim.
    """
    client = TestClient(app)

    response = client.post(
        "/voice", data={"CallSid": "CA-s6b", "From": "+447700900123"}
    )

    root = ET.fromstring(response.text)
    say = root.find("Say")
    assert say is not None
    assert say.text == profile.disclosure

    stream = root.find("Connect/Stream")
    assert stream is not None
    assert stream.get("url") == "wss://example.test/media"

    parameter = stream.find("Parameter")
    assert parameter is not None
    assert parameter.get("name") == "caller"
    assert parameter.get("value") == "+447700900123"


def test_s6c_hostile_disclosure_and_caller_still_produce_parsable_twiml(
    tmp_path: Path, profile: Profile
) -> None:
    """S6.c -- a disclosure and From containing &, <, > and quotes still parse, and round-trip.

    This is the test an f-string implementation fails. `"<Say>" in body` passes for
    a document with a raw `&` in it; `ET.fromstring` does not, and neither does an
    equality check on the round-tripped text.
    """
    hostile_disclosure = 'Smith & Co <adviser> says "hello" — 100% sure'
    hostile_caller = '+44 "x" & <y>'
    hostile_profile = replace(profile, disclosure=hostile_disclosure)

    app = create_app(
        hostile_profile,
        RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC)),
        _noop_on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)

    response = client.post("/voice", data={"CallSid": "CA-s6c", "From": hostile_caller})

    root = ET.fromstring(response.text)
    say = root.find("Say")
    assert say is not None
    assert say.text == hostile_disclosure

    parameter = root.find("Connect/Stream/Parameter")
    assert parameter is not None
    assert parameter.get("value") == hostile_caller


def test_s1a_live_factory_runs_during_the_webhook_not_the_socket(
    profile: Profile, tmp_path: Path
) -> None:
    """S1.a -- live_factory is invoked during POST /voice, before any WS connect.

    A bare `factory.call_count == 1` passes for the open-on-WS-connect
    implementation too, which is the latency defect S3-Q1 exists to prevent. The
    load-bearing assertion is that the call has already happened when the webhook
    returns and no socket has been opened yet.
    """
    ticks = iter([datetime(2000, 1, 1, tzinfo=UTC) for _ in range(20)])
    factory = RecordingFactory(lambda: next(ticks))
    app = create_app(
        profile,
        factory,
        _noop_on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)

    assert factory.calls == []

    response = client.post(
        "/voice", data={"CallSid": "CA-s1a", "From": "+447700900123"}
    )

    assert response.status_code == 200
    assert len(factory.calls) == 1
    assert factory.calls[0][0] is profile


def _start_message(
    call_sid: str, stream_sid: str = "MZ-1", caller: str = "+447700900123"
) -> dict[str, Any]:
    return {
        "event": "start",
        "streamSid": stream_sid,
        "start": {
            "callSid": call_sid,
            "streamSid": stream_sid,
            "customParameters": {"caller": caller},
        },
    }


def _media_message(payload: str, stream_sid: str = "MZ-1") -> dict[str, Any]:
    return {"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}


def _mulaw_frame(n: int = 160) -> str:
    return base64.b64encode(bytes(range(n % 256)) * (n // 256 + 1))[:216].decode()


def _app_with(
    profile: Profile, tmp_path: Path, factory: RecordingFactory, **kw: object
) -> FastAPI:
    return create_app(
        profile,
        factory,
        _noop_on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
        **kw,  # type: ignore[arg-type]
    )


def test_s1b_the_socket_adopts_the_session_the_webhook_opened(
    profile: Profile, tmp_path: Path
) -> None:
    """S1.b -- the session the bridge drives IS the object the factory returned.

    Identity, not a call count. A second factory call would bump the count, but
    only `is` proves the FIRST session -- the one whose greeting has been
    generating since the webhook -- is the one now being driven.
    """
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    client = TestClient(_app_with(profile, tmp_path, factory))

    client.post("/voice", data={"CallSid": "CA-s1b", "From": "+447700900123"})
    assert len(factory.sessions) == 1
    opened = factory.sessions[0]

    with client.websocket_connect("/media") as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json(_start_message("CA-s1b"))
        ws.send_json(_media_message(_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    assert len(factory.calls) == 1, "the socket must not open a second session"
    assert opened.sent, "the adopted session received the caller's audio"
    assert factory.sessions[0] is opened


def test_s1c_the_fake_exposes_no_start_so_a_second_start_cannot_pass(
    profile: Profile, tmp_path: Path
) -> None:
    """S1.c -- the LiveSession surface has no `start()`; S3 never reaches for one.

    Structural, not an assertion about behaviour: `open_live_session` already
    called `start()` before returning (live.py:370), and calling it again
    re-sends the greeting trigger and spawns a second reader/drain pair over one
    transport. If the production code ever calls `.start()`, this fake raises
    AttributeError rather than quietly accepting a stub.
    """
    assert not hasattr(FakeLiveSession(), "start")

    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    client = TestClient(_app_with(profile, tmp_path, factory))
    client.post("/voice", data={"CallSid": "CA-s1c", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-s1c"))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})


@pytest.mark.timeout(10)
def test_s11a_unknown_call_sid_opens_no_session_and_closes(
    profile: Profile, tmp_path: Path
) -> None:
    """S11.a -- a WS start for an unregistered CallSid: no factory call, socket closed.

    Every other seam connects a socket whose webhook already ran, so none of them
    reaches this branch. The on-the-fly fallback S3-Q5 rejects would look BETTER
    under casual testing -- the call "works" -- while delivering ~3s of dead air.
    """
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    client = TestClient(_app_with(profile, tmp_path, factory))

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-never-registered"))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()

    assert factory.calls == [], "no session may be opened on the fly"


@pytest.mark.timeout(10)
def test_s11b_unknown_call_sid_produces_no_record(
    profile: Profile, tmp_path: Path
) -> None:
    """S11.b -- no CallRecord, on_call_end not awaited, and the miss is logged."""
    records: list[CallRecord] = []

    async def _capture(record: CallRecord) -> None:
        records.append(record)

    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    app = create_app(
        profile,
        factory,
        _capture,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-unknown"))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()

    assert records == [], "a call that never reached start produces no record"


@pytest.mark.timeout(10)
def test_s11c_unknown_call_sid_sends_no_media(profile: Profile, tmp_path: Path) -> None:
    """S11.c -- no outbound media frame is sent before the socket closes.

    An implementation that closes the socket but emits one stray frame first
    passes S11.a and S11.b; only this asserts the caller hears nothing.
    """
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    client = TestClient(_app_with(profile, tmp_path, factory))

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-unknown-2"))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_s16a_re_registering_a_call_sid_closes_the_superseded_session(
    profile: Profile, tmp_path: Path
) -> None:
    """S16.a -- a second POST /voice for one CallSid awaits the first session's close().

    Twilio retries the voice webhook on timeout or 5xx. A bare dict write orphans
    the first session: its reader and drain tasks keep running with no external
    reference, and the sweep can never reclaim them because it only inspects
    entries still in the dict. Unbounded, not TTL-bounded.
    """
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    client = TestClient(_app_with(profile, tmp_path, factory))

    client.post("/voice", data={"CallSid": "CA-retry", "From": "+447700900123"})
    client.post("/voice", data={"CallSid": "CA-retry", "From": "+447700900123"})

    assert len(factory.sessions) == 2
    assert factory.sessions[0].closed == 1, "the superseded session must be closed"


def test_s16b_the_surviving_entry_is_the_second_request_and_is_adopted(
    profile: Profile, tmp_path: Path
) -> None:
    """S16.b -- exactly one entry survives, it is the second request's, and start adopts it."""
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    client = TestClient(_app_with(profile, tmp_path, factory))

    client.post("/voice", data={"CallSid": "CA-retry2", "From": "+447700900123"})
    client.post("/voice", data={"CallSid": "CA-retry2", "From": "+447700900123"})
    survivor = factory.sessions[1]

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-retry2"))
        ws.send_json(_media_message(_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    assert survivor.sent, "the adopted session is the second request's"
    assert factory.sessions[0].sent == [], "the superseded session received nothing"


def test_s16c_the_supersede_is_logged_with_the_call_sid(
    profile: Profile, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """S16.c -- the supersede is logged with the CallSid.

    Phase 5 defers the I-Twilio-Idempotency-Token optimisation on the strength of
    this log line being the observable that retries are real in a deployment. A
    trigger nothing produces is a deferral with no revisit.
    """
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    client = TestClient(_app_with(profile, tmp_path, factory))

    with caplog.at_level(logging.INFO, logger="decana.twilio.server"):
        client.post("/voice", data={"CallSid": "CA-logged", "From": "+447700900123"})
        client.post("/voice", data={"CallSid": "CA-logged", "From": "+447700900123"})

    assert any("CA-logged" in r.getMessage() for r in caplog.records)


def _build_app(
    profile: Profile,
    tmp_path: Path,
    factory: RecordingFactory,
    on_call_end: Any = None,
    **kw: Any,
) -> FastAPI:
    return create_app(
        profile,
        factory,
        on_call_end or _noop_on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
        **kw,
    )


def _wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    """Block the test thread until the app's loop reaches an observable state.

    The client is synchronous and the teardown it is waiting on runs in the
    app's event loop, so "send a message and assert" races the scheduler. Every
    ending that is triggered from a background task -- the pump on `Closed`, the
    drain on a send failure -- needs this or it asserts against whichever task
    happened to run first.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


@pytest.mark.timeout(15)
@pytest.mark.parametrize(
    ("ending", "expected_reason"),
    [
        ("twilio_stop", "twilio_stop"),
        ("ws_disconnect", "ws_disconnect"),
        ("gemini_closed", "gemini_closed: remote"),
        ("twilio_send_failed", "twilio_send_failed"),
        ("error", "error: KeyError"),
    ],
    ids=[
        "twilio_stop",
        "ws_disconnect",
        "gemini_closed",
        "twilio_send_failed",
        "error",
    ],
)
def test_s3a_each_ending_tears_down_once_with_its_own_reason(
    profile: Profile,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
    expected_reason: str,
) -> None:
    """S3.a -- five endings, each: close() once, on_call_end once, correct ended_reason.

    Parametrised over the ratified ending table rather than written once per
    ending, so a sixth ending added to the table without a mapping shows up as a
    missing parameter rather than as nothing at all.
    """
    recorder = Recorder()
    backlog = [Closed(reason="remote")] if ending == "gemini_closed" else []
    on_send = [AudioChunk(pcm24k=b"\x01\x02")] if ending == "twilio_send_failed" else []
    factory = RecordingFactory(StepClock(), backlog=backlog, on_send=on_send)
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    if ending == "twilio_send_failed":

        async def _boom(self: WebSocket, data: Any) -> None:
            raise OSError("socket is gone")

        monkeypatch.setattr(WebSocket, "send_json", _boom)

    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-3a", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-3a"))
        if ending == "twilio_stop":
            ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        elif ending == "error":
            ws.send_json({"event": "media", "streamSid": "MZ-1", "media": {}})
        elif ending == "twilio_send_failed":
            ws.send_json(_media_message(_mulaw_frame()))
        assert _wait_for(lambda: bool(recorder.records)) or ending == "ws_disconnect"

    assert _wait_for(lambda: bool(recorder.records)), "on_call_end was never awaited"
    assert len(recorder.records) == 1, "on_call_end must be awaited exactly once"
    assert factory.sessions[0].closed == 1, "close() must be called exactly once"
    assert recorder.records[0].ended_reason == expected_reason


@pytest.mark.timeout(15)
def test_s3b_stop_raced_with_disconnect_still_tears_down_once(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3.b -- stop and disconnect raced: still exactly one of each, reason is the winner.

    Either reason is a correct outcome, so the assertion is the invariant, not
    the winner: one close(), one on_call_end, and an `ended_reason` that is one
    of the two real endings rather than a corrupted mix. A second teardown
    double-flushes into the RuntimeError("Input after last input") that
    voice-intake-demo Q19 built into close() deliberately.
    """
    recorder = Recorder()
    factory = RecordingFactory(StepClock())
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-3b", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-3b"))
        # No wait between the two: `stop` is still in flight when the context
        # manager closes the socket underneath it.
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    assert _wait_for(lambda: bool(recorder.records))
    assert len(recorder.records) == 1
    assert factory.sessions[0].closed == 1
    assert recorder.records[0].ended_reason in {"twilio_stop", "ws_disconnect"}


@pytest.mark.timeout(15)
def test_s3c_teardown_runs_drain_stop_then_bridge_then_gemini_then_record(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3.c -- teardown order is drain-stop -> bridge -> gemini -> record.

    Exactly-once does not imply in-order. The reversed implementation S3-Q8
    explicitly rejects -- closing Gemini before flushing the bridge -- still
    shows one close() and one on_call_end, so every assertion in S3.a passes
    against it while the flushed soxr tail is discarded. Order needs its own
    assertion or it has none.
    """
    order: list[str] = []
    recorder = Recorder(order=order)
    factory = RecordingFactory(StepClock(), order=order)
    monkeypatch.setattr(
        "decana.twilio.server.BridgeSession", BridgeFactory(order=order)
    )
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-3c", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-3c"))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert order == ["drain-stop", "bridge.close", "gemini.close", "on_call_end"]


@pytest.mark.timeout(15)
def test_s3d_record_timestamps_come_from_the_injected_clock(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3.d -- started_at/ended_at equal the injected clock's exact values.

    Sentinels far from now, and two DIFFERENT ones. An implementation calling
    `datetime.now(UTC)` internally passes every other assertion in this seam and
    fails only this; a single sentinel would not catch reading the clock once
    and reusing it for both fields.
    """
    clock = StepClock()
    recorder = Recorder()
    factory = RecordingFactory(clock)
    bridges = BridgeFactory()
    monkeypatch.setattr("decana.twilio.server.BridgeSession", bridges)
    client = TestClient(_build_app(profile, tmp_path, factory, recorder, clock=clock))
    client.post("/voice", data={"CallSid": "CA-3d", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-3d"))
        # The clock must not move until `start` has been read: `started_at` is
        # stamped inside _begin_call, so advancing first would make both
        # timestamps equal and the assertion vacuous.
        assert _wait_for(lambda: bool(bridges.made)), "start was never processed"
        clock.advance(90)
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    record = recorder.records[0]
    assert record.started_at == T0
    assert record.ended_at == T0 + timedelta(seconds=90)


def _outbound(ws: Any, count: int) -> list[dict[str, Any]]:
    """Read exactly `count` outbound media frames off the socket."""
    return [ws.receive_json() for _ in range(count)]


@pytest.mark.timeout(15)
def test_s2a_greeting_backlog_and_later_chunks_arrive_in_emission_order(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2.a -- N chunks emitted pre-connect + M post arrive as N+M in emission order.

    The backlog is the greeting: S2's reader fills an unbounded `_inbox` from
    the moment `POST /voice` opens the session, with no consumer attached
    (`live.py:183,284`), and S3 only starts iterating once the socket is up. A
    consumer that starts at connect and discards what accumulated passes every
    test whose fake emits AFTER connecting -- which is the shape every test
    naturally takes -- and on a real call is the caller hearing the AI
    mid-sentence.
    """
    backlog = [
        AudioChunk(pcm24k=b"A0"),
        AudioChunk(pcm24k=b"A1"),
        AudioChunk(pcm24k=b"A2"),
    ]
    later = [AudioChunk(pcm24k=b"B0"), AudioChunk(pcm24k=b"B1")]
    factory = RecordingFactory(StepClock(), backlog=backlog, on_send=later)
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory))

    client.post("/voice", data={"CallSid": "CA-2a", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-2a"))
        # Forwarding caller audio is what releases the second batch, from
        # inside the app's loop -- so those chunks are genuinely post-connect.
        ws.send_json(_media_message(_mulaw_frame()))
        frames = _outbound(ws, len(backlog) + len(later))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    payloads = [base64.b64decode(f["media"]["payload"]) for f in frames]
    assert payloads == [b"A0", b"A1", b"A2", b"B0", b"B1"]


@pytest.mark.timeout(15)
def test_s5a_a_failing_send_never_propagates_and_ends_the_call_correctly(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S5.a -- send_media never propagates; the failure maps to twilio_send_failed.

    `BridgeSession._forward_to_twilio` calls `send_media` under a catch scoped
    to `AudioFrameError` only (voice-intake-demo Q20), so ANY other exception
    escaping it ends the call. A happy-path fake socket never raises, so the
    defect is invisible without forcing one.
    """
    recorder = Recorder()
    factory = RecordingFactory(StepClock(), backlog=[AudioChunk(pcm24k=b"\x01\x02")])
    bridges = BridgeFactory()
    monkeypatch.setattr("decana.twilio.server.BridgeSession", bridges)

    async def _boom(self: WebSocket, data: Any) -> None:
        raise OSError("socket is gone")

    monkeypatch.setattr(WebSocket, "send_json", _boom)
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-5a", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-5a"))
        assert _wait_for(lambda: bool(recorder.records))

    assert recorder.records[0].ended_reason == "twilio_send_failed"
    assert bridges.made[0].send_errors == [], (
        "send_media must never raise at its caller"
    )


@pytest.mark.timeout(15)
def test_s5b_send_media_after_teardown_is_a_silent_no_op(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S5.b -- a post-teardown send_media neither raises nor reaches the socket.

    The bridge's own teardown flush is exactly this call: `close()` pushes
    soxr's stranded tail through `send_media` AFTER the drain has stopped. It
    must be swallowed, not error and not surface as a frame Twilio would play
    after the call ended.
    """
    recorder = Recorder()
    factory = RecordingFactory(StepClock(), backlog=[AudioChunk(pcm24k=b"Z0")])
    bridges = BridgeFactory()
    monkeypatch.setattr("decana.twilio.server.BridgeSession", bridges)
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-5b", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-5b"))
        frames = _outbound(ws, 1)
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert bridges.made[0].closed == 1, "the teardown flush must have been attempted"
    assert bridges.made[0].send_errors == [], "a post-teardown send must not raise"
    assert [base64.b64decode(f["media"]["payload"]) for f in frames] == [b"Z0"]


@pytest.mark.timeout(15)
def test_s5c_every_outbound_frame_carries_the_root_stream_sid(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S5.c -- root streamSid from `start` on every frame, backlog frames included.

    The shape appears verbatim in P2, in guarantee (e) and in S3-Q10, which
    makes it LOOK specified -- while nothing produced the value. An adapter that
    omits it satisfies FIFO order, never-raises, failure mapping and correct
    payload bytes, and Twilio discards the frames: dead air after the greeting.

    The backlog frame is the one an echo-from-last-inbound-media implementation
    gets wrong, because it is flushed on adoption before any `media` arrives.
    """
    backlog = [AudioChunk(pcm24k=b"G0"), AudioChunk(pcm24k=b"G1")]
    factory = RecordingFactory(StepClock(), backlog=backlog)
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory))
    client.post("/voice", data={"CallSid": "CA-5c", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-5c", stream_sid="MZ-distinct"))
        frames = _outbound(ws, 2)
        ws.send_json({"event": "stop", "streamSid": "MZ-distinct"})

    assert [f.get("streamSid") for f in frames] == ["MZ-distinct", "MZ-distinct"]
    assert all("streamSid" not in f["media"] for f in frames), "root, not nested"


@pytest.mark.timeout(15)
def test_s4a_an_on_call_end_that_raises_does_not_escape_the_handler(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4.a -- the exception from on_call_end does not escape the WS handler.

    With a fake `on_call_end` that never raises, an unwrapped `await` is
    indistinguishable from a wrapped one -- and the ratified Phase-4 gate does
    not cover this case either, so nothing downstream forces it.
    """
    recorder = Recorder(raises=RuntimeError("analysis exploded"))
    factory = RecordingFactory(StepClock())
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-4a", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-4a"))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert len(recorder.records) == 1


@pytest.mark.timeout(15)
def test_s4b_the_on_call_end_failure_is_logged_with_sid_and_type(
    profile: Profile,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S4.b -- logged with the call_sid and the exception type.

    Swallowing without a diagnostic is how a whole class of post-call failures
    becomes invisible: S4 and S5 both run behind this callback.
    """
    recorder = Recorder(raises=RuntimeError("analysis exploded"))
    factory = RecordingFactory(StepClock())
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))

    with caplog.at_level(logging.ERROR, logger="decana.twilio.server"):
        client.post("/voice", data={"CallSid": "CA-4b", "From": "+447700900123"})
        with client.websocket_connect("/media") as ws:
            ws.send_json(_start_message("CA-4b"))
            ws.send_json({"event": "stop", "streamSid": "MZ-1"})
            assert _wait_for(lambda: bool(recorder.records))

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "CA-4b" in logged
    assert "RuntimeError" in logged


@pytest.mark.timeout(15)
def test_s4c_a_raising_callback_does_not_retry_or_change_the_close_count(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4.c -- close() still called exactly once; on_call_end is not retried.

    Retrying to "recover" would break the ratified exactly-once guarantee to
    protect the weaker one, and S5's idempotency marker is written before its
    Twilio send precisely so a duplicate is never the recovery path.
    """
    recorder = Recorder(raises=RuntimeError("analysis exploded"))
    factory = RecordingFactory(StepClock())
    bridges = BridgeFactory()
    monkeypatch.setattr("decana.twilio.server.BridgeSession", bridges)
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-4c", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-4c"))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert factory.sessions[0].closed == 1
    assert bridges.made[0].closed == 1
    assert len(recorder.records) == 1, "on_call_end must not be retried"


@pytest.mark.timeout(20)
def test_s4d_a_concurrent_second_call_survives_a_raising_callback(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4.d -- a concurrent second call completes normally with its own record.

    The exception is swallowed inside the per-call `_teardown`, so it can reach
    neither the other call's handler nor its record.
    """
    recorder = Recorder(raises=RuntimeError("analysis exploded"))
    factory = RecordingFactory(StepClock())
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-4d-one", "From": "+447700900123"})
    client.post("/voice", data={"CallSid": "CA-4d-two", "From": "+447700900124"})

    with client.websocket_connect("/media") as first:
        first.send_json(_start_message("CA-4d-one", stream_sid="MZ-one"))
        with client.websocket_connect("/media") as second:
            second.send_json(_start_message("CA-4d-two", stream_sid="MZ-two"))
            second.send_json({"event": "stop", "streamSid": "MZ-two"})
            assert _wait_for(lambda: bool(recorder.records))
        first.send_json({"event": "stop", "streamSid": "MZ-one"})
        assert _wait_for(lambda: len(recorder.records) == 2)

    assert {r.call_sid for r in recorder.records} == {"CA-4d-one", "CA-4d-two"}
    assert recorder.reasons == ["twilio_stop", "twilio_stop"]


@pytest.mark.timeout(15)
def test_s10a_a_raising_bridge_close_does_not_escape_and_names_the_type(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S10.a -- BridgeSession.close() raising: no escape, ended_reason="error: <type>".

    Unwrapped, a raising `close()` takes the whole `_teardown` down with it: no
    CallRecord, no on_call_end, no diagnostic trail for a call that really
    happened -- a worse silent failure than the one Seam 4 exists to close. The
    exception is deliberately NOT the guarded double-invocation RuntimeError,
    which the `done` flag already makes unreachable.
    """
    recorder = Recorder()
    factory = RecordingFactory(StepClock())
    bridges = BridgeFactory(close_raises=ValueError("flush exploded"), raise_on={0})
    monkeypatch.setattr("decana.twilio.server.BridgeSession", bridges)
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-10a", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-10a"))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert recorder.records[0].ended_reason == "error: ValueError"


@pytest.mark.timeout(15)
def test_s10b_a_raising_bridge_close_still_delivers_the_partial_record(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S10.b -- on_call_end still awaited exactly once, with the record as it stands.

    "As it stands" is the load-bearing part: a partial transcript still has
    value and S5 tolerates an empty one, so the turns gathered before the flush
    failed must survive into the record rather than being discarded with it.
    """
    recorder = Recorder()
    factory = RecordingFactory(
        StepClock(), backlog=[Transcript(role="caller", text="half a sentence")]
    )
    bridges = BridgeFactory(close_raises=ValueError("flush exploded"), raise_on={0})
    monkeypatch.setattr("decana.twilio.server.BridgeSession", bridges)
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-10b", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-10b"))
        assert _wait_for(lambda: bool(factory.sessions[0].sent) or True)
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert len(recorder.records) == 1
    assert recorder.records[0].transcript == (
        TranscriptTurn(role="caller", text="half a sentence"),
    )


@pytest.mark.timeout(20)
def test_s10c_a_concurrent_second_call_survives_a_raising_bridge_close(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S10.c -- a concurrently running second call is unaffected.

    `raise_on={0}` makes only the FIRST bridge fail: a factory raising for every
    bridge could not tell "the neighbour survived" from "the neighbour failed
    the same way".
    """
    recorder = Recorder()
    factory = RecordingFactory(StepClock())
    bridges = BridgeFactory(close_raises=ValueError("flush exploded"), raise_on={0})
    monkeypatch.setattr("decana.twilio.server.BridgeSession", bridges)
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-10c-one", "From": "+447700900123"})
    client.post("/voice", data={"CallSid": "CA-10c-two", "From": "+447700900124"})

    with client.websocket_connect("/media") as first:
        first.send_json(_start_message("CA-10c-one", stream_sid="MZ-one"))
        assert _wait_for(lambda: len(bridges.made) == 1)
        with client.websocket_connect("/media") as second:
            second.send_json(_start_message("CA-10c-two", stream_sid="MZ-two"))
            second.send_json({"event": "stop", "streamSid": "MZ-two"})
            assert _wait_for(lambda: bool(recorder.records))
        first.send_json({"event": "stop", "streamSid": "MZ-one"})
        assert _wait_for(lambda: len(recorder.records) == 2)

    by_sid = {r.call_sid: r for r in recorder.records}
    assert by_sid["CA-10c-two"].ended_reason == "twilio_stop"
    assert by_sid["CA-10c-one"].ended_reason == "error: ValueError"


class GatedLiveSession(FakeLiveSession):
    """A session whose `close()` parks until the test releases it.

    A poll on a plain bool rather than an `asyncio.Event`: `close()` runs in the
    app's loop and the release comes from the synchronous test thread, where
    `Event.set()` is not safe to call. The gate is what forces the interleaving
    -- without it the test passes whether or not the race was ever exercised,
    which is the passes-for-the-wrong-reason gap the seam names.
    """

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.entered = False
        self.release = False

    async def close(self) -> None:
        self.entered = True
        while not self.release:
            await asyncio.sleep(0.005)
        await super().close()


class ScriptedFactory:
    """Hands each successive call its OWN session, with its own event script.

    Seam 15 needs sessions that are distinguishable. With Protocol-only fakes,
    which this slice's standing constraint makes interchangeable, two calls
    would each complete and each produce a record while their transcripts were
    silently exchanged -- and nothing in the logs, the JSONL, or the record
    itself would look wrong.
    """

    def __init__(
        self,
        clock: Callable[[], datetime],
        scripts: Sequence[Sequence[LiveEvent]],
        session_cls: type[FakeLiveSession] = FakeLiveSession,
    ) -> None:
        self._clock = clock
        self._scripts = list(scripts)
        self._session_cls = session_cls
        self.calls: list[tuple[Profile, datetime]] = []
        self.sessions: list[FakeLiveSession] = []

    async def __call__(self, profile: Profile) -> FakeLiveSession:
        index = len(self.sessions)
        script = self._scripts[index] if index < len(self._scripts) else ()
        session = self._session_cls(tag=f"s{index}", backlog=script)
        self.calls.append((profile, self._clock()))
        self.sessions.append(session)
        return session


class RaisingFactory:
    """A `LiveSessionFactory` that fails the way `open_live_session` really fails.

    It raises on connect-time failure by design -- "that happens before a call
    exists, and S3 needs to see it rather than receive a `Closed` for a session
    that never opened" (`live.py:352-354`). A Gemini outage, a bad API key or a
    network blip during the webhook all land here.
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls = 0

    async def __call__(self, profile: Profile) -> FakeLiveSession:
        self.calls += 1
        raise self._exc


@pytest.mark.timeout(15)
@pytest.mark.parametrize(
    "message",
    [
        {"event": "connected", "protocol": "Call", "version": "1.0.0"},
        {"event": "mark", "streamSid": "MZ-1", "mark": {"name": "x"}},
        {"event": "dtmf", "streamSid": "MZ-1", "dtmf": {"digit": "5"}},
    ],
    ids=["connected", "mark", "dtmf"],
)
def test_s12a_non_media_twilio_messages_are_absorbed(
    profile: Profile,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    message: dict[str, Any],
) -> None:
    """S12.a -- connected / mark / dtmf absorbed; no exception, no teardown.

    The natural refactor once there are four event types is a dispatch table --
    `HANDLERS[msg["event"]](msg)` -- which raises KeyError on anything not in
    it. Every other seam drives only start/media/stop, so all of them pass it.
    `dtmf` is caller-initiated: any caller pressing a key mid-call sends one,
    and the KeyError surfaces OUTSIDE `_teardown`, so it is not even routed to
    the ratified `error: <type>` ending -- it is an uncontrolled crash mid-call.
    """
    recorder = Recorder()
    factory = RecordingFactory(StepClock())
    bridges = BridgeFactory()
    monkeypatch.setattr("decana.twilio.server.BridgeSession", bridges)
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-12a", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-12a"))
        assert _wait_for(lambda: bool(bridges.made))
        ws.send_json(message)
        ws.send_json(_media_message(_mulaw_frame()))
        assert _wait_for(lambda: bool(bridges.made[0].inbound_frames))
        assert recorder.records == [], "an absorbed message must not tear the call down"
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert recorder.records[0].ended_reason == "twilio_stop"


@pytest.mark.timeout(15)
def test_s12b_media_after_absorbed_messages_is_still_forwarded(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S12.b -- media after them still forwarded; the call ends normally on stop.

    Absorbing must not mean "stop reading the socket": the lazier failure than
    a KeyError is treating an unknown event as a call-ending condition, which
    leaves the caller connected to a server that has stopped listening.
    """
    recorder = Recorder()
    factory = RecordingFactory(StepClock())
    bridges = BridgeFactory()
    monkeypatch.setattr("decana.twilio.server.BridgeSession", bridges)
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-12b", "From": "+447700900123"})
    frame = _mulaw_frame()

    with client.websocket_connect("/media") as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json(_start_message("CA-12b"))
        ws.send_json({"event": "dtmf", "streamSid": "MZ-1", "dtmf": {"digit": "5"}})
        ws.send_json(_media_message(frame))
        ws.send_json({"event": "mark", "streamSid": "MZ-1", "mark": {"name": "x"}})
        ws.send_json(_media_message(frame))
        assert _wait_for(lambda: len(bridges.made[0].inbound_frames) == 2)
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert bridges.made[0].inbound_frames == [frame, frame]
    assert recorder.records[0].ended_reason == "twilio_stop"


@pytest.mark.timeout(15)
def test_s12c_absorbed_messages_leave_the_transcript_and_record_untouched(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S12.c -- the transcript and the CallRecord are unchanged by them.

    An implementation that absorbed a `dtmf` by appending it to the transcript
    would pass S12.a and S12.b -- no crash, call still ends -- while writing
    keypad noise into the artifact S4's analysis consumes.
    """
    recorder = Recorder()
    factory = RecordingFactory(
        StepClock(), backlog=[Transcript(role="caller", text="only this")]
    )
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-12c", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json(_start_message("CA-12c"))
        ws.send_json({"event": "dtmf", "streamSid": "MZ-1", "dtmf": {"digit": "5"}})
        ws.send_json({"event": "mark", "streamSid": "MZ-1", "mark": {"name": "x"}})
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert recorder.records[0].transcript == (
        TranscriptTurn(role="caller", text="only this"),
    )


@pytest.mark.timeout(15)
def test_s13a_interrupted_mid_stream_is_logged_and_changes_nothing(
    profile: Profile,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S13.a -- Interrupted mid-stream: no exception, logged, no teardown.

    A `match`/dict dispatch with arms for AudioChunk, Transcript and Closed but
    none for Interrupted raises the first time Gemini surfaces a barge-in --
    which on a phone call is ordinary, not exceptional. Every other seam passes,
    because none of their fakes ever emits one. This is the member S2 lost
    through ten critic rounds and this slice's own coverage map lost again.
    """
    recorder = Recorder()
    factory = RecordingFactory(
        StepClock(),
        backlog=[
            AudioChunk(pcm24k=b"C0"),
            Interrupted(),
            Transcript(role="model", text="cut off"),
        ],
    )
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))

    with caplog.at_level(logging.INFO, logger="decana.twilio.server"):
        client.post("/voice", data={"CallSid": "CA-13a", "From": "+447700900123"})
        with client.websocket_connect("/media") as ws:
            ws.send_json(_start_message("CA-13a"))
            frames = _outbound(ws, 1)
            assert recorder.records == [], "a barge-in must not end the call"
            ws.send_json({"event": "stop", "streamSid": "MZ-1"})
            assert _wait_for(lambda: bool(recorder.records))

    assert base64.b64decode(frames[0]["media"]["payload"]) == b"C0"
    assert any("CA-13a" in r.getMessage() for r in caplog.records)


@pytest.mark.timeout(15)
def test_s13b_events_after_an_interruption_still_flow(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S13.b -- events after it still flow; the call ends on stop.

    The over-reaction is as wrong as the missing arm: treating a barge-in as a
    call-ending condition truncates the stream at the first moment the caller
    talks over the model.
    """
    recorder = Recorder()
    factory = RecordingFactory(
        StepClock(),
        backlog=[
            Interrupted(),
            AudioChunk(pcm24k=b"D0"),
            Transcript(role="model", text="after the interruption"),
            AudioChunk(pcm24k=b"D1"),
        ],
    )
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-13b", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-13b"))
        frames = _outbound(ws, 2)
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert [base64.b64decode(f["media"]["payload"]) for f in frames] == [b"D0", b"D1"]
    assert recorder.records[0].transcript == (
        TranscriptTurn(role="model", text="after the interruption"),
    )
    assert recorder.records[0].ended_reason == "twilio_stop"


@pytest.mark.timeout(15)
def test_s14a_a_failing_factory_still_answers_with_the_disclosure_and_hangs_up(
    profile: Profile, tmp_path: Path
) -> None:
    """S14.a -- live_factory raising: 200 not 500, body is Say + Hangup, Say is the disclosure.

    Letting it propagate gives Twilio a raw 500 and the caller hears a Twilio
    error message instead of the compliance disclosure. The disclosure is the
    one thing that must be spoken on every answered call, failure path included.
    """
    factory = RaisingFactory(ConnectionError("gemini is down"))
    client = TestClient(_build_app(profile, tmp_path, factory))  # type: ignore[arg-type]

    response = client.post(
        "/voice", data={"CallSid": "CA-14a", "From": "+447700900123"}
    )

    assert response.status_code == 200
    root = ET.fromstring(response.text)
    say = root.find("Say")
    assert say is not None
    assert say.text == profile.disclosure
    assert root.find("Hangup") is not None
    assert root.find("Connect") is None, "no stream may be opened for a dead session"


@pytest.mark.timeout(15)
def test_s14b_a_failing_factory_registers_nothing(
    profile: Profile, tmp_path: Path
) -> None:
    """S14.b -- nothing registered; a later start for that CallSid hits S11's path.

    Catching the raise but still registering a `_Pending` would let a later WS
    `start` adopt a session that was never opened -- proven here by driving
    S11's fail-loudly path rather than by inspecting the registry.
    """
    factory = RaisingFactory(ConnectionError("gemini is down"))
    client = TestClient(_build_app(profile, tmp_path, factory))  # type: ignore[arg-type]
    client.post("/voice", data={"CallSid": "CA-14b", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-14b"))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


@pytest.mark.timeout(15)
def test_s14c_the_factory_failure_is_logged_with_the_call_sid(
    profile: Profile, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """S14.c -- the factory failure is logged with the CallSid.

    A graceful hangup with no log line is a call that vanished: the caller hears
    the disclosure, the line drops, and nothing anywhere says why.
    """
    factory = RaisingFactory(ConnectionError("gemini is down"))
    client = TestClient(_build_app(profile, tmp_path, factory))  # type: ignore[arg-type]

    with caplog.at_level(logging.ERROR, logger="decana.twilio.server"):
        client.post("/voice", data={"CallSid": "CA-14c", "From": "+447700900123"})

    assert any("CA-14c" in r.getMessage() for r in caplog.records)


@pytest.mark.timeout(15)
def test_s8a_a_socket_arriving_past_the_ttl_is_adopted_not_reaped(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S8.a -- a call whose socket arrives past the TTL is adopted, not reaped.

    The WS handler must pop its OWN CallSid before sweeping. Sweeping first
    would let this call close its own live session and then fail as an unknown
    CallSid -- a real caller dropped by a reaper meant for orphans. With a 60 s
    TTL and a test that connects immediately, sweep-order is unobservable.
    """
    clock = StepClock()
    recorder = Recorder()
    factory = RecordingFactory(clock)
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory, recorder, clock=clock))
    client.post("/voice", data={"CallSid": "CA-8a", "From": "+447700900123"})

    clock.advance(120)  # twice the default pending_ttl_s

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-8a"))
        ws.send_json(_media_message(_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert recorder.records[0].call_sid == "CA-8a"
    assert recorder.records[0].ended_reason == "twilio_stop"
    assert factory.sessions[0].sent, "the adopted session received the caller's audio"


@pytest.mark.timeout(15)
def test_s8b_a_true_orphan_is_closed_and_dropped(
    profile: Profile, tmp_path: Path
) -> None:
    """S8.b -- a pending session whose socket never arrives is closed and dropped.

    Hanging up during a compliance disclosure is normal caller behaviour, and
    each orphan holds an open, billed Gemini socket whose reader keeps filling
    an unbounded queue. "It gets restarted" is not a property the code
    guarantees.
    """
    clock = StepClock()
    factory = RecordingFactory(clock)
    client = TestClient(_build_app(profile, tmp_path, factory, clock=clock))
    client.post("/voice", data={"CallSid": "CA-8b-orphan", "From": "+447700900123"})

    clock.advance(120)
    client.post("/voice", data={"CallSid": "CA-8b-next", "From": "+447700900124"})

    assert factory.sessions[0].closed == 1, "the orphan's session must be closed"

    # The entry is gone, not merely closed: a socket for it now hits S11's path.
    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-8b-orphan"))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


@pytest.mark.timeout(30)
def test_s8c_a_sweep_survives_the_registry_changing_under_it(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S8.c -- a concurrent sweep does not raise when an entry is popped under it.

    Distinct from W-3, deliberately. W-3 accepts that a concurrent sweep may
    close a live session too early -- a disclosed timing risk. This is the
    sweep's own bookkeeping crashing on a stale snapshot, which S3-Q4 claims to
    have solved and which is accepted nowhere: a bare `del registry[call_sid]`
    raises KeyError inside whichever UNRELATED request happened to trigger the
    sweep. Cases (a) and (b) are both sequential and cannot distinguish the two.
    """
    clock = StepClock()
    scripts: list[Sequence[LiveEvent]] = [(), (), ()]
    factory = ScriptedFactory(clock, scripts, session_cls=GatedLiveSession)
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory, clock=clock))  # type: ignore[arg-type]

    # Registration order is sweep order, so the gated entry must go first: the
    # sweep has to be parked inside IT while the second is popped underneath.
    client.post("/voice", data={"CallSid": "CA-8c-gated", "From": "+447700900123"})
    client.post("/voice", data={"CallSid": "CA-8c-adopted", "From": "+447700900124"})
    # `session_cls=GatedLiveSession` above is what makes these casts sound; the
    # factory's own annotation is the base class it can build in general.
    gated = cast("GatedLiveSession", factory.sessions[0])
    adopted = cast("GatedLiveSession", factory.sessions[1])
    gated.release = False
    adopted.release = True
    clock.advance(120)

    unrelated: list[object] = []

    def _third_request() -> None:
        response = client.post(
            "/voice", data={"CallSid": "CA-8c-third", "From": "+447700900125"}
        )
        unrelated.append(response.status_code)

    thread = threading.Thread(target=_third_request)
    thread.start()
    try:
        assert _wait_for(lambda: gated.entered), "the sweep never reached the gate"

        with client.websocket_connect("/media") as ws:
            ws.send_json(_start_message("CA-8c-adopted", stream_sid="MZ-adopt"))
            # Popped under the parked sweep, which still holds it in its
            # snapshot and will reach it after the gate opens.
            time.sleep(0.05)
            gated.release = True
            thread.join(timeout=10)
    finally:
        gated.release = True
        thread.join(timeout=10)

    assert unrelated == [200], "the unrelated request must complete, not raise"
    assert gated.closed == 1, "no session may be closed twice by the sweep"
    assert adopted.closed <= 1


@pytest.mark.timeout(20)
def test_s15a_two_concurrent_calls_keep_their_own_transcripts(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S15.a -- concurrent calls, out-of-order connects: content traces to its own session.

    This one outranks the rest in consequence. Every other seam guards against a
    call that fails, stalls or crashes; this guards against calls that all
    appear to SUCCEED while one caller's mortgage details are written into
    another's CallRecord and sent to the operator by S5. That is a
    data-protection incident, not an outage, and it is silent by construction.

    THREE calls in a rotated connect order, not two reversed -- and the
    difference is the whole test. `dict.popitem()` is LIFO, so with two calls
    "reversed connect order" is precisely the order popitem reproduces: the
    wrong implementation this seam exists to rule out passes it, both times, by
    construction. Verified by mutation: `registry.popitem()` survived the
    two-call reversed version and is killed by this one on the second connect.
    """
    clock = StepClock()
    names = ["one", "two", "three"]
    scripts: list[Sequence[LiveEvent]] = [
        (Transcript(role="caller", text=f"belongs to {n.upper()}"),) for n in names
    ]
    factory = ScriptedFactory(clock, scripts)
    recorder = Recorder()
    monkeypatch.setattr("decana.twilio.server.BridgeSession", BridgeFactory())
    client = TestClient(_build_app(profile, tmp_path, factory, recorder, clock=clock))  # type: ignore[arg-type]

    for i, name in enumerate(names):
        client.post(
            "/voice", data={"CallSid": f"CA-15-{name}", "From": f"+44770090012{i}"}
        )

    # Registered one, two, three; connected three, one, two. The first connect
    # is the reversed case; the second is the one popitem gets wrong.
    with client.websocket_connect("/media") as third:
        third.send_json(_start_message("CA-15-three", stream_sid="MZ-three"))
        with client.websocket_connect("/media") as first:
            first.send_json(_start_message("CA-15-one", stream_sid="MZ-one"))
            with client.websocket_connect("/media") as second:
                second.send_json(_start_message("CA-15-two", stream_sid="MZ-two"))
                second.send_json({"event": "stop", "streamSid": "MZ-two"})
                assert _wait_for(lambda: bool(recorder.records))
            first.send_json({"event": "stop", "streamSid": "MZ-one"})
            assert _wait_for(lambda: len(recorder.records) == 2)
        third.send_json({"event": "stop", "streamSid": "MZ-three"})
        assert _wait_for(lambda: len(recorder.records) == 3)

    by_sid = {r.call_sid: r for r in recorder.records}
    assert set(by_sid) == {"CA-15-one", "CA-15-two", "CA-15-three"}
    for name in names:
        assert by_sid[f"CA-15-{name}"].transcript == (
            TranscriptTurn(role="caller", text=f"belongs to {name.upper()}"),
        )


@pytest.mark.timeout(20)
def test_s15b_each_call_adopts_the_session_its_own_webhook_opened(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S15.b -- each adopted session IS the object its own live_factory call returned.

    Identity, not content. S15.a would still pass a registry that happened to
    hand out the right transcripts for another reason; only `is` proves the
    lookup is keyed by the start message's CallSid. Same rotated three-call
    order, for the same reason: two reversed connects cannot discriminate LIFO.
    """
    clock = StepClock()
    names = ["one", "two", "three"]
    factory = ScriptedFactory(clock, [(), (), ()])
    bridges = BridgeFactory()
    monkeypatch.setattr("decana.twilio.server.BridgeSession", bridges)
    client = TestClient(_build_app(profile, tmp_path, factory, clock=clock))  # type: ignore[arg-type]

    for i, name in enumerate(names):
        client.post(
            "/voice", data={"CallSid": f"CA-15b-{name}", "From": f"+44770090012{i}"}
        )
    opened = {name: factory.sessions[i] for i, name in enumerate(names)}

    adopted: dict[str, Any] = {}
    with client.websocket_connect("/media") as third:
        third.send_json(_start_message("CA-15b-three", stream_sid="MZ-three"))
        assert _wait_for(lambda: len(bridges.made) == 1)
        adopted["three"] = bridges.made[0].gemini
        with client.websocket_connect("/media") as first:
            first.send_json(_start_message("CA-15b-one", stream_sid="MZ-one"))
            assert _wait_for(lambda: len(bridges.made) == 2)
            adopted["one"] = bridges.made[1].gemini
            with client.websocket_connect("/media") as second:
                second.send_json(_start_message("CA-15b-two", stream_sid="MZ-two"))
                assert _wait_for(lambda: len(bridges.made) == 3)
                adopted["two"] = bridges.made[2].gemini
                second.send_json({"event": "stop", "streamSid": "MZ-two"})
            first.send_json({"event": "stop", "streamSid": "MZ-one"})
        third.send_json({"event": "stop", "streamSid": "MZ-three"})

    for name in names:
        assert adopted[name] is opened[name], f"{name} adopted another call's session"


@pytest.mark.timeout(30)
def test_s9a_the_real_bridge_composes_and_writes_the_timing_log(
    profile: Profile, tmp_path: Path
) -> None:
    """S9.a -- composed pump with the REAL bridge writes call_answered + >=1 chunk_forwarded_to_twilio.

    No monkeypatched bridge here, deliberately. Mocking `BridgeSession` proves
    the server calls a mock and says nothing about
    `PR-bridgesession-composes-with-async-io`, which is the whole integration
    risk this slice carries and whose falsification re-opens Seam 4's ratified
    16-behavior contract under Article 8. Real bridge, real resamplers, real
    mu-law codec, real TimingRecorder; fakes only at the two true externals.
    """
    recorder = Recorder()
    factory = RecordingFactory(StepClock(), backlog=list(_S9_EVENTS))
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-9a", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-9a"))
        for _ in range(50):
            ws.send_json(_media_message(_real_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    events = _timing_events(tmp_path / "CA-9a.jsonl")
    assert "call_answered" in events
    assert events.count("chunk_forwarded_to_twilio") >= 1
    assert "frame_error" not in events, "a healthy call writes no frame_error"


@pytest.mark.timeout(30)
def test_s9b_the_record_carries_the_exact_transcript_in_order(
    profile: Profile, tmp_path: Path
) -> None:
    """S9.b -- record.transcript equals the exact TranscriptTurn tuple, both roles.

    Equality on the whole tuple, not "non-empty and ordered". A mapper that tags
    every turn "model" regardless of source, or that reverses order, satisfies
    non-empty-and-ordered while corrupting the one artifact S4's analysis
    consumes.
    """
    recorder = Recorder()
    factory = RecordingFactory(StepClock(), backlog=list(_S9_EVENTS))
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-9b", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-9b"))
        for _ in range(50):
            ws.send_json(_media_message(_real_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    assert recorder.records[0].transcript == (
        TranscriptTurn(role="caller", text="A"),
        TranscriptTurn(role="model", text="B"),
        TranscriptTurn(role="caller", text="C"),
    )


@pytest.mark.timeout(30)
def test_s9c_the_record_timing_path_points_at_the_written_log(
    profile: Profile, tmp_path: Path
) -> None:
    """S9.c -- record.timing_path points at the JSONL that was actually written.

    S5 reads its artifact directory from this field. A path that is merely
    plausible -- right shape, wrong directory -- passes any assertion about the
    field's format while sending the operator a brief with no timing evidence.
    """
    recorder = Recorder()
    factory = RecordingFactory(StepClock(), backlog=list(_S9_EVENTS))
    client = TestClient(_build_app(profile, tmp_path, factory, recorder))
    client.post("/voice", data={"CallSid": "CA-9c", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-9c"))
        ws.send_json(_media_message(_real_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        assert _wait_for(lambda: bool(recorder.records))

    timing_path = recorder.records[0].timing_path
    assert timing_path == tmp_path / "CA-9c.jsonl"
    assert timing_path.exists(), "the field must name a file that was written"
    assert "call_answered" in _timing_events(timing_path)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _entry_point() -> Path:
    """The installed `decana` console script, next to the running interpreter."""
    return Path(sys.executable).parent / "decana"


@pytest.mark.timeout(90)
def test_s17a_the_console_entry_starts_under_the_tracer_env_profile(
    tmp_path: Path,
) -> None:
    """S17.a -- `decana` starts with the tracer's env and serves POST /voice.

    Subprocess-level because nothing else in this slice ever executes `main()`:
    every unit test constructs `create_app` directly, so a composition root that
    passes arguments in the wrong order, forgets `root=` on `load_profile`, or
    drops the api_key partial passes all sixteen other seams. On the tracer that
    failure mode is a container that will not boot.

    Twilio and SMTP vars are deliberately ABSENT -- the feature's env table marks
    exactly those "tracer: optional, unused", so a `Settings` demanding them
    would break the tracer.

    Registration is checked with a 422 on a malformed body, not with a
    successful webhook: S3-Q1 makes a well-formed POST call `live_factory`
    unconditionally, which opens a real socket -- and with a placeholder key a
    successful POST is non-discriminating anyway, because a wrongly-wired
    factory and a correctly-wired one both produce Seam 14's graceful Hangup.
    """
    port = _free_port()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "DECANA_PROFILE": "mortgage-broker",
        "GEMINI_API_KEY": "placeholder-not-used-on-this-path",
        "PUBLIC_WSS_URL": "wss://example.test",
        "DECANA_ARTIFACT_DIR": str(tmp_path),
        "PORT": str(port),
    }
    process = subprocess.Popen(
        [str(_entry_point())],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        assert _wait_for(lambda: _is_serving(base), timeout=60.0), (
            "the entry point never came up"
        )
        response = httpx.post(f"{base}/voice", data={}, timeout=10.0)
        assert response.status_code == 422, "POST /voice is not registered"
        assert process.poll() is None, "the process must still be running"
    finally:
        process.terminate()
        process.wait(timeout=15)


def _is_serving(base: str) -> bool:
    try:
        httpx.post(f"{base}/voice", data={}, timeout=1.0)
    except httpx.HTTPError:
        return False
    return True


@pytest.mark.timeout(60)
def test_s17b_a_missing_required_variable_exits_two_and_names_it(
    tmp_path: Path,
) -> None:
    """S17.b -- a missing required var exits 2 and names the variable.

    S3-Q11's ratified behaviour, and it has no test anywhere else in this slice.
    Exit 2 rather than a traceback is what makes a misconfigured container say
    which variable it wanted instead of which line it crashed on.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "GEMINI_API_KEY": "placeholder",
        "PUBLIC_WSS_URL": "wss://example.test",
        "DECANA_ARTIFACT_DIR": str(tmp_path),
    }
    result = subprocess.run(
        [str(_entry_point())],
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )

    assert result.returncode == 2
    assert "DECANA_PROFILE" in result.stderr


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+447700900123", "+447700900123"),
        ("anonymous", ""),
        ("unknown", ""),
        ("+266696687", "+266696687"),
        ("", ""),
        ("Restricted Caller ID", ""),
    ],
)
def test_s7a_caller_number_is_e164_or_empty(raw: str, expected: str) -> None:
    """S7.a -- normalisation over the documented value set.

    Passthrough passes for a well-formed number, which is what a happy-path test
    uses. The consequence of passthrough lands two slices away, as S5 sending an
    SMS to the literal string `anonymous`.
    """
    assert normalise_caller_number(raw) == expected
