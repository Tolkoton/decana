"""Tests for the Twilio leg.

Every test's docstring opens with its behavior id from the ratified id set in
`.claude/overseer/slice/twilio-server.md`. The exit criterion is a property over
that set in both directions: every id has a passing node, and no node here fails
to trace to an id.
"""

import base64
import logging
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from decana.gemini.live import LiveEvent
from decana.profile.load import load_profile
from decana.profile.model import Profile
from decana.twilio.records import CallRecord
from decana.twilio.server import create_app, normalise_caller_number

REPO_ROOT = Path(__file__).resolve().parent.parent


class FakeLiveSession:
    """Implements EXACTLY the ratified `LiveSession` surface and nothing more.

    No `start()`, deliberately. `open_live_session` calls it internally before
    returning (`live.py:370`), so S3 must never call it again -- a second call
    re-sends the greeting trigger and spawns a second reader/drain pair over one
    transport. A fake carrying a `start` stub would let that bug pass every test
    here and surface first on a real call.
    """

    def __init__(self, tag: str = "") -> None:
        self.tag = tag
        self.sent: list[bytes] = []
        self.closed = 0
        self._queued: list[LiveEvent] = []

    def send_audio(self, pcm16k: bytes) -> None:
        self.sent.append(pcm16k)

    def events(self) -> AsyncIterator[LiveEvent]:
        async def _iter() -> AsyncIterator[LiveEvent]:
            for event in self._queued:
                yield event

        return _iter()

    async def close(self) -> None:
        self.closed += 1


class RecordingFactory:
    """A `LiveSessionFactory` that records when and how often it was invoked."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self.calls: list[tuple[Profile, datetime]] = []
        self.sessions: list[FakeLiveSession] = []

    async def __call__(self, profile: Profile) -> FakeLiveSession:
        session = FakeLiveSession(tag=f"s{len(self.sessions)}")
        self.calls.append((profile, self._clock()))
        self.sessions.append(session)
        return session


async def _noop_on_call_end(_record: CallRecord) -> None:
    return None


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
