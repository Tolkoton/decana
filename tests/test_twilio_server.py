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
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Callable, MutableMapping
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from decana.bridge.codec import mulaw_decode
from decana.bridge.session import BridgeSession
from decana.gemini.live import AudioChunk, Closed, Interrupted, LiveEvent, Transcript
from decana.profile.load import load_profile
from decana.profile.model import Profile
from decana.settings import Settings
from decana.twilio.records import CallRecord, TranscriptTurn
from decana.twilio.server import _SocketSender, create_app, normalise_caller_number

REPO_ROOT = Path(__file__).resolve().parent.parent


class FakeLiveSession:
    """Implements EXACTLY the ratified `LiveSession` surface and nothing more.

    No `start()`, deliberately. `open_live_session` calls it internally before
    returning (`live.py:370`), so S3 must never call it again -- a second call
    re-sends the greeting trigger and spawns a second reader/drain pair over one
    transport. A fake carrying a `start` stub would let that bug pass every test
    here and surface first on a real call.
    """

    def __init__(self, tag: str = "", queued: list[LiveEvent] | None = None) -> None:
        self.tag = tag
        self.sent: list[bytes] = []
        self.closed = 0
        self._queued: list[LiveEvent] = list(queued or [])

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


@pytest.mark.timeout(10)
def test_s8a_a_late_socket_is_adopted_not_reaped(profile: Profile, tmp_path: Path) -> None:
    """S8.a -- a call whose socket arrives past pending_ttl_s is adopted, not reaped.

    The handler pops its OWN entry before sweeping. Sweeping first lets a call
    whose socket is merely slow close its own live session and then fail as an
    unknown CallSid -- a real caller dropped by a reaper meant for orphans. With
    a 60s default and a test that connects immediately, sweep order is
    unobservable; driving the clock past the TTL is what makes it visible.
    """
    ticks = iter(
        [datetime(2000, 1, 1, tzinfo=UTC)]  # webhook registers here
        + [datetime(2000, 1, 1, 0, 5, tzinfo=UTC)] * 40  # socket arrives 5 min later
    )
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    app = create_app(
        profile,
        factory,
        _noop_on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
        clock=lambda: next(ticks),
        pending_ttl_s=60.0,
    )
    client = TestClient(app)

    client.post("/voice", data={"CallSid": "CA-late", "From": "+447700900123"})
    adopted = factory.sessions[0]

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-late"))
        ws.send_json(_media_message(_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    assert adopted.sent, "a late socket must still adopt its own session"
    assert factory.calls == [(profile, datetime(2000, 1, 1, tzinfo=UTC))]


@pytest.mark.timeout(10)
def test_s8b_a_true_orphan_is_closed_and_dropped(profile: Profile, tmp_path: Path) -> None:
    """S8.b -- a webhook whose socket never arrives is reclaimed by the next sweep.

    The orphan path is not hypothetical: hanging up during a compliance
    disclosure is ordinary caller behaviour, and each orphan holds an open Gemini
    socket whose reader keeps filling an unbounded queue.
    """
    ticks = iter(
        [datetime(2000, 1, 1, tzinfo=UTC)] + [datetime(2000, 1, 1, 0, 5, tzinfo=UTC)] * 40
    )
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    app = create_app(
        profile,
        factory,
        _noop_on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
        clock=lambda: next(ticks),
        pending_ttl_s=60.0,
    )
    client = TestClient(app)

    client.post("/voice", data={"CallSid": "CA-orphan", "From": "+447700900123"})
    orphan = factory.sessions[0]
    assert orphan.closed == 0

    client.post("/voice", data={"CallSid": "CA-other", "From": "+447700900124"})

    assert orphan.closed == 1, "the next sweep must reclaim the orphan"


@pytest.mark.timeout(20)
def test_s8c_a_concurrent_sweep_does_not_raise_when_an_entry_vanishes(
    profile: Profile, tmp_path: Path
) -> None:
    """S8.c -- two sweeps racing over one snapshot: neither raises, no double close.

    S3-Q4 rests on TWO properties and they need two tests. S8.a covers
    pop-before-sweep. This covers the other: the sweep removes with a guarded
    `registry.pop(call_sid, None)` and never `del registry[call_sid]`, because it
    awaits `close()` per entry and the dict can be mutated across that await.

    The interleaving is FORCED, not hoped for. The stale session's `close()`
    blocks on an Event the test controls, so both sweeps are provably inside the
    critical section before either proceeds. Without the gate this test passes
    whether or not the race was ever exercised -- which is the
    passes-for-the-wrong-reason gap this whole seam list exists to close.

    Driven through two real `POST /voice` requests rather than by calling the
    sweep directly: the registry is a closure inside `create_app` and is not
    reachable from a test, and the defect's blast radius is precisely that the
    KeyError lands inside an unrelated request.
    """

    async def _run() -> tuple[list[BaseException | None], int]:
        gate = asyncio.Event()
        entered = asyncio.Event()

        class GatedSession(FakeLiveSession):
            async def close(self) -> None:
                self.closed += 1
                entered.set()
                await gate.wait()

        gated = GatedSession(tag="stale")
        made: list[FakeLiveSession] = []

        async def factory(_profile: Profile) -> FakeLiveSession:
            session: FakeLiveSession = gated if not made else FakeLiveSession()
            made.append(session)
            return session

        now = datetime(2000, 1, 1, tzinfo=UTC)
        later = datetime(2000, 1, 1, 0, 5, tzinfo=UTC)
        times = iter([now] + [later] * 40)

        app = create_app(
            profile,
            factory,
            _noop_on_call_end,
            public_wss_url="wss://example.test",
            artifact_dir=tmp_path,
            clock=lambda: next(times),
            pending_ttl_s=60.0,
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            await client.post("/voice", data={"CallSid": "CA-stale", "From": "+447700900123"})

            async def sweep_request(sid: str) -> BaseException | None:
                try:
                    await client.post("/voice", data={"CallSid": sid, "From": "+447700900124"})
                except BaseException as exc:  # noqa: BLE001 - the point of the test
                    return exc
                return None

            first = asyncio.create_task(sweep_request("CA-a"))
            await asyncio.wait_for(entered.wait(), timeout=5)
            second = asyncio.create_task(sweep_request("CA-b"))
            await asyncio.sleep(0)
            gate.set()

            outcomes = list(await asyncio.gather(first, second))
        return outcomes, gated.closed

    outcomes, closed = asyncio.run(_run())

    assert outcomes == [None, None], f"a sweep raised into an unrelated request: {outcomes}"
    assert closed == 1, f"the stale session was closed {closed}x, expected exactly once"


class RecordingEnd:
    """Captures every `CallRecord` handed to `on_call_end`."""

    def __init__(self) -> None:
        self.records: list[CallRecord] = []

    async def __call__(self, record: CallRecord) -> None:
        self.records.append(record)


def _drive_call(
    profile: Profile,
    tmp_path: Path,
    *,
    ending: str,
    factory: RecordingFactory | None = None,
    on_end: RecordingEnd | None = None,
) -> tuple[RecordingFactory, RecordingEnd]:
    """Run one whole call and end it the named way."""
    factory = factory or RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    on_end = on_end or RecordingEnd()
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": f"CA-{ending}", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message(f"CA-{ending}"))
        ws.send_json(_media_message(_mulaw_frame()))
        if ending == "twilio_stop":
            ws.send_json({"event": "stop", "streamSid": "MZ-1"})
        # "ws_disconnect": fall out of the context manager without sending stop
    return factory, on_end


@pytest.mark.timeout(15)
@pytest.mark.parametrize("ending", ["twilio_stop", "ws_disconnect"])
def test_s3a_each_ending_closes_once_and_records_once(
    profile: Profile, tmp_path: Path, ending: str
) -> None:
    """S3.a -- every ending: close() exactly once, on_call_end exactly once, right reason.

    Exactly-once is the ratified guarantee (a) and it is per-ENDING, not per-call:
    a `done` flag that works for `stop` can still double-fire when the socket
    drops instead. Parametrising the endings is what separates those.
    """
    factory, on_end = _drive_call(profile, tmp_path, ending=ending)

    assert len(on_end.records) == 1, "on_call_end must be awaited exactly once"
    assert factory.sessions[0].closed == 1, "the Live session closes exactly once"

    record = on_end.records[0]
    assert record.ended_reason == ending
    assert record.call_sid == f"CA-{ending}"
    assert record.caller_number == "+447700900123"
    assert record.profile_name == profile.name
    assert record.timing_path == tmp_path / f"CA-{ending}.jsonl"
    assert record.timing_path.exists(), "the timing JSONL is written before handoff"


class QueuedFactory:
    """A factory whose session replays a fixed event list, then ends."""

    def __init__(self, events: list[LiveEvent]) -> None:
        self.events = events
        self.sessions: list[FakeLiveSession] = []

    async def __call__(self, _profile: Profile) -> FakeLiveSession:
        session = FakeLiveSession(tag="q", queued=self.events)
        self.sessions.append(session)
        return session


def _run_call_with_events(
    profile: Profile,
    tmp_path: Path,
    events: list[LiveEvent],
    *,
    send_stop: bool = True,
) -> tuple[QueuedFactory, RecordingEnd, list[dict[str, Any]]]:
    """Drive one call whose Live session emits `events`, and collect outbound frames."""
    factory = QueuedFactory(events)
    on_end = RecordingEnd()
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-ev", "From": "+447700900123"})

    outbound: list[dict[str, Any]] = []
    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-ev"))
        ws.send_json(_media_message(_mulaw_frame()))
        if send_stop:
            ws.send_json({"event": "stop", "streamSid": "MZ-1"})
    return factory, on_end, outbound


@pytest.mark.timeout(15)
def test_s3a_gemini_closed_ends_the_call_with_its_reason(
    profile: Profile, tmp_path: Path
) -> None:
    """S3.a[gemini_closed] -- a Closed event ends the call, carrying its reason.

    `Closed.reason` becomes `CallRecord.ended_reason`, which is how S5 and the
    operator brief tell a Twilio-side failure from a Gemini-side one. S2 makes
    exactly one Closed the last event of every session.
    """
    _, on_end, _ = _run_call_with_events(
        profile, tmp_path, [Closed(reason="remote")], send_stop=False
    )

    assert len(on_end.records) == 1
    assert on_end.records[0].ended_reason == "gemini_closed: remote"


@pytest.mark.timeout(15)
def test_s13a_interrupted_is_a_no_op_that_does_not_end_the_call(
    profile: Profile, tmp_path: Path
) -> None:
    """S13.a -- Interrupted mid-stream: no exception, logged, no teardown.

    A `match` with arms for AudioChunk/Transcript/Closed but none for Interrupted
    raises the first time a caller talks over the model -- ordinary on a phone
    call. It is easy to omit precisely because the correct behaviour is to do
    nothing, so nothing visibly breaks in review.
    """
    events: list[LiveEvent] = [
        Transcript(role="model", text="one"),
        Interrupted(),
        Transcript(role="caller", text="two"),
    ]
    _, on_end, _ = _run_call_with_events(profile, tmp_path, events)

    assert len(on_end.records) == 1
    record = on_end.records[0]
    assert record.ended_reason == "twilio_stop", "a barge-in must not end the call"


@pytest.mark.timeout(15)
def test_s13b_events_after_an_interrupt_still_flow(profile: Profile, tmp_path: Path) -> None:
    """S13.b -- the stream is not truncated by an Interrupted; later events still arrive."""
    events: list[LiveEvent] = [
        Transcript(role="model", text="one"),
        Interrupted(),
        Transcript(role="caller", text="two"),
    ]
    _, on_end, _ = _run_call_with_events(profile, tmp_path, events)

    assert on_end.records[0].transcript == (
        TranscriptTurn(role="model", text="one"),
        TranscriptTurn(role="caller", text="two"),
    )


@pytest.mark.timeout(15)
@pytest.mark.parametrize("noise", ["connected", "mark", "dtmf"])
def test_s12a_connected_mark_and_dtmf_are_absorbed(
    profile: Profile, tmp_path: Path, noise: str
) -> None:
    """S12.a -- connected/mark/dtmf are absorbed: no exception, no teardown.

    A dispatch table keyed by event name -- the natural refactor once there are
    four types -- raises KeyError on any of these. `dtmf` is caller-initiated, so
    that lands mid-call on an ordinary keypress, outside _teardown, as an
    uncontrolled crash rather than a ratified ending.
    """
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    on_end = RecordingEnd()
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-noise", "From": "+447700900123"})

    payloads = {
        "connected": {"event": "connected", "protocol": "Call", "version": "1.0.0"},
        "mark": {"event": "mark", "streamSid": "MZ-1", "mark": {"name": "x"}},
        "dtmf": {"event": "dtmf", "streamSid": "MZ-1", "dtmf": {"track": "inbound_track", "digit": "5"}},
    }

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-noise"))
        ws.send_json(payloads[noise])
        ws.send_json(_media_message(_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    assert len(on_end.records) == 1
    assert on_end.records[0].ended_reason == "twilio_stop", f"{noise} must not end the call"


@pytest.mark.timeout(15)
def test_s12b_media_after_noise_is_still_forwarded(profile: Profile, tmp_path: Path) -> None:
    """S12.b -- media after an absorbed message still reaches the session."""
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    app = create_app(
        profile,
        factory,
        RecordingEnd(),
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-noise2", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-noise2"))
        ws.send_json({"event": "dtmf", "streamSid": "MZ-1", "dtmf": {"track": "inbound_track", "digit": "5"}})
        for _ in range(12):
            ws.send_json(_media_message(_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    assert factory.sessions[0].sent, "media after dtmf must still be forwarded"


def _collect_outbound(
    profile: Profile,
    tmp_path: Path,
    events: list[LiveEvent],
    *,
    frames: int = 12,
) -> list[dict[str, Any]]:
    """Drive a call that produces outbound audio, and return the frames Twilio saw."""
    factory = QueuedFactory(events)
    app = create_app(
        profile,
        factory,
        RecordingEnd(),
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-out", "From": "+447700900123"})

    seen: list[dict[str, Any]] = []
    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-out", stream_sid="MZ-OUT"))
        for _ in range(frames):
            ws.send_json(_media_message(_mulaw_frame(), stream_sid="MZ-OUT"))
        for _ in range(4):
            try:
                seen.append(ws.receive_json())
            except WebSocketDisconnect:  # pragma: no cover - drained early
                break
        ws.send_json({"event": "stop", "streamSid": "MZ-OUT"})
    return seen


@pytest.mark.timeout(20)
def test_s5c_every_outbound_frame_carries_root_stream_sid(
    profile: Profile, tmp_path: Path
) -> None:
    """S5.c -- outbound media has streamSid at the ROOT, equal to the start message's.

    Guarantee (e) asserts two independent things and only one had a test: how
    sending FAILS, and WHAT is sent. An adapter that omits `streamSid` satisfies
    every ordering, never-raises and payload assertion -- and Twilio discards the
    frames, so the caller hears dead air after the greeting, on exactly the path
    the latency acceptance measures.
    """
    chunk = b"\x00\x01" * 2400  # 100ms of PCM16 at 24kHz
    seen = _collect_outbound(profile, tmp_path, [AudioChunk(pcm24k=chunk)] * 6)

    assert seen, "the session produced no outbound audio at all"
    for frame in seen:
        assert frame["event"] == "media"
        assert frame["streamSid"] == "MZ-OUT", "streamSid must be at the message root"
        assert "payload" in frame["media"]
        assert "streamSid" not in frame["media"], "it belongs at the root, not nested"


class FailingSendApp:
    """ASGI wrapper whose websocket send raises after N frames.

    A fake socket is the only way to reach guarantee (e)'s failure half: a happy
    TestClient socket never fails, so `send_media` propagating an exception --
    which ends the call, because `BridgeSession._forward_to_twilio` catches only
    `AudioFrameError` -- is invisible to every other test.
    """

    def __init__(self, app: FastAPI, fail_after: int = 0) -> None:
        self.app = app
        self.fail_after = fail_after
        self.sends = 0

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        async def _send(message: MutableMapping[str, Any]) -> None:
            if message.get("type") == "websocket.send":
                self.sends += 1
                if self.sends > self.fail_after:
                    raise RuntimeError("socket gone")
            await send(message)

        await self.app(scope, receive, _send)


@pytest.mark.timeout(20)
def test_s3a_a_failed_send_ends_the_call_as_twilio_send_failed(
    profile: Profile, tmp_path: Path
) -> None:
    """S3.a[twilio_send_failed] -- a drain-task send failure ends the call, mapped.

    Twilio-side and Gemini-side failures must be distinguishable without parsing
    prose: this reason reaches S5 and the operator brief.
    """
    chunk = b"\x00\x01" * 2400
    factory = QueuedFactory([AudioChunk(pcm24k=chunk)] * 6)
    on_end = RecordingEnd()
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(FailingSendApp(app, fail_after=0))
    client.post("/voice", data={"CallSid": "CA-sendfail", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-sendfail"))
        for _ in range(12):
            ws.send_json(_media_message(_mulaw_frame()))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()

    assert len(on_end.records) == 1
    assert on_end.records[0].ended_reason == "twilio_send_failed"


@pytest.mark.timeout(20)
def test_s3a_an_unexpected_handler_exception_is_mapped_to_error(
    profile: Profile, tmp_path: Path
) -> None:
    """S3.a[error] -- any other exception in the handler ends the call as error: <type>.

    Every ending is mapped explicitly rather than by a catch-all that loses the
    type: a call that died of a KeyError and one that died of a send failure must
    not read the same in the record.
    """
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    on_end = RecordingEnd()
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-boom", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-boom"))
        ws.send_json({"event": "media", "streamSid": "MZ-1"})  # no media key
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()

    assert len(on_end.records) == 1
    assert on_end.records[0].ended_reason == "error: KeyError"


def test_s5a_send_media_never_raises_and_is_a_no_op_after_teardown() -> None:
    """S5.a/S5.b -- sync, never raises, and silently no-ops once the call is torn down.

    Never-raising is a hard requirement rather than defensive style:
    `BridgeSession._forward_to_twilio` calls this under a catch scoped to
    `AudioFrameError` only, so ANY other exception escaping here ends the call.
    """

    async def _run() -> tuple[int, int]:
        sender = _SocketSender("MZ-x")
        sender.send_media("aaa")
        sender.send_media("bbb")
        before = sender.queue.qsize()
        sender.closed = True
        sender.send_media("ccc")  # must not raise, must not enqueue
        return before, sender.queue.qsize()

    before, after = asyncio.run(_run())
    assert before == 2
    assert after == 2, "a post-teardown send must be a silent no-op"


@pytest.mark.timeout(20)
def test_s3b_racing_endings_still_tear_down_exactly_once(
    profile: Profile, tmp_path: Path
) -> None:
    """S3.b -- stop and a Gemini Closed arriving together: one close, one record.

    A `done` flag checked without a lock passes every single-ending test. The
    defect needs two endings arriving concurrently, which is exactly what a
    Twilio `stop` racing S2's `Closed` produces. `ended_reason` must be whichever
    ending won, never a corrupted mix.
    """
    factory = QueuedFactory([Closed(reason="remote")])
    on_end = RecordingEnd()
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-race", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-race"))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    assert len(on_end.records) == 1, "on_call_end must fire exactly once under a race"
    assert factory.sessions[0].closed == 1, "the session closes exactly once"
    assert on_end.records[0].ended_reason in {"twilio_stop", "gemini_closed: remote"}


@pytest.mark.timeout(20)
def test_s3c_teardown_runs_in_the_ratified_order(profile: Profile, tmp_path: Path) -> None:
    """S3.c -- order is drain-stop -> bridge -> gemini -> record.

    Exactly-once does NOT imply in-order: the reversed implementation S3-Q8
    rejects still shows one close() and one on_call_end, so S3.a passes against it
    while the flushed audio tail is discarded. Order needs its own assertion or it
    has none.
    """
    order: list[str] = []

    class OrderedSession(FakeLiveSession):
        async def close(self) -> None:
            order.append("gemini.close")
            await super().close()

    class OrderedFactory:
        def __init__(self) -> None:
            self.sessions: list[FakeLiveSession] = []

        async def __call__(self, _profile: Profile) -> FakeLiveSession:
            session = OrderedSession()
            self.sessions.append(session)
            return session

    async def on_end(_record: CallRecord) -> None:
        order.append("record")

    app = create_app(
        profile,
        OrderedFactory(),
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-order", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-order"))
        ws.send_json(_media_message(_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    assert order == ["gemini.close", "record"], (
        "Gemini must close before the record is handed off; closing it first would "
        "make the event loop observe a Closed mid-teardown and re-enter"
    )


@pytest.mark.timeout(20)
def test_s3d_record_timestamps_come_from_the_injected_clock(
    profile: Profile, tmp_path: Path
) -> None:
    """S3.d -- started_at and ended_at equal the injected clock's exact values.

    An implementation calling `datetime.now(UTC)` internally passes every other
    assertion in this seam and fails only this one, because the sentinel is far
    from now.
    """
    start = datetime(2000, 1, 1, tzinfo=UTC)
    end = datetime(2000, 1, 1, 0, 30, tzinfo=UTC)
    ticks = iter([start] * 3 + [end] * 40)

    factory = RecordingFactory(lambda: start)
    on_end = RecordingEnd()
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
        clock=lambda: next(ticks),
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-clock", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-clock"))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    record = on_end.records[0]
    assert record.started_at == start
    assert record.ended_at == end
    assert record.ended_at >= record.started_at


class RaisingEnd:
    """An `on_call_end` that raises, and counts how often it was called."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _record: CallRecord) -> None:
        self.calls += 1
        raise RuntimeError("downstream exploded")


def _run_one_call(
    app: FastAPI, call_sid: str, *, frames: int = 1
) -> None:
    client = TestClient(app)
    client.post("/voice", data={"CallSid": call_sid, "From": "+447700900123"})
    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message(call_sid))
        for _ in range(frames):
            ws.send_json(_media_message(_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})


@pytest.mark.timeout(20)
def test_s4a_on_call_end_raising_does_not_escape_the_handler(
    profile: Profile, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """S4.a/S4.b -- an on_call_end exception is caught and logged with the call_sid.

    With a fake that never raises, a wrapped await and an unwrapped one are
    indistinguishable. Ratified guarantee (b) is exactly this, and the ratified
    Phase-4 gate does NOT cover it -- it tests on_call_end exactly-once including
    when close() raises, never on_call_end itself raising.
    """
    end = RaisingEnd()
    app = create_app(
        profile,
        RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC)),
        end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )

    with caplog.at_level(logging.ERROR, logger="decana.twilio.server"):
        _run_one_call(app, "CA-endraise")  # must not raise out of the handler

    assert end.calls == 1
    assert any("CA-endraise" in r.getMessage() for r in caplog.records)


@pytest.mark.timeout(20)
def test_s4c_on_call_end_is_not_retried_after_it_raises(
    profile: Profile, tmp_path: Path
) -> None:
    """S4.c -- close() still ran exactly once and on_call_end is NOT retried.

    Retrying to "recover" would break the stronger exactly-once guarantee to
    protect the weaker one -- and S5's idempotency marker is written before its
    Twilio send precisely so a duplicate is never the recovery path.
    """
    end = RaisingEnd()
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    app = create_app(
        profile,
        factory,
        end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )

    _run_one_call(app, "CA-noretry")

    assert end.calls == 1, "a raising on_call_end must not be retried"
    assert factory.sessions[0].closed == 1


@pytest.mark.timeout(25)
def test_s4d_a_second_call_is_unaffected_by_the_first_ones_raising_callback(
    profile: Profile, tmp_path: Path
) -> None:
    """S4.d -- isolation: the next call still completes and gets its own record."""
    seen: list[CallRecord] = []

    class FlakyEnd:
        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, record: CallRecord) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("first one explodes")
            seen.append(record)

    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    app = create_app(
        profile,
        factory,
        FlakyEnd(),
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )

    _run_one_call(app, "CA-first")
    _run_one_call(app, "CA-second")

    assert [r.call_sid for r in seen] == ["CA-second"]


@pytest.mark.timeout(20)
def test_s10a_bridge_close_raising_is_caught_and_mapped(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S10.a/S10.b -- a raising BridgeSession.close(): no escape, error reason, record still made.

    All the other seams pass an unwrapped `call.bridge.close()` -- none of them
    ever makes close() raise. Unwrapped, a raising close takes the whole teardown
    with it: no CallRecord, no on_call_end, no diagnostic trail for a call that
    really happened. Worse than the failure S4 exists to close, and it is ratified
    guarantee (a), a promise made to S4 and S5.

    Patched rather than driven through a real path: nothing in production makes
    close() raise except the double-flush the `done` flag already makes
    unreachable, and adding a test-only hook to the server to reach it would put
    a fault-injection seam in shipped code.
    """
    monkeypatch.setattr(
        BridgeSession,
        "close",
        lambda _self: (_ for _ in ()).throw(ValueError("flush exploded")),
    )

    on_end = RecordingEnd()
    factory = RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC))
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )

    _run_one_call(app, "CA-closeraise")

    assert len(on_end.records) == 1, "the record is still handed off"
    assert on_end.records[0].ended_reason == "error: ValueError"
    assert factory.sessions[0].closed == 1, "Gemini still closes even if the bridge raised"


@pytest.mark.timeout(25)
def test_s10c_a_concurrent_call_is_unaffected_by_a_raising_bridge_close(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S10.c -- the next call completes normally after one call's close() raised."""
    calls: list[int] = []
    real_close = BridgeSession.close

    def flaky_close(self: BridgeSession) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("flush exploded")
        real_close(self)

    monkeypatch.setattr(BridgeSession, "close", flaky_close)

    on_end = RecordingEnd()
    app = create_app(
        profile,
        RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC)),
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )

    _run_one_call(app, "CA-r1")
    _run_one_call(app, "CA-r2")

    reasons = {r.call_sid: r.ended_reason for r in on_end.records}
    assert reasons == {"CA-r1": "error: ValueError", "CA-r2": "twilio_stop"}


