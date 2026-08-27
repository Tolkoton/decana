"""The Twilio leg: TwiML webhook, media WebSocket, and the composition root.

WHAT: `create_app` builds the FastAPI app that answers Twilio's voice webhook with
`<Say>{disclosure}</Say><Connect><Stream>`, then bridges the media WebSocket to a
Gemini Live session opened during the webhook.

WHY the session opens in the webhook and not in the socket handler: `<Connect><Stream>`
is terminal and TwiML verbs run in order, so the WebSocket does not exist while `<Say>`
is playing. The webhook is the only code that runs during the disclosure, and Gemini's
~3-4s connect has to hide behind it. See the slice artifact, S3-Q1.

WHAT THIS DOES NOT DO: deployment, post-call analysis, dispatch, retry/reconnection
policy, or barge-in beyond logging `Interrupted`. `on_call_end` is injected; this slice
ships only the log-only no-op the tracer uses.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect

from decana.bridge.resampler import inbound_resampler, outbound_resampler
from decana.bridge.session import BridgeSession
from decana.bridge.timing import TimingRecorder
from decana.gemini.live import LiveEvent
from decana.profile.model import Profile
from decana.twilio.records import OnCallEnd

__all__ = ["LiveSession", "LiveSessionFactory", "create_app"]

logger = logging.getLogger(__name__)


class LiveSession(Protocol):
    """What S3 consumes from S2 -- and nothing more.

    Defined here, consumer-side, because S2 shipped `LiveTransport` (its own
    inbound test seam) but never this one, even though the ratified feature
    contract's Edge S2 -> S3 specifies it. `GeminiLiveSession` satisfies it
    structurally, so nothing in S2 changes.

    The surface is deliberately exactly the three ratified members. There is no
    `start()`: `open_live_session` calls it internally before returning
    (`live.py:370`), and calling it again re-sends the greeting trigger and spawns
    a second reader/drain pair over one transport.
    """

    def send_audio(self, pcm16k: bytes) -> None: ...
    def events(self) -> AsyncIterator[LiveEvent]: ...
    async def close(self) -> None: ...


LiveSessionFactory = Callable[[Profile], Awaitable[LiveSession]]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Pending:
    """A session opened by the webhook, waiting for its socket to arrive."""

    session: LiveSession
    registered_at: datetime


@dataclass
class _Call:
    """Per-call state for one adopted socket."""

    call_sid: str
    stream_sid: str
    caller_number: str
    session: LiveSession
    bridge: BridgeSession
    sender: "_SocketSender"
    started_at: datetime


_E164 = re.compile(r"^\+[1-9]\d{1,14}$")


def normalise_caller_number(raw: str) -> str:
    """E.164 if it parses as one, otherwise the empty string.

    Twilio's `From` is NOT always E.164: on a withheld or unnormalisable caller
    ID it reports "a string that contains `anonymous`, `unknown`, or other
    descriptions", or the raw caller ID string. This value reaches S5's SMS
    send, where a non-number is an SMS to a non-number -- so "no usable number"
    collapses to one testable state rather than an open set of vendor strings.
    See S3-Q6.
    """
    return raw if _E164.match(raw) else ""


class _SocketSender:
    """Sync `send_media` that enqueues; one drain task writes to the socket.

    Sync and never-raising is a hard requirement, not defensive style:
    `BridgeSession._forward_to_twilio` calls this under a catch scoped to
    `AudioFrameError` only, so any other exception escaping here ends the call.
    After teardown it is a silent no-op. See S3-Q10.
    """

    def __init__(self, stream_sid: str) -> None:
        self._stream_sid = stream_sid
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    def send_media(self, base64_mulaw: str) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait(base64_mulaw)
        except Exception:  # pragma: no cover - unbounded queue does not raise
            logger.exception("dropping outbound frame for stream %s", self._stream_sid)


async def _sweep_expired(
    registry: dict[str, _Pending],
    *,
    now: datetime,
    ttl_s: float,
) -> None:
    """Close and drop pending sessions whose socket never arrived.

    Iterates a snapshot and removes with a guarded pop -- never
    `del registry[call_sid]` -- because it awaits `close()` per entry and the dict
    can be mutated by a concurrent webhook or socket across that await. The bare
    `del` raises `KeyError` inside whichever unrelated request happened to trigger
    the sweep. See S3-Q4.
    """
    for call_sid, pending in list(registry.items()):
        if (now - pending.registered_at).total_seconds() <= ttl_s:
            continue
        await pending.session.close()
        registry.pop(call_sid, None)


async def _register(
    registry: dict[str, _Pending],
    call_sid: str,
    session: LiveSession,
    *,
    now: datetime,
) -> None:
    """Register a session, closing any session already held under this CallSid.

    Twilio retries the voice webhook on timeout or 5xx, so a second `POST /voice`
    for a pending `CallSid` is a documented condition. A bare dict write would
    orphan the first session -- its reader and drain tasks keep running with no
    external reference, and the sweep can never reclaim them because it only
    inspects entries still in the dict. See S3-Q14.
    """
    superseded = registry.get(call_sid)
    if superseded is not None:
        logger.info("superseding pending session for CallSid %s", call_sid)
        await superseded.session.close()
    registry[call_sid] = _Pending(session=session, registered_at=now)


def _render_twiml(profile: Profile, public_wss_url: str, caller: str) -> str:
    """Render the answer TwiML: speak the disclosure, then open the media stream.

    Built as an element tree rather than an f-string so escaping is correct by
    construction. A disclosure containing `&` -- ordinary English prose, "Smith &
    Co" -- produces a document Twilio cannot parse if interpolated raw, while
    still satisfying a `"<Say>" in body` assertion.
    """
    response = Element("Response")
    say = SubElement(response, "Say")
    say.text = profile.disclosure
    connect = SubElement(response, "Connect")
    stream = SubElement(connect, "Stream", {"url": f"{public_wss_url}/media"})
    SubElement(stream, "Parameter", {"name": "caller", "value": caller})
    return tostring(response, encoding="unicode")


def create_app(
    profile: Profile,
    live_factory: LiveSessionFactory,
    on_call_end: OnCallEnd,
    *,
    public_wss_url: str,
    artifact_dir: Path,
    clock: Callable[[], datetime] = _utc_now,
    pending_ttl_s: float = 60.0,
) -> FastAPI:
    """Flow: build the app, register the endpoints, hand it back."""
    app = FastAPI()
    registry: dict[str, _Pending] = {}

    @app.post("/voice")
    async def voice(request: Request) -> Response:
        """Flow: open the session, register it, answer with the TwiML.

        The session opens HERE and not in the socket handler because
        `<Connect><Stream>` is terminal and TwiML verbs run in order: the socket
        does not exist while `<Say>` is playing, and this is the only code that
        runs during the disclosure. See S3-Q1.
        """
        form = await request.form()
        call_sid = str(form.get("CallSid", ""))
        caller = str(form.get("From", ""))
        now = clock()
        await _sweep_expired(registry, now=now, ttl_s=pending_ttl_s)

        session = await live_factory(profile)
        await _register(registry, call_sid, session, now=now)

        return Response(
            content=_render_twiml(profile, public_wss_url, caller),
            media_type="application/xml",
        )

    async def _adopt(call_sid: str, now: datetime) -> LiveSession | None:
        """Take this call's own session out of the registry, then sweep the rest.

        Pops its OWN key FIRST. Sweeping first would let a call whose socket
        arrives later than `pending_ttl_s` after the webhook close its own live
        session and then fail as an unknown CallSid -- a real caller dropped by a
        reaper meant for orphans. See S3-Q4.
        """
        mine = registry.pop(call_sid, None)
        await _sweep_expired(registry, now=now, ttl_s=pending_ttl_s)
        return None if mine is None else mine.session

    @app.websocket("/media")
    async def media(websocket: WebSocket) -> None:
        """Flow: accept, dispatch inbound messages, tear down once."""
        await websocket.accept()
        call: _Call | None = None
        try:
            while True:
                message = await websocket.receive_json()
                event = message.get("event")

                if event == "start":
                    call = await _begin_call(websocket, message)
                    if call is None:
                        break
                elif event == "media" and call is not None:
                    call.bridge.handle_twilio_frame(message["media"]["payload"])
                elif event == "stop":
                    break
                # `connected` carries only protocol/version -- nothing to bind a
                # call to yet. `mark` and `dtmf` are ignored per guarantee (d).
                # All three are deliberate no-ops, not forgotten cases.
        except WebSocketDisconnect:
            logger.info("socket disconnected")
        finally:
            if call is not None:
                await _teardown(call)

    async def _begin_call(
        websocket: WebSocket, message: dict[str, Any]
    ) -> "_Call | None":
        """Flow: adopt the session, build the bridge, record `call_answered`."""
        start = message.get("start", {})
        call_sid = str(start.get("callSid", ""))
        stream_sid = str(message.get("streamSid", ""))
        now = clock()

        session = await _adopt(call_sid, now)
        if session is None:
            # Either the TTL fired (impossible in a normal call) or POST /voice
            # never ran for this CallSid. Opening a session here would convert a
            # wiring bug into a ~3s-dead-air latency bug and hide the one symptom
            # that reveals a broken webhook path. See S3-Q5.
            logger.warning("WS start for unknown CallSid %s; closing", call_sid)
            await websocket.close()
            return None

        caller = normalise_caller_number(
            str(start.get("customParameters", {}).get("caller", ""))
        )
        sender = _SocketSender(stream_sid)
        timing = TimingRecorder(
            clock=clock, sink_path=artifact_dir / f"{call_sid}.jsonl"
        )
        bridge = BridgeSession(
            twilio=sender,
            gemini=session,
            timing=timing,
            inbound=inbound_resampler(),
            outbound=outbound_resampler(),
        )
        bridge.start()
        return _Call(
            call_sid=call_sid,
            stream_sid=stream_sid,
            caller_number=caller,
            session=session,
            bridge=bridge,
            sender=sender,
            started_at=now,
        )

    async def _teardown(call: "_Call") -> None:
        """Flow: stop sending, flush the bridge, close Gemini, hand off the record."""
        call.sender.closed = True
        call.bridge.close()
        await call.session.close()

    return app
