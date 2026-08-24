"""ITU-T G.711 mu-law codec for the Twilio leg of the audio bridge.

Twilio Media Streams carry 8-bit mu-law mono at 8kHz; everything upstream of
this module works in raw PCM16LE mono. These two functions are the only place
that conversion happens.

Hand-implemented rather than taken from a library: `audioop` was removed in
Python 3.13 (PEP 594) and this project pins 3.13 (see premise
PR-audioop-unavailable and slice decision Q2). The codec is a small piece of
well-defined standard math.

What this module does NOT do: resampling (that is the soxr-backed resampler
pair), base64 framing (the BridgeSession handlers own that), timing, or any
network I/O. It is pure and stateless -- no clock, no client, no session.
"""

from __future__ import annotations

import struct

# ITU-T G.711 mu-law field layout. A mu-law byte is stored complemented; once
# inverted it is one sign bit, a 3-bit segment (exponent) and a 4-bit quantum
# (mantissa), with a constant bias folded into the magnitude.
_BIAS = 0x84
_SIGN_BIT = 0x80
_SEG_MASK = 0x70
_SEG_SHIFT = 4
_QUANT_MASK = 0x0F

# Encoding works in 14-bit space (int16 >> 2). _CLIP is the largest magnitude
# representable there; anything louder saturates to it rather than wrapping
# into a wrong segment. _SEG_UEND holds each segment's inclusive upper bound.
_CLIP = 8159
_SEG_UEND = (0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF)


class AudioFrameError(ValueError):
    """A single audio frame could not be decoded or encoded.

    Raised rather than swallowed so the caller decides the policy. The ratified
    policy (slice decision Q6) is that BridgeSession's handlers catch this at
    their top level, record a `frame_error` timing event, drop the frame, and
    continue the call -- one corrupt frame must not end a scarce test call.
    """


def _reject_empty(payload: bytes) -> None:
    """Guard: a zero-sample frame is a wire anomaly, not a legitimate no-op.

    Both directions check this. Contrast the resampler contract (Q9), where an
    empty *return* is normal soxr batching -- keeping the two distinct is what
    lets the handler tell an anomaly apart from an ordinary batching gap.
    """
    if not payload:
        raise AudioFrameError("audio frame is empty")


def reject_partial_pcm16(payload: bytes) -> None:
    """Guard: PCM16 input must be a whole number of two-byte samples.

    Public because the resampler needs the same invariant -- it is a property of
    the PCM16 representation, which this module owns, not of mu-law coding.
    Duplicating it there is how the two would drift apart.

    Not applied when decoding mu-law: one mu-law byte is one sample, so any
    non-empty length is valid in that direction.

    Checked explicitly rather than by catching struct.error, which would also
    swallow unrelated struct failures and re-label them as frame errors.
    """
    if len(payload) % 2:
        raise AudioFrameError(
            f"PCM16 payload must be a whole number of 2-byte samples, got {len(payload)}"
        )


def _decode_sample(code: int) -> int:
    """Expand one mu-law code to its signed 16-bit sample value."""
    inverted = ~code & 0xFF
    magnitude = ((inverted & _QUANT_MASK) << 3) + _BIAS
    magnitude <<= (inverted & _SEG_MASK) >> _SEG_SHIFT
    if inverted & _SIGN_BIT:
        return _BIAS - magnitude
    return magnitude - _BIAS


def mulaw_decode(payload: bytes) -> bytes:
    """Decode G.711 mu-law bytes to raw PCM16LE mono.

    One input byte yields one 16-bit sample, so output is exactly twice the
    input length.
    """
    _reject_empty(payload)
    samples = [_decode_sample(code) for code in payload]
    return struct.pack(f"<{len(samples)}h", *samples)


def _segment(magnitude: int) -> int:
    """Locate the G.711 segment holding a biased 14-bit magnitude.

    Returns len(_SEG_UEND) when the magnitude is above every segment, which the
    caller treats as the saturated code.
    """
    for index, upper_bound in enumerate(_SEG_UEND):
        if magnitude <= upper_bound:
            return index
    return len(_SEG_UEND)


def _encode_sample(sample: int) -> int:
    """Compress one signed 16-bit sample to its mu-law code."""
    # Arithmetic shift, so negative odd values floor rather than truncate
    # toward zero; `int(sample / 4)` would differ here and is wrong.
    scaled = sample >> 2
    if scaled < 0:
        magnitude = -scaled
        mask = 0x7F
    else:
        magnitude = scaled
        mask = 0xFF
    # Clip after the 14-bit shift and after taking the magnitude -- clipping
    # the raw int16 would flatten everything above roughly 2000 in PCM terms.
    magnitude = min(magnitude, _CLIP)
    magnitude += _BIAS >> 2
    segment = _segment(magnitude)
    if segment >= len(_SEG_UEND):
        return 0x7F ^ mask
    quantum = (magnitude >> (segment + 1)) & _QUANT_MASK
    return ((segment << _SEG_SHIFT) | quantum) ^ mask


def mulaw_encode(payload: bytes) -> bytes:
    """Encode raw PCM16LE mono to G.711 mu-law bytes.

    One 16-bit sample yields one output byte, so output is exactly half the
    input length.
    """
    _reject_empty(payload)
    reject_partial_pcm16(payload)
    samples = struct.unpack(f"<{len(payload) // 2}h", payload)
    return bytes(_encode_sample(sample) for sample in samples)