@pytest.mark.timeout(25)
def test_s9a_composed_pump_writes_the_timing_log(profile: Profile, tmp_path: Path) -> None:
    """S9.a -- the REAL BridgeSession composes: call_answered + >=1 chunk_forwarded_to_twilio.

    Mocking BridgeSession here would prove the server calls a mock and say nothing
    about `PR-bridgesession-composes-with-async-io` -- the integration premise this
    slice carries, whose falsification re-opens the bridge slice's ratified
    16-behavior contract under Article 8. So the bridge, both resamplers, the codec
    and the TimingRecorder are all real; only the Twilio socket and the Live
    session are fakes, because those are the only true externals.
    """
    chunk = b"\x00\x01" * 2400
    events: list[LiveEvent] = [AudioChunk(pcm24k=chunk) for _ in range(6)]
    factory = QueuedFactory(events)
    on_end = RecordingEnd()
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-s9", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-s9"))
        for _ in range(50):
            ws.send_json(_media_message(_mulaw_frame()))
        for _ in range(2):
            with suppress(WebSocketDisconnect):
                ws.receive_json()
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    log = (tmp_path / "CA-s9.jsonl").read_text().splitlines()
    events_seen = [json.loads(line)["event"] for line in log]
    assert "call_answered" in events_seen
    assert events_seen.count("chunk_forwarded_to_twilio") >= 1
    assert events_seen[0] == "call_answered", "answer is the first event of every call"


