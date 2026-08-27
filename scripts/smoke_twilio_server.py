"""Real-environment smoke for the Twilio leg: everything real except Twilio.

WHAT IS REAL: the real `create_app`, the real `open_live_session` against the live
Gemini API, a real uvicorn server, a real HTTP webhook POST, and a real WebSocket
client. Only Twilio is simulated -- which is precisely the leg that is blocked on
provisioning, and precisely the leg the tracer (feature step 4) exists to prove.

WHY that split is the right one: this is the first end-to-end evidence for
`PR-bridgesession-composes-with-async-io`, the premise whose falsification
re-opens the bridge slice's ratified 16-behavior contract under Article 8.
Mocking any of it would prove the server calls a mock.

NO HUMAN ORACLE: every assertion is machine-checkable, so this runs to completion
and its output goes in the transcript rather than stopping for a human to verify.

Usage:  uv run python scripts/smoke_twilio_server.py
Needs:  GEMINI_API_KEY in the process environment.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import numpy as np
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _budget import Budget

from decana.bridge.codec import mulaw_decode, mulaw_encode

PORT = 8942
CALL_SID = "CAsmoke0000000000000000000000001"
STREAM_SID = "MZsmoke000000000000000000000001"
# Measured, not chosen: digital silence round-trips to exactly 0.00 through this
# repo's mu-law codec, a -60 dBFS line-noise floor measures 0.001044 of full
# scale, and speech level measures 0.044264. 0.005 sits ~5x above the noise floor
# and ~9x below speech.
MIN_RMS_FRACTION = 0.005
# Anchored to S2's measured first-audio latency (3229 ms; 3.5-4.0 s across runs):
# a 20 s cap is ~5x the observed worst case, and the 2 s quiet gap is ~33x the
# ~61 ms soxr outbound burst interval. A too-short window is a false negative in
# this script's own >=1-frame assertion.
READ_CAP_S = 20.0
QUIET_GAP_S = 2.0


def _frames_of_silence(count: int) -> list[str]:
    """`count` Twilio-shaped 20ms mu-law frames, base64 encoded."""
    pcm = np.zeros(160, dtype=np.int16).tobytes()
    payload = base64.b64encode(mulaw_encode(pcm)).decode()
    return [payload] * count


async def _run(artifact_dir: Path) -> int:
    url = f"ws://127.0.0.1:{PORT}/media"

    async with websockets.connect(url) as ws:
        await ws.send(
            json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        )
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "streamSid": STREAM_SID,
                    "start": {
                        "callSid": CALL_SID,
                        "streamSid": STREAM_SID,
                        "customParameters": {"caller": "+447700900123"},
                    },
                }
            )
        )

        started = time.monotonic()
        first_frame_at: float | None = None
        payloads: list[str] = []
        last_seen = time.monotonic()

        async def pump_silence() -> None:
            """Feed 20ms frames as Twilio would, so the bridge has real input."""
            for payload in _frames_of_silence(200):
                await ws.send(
                    json.dumps(
                        {
                            "event": "media",
                            "streamSid": STREAM_SID,
                            "media": {"payload": payload},
                        }
                    )
                )
                await asyncio.sleep(0.02)

        pump = asyncio.create_task(pump_silence())
        try:
            while time.monotonic() - started < READ_CAP_S:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                except TimeoutError:
                    if payloads and time.monotonic() - last_seen > QUIET_GAP_S:
                        break
                    continue
                message = json.loads(raw)
                if message.get("event") != "media":
                    continue
                if first_frame_at is None:
                    first_frame_at = time.monotonic() - started
                assert message.get("streamSid") == STREAM_SID, (
                    f"outbound frame missing root streamSid: {message!r}"
                )
                payloads.append(message["media"]["payload"])
                last_seen = time.monotonic()
        finally:
            pump.cancel()

        await ws.send(json.dumps({"event": "stop", "streamSid": STREAM_SID}))

    print(f"  outbound frames        : {len(payloads)}")
    print(
        f"  time to first frame    : {first_frame_at:.2f}s"
        if first_frame_at
        else "  no frames"
    )

    failures: list[str] = []
    if not payloads:
        failures.append(
            "no outbound media frame arrived -- the greeting never reached the socket"
        )
    else:
        decoded = b"".join(mulaw_decode(base64.b64decode(p)) for p in payloads)
        samples = np.frombuffer(decoded, dtype=np.int16).astype(np.float64)
        rms = float(np.sqrt((samples * samples).mean())) / 32768
        print(
            f"  outbound RMS           : {rms:.6f} of full scale (floor {MIN_RMS_FRACTION})"
        )
        if rms < MIN_RMS_FRACTION:
            failures.append(f"outbound audio is effectively silent: RMS {rms:.6f}")

    log = artifact_dir / f"{CALL_SID}.jsonl"
    if not log.exists():
        failures.append(f"no timing log at {log}")
    else:
        events = [json.loads(line)["event"] for line in log.read_text().splitlines()]
        print(f"  timing events          : {len(events)} ({sorted(set(events))})")
        if "call_answered" not in events:
            failures.append("timing log has no call_answered")
        if events.count("chunk_forwarded_to_twilio") < 1:
            failures.append("timing log has no chunk_forwarded_to_twilio")

    print()
    if failures:
        for line in failures:
            print(f"  FAIL: {line}")
        return 1
    print("  PASS: every assertion held.")
    if first_frame_at is not None:
        print(
            f"  RECORDED, not gated: time to first outbound frame = {first_frame_at:.2f}s.\n"
            "  This predicts whether the tracer meets A3, but A3 is measured on a real\n"
            "  PSTN call with the disclosure playing, so asserting a local proxy against\n"
            "  its threshold would be inventing a threshold the feature never ratified."
        )
    return 0


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("PARKED: GEMINI_API_KEY is not in the environment. Nothing was called.")
        return 3

    budget = Budget(Path(".claude/overseer/.api-budget.json"))
    if not budget.try_spend("smoke_twilio_server"):
        print(
            f"PARKED: real-API budget exhausted (limit {budget.limit}/day). Nothing was called."
        )
        return 3
    print(f"budget: {budget.remaining()} real-API calls left today")

    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        env = {
            **os.environ,
            "DECANA_PROFILE": "mortgage-broker",
            "PUBLIC_WSS_URL": f"ws://127.0.0.1:{PORT}",
            "DECANA_ARTIFACT_DIR": str(artifact_dir),
            "PORT": str(PORT),
        }
        proc = subprocess.Popen(
            [sys.executable, "-m", "decana"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    print(f"FAIL: decana exited early:\n{proc.communicate()[0]}")
                    return 1
                try:
                    httpx.get(f"http://127.0.0.1:{PORT}/voice", timeout=1)
                    break
                except httpx.HTTPError:
                    time.sleep(0.3)
            else:
                print("FAIL: decana never came up")
                return 1

            response = httpx.post(
                f"http://127.0.0.1:{PORT}/voice",
                data={"CallSid": CALL_SID, "From": "+447700900123"},
                timeout=30,
            )
            print(f"  POST /voice            : {response.status_code}")
            if "<Connect>" not in response.text:
                print(f"FAIL: the webhook did not open a stream:\n{response.text}")
                return 1

            return asyncio.run(_run(artifact_dir))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    print("=== smoke: twilio-server (real Gemini, simulated Twilio) ===")
    raise SystemExit(main())
