"""Streaming sample-rate conversion for the two legs of the audio bridge.

Twilio speaks 8kHz, Gemini Live consumes 16kHz and produces 24kHz, so every
frame crosses a rate boundary in both directions. Each direction gets its own
long-lived instance, constructed once per BridgeSession and reused for every
chunk -- soxr keeps filter history inside the instance, and a fresh instance
per chunk produces silence rather than audio (see PR-resampler-emits-per-chunk
and the Seam 2 amendment).

One class covers both directions, per critic note 2: they differ only by rate.
`inbound_resampler()` and `outbound_resampler()` name the two the bridge uses.

IMPORTANT -- push() may legally return b"". soxr batches internally and emits
on its own schedule; measured against real frame sizes, 41 of 50 inbound and 34
of 50 outbound pushes return nothing. That is not an error and not data loss:
the ratified handler contract (Q9) treats an empty return as a no-op -- no
forward, no timing event -- and close() flushes the remainder at teardown (Q10).
This is deliberately the opposite of the codec's rule, where an empty *input*
off the wire is an anomaly and raises.

What this module does NOT do: mu-law coding, base64 framing, timing, network
I/O, or deciding what to do with an empty return. That last one belongs to
BridgeSession.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import soxr

from decana.bridge.codec import reject_partial_pcm16

TWILIO_RATE_HZ = 8000
GEMINI_INPUT_RATE_HZ = 16000
GEMINI_OUTPUT_RATE_HZ = 24000


class Resampler:
    """One direction of streaming rate conversion, stateful across pushes."""

    def __init__(self, in_rate: int, out_rate: int) -> None:
        # dtype is pinned to int16 rather than soxr's float32 default, so raw
        # PCM16 samples are not reinterpreted as float amplitudes. Constructed
        # once and reused: the filter history lives in this instance.
        self._stream = soxr.ResampleStream(in_rate, out_rate, 1, dtype="int16")

    def push(self, pcm16: bytes, *, last: bool = False) -> bytes:
        """Convert one chunk, returning whatever soxr chooses to emit.

        An empty return is normal. Pass `last=True` once per direction at
        session teardown to flush the buffered tail; empty input is valid on
        that call.
        """
        # Explicit, so a malformed chunk surfaces as AudioFrameError rather than
        # the bare ValueError np.frombuffer would raise -- that one would sail
        # past the handler's catch (Q6) and end the call.
        reject_partial_pcm16(pcm16)
        samples: npt.NDArray[np.int16] = np.frombuffer(pcm16, dtype=np.int16)
        converted: npt.NDArray[np.int16] = self._stream.resample_chunk(
            samples, last=last
        )
        return converted.tobytes()


def inbound_resampler() -> Resampler:
    """Twilio -> Gemini: 8kHz to 16kHz."""
    return Resampler(TWILIO_RATE_HZ, GEMINI_INPUT_RATE_HZ)


def outbound_resampler() -> Resampler:
    """Gemini -> Twilio: 24kHz to 8kHz."""
    return Resampler(GEMINI_OUTPUT_RATE_HZ, TWILIO_RATE_HZ)


__all__ = ["Resampler", "inbound_resampler", "outbound_resampler"]