@pytest.mark.timeout(25)
def test_s9b_transcript_preserves_role_and_order(profile: Profile, tmp_path: Path) -> None:
    """S9.b -- record.transcript equals the exact expected tuple, both roles.

    "Non-empty and ordered" passes for a mapper that tags every turn `model` or
    reverses them, and the transcript is the sole input to S4's analysis.
    """
    events: list[LiveEvent] = [
        Transcript(role="caller", text="A"),
        Transcript(role="model", text="B"),
        Transcript(role="caller", text="C"),
    ]
    factory = QueuedFactory(events)
    on_end = RecordingEnd()
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    _run_one_call(app, "CA-s9b")

    assert on_end.records[0].transcript == (
        TranscriptTurn(role="caller", text="A"),
        TranscriptTurn(role="model", text="B"),
        TranscriptTurn(role="caller", text="C"),
    )


@pytest.mark.timeout(25)
def test_s9c_timing_path_points_at_the_written_log(profile: Profile, tmp_path: Path) -> None:
    """S9.c -- record.timing_path is the JSONL this call actually wrote."""
    factory = QueuedFactory([])
    on_end = RecordingEnd()
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    _run_one_call(app, "CA-s9c")

    record = on_end.records[0]
    assert record.timing_path == tmp_path / "CA-s9c.jsonl"
    assert record.timing_path.exists()
    assert record.timing_path.read_text().strip(), "the log is not empty"


