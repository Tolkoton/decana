"""Inbound gain -- owner request, 2026-09-13 ("improve the hearing a bit more").

Not traced to a ratified behavior id, like `test_recording.py`: built as a
standalone addition after the first recorded real call measured the caller at
-39 dBFS against the model's -10 dBFS, then corrected after the second showed
the +12 dB hard clip distorting loud syllables. Docstrings deliberately do not
open with an id so `scripts/check_ids.py` neither counts nor flags them.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from decana.bridge.codec import AudioFrameError
from decana.bridge.gain import PHONE_INBOUND_GAIN_DB, apply_gain, db_to_linear


def _pcm(*samples: int) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def _samples(pcm: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(pcm) // 2}h", pcm))


def test_gain_scales_small_samples_by_the_factor() -> None:
    """Owner request 2026-09-13 -- well below the limiter's knee, gain is exact."""
    assert apply_gain(_pcm(10, -20, 0, 30), 4.0) == _pcm(40, -80, 0, 120)


def test_limiter_keeps_loud_samples_inside_the_rails_and_never_wraps() -> None:
    """Owner request 2026-09-13 -- an overdriven sample is rounded, not clipped or wrapped.

    The +12 dB hard clip on revision 00017 squared off 7.6 % of a louder
    caller's frames and the transcript garbled on exactly those syllables. The
    soft limiter must (a) never reach the rails, (b) keep the sign, and (c)
    stay monotonic so louder in is still louder out.
    """
    out = _samples(apply_gain(_pcm(32000, -32000, 8192, 16384), 4.0))
    assert all(-32767 < s < 32767 for s in out)
    assert out[0] > 0 > out[1] and out[0] == -out[1]
    assert 8192 * 4 * 0.6 < out[2] < 8192 * 4  # compressed, but still lifted
    assert out[3] > out[2]  # monotonic


def test_limiter_is_transparent_below_minus_twelve_dbfs() -> None:
    """Owner request 2026-09-13 -- ordinary speech levels pass within 0.3 dB of exact.

    Pins the knee: a -12 dBFS sine after gain must come out within 0.3 dB of
    a plain multiply, so the limiter only ever touches peaks.
    """
    amplitude = 32767 * 10 ** (-12 / 20) / 2.0  # so that x2 lands at -12 dBFS
    t = np.arange(800) / 8000.0
    tone = (amplitude * np.sin(2 * np.pi * 300 * t)).astype("<i2").tobytes()
    out = np.frombuffer(apply_gain(tone, 2.0), dtype="<i2").astype(float)
    exact = np.frombuffer(tone, dtype="<i2").astype(float) * 2.0
    ratio_db = 20 * np.log10(np.sqrt(np.mean(out**2)) / np.sqrt(np.mean(exact**2)))
    assert -0.3 < ratio_db <= 0.0


def test_unity_gain_and_empty_payload_are_returned_untouched() -> None:
    """Owner request 2026-09-13 -- gain 1.0 and b"" are identity, same object."""
    frame = _pcm(1, 2, 3)
    assert apply_gain(frame, 1.0) is frame
    assert apply_gain(b"", 4.0) == b""


def test_odd_length_payload_raises_audio_frame_error() -> None:
    """Owner request 2026-09-13 -- a partial sample is the codec's fault type.

    So the bridge's single Q6 catch handles it: the frame is dropped and the
    call continues, rather than numpy raising a bare ValueError that would end
    the call (the exact defect Q12 part 2 fixed at the resampler boundary).
    """
    with pytest.raises(AudioFrameError):
        apply_gain(b"\x01\x02\x03", 2.0)


def test_production_gain_is_zero_and_the_production_path_is_a_no_op() -> None:
    """Owner request 2026-09-13 -- the shipped constant is 0 dB: identity, same object.

    Pinned as a number so a later lift is a deliberate diff, with the reason
    in `gain.py`: +12 dB and +9 dB each coincided with a worse real call
    (revisions 00017/00018) and were the only variable against the owner's
    best call. 0 dB must be byte-for-byte revision 00016's path, which is what
    `is` asserts.
    """
    assert PHONE_INBOUND_GAIN_DB == 0.0
    factor = db_to_linear(PHONE_INBOUND_GAIN_DB)
    assert factor == 1.0

    amplitude = 32768 * 10 ** (-39 / 20)  # a -39 dBFS sine, the quiet-caller level
    t = np.arange(800) / 8000.0
    tone = (amplitude * np.sin(2 * np.pi * 300 * t)).astype("<i2").tobytes()
    assert apply_gain(tone, factor) is tone
