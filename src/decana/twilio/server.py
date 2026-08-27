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

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI

from decana.gemini.live import LiveEvent
from decana.profile.model import Profile
from decana.twilio.records import OnCallEnd

__all__ = ["LiveSession", "LiveSessionFactory", "create_app"]


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
    """Build the app. Slice in progress."""
    raise NotImplementedError("slice in progress")