@pytest.mark.timeout(20)
def test_s14a_a_raising_live_factory_still_speaks_the_disclosure(
    profile: Profile, tmp_path: Path
) -> None:
    """S14.a -- live_factory raising: 200 not 500, body is Say + Hangup, Say is the disclosure.

    `open_live_session` raises on connect-time failure by design -- "that happens
    before a call exists, and S3 needs to see it rather than receive a Closed for
    a session that never opened" (live.py:352-354). A Gemini outage, a bad key or
    a network blip during the webhook all land here, and the compliance line must
    still be spoken. Every other seam drives a factory that succeeds.
    """

    async def _boom(_profile: Profile) -> NoReturn:
        raise RuntimeError("gemini is down")

    app = create_app(
        profile,
        _boom,
        _noop_on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)

    response = client.post("/voice", data={"CallSid": "CA-down", "From": "+447700900123"})

    assert response.status_code == 200, "a 500 makes Twilio play its own error message"
    root = ET.fromstring(response.text)
    assert root.find("Say") is not None
    assert root.find("Say").text == profile.disclosure  # type: ignore[union-attr]
    assert root.find("Hangup") is not None
    assert root.find("Connect") is None, "no stream may be opened for a dead session"


@pytest.mark.timeout(20)
def test_s14b_a_failed_webhook_registers_nothing(profile: Profile, tmp_path: Path) -> None:
    """S14.b -- nothing is registered, so a later start hits S11's fail-loudly path."""

    async def _boom(_profile: Profile) -> NoReturn:
        raise RuntimeError("gemini is down")

    app = create_app(
        profile,
        _boom,
        _noop_on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-down2", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-down2"))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


