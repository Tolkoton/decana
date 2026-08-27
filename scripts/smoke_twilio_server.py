"""Smoke test for slice S3 -- `decana.twilio.server` against the REAL Gemini API.

Closes the slice's exit criterion §2. Every assertion is machine-checkable, so
this runs unattended: there is no human-only oracle here.

Everything except the Twilio leg is real -- the real `create_app`, the real
`open_live_session` against the live Live API, a real uvicorn server, a real
HTTP webhook POST and a real WebSocket client. Only Twilio itself is simulated,
which is exactly the leg blocked on provisioning and exactly the leg the tracer
(feature step 4) exists to prove.

DEVIATION from the artifact's §2 wording, recorded rather than hidden: the
caller audio is synthesised here instead of read from a WAV on disk, because
this repo ships no WAV fixture. The shape Twilio actually sends is preserved --
100 frames of real mu-law, 160 bytes each, at a 20 ms cadence -- and no
assertion depends on the audio being intelligible: the transcript assertion is
carried by the model's own unprompted greeting turn, not by the caller leg.

Cost discipline: ONE call, one greeting, then stop. Not a loop.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import math
import os
import socket
import struct
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import uvicorn
import websockets

from decana.bridge.codec import mulaw_decode, mulaw_encode
from decana.gemini.live import open_live_session
from decana.profile.load import load_profile
from decana.twilio.records import CallRecord
from decana.twilio.server import create_app

CALL_SID = "CAsmoke000000000000000000000000001"
STREAM_SID = "MZsmoke000000000000000000000000001"
CALLER = "+447700900123"

FRAME_BYTES = 160  # 20 ms of 8 kHz mu-law -- the real Twilio frame size
FRAME_INTERVAL_S = 0.02
CALLER_FRAMES = 100

# Both anchored in the artifact, not chosen here: S2 measured first greeting
# audio at 3229 ms (3.5-4.0 s across runs), so 20 s is ~5x the observed worst
# case; the outbound soxr burst interval measured ~61 ms, so a 2 s quiet gap is
# ~33x that. A too-short window is a false negative in the >=1-frame assertion.
OUTBOUND_CAP_S = 20.0
OUTBOUND_QUIET_S = 2.0

# Measured floor, not a guess. Round-tripping this repo's own codec: digital
# silence -> 0.00, ~-60 dBFS line noise -> 0.001044, ~-18 dBFS speech ->
# 0.044264. mu-law maps digital zero to exactly zero, so the failure this
# guards (a path emitting silence) has a hard floor of 0.00.
MIN_RMS_FRACTION = 0.005
FULL_SCALE = 32768.0


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


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _caller_frames() -> list[str]:
    """`CALLER_FRAMES` base64 mu-law frames in Twilio's exact wire shape."""
    samples_per_frame = FRAME_BYTES
    frames: list[str] = []
    phase = 0.0
    for index in range(CALLER_FRAMES):
        pcm = bytearray()
        # Two speech-band tones with an envelope: real mu-law, real amplitude,
        # so the inbound codec and resampler do real work rather than
        # round-tripping zeros.
        for _ in range(samples_per_frame):
            envelope = 0.35 * (1.0 + math.sin(index / 8.0))
            value = envelope * (
                0.6 * math.sin(phase * 320.0) + 0.4 * math.sin(phase * 780.0)
            )
            pcm += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 12000))
            phase += 2.0 * math.pi / 8000.0
        frames.append(base64.b64encode(mulaw_encode(bytes(pcm))).decode("ascii"))
    return frames


def _parse_twiml(body: str) -> tuple[str, str]:
    """Extract the spoken disclosure and the stream URL from the answer TwiML."""
    root = ET.fromstring(body)
    say = root.find("Say")
    stream = root.find("Connect/Stream")
    if say is None or stream is None:
        raise AssertionError(f"TwiML missing Say or Connect/Stream: {body!r}")
    return say.text or "", stream.get("url") or ""


async def _send_caller_audio(ws: Any, frames: list[str]) -> None:
    """Push frames at Twilio's real 20 ms cadence, not as fast as possible."""
    for payload in frames:
        await ws.send(
            json.dumps(
                {
                    "event": "media",
                    "streamSid": STREAM_SID,
                    "media": {"payload": payload},
                }
            )
        )
        await asyncio.sleep(FRAME_INTERVAL_S)


async def _read_outbound(ws: Any) -> tuple[list[dict[str, Any]], float | None]:
    """Collect outbound frames until the greeting goes quiet, or the cap."""
    frames: list[dict[str, Any]] = []
    first_at: float | None = None
    started = time.monotonic()
    while time.monotonic() - started < OUTBOUND_CAP_S:
        remaining = OUTBOUND_CAP_S - (time.monotonic() - started)
        timeout = min(OUTBOUND_QUIET_S, remaining) if frames else remaining
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        except TimeoutError:
            if frames:
                return frames, first_at  # >=1 frame and a quiet gap: done
            break
        if first_at is None:
            first_at = time.monotonic()
        frames.append(json.loads(raw))
    return frames, first_at


