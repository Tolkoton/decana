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
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect

from decana.bridge.resampler import inbound_resampler, outbound_resampler
from decana.bridge.session import BridgeSession
from decana.bridge.timing import TimingRecorder
from decana.gemini.live import AudioChunk, Closed, Interrupted, LiveEvent, Transcript
from decana.profile.model import Profile
from decana.twilio.records import CallRecord, OnCallEnd, TranscriptTurn

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
    timing_path: Path
    transcript: list[TranscriptTurn] = field(default_factory=list)
    done: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tasks: list[asyncio.Task[None]] = field(default_factory=list)


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
        # Claim BEFORE closing. The pop is what makes this sweeper the owner of
        # the entry; whoever pops it is the only one that closes it. Closing
        # first and popping after lets two concurrent sweeps both close the same
        # session -- the guarded pop keeps the dict consistent but does nothing
        # about the duplicate close, which S8.c caught.
        if registry.pop(call_sid, None) is None:
            continue
        await pending.session.close()


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


def _render_hangup_twiml(profile: Profile) -> str:
    """Speak the disclosure, then hang up -- the answer when no session could open.

    The compliance line is spoken even on the failure path: it is the one thing
    the caller is owed regardless of whether the AI can talk to them.
    """
    response = Element("Response")
    say = SubElement(response, "Say")
    say.text = profile.disclosure
    SubElement(response, "Hangup")
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

        try:
            session = await live_factory(profile)
        except Exception:
            # `open_live_session` raises on connect-time failure deliberately, so
            # S3 sees it rather than receiving a `Closed` for a session that never
            # opened. A 500 here makes Twilio play its own error message instead
            # of the compliance disclosure, and registering nothing keeps a later
            # stray socket on S3-Q5's fail-loudly path.
            logger.exception("live_factory failed for CallSid %s", call_sid)
            return Response(
                content=_render_hangup_twiml(profile),
                media_type="application/xml",
            )

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
        ending = "ws_disconnect"
        try:
            while True:
                message = await websocket.receive_json()
                event = message.get("event")

                if event == "start":
                    call = await _begin_call(websocket, message)
                    if call is None:
                        break
                    call.tasks = [
                        asyncio.create_task(_pump_events(call, websocket)),
                        asyncio.create_task(_drain_outbound(call, websocket)),
                    ]
                elif event == "media" and call is not None:
                    call.bridge.handle_twilio_frame(message["media"]["payload"])
                elif event == "stop":
                    ending = "twilio_stop"
                    break
                # `connected` carries only protocol/version -- nothing to bind a
                # call to yet. `mark` and `dtmf` are ignored per guarantee (d).
                # All three are deliberate no-ops, not forgotten cases.
        except WebSocketDisconnect:
            ending = "ws_disconnect"
        except Exception as exc:
            logger.exception("unexpected failure in the media socket")
            ending = f"error: {type(exc).__name__}"
        finally:
            if call is not None:
                await _teardown(call, ending, websocket)

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
        timing_path = artifact_dir / f"{call_sid}.jsonl"
        timing = TimingRecorder(clock=clock, sink_path=timing_path)
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
            timing_path=timing_path,
        )

    async def _pump_events(call: "_Call", websocket: WebSocket) -> None:
        """Route S2's event stream by type, for the life of the session.

        The ratified routing table, and every member of `LiveEvent` is here on
        purpose: an omitted arm raises mid-call the first time a caller talks over
        the model, which is ordinary on a phone call rather than exceptional.
        """
        try:
            async for event in call.session.events():
                if isinstance(event, AudioChunk):
                    call.bridge.handle_gemini_chunk(event.pcm24k)
                elif isinstance(event, Transcript):
                    call.transcript.append(
                        TranscriptTurn(role=event.role, text=event.text)
                    )
                elif isinstance(event, Interrupted):
                    # Log-only no-op, ratified as feature Q4. Deliberately does
                    # NOT end the call: a barge-in is the caller talking, not a
                    # failure.
                    logger.info("caller interrupted the model on %s", call.call_sid)
                elif isinstance(event, Closed):
                    await _teardown(call, f"gemini_closed: {event.reason}", websocket)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("event pump failed for %s", call.call_sid)
            await _teardown(call, f"error: {type(exc).__name__}", websocket)

    async def _drain_outbound(call: "_Call", websocket: WebSocket) -> None:
        """Write queued frames to the socket in FIFO order.

        `streamSid` rides at the ROOT of every outbound message, captured from the
        `start` message. Twilio requires it there and discards frames without it,
        which on a real call is dead air after the greeting -- silent, and on
        exactly the path the latency acceptance measures. See S3-Q13.
        """
        try:
            while True:
                payload = await call.sender.queue.get()
                await websocket.send_json(
                    {
                        "event": "media",
                        "streamSid": call.stream_sid,
                        "media": {"payload": payload},
                    }
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbound send failed for %s", call.call_sid)
            await _teardown(call, "twilio_send_failed", websocket)

    async def _teardown(
        call: "_Call", reason: str, websocket: WebSocket | None = None
    ) -> None:
        """Flow: stop sending, flush the bridge, close Gemini, hand off the record.

        At-most-once, guarded by a per-call lock AND a `done` flag: every path that
        ends a call funnels here, and `BridgeSession.close()` raises
        `RuntimeError("Input after last input")` by design on a second flush
        (`voice-intake-demo` Q19). The guard must make that unreachable rather than
        swallow it.

        Order is drain-stop -> bridge -> gemini -> record (S3-Q8). The bridge flush
        forwards soxr's stranded tail, so it must run while the Twilio send path can
        still accept it but after the drain stops taking new work. Gemini closes last
        because closing it first makes the event loop observe a `Closed` mid-teardown
        and re-enter here.
        """
        async with call.lock:
            if call.done:
                return
            call.done = True

            call.sender.closed = True
            for task in call.tasks:
                if task is not asyncio.current_task():
                    task.cancel()
            ended_reason = reason
            try:
                call.bridge.close()
            except Exception as exc:
                logger.exception("bridge close failed for %s", call.call_sid)
                ended_reason = f"error: {type(exc).__name__}"
            await call.session.close()

            if websocket is not None:
                # Close the socket so the handler's blocked `receive_json` returns.
                # Teardown can be triggered from the drain or pump task while the
                # main loop still waits for the next inbound message; without this
                # the call is over but the socket stays open forever -- which is a
                # hang, not an error, and the worst failure shape available.
                with suppress(Exception):
                    await websocket.close()

            record = CallRecord(
                call_sid=call.call_sid,
                caller_number=call.caller_number,
                profile_name=profile.name,
                started_at=call.started_at,
                ended_at=clock(),
                transcript=tuple(call.transcript),
                timing_path=call.timing_path,
                ended_reason=ended_reason,
            )
            try:
                await on_call_end(record)
            except Exception:
                # Logged and swallowed. Everything above is already settled, so a
                # raise here cannot leave the call half-torn-down; and retrying
                # would break the stronger exactly-once guarantee to protect the
                # weaker one.
                logger.exception("on_call_end failed for %s", call.call_sid)

    return app
