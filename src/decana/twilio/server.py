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
import contextlib
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Protocol
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import FastAPI, Form, Response, WebSocket, WebSocketDisconnect

from decana.bridge.resampler import inbound_resampler, outbound_resampler
from decana.bridge.session import BridgeSession
from decana.bridge.timing import TimingRecorder
from decana.gemini.live import AudioChunk, Closed, Interrupted, LiveEvent, Transcript
from decana.profile.model import Profile
from decana.twilio.records import CallRecord, OnCallEnd, TranscriptTurn

__all__ = ["LiveSession", "LiveSessionFactory", "build_on_call_end", "create_app"]

logger = logging.getLogger(__name__)


def build_on_call_end() -> OnCallEnd:
    """The tracer's post-call handler: log the record, do nothing else.

    A factory rather than a bare function because S5 replaces this body with
    `post_call` once analysis and dispatch exist, and it will need its own
    injected senders. Keeping the seam a factory now means that change touches
    one function, not `__main__`'s wiring.
    """

    async def _log_only(record: CallRecord) -> None:
        logger.info(
            "call %s ended (%s) after %d turns; timing log at %s",
            record.call_sid,
            record.ended_reason,
            len(record.transcript),
            record.timing_path,
        )

    return _log_only


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
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    done: bool = False
    pump: "asyncio.Task[None] | None" = None
    drain: "asyncio.Task[None] | None" = None


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


async def _stop_task(task: "asyncio.Task[None] | None") -> None:
    """Cancel a per-call task and wait for it to finish.

    Cancels rather than awaits natural completion, and the difference is a
    deadlock. `_teardown` holds the per-call lock for its whole body, and both
    background tasks can call `_teardown` themselves -- the pump on `Closed`,
    the drain on a send failure. A task blocked on that lock will never finish
    on its own while we hold it, so awaiting it here would hang the call
    forever. Cancelling unblocks it at the `acquire`.

    The self-check is the other half: `_teardown` is reached FROM these tasks,
    and a task that cancels and awaits itself never returns.
    """
    if task is None or task is asyncio.current_task():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _route_live_event(
    call: _Call, event: AudioChunk | Transcript | Interrupted
) -> None:
    """One non-terminal `LiveEvent` to its ratified destination.

    `Interrupted` is a log-only no-op (feature Q4), and it is spelled out as its
    own arm rather than falling into an `else: pass`: it is the member that went
    missing from S2 through ten critic rounds and from this slice's own coverage
    map, precisely because there is nothing to do for it.
    """
    if isinstance(event, AudioChunk):
        call.bridge.handle_gemini_chunk(event.pcm24k)
    elif isinstance(event, Transcript):
        call.transcript.append(TranscriptTurn(role=event.role, text=event.text))
    else:
        logger.info("barge-in on call %s; no action taken", call.call_sid)


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
    """Render the failure TwiML: speak the disclosure, then hang up.

    The disclosure still goes out. It is the compliance line, and the caller is
    owed it on every answered call -- including the one where Gemini never came
    up. No `<Connect>`: there is no session for a stream to carry.
    """
    response = Element("Response")
    say = SubElement(response, "Say")
    say.text = profile.disclosure
    SubElement(response, "Hangup")
    return tostring(response, encoding="unicode")


