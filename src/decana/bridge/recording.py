"""Per-call audio recording: what the caller sent, and what the caller heard.

Owner request, 2026-09-13. The owner heard two voices on one softphone call and
nothing had captured the audio: the transcript records what the model said, not
how it sounded. This turns the next such call into two files that can be played.

Two mono files rather than one stereo file, deliberately. The model leg is sent
to Twilio FASTER than real time (a whole greeting arrives in ~50 ms of bursts,
see any `.jsonl`), so aligning the two legs by sample count would place the
model's words seconds before the caller actually heard them. Two files make no
timing claim; the JSONL already carries the timing.

Both legs are kept as the mu-law bytes that actually crossed the Twilio socket
-- the caller's frames as decoded from base64, the model's chunks as encoded for
Twilio -- so the model file IS what reached the caller's ear, codec loss and
all. They are decoded to PCM16 only at close(), through a 256-entry table built
from the codec itself, so a ten-minute call decodes in milliseconds rather than
through the codec's per-sample Python loop.

Buffered in memory and written ONCE per leg at close(). Load-bearing on Cloud
Run: the recording directory is the Cloud Storage FUSE mount, where every
append rewrites the object -- a per-frame write is exactly the 429 storm that
broke revision 00004 (`docs/deploy.md`). Memory cost is 8 kB/s per leg.

What this module does NOT do: create directories (the server owns the
directory), decide file names (the server names files by CallSid), or raise on a
failed write -- see `close()`.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path

import numpy as np

from decana.bridge.codec import mulaw_decode
from decana.bridge.resampler import TWILIO_RATE_HZ

logger = logging.getLogger(__name__)

# One row per mu-law code, produced by the codec so the two can never disagree.
_MULAW_TABLE = np.frombuffer(mulaw_decode(bytes(range(256))), dtype="<i2")


def _mulaw_to_pcm16(mulaw: bytes) -> bytes:
    """Vectorised G.711 decode; byte-identical to `mulaw_decode` on the same input."""
    if not mulaw:
        return b""
    codes = np.frombuffer(mulaw, dtype=np.uint8)
    return _MULAW_TABLE[codes].tobytes()


class CallRecorder:
    """Buffers each leg's mu-law bytes; writes two 8 kHz mono PCM16 WAVs on close."""

    def __init__(self, *, caller_path: Path, model_path: Path) -> None:
        self._caller_path = caller_path
        self._model_path = model_path
        self._caller = bytearray()
        self._model = bytearray()

    def caller(self, mulaw: bytes) -> None:
        """Caller -> AI leg: the mu-law bytes decoded from one Twilio frame."""
        self._caller += mulaw

    def model(self, mulaw: bytes) -> None:
        """AI -> caller leg: the mu-law bytes encoded for one Twilio chunk."""
        self._model += mulaw

    def close(self) -> None:
        """Write both legs. A leg that carried nothing still gets a valid empty file.

        A failed write is logged and swallowed, never raised: this runs inside
        `BridgeSession.close()`, which the server wraps so that a raise becomes
        the call's ending reason (S3-Q9). A recording failure must not relabel a
        real call as an error -- the transcript, analysis and brief are worth
        more than the audio and are delivered after this returns.
        """
        self._write(self._caller_path, bytes(self._caller))
        self._write(self._model_path, bytes(self._model))

    @staticmethod
    def _write(path: Path, mulaw: bytes) -> None:
        try:
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(TWILIO_RATE_HZ)
                wav.writeframes(_mulaw_to_pcm16(mulaw))
        except OSError:
            logger.exception("could not write call recording %s", path)


__all__ = ["CallRecorder"]