def _rms_fraction(frames: list[dict[str, Any]]) -> float:
    """RMS of the outbound audio, as a fraction of int16 full scale."""
    pcm = bytearray()
    for frame in frames:
        payload = frame.get("media", {}).get("payload", "")
        if payload:
            pcm += mulaw_decode(base64.b64decode(payload))
    if not pcm:
        return 0.0
    samples = struct.unpack(f"<{len(pcm) // 2}h", bytes(pcm[: len(pcm) // 2 * 2]))
    return math.sqrt(sum(float(s) * s for s in samples) / len(samples)) / FULL_SCALE


def _timing_events(path: Path) -> list[str]:
    return [json.loads(line)["event"] for line in path.read_text().splitlines() if line]


def _check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{f' -- {detail}' if detail else ''}")
    return ok


async def main() -> int:
    """Flow: serve -> webhook -> socket -> audio -> stop -> check."""
    load_env()
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("GEMINI_API_KEY is not set (checked env and .env)", file=sys.stderr)
        return 2

    profile = load_profile("mortgage-broker", root=Path("profiles").resolve())
    artifact_dir = Path(tempfile.mkdtemp(prefix="decana-smoke-"))
    records: list[CallRecord] = []

    async def _capture(record: CallRecord) -> None:
        records.append(record)

    port = _free_port()
    app = create_app(
        profile,
        partial(open_live_session, api_key=api_key),
        _capture,
        public_wss_url=f"ws://127.0.0.1:{port}",
        artifact_dir=artifact_dir,
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)

    print(f"serving on 127.0.0.1:{port}; artifacts in {artifact_dir}")
    ok = True
    try:
        webhook_started = time.monotonic()
        async with httpx.AsyncClient(timeout=30.0) as http:
            response = await http.post(
                f"http://127.0.0.1:{port}/voice",
                data={"CallSid": CALL_SID, "From": CALLER},
            )
        disclosure, stream_url = _parse_twiml(response.text)
        webhook_ms = (time.monotonic() - webhook_started) * 1000.0
        print(f"webhook answered in {webhook_ms:.0f} ms; stream url {stream_url}")

        ok &= _check(
            "TwiML parsed and Say carries the disclosure",
            disclosure == profile.disclosure,
        )

        async with websockets.connect(stream_url) as ws:
            await ws.send(
                json.dumps(
                    {"event": "connected", "protocol": "Call", "version": "1.0.0"}
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "event": "start",
                        "streamSid": STREAM_SID,
                        "start": {
                            "callSid": CALL_SID,
                            "streamSid": STREAM_SID,
                            "customParameters": {"caller": CALLER},
                        },
                    }
                )
            )
            start_at = time.monotonic()
            audio = asyncio.create_task(_send_caller_audio(ws, _caller_frames()))
            frames, first_at = await _read_outbound(ws)
            audio.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await audio
            await ws.send(json.dumps({"event": "stop", "streamSid": STREAM_SID}))

        deadline = time.monotonic() + 30.0
        while not records and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

        rms = _rms_fraction(frames)
        ok &= _check(
            ">=1 outbound media frame arrived", bool(frames), f"{len(frames)} frames"
        )
        ok &= _check(
            "every frame carries the root streamSid from start",
            all(f.get("streamSid") == STREAM_SID for f in frames),
        )
        ok &= _check(
            "outbound audio is non-silent",
            rms >= MIN_RMS_FRACTION,
            f"RMS {rms:.6f} of full scale (floor {MIN_RMS_FRACTION})",
        )

        timing_path = artifact_dir / f"{CALL_SID}.jsonl"
        events = _timing_events(timing_path) if timing_path.is_file() else []
        ok &= _check("timing JSONL contains call_answered", "call_answered" in events)
        ok &= _check(
            "timing JSONL contains >=1 chunk_forwarded_to_twilio",
            events.count("chunk_forwarded_to_twilio") >= 1,
            f"{events.count('chunk_forwarded_to_twilio')} of {len(events)}",
        )

        ok &= _check("on_call_end fired exactly once", len(records) == 1)
        if records:
            record = records[0]
            ok &= _check(
                "transcript is non-empty",
                bool(record.transcript),
                f"{len(record.transcript)} turns",
            )
            ok &= _check(
                "ended_reason is twilio_stop",
                record.ended_reason == "twilio_stop",
                record.ended_reason,
            )
            print("\ntranscript:")
            for turn in record.transcript:
                print(f"  {turn.role.upper():6s} {turn.text.strip()[:100]}")

        # Recorded, NOT gated: the ratified A3 threshold is measured on a real
        # PSTN call with the disclosure playing, so asserting a local proxy
        # against it would invent a threshold the feature never ratified.
        if first_at is not None:
            print(
                f"\nRECORDED (not gated): start -> first outbound frame = "
                f"{(first_at - start_at) * 1000.0:.0f} ms"
            )
    finally:
        server.should_exit = True
        await serving

    print(f"\n{'SMOKE PASSED' if ok else 'SMOKE FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