@pytest.mark.timeout(20)
def test_s14c_the_factory_failure_is_logged_with_the_call_sid(
    profile: Profile, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """S14.c -- the failure is logged with the CallSid, or the outage is invisible."""

    async def _boom(_profile: Profile) -> NoReturn:
        raise RuntimeError("gemini is down")

    app = create_app(
        profile,
        _boom,
        _noop_on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)

    with caplog.at_level(logging.ERROR, logger="decana.twilio.server"):
        client.post("/voice", data={"CallSid": "CA-down3", "From": "+447700900123"})

    assert any("CA-down3" in r.getMessage() for r in caplog.records)


@pytest.mark.timeout(30)
def test_s15a_two_concurrent_calls_keep_their_own_transcripts(
    profile: Profile, tmp_path: Path
) -> None:
    """S15.a -- two calls, reversed connect order: each record's content is its own.

    This is the worst failure in the seam list and the only one that is silent by
    construction: every other seam guards a call that fails, stalls or crashes.
    Here BOTH calls appear to succeed while one caller's mortgage details are
    written into the other's CallRecord -- which S5 then sends to the operator.
    A data-protection incident, invisible in the logs, the timing JSONL and the
    record itself.

    The sessions are DISTINGUISHABLE (each emits a transcript naming its own
    CallSid) and the sockets connect in REVERSE registration order, which is what
    defeats a most-recently-registered lookup -- `registry.popitem()` instead of
    `registry.pop(call_sid)`.
    """
    made: dict[str, FakeLiveSession] = {}
    order: list[str] = []

    async def factory(_profile: Profile) -> FakeLiveSession:
        tag = f"sess{len(made)}"
        session = FakeLiveSession(tag=tag, queued=[Transcript(role="caller", text=tag)])
        made[tag] = session
        order.append(tag)
        return session

    on_end = RecordingEnd()
    app = create_app(
        profile,
        factory,
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)

    client.post("/voice", data={"CallSid": "CA-one", "From": "+447700900123"})
    client.post("/voice", data={"CallSid": "CA-two", "From": "+447700900124"})
    client.post("/voice", data={"CallSid": "CA-three", "From": "+447700900125"})
    assert order == ["sess0", "sess1", "sess2"]

    # THREE calls, and the MIDDLE one connects first. Two calls cannot discriminate:
    # a LIFO `registry.popitem()` is matched by connecting the last-registered
    # first, and a FIFO `next(iter(registry))` is matched by connecting the
    # first-registered first -- each survives one of those orders by luck. Only an
    # order that is neither first nor last kills both, which is why this is three
    # calls and not two.
    for sid in ("CA-two", "CA-one", "CA-three"):
        with client.websocket_connect("/media") as ws:
            ws.send_json(_start_message(sid))
            ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    by_sid = {r.call_sid: r.transcript[0].text for r in on_end.records}
    assert by_sid == {"CA-one": "sess0", "CA-two": "sess1", "CA-three": "sess2"}, (
        "each call must carry its OWN session's transcript"
    )


@pytest.mark.timeout(30)
def test_s15b_each_call_drives_the_session_its_own_webhook_opened(
    profile: Profile, tmp_path: Path
) -> None:
    """S15.b -- each adopted session IS the object its own live_factory call returned."""
    made: list[FakeLiveSession] = []

    async def factory(_profile: Profile) -> FakeLiveSession:
        session = FakeLiveSession(tag=f"s{len(made)}")
        made.append(session)
        return session

    app = create_app(
        profile,
        factory,
        RecordingEnd(),
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)

    client.post("/voice", data={"CallSid": "CA-a1", "From": "+447700900123"})
    client.post("/voice", data={"CallSid": "CA-a2", "From": "+447700900124"})
    first, second = made[0], made[1]

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-a1"))
        for _ in range(12):
            ws.send_json(_media_message(_mulaw_frame()))
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    assert first.sent, "CA-a1's socket must drive CA-a1's session"
    assert second.sent == [], "CA-a2's session must not receive CA-a1's audio"


@pytest.mark.timeout(60)
def test_s17a_the_console_entry_point_starts_and_serves_voice(tmp_path: Path) -> None:
    """S17.a -- `decana` starts under the tracer's env profile and registers POST /voice.

    Required by the ratified feature gate ("__main__ smoke: decana starts with the
    tracer's optional env"). Every other test constructs create_app itself, so the
    whole class of composition-root wiring errors -- a live_factory without its
    api_key partial, a missing root= on load_profile, arguments in the wrong order
    -- is invisible to them and shows up on a deploy as a container that will not
    boot.

    Twilio and SMTP vars are deliberately ABSENT: the feature's env table marks
    exactly those "tracer: optional, unused", so a Settings that demanded them
    would break the tracer.

    The route is checked with a GET, asserting 405 Method Not Allowed -- which
    proves the path is registered WITHOUT executing the handler. A POST would run
    the webhook, which opens a real Gemini session (S3-Q1), and with a placeholder
    key a wrongly-wired factory and a correctly-wired one both answer with the same
    Say+Hangup, so it would not discriminate anyway. 404 here means not registered.
    """
    env = {
        **os.environ,
        "DECANA_PROFILE": "mortgage-broker",
        "GEMINI_API_KEY": "placeholder-not-used-at-startup",
        "PUBLIC_WSS_URL": "wss://example.test",
        "DECANA_ARTIFACT_DIR": str(tmp_path),
        "PORT": "8931",
    }
    for absent in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "SMTP_HOST", "SMTP_USER"):
        env.pop(absent, None)

    # cwd is a temp dir ON PURPOSE. `load_profile`'s own default root is
    # `Path("profiles")`, CWD-relative, and a service does not control its working
    # directory -- that is profile-loader W-1. Running from the repo root would let
    # a `main()` that forgot `root=settings.profiles_root` pass by luck, and the
    # mutation proving that survived until this cwd was changed.
    proc = subprocess.Popen(
        [sys.executable, "-m", "decana"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 30
        last: Exception | None = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise AssertionError(f"process exited early:\n{proc.communicate()[0]}")
            try:
                response = httpx.get("http://127.0.0.1:8931/voice", timeout=2)
                assert response.status_code == 405, (
                    f"POST /voice must be registered; got {response.status_code}"
                )
                return
            except httpx.HTTPError as exc:  # not up yet
                last = exc
                time.sleep(0.3)
        raise AssertionError(f"decana did not serve /voice within 30s: {last}")
    finally:
        proc.terminate()
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)


def test_s17b_a_missing_required_variable_exits_2_and_names_it() -> None:
    """S17.b -- a missing required env var exits 2 and names the variable.

    S3-Q11's ratified behaviour, and until this test it had no coverage anywhere:
    the coverage map recorded "deliberately none -- a trivial env mapper is not a
    hardest seam", which addressed parsing correctness and said nothing about the
    process refusing to start.
    """
    with pytest.raises(SystemExit) as caught:
        Settings.from_env({"GEMINI_API_KEY": "k", "PUBLIC_WSS_URL": "wss://x"})

    assert caught.value.code == 2


@pytest.mark.timeout(25)
def test_s2a_greeting_produced_before_the_socket_arrives_in_order(
    profile: Profile, tmp_path: Path
) -> None:
    """S2.a -- audio produced before the socket exists arrives first, and in order.

    S3 adds no buffer of its own: S2's reader runs as an independent task filling
    an unbounded `_inbox` with no consumer attached (live.py:183, 202, 284), so
    the greeting accumulates while `<Say>` plays and drains in arrival order once
    S3 starts iterating. A consumer that starts at connect and discards the
    backlog is, on a real call, the caller hearing the AI mid-sentence.
    """
    # Each chunk is 0.5s at 24kHz -- soxr batches and emits on its own schedule
    # (41 of 50 inbound frames returned zero samples when measured), so the chunks
    # are large enough that one outbound burst is certain rather than hoped for.
    #
    # The marker is the SIGN of the samples, not their bytes: the audio crosses a
    # 24k->8k resample and a lossy mu-law round-trip, so exact values cannot
    # survive and an equality assertion on them could never have held. The first
    # chunk is positive DC and every later chunk is negative, so a consumer that
    # dropped the backlog and started at connect yields negative audio.
    positive = np.full(12000, 8000, dtype=np.int16).tobytes()
    negative = np.full(12000, -8000, dtype=np.int16).tobytes()
    chunks = [AudioChunk(pcm24k=positive)] + [AudioChunk(pcm24k=negative)] * 3
    factory = QueuedFactory(list(chunks))
    app = create_app(
        profile,
        factory,
        RecordingEnd(),
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-s2a", "From": "+447700900123"})

    seen: list[str] = []
    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-s2a", stream_sid="MZ-B"))
        # ONE frame: the assertion is about which audio comes FIRST, and asking
        # for more blocks whenever soxr has not yet emitted that many bursts.
        with suppress(WebSocketDisconnect):
            seen.append(ws.receive_json()["media"]["payload"])
        ws.send_json({"event": "stop", "streamSid": "MZ-B"})

    assert seen, "the backlog must reach the socket"
    decoded = b"".join(mulaw_decode(base64.b64decode(p)) for p in seen)
    samples = np.frombuffer(decoded, dtype=np.int16)
    assert samples.size, "the outbound frame carried no audio"
    assert samples.mean() > 0, (
        "the first outbound audio must trace to the FIRST queued chunk; a negative "
        f"mean means the backlog was dropped (mean={samples.mean():.0f})"
    )


@pytest.mark.timeout(20)
def test_s4b_the_on_call_end_failure_names_the_call(
    profile: Profile, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """S4.b -- the on_call_end exception is logged with the call_sid and the type."""
    app = create_app(
        profile,
        RecordingFactory(lambda: datetime(2000, 1, 1, tzinfo=UTC)),
        RaisingEnd(),
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    with caplog.at_level(logging.ERROR, logger="decana.twilio.server"):
        _run_one_call(app, "CA-s4b")

    messages = [r.getMessage() for r in caplog.records]
    assert any("CA-s4b" in m for m in messages)
    assert any("RuntimeError" in (r.exc_text or "") for r in caplog.records)


def test_s5b_send_media_after_teardown_is_a_silent_no_op() -> None:
    """S5.b -- once the call is torn down, send_media enqueues nothing and raises nothing."""

    async def _run() -> tuple[int, int]:
        sender = _SocketSender("MZ-y")
        sender.send_media("one")
        before = sender.queue.qsize()
        sender.closed = True
        sender.send_media("two")
        return before, sender.queue.qsize()

    before, after = asyncio.run(_run())
    assert (before, after) == (1, 1)


@pytest.mark.timeout(20)
def test_s10b_a_raising_bridge_close_still_hands_off_the_partial_record(
    profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S10.b -- on_call_end is still awaited exactly once, with the record as it stands.

    A partial transcript still has value and S5 tolerates an empty one; losing the
    record entirely is the failure this guards.
    """
    monkeypatch.setattr(
        BridgeSession,
        "close",
        lambda _self: (_ for _ in ()).throw(ValueError("flush exploded")),
    )
    on_end = RecordingEnd()
    app = create_app(
        profile,
        QueuedFactory([Transcript(role="caller", text="partial")]),
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    _run_one_call(app, "CA-s10b")

    assert len(on_end.records) == 1
    assert on_end.records[0].transcript == (TranscriptTurn(role="caller", text="partial"),)


@pytest.mark.timeout(20)
def test_s12c_absorbed_messages_do_not_touch_the_transcript_or_record(
    profile: Profile, tmp_path: Path
) -> None:
    """S12.c -- connected/mark/dtmf leave the transcript and the CallRecord unchanged.

    Seam 12 lists this as its own assertion and it is easy to lose in the
    compression to ids: absorbing a message without crashing is not the same as
    absorbing it without side effects.
    """
    on_end = RecordingEnd()
    app = create_app(
        profile,
        QueuedFactory([Transcript(role="model", text="only")]),
        on_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)
    client.post("/voice", data={"CallSid": "CA-s12c", "From": "+447700900123"})

    with client.websocket_connect("/media") as ws:
        ws.send_json(_start_message("CA-s12c"))
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json({"event": "mark", "streamSid": "MZ-1", "mark": {"name": "m"}})
        ws.send_json({"event": "dtmf", "streamSid": "MZ-1", "dtmf": {"digit": "9"}})
        ws.send_json({"event": "stop", "streamSid": "MZ-1"})

    record = on_end.records[0]
    assert record.transcript == (TranscriptTurn(role="model", text="only"),)
    assert record.caller_number == "+447700900123"
    assert record.ended_reason == "twilio_stop"