def _twiml_response(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


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
    async def voice(
        call_sid: Annotated[str, Form(alias="CallSid")],
        caller: Annotated[str, Form(alias="From")],
    ) -> Response:
        """Flow: open the session, register it, answer with the TwiML.

        The session opens HERE and not in the socket handler because
        `<Connect><Stream>` is terminal and TwiML verbs run in order: the socket
        does not exist while `<Say>` is playing, and this is the only code that
        runs during the disclosure. See S3-Q1.

        Both fields are REQUIRED, so a malformed webhook is a 422 rather than a
        session registered under the empty string -- where two of them would
        collide on one key and the second would close the first.
        """
        now = clock()
        await _sweep_expired(registry, now=now, ttl_s=pending_ttl_s)

        try:
            session = await live_factory(profile)
        except Exception as exc:  # noqa: BLE001 -- see _render_hangup_twiml
            # `open_live_session` raises on connect-time failure deliberately
            # (`live.py:352-354`). Registering nothing is the load-bearing half:
            # a `_Pending` left behind would let a later WS `start` adopt a
            # session that was never opened.
            logger.exception(
                "live_factory raised %s for CallSid %s",
                type(exc).__name__,
                call_sid,
            )
            return _twiml_response(_render_hangup_twiml(profile))

        await _register(registry, call_sid, session, now=now)
        return _twiml_response(_render_twiml(profile, public_wss_url, caller))

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
        """Flow: accept, dispatch inbound messages, tear down once.

        Every exit from the loop names its own ending (the ratified error
        table); the `finally` is the single funnel into `_teardown`, so an
        ending added later cannot skip the record.
        """
        await websocket.accept()
        call: _Call | None = None
        reason = "ws_disconnect"
        try:
            while True:
                message = await websocket.receive_json()
                event = message.get("event")

                if event == "start":
                    call = await _begin_call(websocket, message)
                    if call is None:
                        return
                elif event == "media" and call is not None:
                    call.bridge.handle_twilio_frame(message["media"]["payload"])
                elif event == "stop":
                    reason = "twilio_stop"
                    break
                # `connected` carries only protocol/version -- nothing to bind a
                # call to yet. `mark` and `dtmf` are ignored per guarantee (d).
                # All three are deliberate no-ops, not forgotten cases.
        except WebSocketDisconnect:
            reason = "ws_disconnect"
            logger.info("socket disconnected")
        except Exception as exc:  # noqa: BLE001 -- ratified `error: <type>` ending
            reason = f"error: {type(exc).__name__}"
            logger.exception("media socket failed for call %s", getattr(call, "call_sid", "?"))
        finally:
            if call is not None:
                await _teardown(call, reason)

    async def _begin_call(
        websocket: WebSocket, message: dict[str, Any]
    ) -> "_Call | None":
        """Flow: adopt the session, build the bridge, start the two pumps."""
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

        call = _build_call(session, start, call_sid, stream_sid, now)
        call.bridge.start()
        call.pump = asyncio.create_task(_pump_events(call))
        call.drain = asyncio.create_task(_drain_outbound(websocket, call))
        return call

    def _build_call(
        session: LiveSession,
        start: dict[str, Any],
        call_sid: str,
        stream_sid: str,
        now: datetime,
    ) -> "_Call":
        """Assemble one call's collaborators. No I/O, no task creation."""
        timing_path = artifact_dir / f"{call_sid}.jsonl"
        sender = _SocketSender(stream_sid)
        return _Call(
            call_sid=call_sid,
            stream_sid=stream_sid,
            caller_number=normalise_caller_number(
                str(start.get("customParameters", {}).get("caller", ""))
            ),
            session=session,
            bridge=BridgeSession(
                twilio=sender,
                gemini=session,
                timing=TimingRecorder(clock=clock, sink_path=timing_path),
                inbound=inbound_resampler(),
                outbound=outbound_resampler(),
            ),
            sender=sender,
            started_at=now,
            timing_path=timing_path,
        )

    async def _pump_events(call: "_Call") -> None:
        """Flow: consume S2's event stream, route each event, end on `Closed`.

        `Closed` is handled here rather than in the router because it is the one
        arm that ends the call: S2 guarantees exactly one, always last, so the
        `return` after it is what makes this task finish on its own.
        """
        async for event in call.session.events():
            if isinstance(event, Closed):
                await _teardown(call, f"gemini_closed: {event.reason}")
                return
            _route_live_event(call, event)

    async def _drain_outbound(websocket: WebSocket, call: "_Call") -> None:
        """Flow: take one queued frame, write it to the socket, repeat.

        The `streamSid` at message ROOT is S3-Q13 and is not decoration: Twilio
        discards a media frame without it, silently, and the caller hears dead
        air after the greeting on exactly the path A3 measures.
        """
        while True:
            payload = await call.sender.queue.get()
            try:
                await websocket.send_json(
                    {
                        "event": "media",
                        "streamSid": call.stream_sid,
                        "media": {"payload": payload},
                    }
                )
            except Exception:  # noqa: BLE001 -- ratified `twilio_send_failed` ending
                logger.exception("outbound send failed for call %s", call.call_sid)
                await _teardown(call, "twilio_send_failed")
                return

    async def _teardown(call: "_Call", reason: str) -> None:
        """Flow: stop the drain, flush the bridge, close Gemini, hand off the record.

        Exactly once per call, and in the ratified S3-Q8 order. The lock is held
        across the whole body so a second ending arriving mid-teardown waits and
        then sees `done`, rather than double-flushing into the
        `RuntimeError("Input after last input")` that `BridgeSession.close()`
        raises by design.
        """
        async with call.lock:
            if call.done:
                return
            call.done = True
            call.sender.closed = True
            await _stop_task(call.drain)
            reason = _close_bridge(call, reason)
            await call.session.close()
            await _stop_task(call.pump)
            await _deliver_record(call, reason)

    def _close_bridge(call: "_Call", reason: str) -> str:
        """Flush the bridge's stranded tail; a raise becomes the ending (S3-Q9).

        Unwrapped, a raising `close()` takes the whole teardown with it: no
        `CallRecord`, no `on_call_end`, no diagnostic trail for a call that
        really happened.
        """
        try:
            call.bridge.close()
        except Exception as exc:  # noqa: BLE001 -- ratified `error: <type>` ending
            logger.exception("BridgeSession.close() failed for call %s", call.call_sid)
            return f"error: {type(exc).__name__}"
        return reason

    async def _deliver_record(call: "_Call", reason: str) -> None:
        """Build the record and hand it to the injected callback (S3-Q12).

        The callback is the LAST thing that happens to a call: every close, the
        drain stop and the `done` flag are already settled, so a raise here
        cannot leave the call half-torn-down. It is logged and swallowed -- never
        retried, because `on_call_end` is ratified as awaited exactly once and
        retrying would break the stronger guarantee to protect the weaker one.
        """
        record = CallRecord(
            call_sid=call.call_sid,
            caller_number=call.caller_number,
            profile_name=profile.name,
            started_at=call.started_at,
            ended_at=clock(),
            transcript=tuple(call.transcript),
            timing_path=call.timing_path,
            ended_reason=reason,
        )
        try:
            await on_call_end(record)
        except Exception as exc:  # noqa: BLE001 -- ratified guarantee (b)
            logger.exception(
                "on_call_end raised %s for call %s",
                type(exc).__name__,
                call.call_sid,
            )

    return app
