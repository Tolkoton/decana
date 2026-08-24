"""Seam 1 -- mu-law codec correctness against the ITU-T G.711 standard.

The slice exit criterion names `test_mulaw_codec_reference_table`; it is
satisfied here by the two direction-specific tests sharing that stem
(`pytest -k mulaw_codec_reference_table` selects both).

Why a hardcoded table (slice decision Q8): `audioop` was removed in Python 3.13
(PEP 594), so there is no runtime oracle on this interpreter to generate
expected values from. Deriving them from our own codec would make the test
tautological -- it would pass on an A-law implementation, which is precisely
the bug this seam exists to rule out.

THE CONSTANTS BELOW ARE LOAD-BEARING. They are the standard, transcribed. They
are not magic numbers awaiting a cleanup pass, and they must not be replaced by
anything computed at test time -- that would remove the only independent
reference point this suite has.
"""

from __future__ import annotations

import struct

import pytest

from decana.bridge.codec import AudioFrameError, mulaw_decode, mulaw_encode

# Decode direction: every mu-law code maps to exactly one PCM16 value.
# Covers both signs, both zeros, both maximum excursions, and a mid segment.
DECODE_PAIRS: list[tuple[int, int]] = [
    (0x00, -32124),  # max negative excursion
    (0x40, -1884),  # mid segment, negative
    (0x70, -120),  # small magnitude, negative
    (0x7E, -8),  # smallest non-zero step, negative
    (0x7F, 0),  # negative zero -- decodes to 0, unreachable from encode
    (0xFF, 0),  # positive zero
    (0xFE, 8),  # smallest non-zero step, positive
    (0xF0, 120),  # small magnitude, positive
    (0xC0, 1884),  # mid segment, positive
    (0x80, 32124),  # max positive excursion
]


# Encode direction. Deliberately NOT the reverse of DECODE_PAIRS:
#
#   - 0x7F is absent. It decodes to 0, but the encoder never produces it:
#     encode(0) takes the positive branch (mask 0xFF) and yields 0xFF. The
#     negative branch can only be reached when pcm >> 2 < 0, which forces a
#     magnitude of at least 1, so the all-zero quantum that would give 0x7F is
#     unreachable. The asymmetry is standard, and asserted below rather than
#     smoothed over.
#   - +-32767/-32768 are added. soxr hands the outbound path the full int16
#     range, while every value in DECODE_PAIRS sits inside +-32124. An encoder
#     missing the CLIP step (8159 in 14-bit space) overflows into the wrong
#     segment and distorts exactly the loudest samples -- inaudible to any test
#     that stays inside the decoded range.
ENCODE_PAIRS: list[tuple[int, int]] = [
    (-32768, 0x00),  # clips to the same code as -32124
    (-32124, 0x00),
    (-1884, 0x40),
    (-120, 0x70),
    (-8, 0x7E),
    (0, 0xFF),  # positive branch; NOT 0x7F
    (8, 0xFE),
    (120, 0xF0),
    (1884, 0xC0),
    (32124, 0x80),
    (32767, 0x80),  # clips to the same code as +32124
]


def _pcm16le(value: int) -> bytes:
    return struct.pack("<h", value)


@pytest.mark.parametrize(("code", "expected_pcm"), DECODE_PAIRS)
def test_mulaw_codec_reference_table_decode(code: int, expected_pcm: int) -> None:
    """B1: each reference code decodes to its standard PCM16 value."""
    assert mulaw_decode(bytes([code])) == _pcm16le(expected_pcm)


def test_mulaw_codec_reference_table_decode_length() -> None:
    """B1: one input byte yields exactly one 16-bit sample."""
    codes = bytes(code for code, _ in DECODE_PAIRS)
    expected = b"".join(_pcm16le(pcm) for _, pcm in DECODE_PAIRS)
    assert mulaw_decode(codes) == expected
    assert len(mulaw_decode(codes)) == 2 * len(codes)


@pytest.mark.parametrize(("pcm", "expected_code"), ENCODE_PAIRS)
def test_mulaw_codec_reference_table_encode(pcm: int, expected_code: int) -> None:
    """B2: each reference PCM16 value encodes to its standard mu-law code."""
    assert mulaw_encode(_pcm16le(pcm)) == bytes([expected_code])


def test_mulaw_codec_reference_table_encode_length() -> None:
    """B2: one 16-bit sample yields exactly one output byte."""
    pcm_bytes = b"".join(_pcm16le(pcm) for pcm, _ in ENCODE_PAIRS)
    expected = bytes(code for _, code in ENCODE_PAIRS)
    assert mulaw_encode(pcm_bytes) == expected
    assert len(mulaw_encode(pcm_bytes)) == len(pcm_bytes) // 2


def test_mulaw_codec_reference_table_encode_never_emits_negative_zero() -> None:
    """B2: 0x7F decodes to 0, but no PCM value encodes back to it."""
    assert mulaw_decode(bytes([0x7F])) == _pcm16le(0)
    assert mulaw_encode(_pcm16le(0)) == bytes([0xFF])


@pytest.mark.parametrize("odd_length", [1, 3, 5, 321])
def test_mulaw_encode_rejects_odd_length_payload(odd_length: int) -> None:
    """B3: PCM16 samples are two bytes; an odd length cannot be whole samples."""
    with pytest.raises(AudioFrameError):
        mulaw_encode(b"\x00" * odd_length)


def test_mulaw_decode_rejects_empty_payload() -> None:
    """B4: a zero-sample frame off the wire is an anomaly, not a silent no-op.

    Deliberately distinct from the resampler contract (Q9), where an empty
    return IS legitimate. If the codec returned b"" here, a wire anomaly would
    be indistinguishable from normal soxr batching at the handler's decision
    point. Raising keeps it visible: the ratified frame-error rule (Q6) catches
    it, records `frame_error`, drops the frame, and continues the call.
    """
    with pytest.raises(AudioFrameError):
        mulaw_decode(b"")


def test_mulaw_encode_rejects_empty_payload() -> None:
    """B5: same reasoning as B4, outbound direction."""
    with pytest.raises(AudioFrameError):
        mulaw_encode(b"")
