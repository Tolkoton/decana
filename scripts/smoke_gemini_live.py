"""Smoke test for slice S2 -- `decana.gemini.live` against the REAL Live API.

Closes the slice's exit criterion. Every assertion is machine-checkable, so this
runs unattended: there is no human-only oracle here.

Flow: open a session on `profiles/mortgage-broker/`, let the model open the
conversation unprompted, feed its own greeting audio back as "caller" audio
(resampled 24k -> 16k with the shipped Resampler), then close and check the
whole event stream.

Cost discipline: ONE session, one greeting turn, one feed-back, then close.
Not a loop.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from decana.bridge.resampler import Resampler
from decana.gemini.live import (
    AudioChunk,
    Closed,
    GeminiLiveSession,
    LiveEvent,
    Transcript,
    open_live_session,
)
from decana.profile.load import load_profile

TIMEOUT_S = 90.0
GREETING_WAIT_S = 25.0
REPLY_WAIT_S = 12.0


def load_env(path: Path = Path(".env")) -> None:
    """Read secrets from disk into the process, never printing them."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


async def _collect(
    session: GeminiLiveSession, sink: list[LiveEvent], stamps: dict[str, float]
) -> None:
    """Drain the stream, stamping the moment the first audio chunk lands."""
    async for event in session.events():
        if isinstance(event, AudioChunk) and "first_audio" not in stamps:
            stamps["first_audio"] = time.monotonic()
        sink.append(event)


async def main() -> int:
    load_env()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("FAIL: GEMINI_API_KEY not set (put it in .env)")
        return 2

    profile = load_profile("mortgage-broker")
    print(f"profile      : {profile.name} / {profile.live_model}")

    events: list[LiveEvent] = []
    stamps: dict[str, float] = {}
    started = time.monotonic()
    session = await open_live_session(profile, api_key=api_key)
    consumer = asyncio.create_task(_collect(session, events, stamps))

    # --- wait for the model to open the conversation, unprompted -------------
    deadline = time.monotonic() + GREETING_WAIT_S
    while time.monotonic() < deadline:
        if any(isinstance(e, Transcript) and e.role == "model" for e in events):
            break
        await asyncio.sleep(0.2)

    greeting_audio = b"".join(e.pcm24k for e in events if isinstance(e, AudioChunk))
    elapsed_to_audio_ms = (
        (stamps["first_audio"] - started) * 1000 if "first_audio" in stamps else -1.0
    )

    print(f"greeting     : {len(greeting_audio)} bytes of 24k audio")
    print(f"time to audio: ~{elapsed_to_audio_ms:.0f} ms (see F)")

    # --- feed the model's own greeting back as caller audio -----------------
    if greeting_audio:
        down = Resampler(24000, 16000)
        pcm16k = down.push(greeting_audio) + down.push(b"", last=True)
        print(f"caller audio : {len(pcm16k)} bytes of 16k, sending at 20ms pacing")
        for offset in range(0, len(pcm16k), 640):
            session.send_audio(pcm16k[offset : offset + 640])
            await asyncio.sleep(0.02)
        await asyncio.sleep(REPLY_WAIT_S)

    await session.close()
    await asyncio.wait_for(consumer, TIMEOUT_S)

    # --- report -------------------------------------------------------------
    chunks = [e for e in events if isinstance(e, AudioChunk)]
    model_turns = [e for e in events if isinstance(e, Transcript) and e.role == "model"]
    caller_turns = [
        e for e in events if isinstance(e, Transcript) and e.role == "caller"
    ]
    closes = [e for e in events if isinstance(e, Closed)]

    print("\n--- event stream ---")
    for event in events:
        if isinstance(event, AudioChunk):
            continue
        print(f"  {type(event).__name__}: {event}")
    print(f"  (+{len(chunks)} AudioChunk events, elided)")

    failures: list[str] = []

    def check(ok: bool, label: str) -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            failures.append(label)

    print("\n--- exit criterion ---")
    check(
        bool(chunks) and sum(len(c.pcm24k) for c in chunks) > 0,
        f"A  >=1 AudioChunk with bytes (got {len(chunks)})",
    )
    check(
        all(len(c.pcm24k) % 2 == 0 for c in chunks),
        "A  every pcm24k is even-length",
    )
    check(
        len(model_turns) == 1,
        f"B  exactly one model Transcript for the greeting turn (got {len(model_turns)})",
    )
    if model_turns:
        text = model_turns[0].text
        check(
            len(text.split()) >= 5 and text.rstrip().endswith((".", "?", "!")),
            f"C  model turn is a whole utterance: {text!r}",
        )
    else:
        check(False, "C  model turn is a whole utterance (no turn to check)")
    check(
        len(closes) == 1 and isinstance(events[-1], Closed),
        f"D  exactly one Closed, last (got {len(closes)})",
    )
    check(
        bool(closes) and closes[0].reason == "local",
        f"D  Closed.reason == 'local' (got {closes[0].reason!r} )"
        if closes
        else "D  Closed.reason == 'local' (no Closed)",
    )
    check(
        len(caller_turns) >= 1,
        f"E  >=1 caller Transcript after feeding audio back (got {len(caller_turns)})",
    )
    print(
        f"INFO  F  time to first audio ~{elapsed_to_audio_ms:.0f} ms "
        f"(recorded, not gated -- S3 must open the session concurrently with <Say>)"
    )

    print()
    if failures:
        print(f"SMOKE FAILED: {len(failures)} assertion(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SMOKE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
