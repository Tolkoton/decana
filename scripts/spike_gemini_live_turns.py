"""Measure how Gemini Live signals TRANSCRIPT TURN BOUNDARIES.

The S2 seam must emit one `Transcript(role, text)` per TURN, but the spike
proved transcripts arrive as fragments (' I', ' CAN', ' HELP'). So S2 needs a
flush rule. Candidate signals, in order of preference:

  1. Transcription.finished == True        (explicit, per-direction)
  2. server_content.generation_complete    (model side only)
  3. server_content.turn_complete          (model side only)
  4. role switch (output fragment after input fragments, or vice versa)

Which of these actually arrive is a RUNTIME claim about the library, and this
project's standing rule is that such claims are measured, not reasoned about.
This prints every field that could carry a boundary, for both directions.

Phase A: greeting turn (model speaks) -> output_transcription boundaries.
Phase B: feed the model's own greeting audio back as "caller" audio, resampled
         24k -> 16k with the project's own Resampler -> input_transcription
         boundaries.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

for _line in Path(".env").read_text().splitlines():
    if "=" in _line and not _line.strip().startswith("#"):
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

from google import genai
from google.genai import types

from decana.bridge.resampler import Resampler
from decana.profile.load import load_profile

GREETING_TRIGGER = (
    "[call connected - the disclosure has been played; open the conversation]"
)


def describe(sc: types.LiveServerContent) -> dict[str, Any]:
    """Every field on LiveServerContent that could mark a boundary."""
    out: dict[str, Any] = {}
    for field in (
        "turn_complete",
        "interrupted",
        "generation_complete",
        "waiting_for_input",
        "turn_complete_reason",
    ):
        val = getattr(sc, field, None)
        if val is not None:
            out[field] = str(val)
    for name in (
        "input_transcription",
        "output_transcription",
        "interim_input_transcription",
    ):
        tr = getattr(sc, name, None)
        if tr is not None:
            out[name] = {
                "text": tr.text,
                "finished": tr.finished,
                "speaker_label": tr.speaker_label,
            }
    if sc.model_turn is not None:
        n = 0
        for part in sc.model_turn.parts or []:
            if part.inline_data is not None and part.inline_data.data:
                n += len(part.inline_data.data)
        if n:
            out["audio_bytes"] = n
    return out


async def run() -> None:
    profile = load_profile("mortgage-broker")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=profile.conversation,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    events: list[dict[str, Any]] = []
    greeting_audio = bytearray()
    t0 = time.monotonic()

    def stamp() -> int:
        return int((time.monotonic() - t0) * 1000)

    async with client.aio.live.connect(
        model=profile.live_model, config=config
    ) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=GREETING_TRIGGER)]),
            turn_complete=True,
        )

        # ---- Phase A: model greeting -------------------------------------
        print("=== PHASE A: model greeting turn ===")
        try:
            async with asyncio.timeout(45):
                async for msg in session.receive():
                    sc = msg.server_content
                    if sc is None:
                        if msg.setup_complete is not None:
                            events.append(
                                {"at": stamp(), "phase": "A", "setup_complete": True}
                            )
                        continue
                    if sc.model_turn is not None:
                        for part in sc.model_turn.parts or []:
                            if part.inline_data and part.inline_data.data:
                                greeting_audio.extend(part.inline_data.data)
                    d = describe(sc)
                    if d:
                        rec = {"at": stamp(), "phase": "A", **d}
                        events.append(rec)
                        print(json.dumps(rec)[:220])
                    if sc.turn_complete:
                        break
        except TimeoutError:
            print("  !! PHASE A timed out at 45s")

        print(f"\n  greeting audio: {len(greeting_audio)} bytes @24k")

        # ---- Phase B: feed it back as caller audio -----------------------
        print("\n=== PHASE B: caller audio (greeting resampled 24k->16k) ===")
        down = Resampler(24000, 16000)
        pcm16k = bytes(down.push(bytes(greeting_audio))) + bytes(
            down.push(b"", last=True)
        )
        print(f"  caller audio: {len(pcm16k)} bytes @16k")

        chunk = 640  # 20 ms at 16 kHz PCM16, Twilio-like pacing
        for i in range(0, len(pcm16k), chunk):
            await session.send_realtime_input(
                audio=types.Blob(
                    data=pcm16k[i : i + chunk], mime_type="audio/pcm;rate=16000"
                )
            )
            await asyncio.sleep(0.02)
        print("  ...caller audio sent, draining")

        try:
            async with asyncio.timeout(45):
                async for msg in session.receive():
                    sc = msg.server_content
                    if sc is None:
                        continue
                    d = describe(sc)
                    if d:
                        rec = {"at": stamp(), "phase": "B", **d}
                        events.append(rec)
                        print(json.dumps(rec)[:220])
        except TimeoutError:
            print("  !! PHASE B drain hit 45s (expected: stream stays open)")

    # ---- Summary ---------------------------------------------------------
    print("\n=== BOUNDARY SIGNAL SUMMARY ===")
    for direction in (
        "output_transcription",
        "input_transcription",
        "interim_input_transcription",
    ):
        frags = [e for e in events if direction in e]
        fin = [e for e in frags if e[direction].get("finished")]
        print(f"  {direction}: {len(frags)} fragments, {len(fin)} with finished=True")
    for field in (
        "turn_complete",
        "generation_complete",
        "waiting_for_input",
        "interrupted",
    ):
        hits = [e for e in events if field in e]
        print(f"  {field}: {len(hits)} occurrences")

    out = Path(".claude/artifacts/spikes/gemini-live-turn-boundaries-rerun.json")
    out.write_text(json.dumps(events, indent=1))
    print(f"\n  full event log -> {out}")


asyncio.run(run())
