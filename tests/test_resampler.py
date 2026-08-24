"""Seam 2 -- streaming resampler statefulness across chunk boundaries.

This is the seam that drove most of the slice's design iteration, and the one
amended after a runtime probe falsified PR-resampler-emits-per-chunk. The
amendment requires three things to be asserted behaviours rather than comments:

  (a) an empty push() return is expected and legal
  (b) streamed output plus the last=True flush loses nothing
  (c) a fresh instance per chunk yields silence -- and silence plus Q9's
      suppressed events is indistinguishable from a healthy idle line by the
      timing artifact alone, so this test is the only thing that catches it

Chunk sizes are the real ones: 160 samples is a 20ms Twilio frame at 8kHz;
480 samples is 20ms at Gemini's 24kHz output rate.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import soxr

from decana.bridge.codec import AudioFrameError
from decana.bridge.resampler import Resampler, outbound_resampler

TONE_HZ = 440.0

# (in_rate, out_rate, chunk_samples) for the two directions the bridge uses.
DIRECTIONS = [
    pytest.param(8000, 16000, 160, id="inbound-8k-to-16k"),
    pytest.param(24000, 8000, 480, id="outbound-24k-to-8k"),
]

# Critic note 4 asks the implementer to pick a concrete tolerance, since soxr
# publishes no numeric guarantee. Measured error for the correct pattern is
# ~2.2e-5 of full scale; 1e-3 leaves two orders of magnitude of headroom while
# staying far below audibility. A stateless implementation emits silence, whose
# error against a full-amplitude tone is ~0.43 -- it fails this by ~400x, so the
# threshold discriminates by orders of magnitude, not by a hair.
MAX_RMS_ERROR = 1e-3


def _tone(sample_rate: int, samples: int) -> np.ndarray:
    """A continuous int16 sine -- any discontinuity must come from the resampler."""
    t = np.arange(samples, dtype=np.float64) / sample_rate
    return (np.sin(2 * math.pi * TONE_HZ * t) * 20000).astype(np.int16)


def _byte_chunks(tone: np.ndarray, chunk_samples: int) -> list[bytes]:
    raw = tone.tobytes()
    step = chunk_samples * 2
    return [raw[i : i + step] for i in range(0, len(raw), step)]


def _rms_error(actual: np.ndarray, expected: np.ndarray) -> float:
    """RMS difference over the overlapping span, as a fraction of full scale."""
    n = min(len(actual), len(expected))
    if n == 0:
        return float("inf")
    diff = actual[:n].astype(np.float64) - expected[:n].astype(np.float64)
    return float(np.sqrt(np.mean(diff**2)) / 32768.0)


@pytest.mark.parametrize(("in_rate", "out_rate", "chunk"), DIRECTIONS)
def test_resampler_statefulness_across_chunks(
    in_rate: int, out_rate: int, chunk: int
) -> None:
    """B1: one reused instance reproduces a whole-array resample.

    Filter history must survive across push() calls; without it every chunk
    boundary introduces a discontinuity.
    """
    tone = _tone(in_rate, in_rate)
    resampler = Resampler(in_rate, out_rate)

    streamed = b"".join(resampler.push(c) for c in _byte_chunks(tone, chunk))
    streamed += resampler.push(b"", last=True)

    actual = np.frombuffer(streamed, dtype=np.int16)
    expected = soxr.resample(tone, in_rate, out_rate).astype(np.int16)
    assert _rms_error(actual, expected) < MAX_RMS_ERROR


@pytest.mark.parametrize(("in_rate", "out_rate", "chunk"), DIRECTIONS)
def test_push_returns_empty_for_some_chunks_and_audio_for_others(
    in_rate: int, out_rate: int, chunk: int
) -> None:
    """B2 (amendment a): an empty return is expected, not an error.

    Both halves matter. Only-empty would mean the resampler is dead; only-audio
    would mean the batching this assertion documents does not happen, and the
    handler's Q9 suppression branch would be unreachable.
    """
    tone = _tone(in_rate, in_rate)
    resampler = Resampler(in_rate, out_rate)

    returns = [resampler.push(c) for c in _byte_chunks(tone, chunk)]

    assert any(r == b"" for r in returns), "expected soxr to batch some chunks"
    assert any(r != b"" for r in returns), "expected audio from at least one chunk"


@pytest.mark.parametrize(("in_rate", "out_rate", "chunk"), DIRECTIONS)
def test_flush_recovers_every_stranded_sample(
    in_rate: int, out_rate: int, chunk: int
) -> None:
    """B3 (amendment b): streamed + flush loses nothing.

    Exact on sample COUNT, not bytes: streaming output is not byte-identical to
    a one-shot resample (B1 covers content, within tolerance). This is what
    proves the empty returns of B2 are batching rather than data loss.
    """
    tone = _tone(in_rate, in_rate)
    resampler = Resampler(in_rate, out_rate)

    streamed = b"".join(resampler.push(c) for c in _byte_chunks(tone, chunk))
    flushed = resampler.push(b"", last=True)

    assert flushed != b"", "flush returned nothing -- the tail was never stranded?"
    expected = soxr.resample(tone, in_rate, out_rate).astype(np.int16)
    assert (len(streamed) + len(flushed)) // 2 == len(expected)


@pytest.mark.parametrize(("in_rate", "out_rate", "chunk"), DIRECTIONS)
def test_fresh_instance_per_chunk_yields_total_silence(
    in_rate: int, out_rate: int, chunk: int
) -> None:
    """B4 (amendment c): the stateless bug produces silence, not degraded audio.

    This is the load-bearing one. A fresh instance never accumulates enough
    input to emit, so it returns empty on EVERY push -- and Q9 suppresses the
    forward and the timing event on an empty push. A bridge broken this way
    forwards nothing and writes no events, which is byte-identical in the timing
    artifact to a healthy line that nobody spoke on. Nothing downstream can tell
    those apart; this assertion is the only place the difference is visible.

    Asserting the correct pattern is non-empty in the same test is essential --
    without it, an implementation that emitted nothing at all would pass.
    """
    tone = _tone(in_rate, in_rate)
    chunks = _byte_chunks(tone, chunk)

    stateless = b"".join(Resampler(in_rate, out_rate).push(c) for c in chunks)
    assert stateless == b""

    stateful = Resampler(in_rate, out_rate)
    assert b"".join(stateful.push(c) for c in chunks) != b""


@pytest.mark.parametrize(("in_rate", "out_rate", "chunk"), DIRECTIONS)
def test_flush_accepts_empty_input(in_rate: int, out_rate: int, chunk: int) -> None:
    """B5: close() flushes by pushing empty bytes, so that must not be rejected.

    Deliberately unlike the codec, where empty input off the wire raises.
    """
    resampler = Resampler(in_rate, out_rate)
    assert resampler.push(b"", last=True) == b""


@pytest.mark.parametrize("odd_length", [1, 3, 481])
def test_push_rejects_odd_length_payload(odd_length: int) -> None:
    """B7: an odd byte count cannot be whole PCM16 samples.

    np.frombuffer raises a bare ValueError here, which would sail past
    handle_gemini_chunk's AudioFrameError catch (Q6) and end the call. That is
    a live path: inbound is safe because mulaw_decode always emits even-length
    output, but handle_gemini_chunk pushes Gemini's bytes with nothing between.
    """
    resampler = outbound_resampler()
    with pytest.raises(AudioFrameError):
        resampler.push(b"\x00" * odd_length)
