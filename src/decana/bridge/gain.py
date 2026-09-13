"""Inbound gain with a soft limiter: lift quiet caller audio without clipping it.

Owner request, 2026-09-13 ("try to improve the hearing of the model a bit more").
Measured on the first recorded real call (`CA927f30…`, revision 00016): the
caller's speech sat at -39 dBFS (90th percentile of 20 ms frames), the model's
own voice at -10 dBFS, noise floor -72 dBFS. The softphone leg measured the
same (-32 to -36 dBFS). Phone audio is simply quiet, and Gemini's speech
detection and recognition are tuned for close-mic levels.

The first version was +12 dB with a HARD clip. On the next real call
(`CA0d88da…`, revision 00017) the caller spoke louder (-15 dBFS at p97) and
7.6 % of frames clipped; the garbled words in that transcript ("tenkей",
"No, no, si es") sit exactly on the loud syllables, and the owner heard it as
"slightly worse". Two corrections follow from that:

  * +9 dB, not +12: quiet callers still gain 3 dB less than before, loud
    callers stay well under full scale.
  * a tanh soft limiter instead of a hard clip: below about -12 dBFS it is
    the identity to within 0.3 dB, above it the peaks are rounded rather
    than squared off, and the 16-bit rails are unreachable by construction.

Applied AFTER the mu-law decode and BEFORE the 8k->16k resample, so the
resampler sees the final level. The call recording keeps the raw mu-law as
received, so a recording still shows what actually arrived, not the lifted
copy.

Transport-level, not profile data: it describes the phone line, not the
vertical, exactly like `_PHONE_VAD` in `decana.gemini.live`.
"""

from __future__ import annotations

import numpy as np

from decana.bridge.codec import reject_partial_pcm16

PHONE_INBOUND_GAIN_DB = 0.0
"""The lift applied to every caller frame in production. ZERO, deliberately.

Both lifts made real calls WORSE, not better (2026-09-13):
  * +12 dB hard clip, revision 00017 -- "slightly worse"; loud syllables clipped.
  * +9 dB soft limiter, revision 00018 -- "much worse, barely working": on
    `CA52d9c0…` the model took 3 turns in 35 s and sat silent for 19 s while
    caller audio flowed the whole time (raw level -47 dBFS p90).
The mechanism is NOT established: the between-word level on all three
recorded calls is digital silence (-72 dBFS), so "amplified noise fooled the
speech detection" is ruled out, and Gemini's turn-taking varies call to call
anyway. What is established is that the gain was the only variable between the
owner's best call (revision 00016) and the two worse ones, so it is backed out.
0 dB is a byte-for-byte no-op (`apply_gain` short-circuits at unity), i.e.
revision 00016's audio path. The module stays because the limiter is right if
a lift is ever tried again -- and then it should be one A/B pair of calls with
the recordings compared, not a single impression.
"""

_UNITY = 1.0
_FULL_SCALE = 32767.0


def db_to_linear(db: float) -> float:
    """Decibels to a linear amplitude factor (9 dB -> ~2.82)."""
    return float(10 ** (db / 20))


def apply_gain(pcm16: bytes, gain: float) -> bytes:
    """Scale PCM16LE mono by `gain` through a soft limiter.

    `y = FS * tanh(x * gain / FS)`: transparent for small signals, asymptotic
    to full scale for large ones, so no output sample can reach the rails and
    nothing ever wraps. Unity gain and an empty payload are returned untouched
    (same object), so the no-gain path costs nothing and cannot alter bytes.
    An odd-length payload raises `AudioFrameError` through the codec's own
    guard, so the bridge's Q6 catch handles it like any other conversion fault.
    """
    reject_partial_pcm16(pcm16)
    if gain == _UNITY or not pcm16:
        return pcm16
    samples = np.frombuffer(pcm16, dtype="<i2").astype(np.float64) * gain
    limited = _FULL_SCALE * np.tanh(samples / _FULL_SCALE)
    return np.rint(limited).astype("<i2").tobytes()


__all__ = ["PHONE_INBOUND_GAIN_DB", "apply_gain", "db_to_linear"]
