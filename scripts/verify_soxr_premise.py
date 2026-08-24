"""Runtime verification of premise PR-soxr-streaming-api.

Until this script was run, the premise rested only on reading soxr's docs and
GitHub source. Slice `voice-intake-demo` Seam 2 assumes four things about the
installed library; this script checks each against the real package and prints
a per-claim verdict.

Claims under test (from the slice's Q1 and Seam 2):
  C1. `soxr.ResampleStream`'s third constructor parameter is `num_channels`
      (not `channels`), and it accepts `dtype='int16'`.
  C2. `.resample_chunk(x, last=False)` exists with that call shape.
  C3. With `dtype='int16'` the output is already int16 -- no separate cast.
  C4. One instance retains filter history across `.resample_chunk()` calls, so
      feeding real-sized Twilio frames sequentially through a SINGLE instance
      closely reproduces a whole-array resample, while a FRESH instance per
      chunk does not.

C4 is the load-bearing one: it is the difference between the streaming design
the seam ratified and the stateless bug found and fixed during planning.

This script is a premise probe, not a test and not part of the slice's exit
criterion. It does NOT verify latency, Twilio, or Gemini.
"""

from __future__ import annotations

import inspect
import math

import numpy as np
import soxr

TWILIO_FRAME_SAMPLES = 160  # 20ms at 8kHz, the real inbound frame size
TONE_HZ = 440.0


def _make_tone(sample_rate: int, samples: int) -> np.ndarray:
    """Build a continuous int16 sine tone -- discontinuities must come from the
    resampler under test, never from the input signal."""
    t = np.arange(samples, dtype=np.float64) / sample_rate
    return (np.sin(2 * math.pi * TONE_HZ * t) * 20000).astype(np.int16)


def _chunks(x: np.ndarray, size: int) -> list[np.ndarray]:
    return [x[i : i + size] for i in range(0, len(x), size)]


def _stream_through_one_instance(
    tone: np.ndarray, in_rate: int, out_rate: int, chunk: int
) -> np.ndarray:
    """The ratified pattern: construct once, reuse across every chunk."""
    stream = soxr.ResampleStream(in_rate, out_rate, 1, dtype="int16")
    out = [stream.resample_chunk(c) for c in _chunks(tone, chunk)]
    return np.concatenate(out)


def _stream_through_fresh_instances(
    tone: np.ndarray, in_rate: int, out_rate: int, chunk: int
) -> np.ndarray:
    """The stateless bug: a new instance per chunk, no cross-chunk history."""
    out = []
    for c in _chunks(tone, chunk):
        stream = soxr.ResampleStream(in_rate, out_rate, 1, dtype="int16")
        out.append(stream.resample_chunk(c))
    return np.concatenate(out)


def _rms_error(a: np.ndarray, b: np.ndarray) -> float:
    """RMS difference over the overlapping span, as a fraction of full scale."""
    n = min(len(a), len(b))
    if n == 0:
        return float("inf")
    diff = a[:n].astype(np.float64) - b[:n].astype(np.float64)
    return float(np.sqrt(np.mean(diff**2)) / 32768.0)


def check_constructor_signature() -> None:
    print("--- C1: constructor signature ---")
    try:
        sig = inspect.signature(soxr.ResampleStream.__init__)
        print(f"  ResampleStream.__init__{sig}")
        names = list(sig.parameters)
        print(f"  parameter names: {names}")
        print(f"  'num_channels' present: {'num_channels' in names}")
        print(f"  'channels' present:     {'channels' in names}")
    except (ValueError, TypeError) as exc:
        print(f"  signature not introspectable ({exc}); probing by call instead")

    for kwargs in ({"num_channels": 1}, {"channels": 1}):
        key = next(iter(kwargs))
        try:
            soxr.ResampleStream(8000, 16000, dtype="int16", **kwargs)
            print(f"  keyword '{key}=1' accepted: True")
        except TypeError as exc:
            print(f"  keyword '{key}=1' accepted: False ({exc})")

    soxr.ResampleStream(8000, 16000, 1, dtype="int16")
    print("  positional (8000, 16000, 1, dtype='int16') accepted: True")


def check_resample_chunk_signature() -> None:
    print("--- C2: resample_chunk signature ---")
    try:
        sig = inspect.signature(soxr.ResampleStream.resample_chunk)
        print(f"  resample_chunk{sig}")
    except (ValueError, TypeError) as exc:
        print(f"  signature not introspectable ({exc})")
    stream = soxr.ResampleStream(8000, 16000, 1, dtype="int16")
    probe = _make_tone(8000, TWILIO_FRAME_SAMPLES)
    print(f"  resample_chunk(x) ok:            {stream.resample_chunk(probe).shape}")
    print(
        f"  resample_chunk(x, last=True) ok: {stream.resample_chunk(probe, last=True).shape}"
    )


def check_output_dtype() -> None:
    print("--- C3: output dtype with dtype='int16' ---")
    stream = soxr.ResampleStream(8000, 16000, 1, dtype="int16")
    out = stream.resample_chunk(_make_tone(8000, TWILIO_FRAME_SAMPLES))
    print(f"  output dtype: {out.dtype} (expected int16)")
    print(f"  matches int16: {out.dtype == np.int16}")


def check_statefulness(in_rate: int, out_rate: int) -> None:
    print(f"--- C4: statefulness across chunks, {in_rate} -> {out_rate} ---")
    tone = _make_tone(in_rate, in_rate)  # one second
    chunk = TWILIO_FRAME_SAMPLES if in_rate == 8000 else TWILIO_FRAME_SAMPLES * 3

    reference = soxr.resample(tone, in_rate, out_rate).astype(np.int16)
    stateful = _stream_through_one_instance(tone, in_rate, out_rate, chunk)
    stateless = _stream_through_fresh_instances(tone, in_rate, out_rate, chunk)

    err_stateful = _rms_error(stateful, reference)
    err_stateless = _rms_error(stateless, reference)

    print(f"  chunk size: {chunk} samples; {len(_chunks(tone, chunk))} chunks")
    print(
        f"  lengths -- reference {len(reference)}, "
        f"one-instance {len(stateful)}, fresh-per-chunk {len(stateless)}"
    )
    print("  RMS error vs whole-array reference:")
    print(f"    one instance reused (ratified pattern): {err_stateful:.6f}")
    print(f"    fresh instance per chunk (the bug):     {err_stateless:.6f}")
    if err_stateful < err_stateless:
        ratio = err_stateless / err_stateful if err_stateful else float("inf")
        print(f"  -> reuse is {ratio:.1f}x closer to the reference. State is retained.")
    else:
        print("  -> NO measurable benefit from reuse. Premise looks FALSIFIED.")


def main() -> None:
    print(f"soxr version: {soxr.__version__}")
    print(f"numpy version: {np.__version__}\n")
    check_constructor_signature()
    print()
    check_resample_chunk_signature()
    print()
    check_output_dtype()
    print()
    check_statefulness(8000, 16000)
    print()
    check_statefulness(24000, 8000)


if __name__ == "__main__":
    main()
