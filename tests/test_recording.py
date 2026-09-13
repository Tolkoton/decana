"""Audio recording of every call -- owner request, 2026-09-13.

WHY this exists: the owner heard two voices (a woman and a man) on one softphone
call, and nothing in the pipeline had captured the audio. The transcript records
what the model SAID, not how it sounded. Without audio a voice defect is a
memory, not evidence; with it the next occurrence is a file that can be listened
to and attached to a bug report.

These tests are not traced to a ratified behavior id: the request arrived after
S3 was ratified and was built as a standalone addition rather than an amendment
to the slice contract. Their docstrings deliberately do not open with an id so
`scripts/check_ids.py` neither counts them as ratified nor flags them as drift.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path

import pytest

from decana.bridge.codec import mulaw_decode
from decana.bridge.recording import CallRecorder

# Hostile bytes, same rationale as Seam 4's RAW_FRAME: the extremes and the
# sign-bit straddle expose a decoder that mangles or drops high codes.
CALLER_BYTES = bytes([0xFF, 0x7F, 0x00, 0x80, 0x01, 0xFE, 0x10, 0xEF])
MODEL_BYTES = bytes([0x00, 0xFF, 0x80, 0x7F])


def _read_wav(path: Path) -> tuple[int, int, int, bytes]:
    with wave.open(str(path), "rb") as wav:
        return (
            wav.getnchannels(),
            wav.getsampwidth(),
            wav.getframerate(),
            wav.readframes(wav.getnframes()),
        )


def test_recorder_writes_both_legs_as_8k_mono_pcm16_wav(tmp_path: Path) -> None:
    """Owner request 2026-09-13 -- close() writes caller and model WAVs, 8 kHz mono PCM16.

    The PCM in each file equals mulaw_decode of the bytes the leg received, in
    order, across multiple pushes. Compared exactly: decode is pure and this is
    the same codec on the same bytes, so there is no tolerance to apply.
    """
    recorder = CallRecorder(
        caller_path=tmp_path / "CA1.caller.wav",
        model_path=tmp_path / "CA1.model.wav",
    )
    recorder.caller(CALLER_BYTES[:3])
    recorder.model(MODEL_BYTES[:1])
    recorder.caller(CALLER_BYTES[3:])
    recorder.model(MODEL_BYTES[1:])

    recorder.close()

    assert _read_wav(tmp_path / "CA1.caller.wav") == (
        1,
        2,
        8000,
        mulaw_decode(CALLER_BYTES),
    )
    assert _read_wav(tmp_path / "CA1.model.wav") == (
        1,
        2,
        8000,
        mulaw_decode(MODEL_BYTES),
    )


def test_recorder_writes_nothing_before_close(tmp_path: Path) -> None:
    """Owner request 2026-09-13 -- audio is buffered; no file exists until close().

    Load-bearing on Cloud Run: the recording directory is the Cloud Storage FUSE
    mount, where every append rewrites the object and a per-frame write is the
    exact 429 storm that broke revision 00004. One write per leg per call.
    """
    recorder = CallRecorder(
        caller_path=tmp_path / "CA2.caller.wav",
        model_path=tmp_path / "CA2.model.wav",
    )
    recorder.caller(CALLER_BYTES)
    recorder.model(MODEL_BYTES)

    assert not (tmp_path / "CA2.caller.wav").exists()
    assert not (tmp_path / "CA2.model.wav").exists()


def test_recorder_writes_a_valid_empty_wav_for_a_silent_leg(tmp_path: Path) -> None:
    """Owner request 2026-09-13 -- a leg that carried no audio still gets a file.

    An empty file that exists says "the leg was recorded and carried nothing";
    a missing file would be indistinguishable from recording being switched
    off. The distinction is the whole diagnostic value on a dead-air call.
    """
    recorder = CallRecorder(
        caller_path=tmp_path / "CA3.caller.wav",
        model_path=tmp_path / "CA3.model.wav",
    )
    recorder.caller(CALLER_BYTES)

    recorder.close()

    assert _read_wav(tmp_path / "CA3.model.wav") == (1, 2, 8000, b"")


def test_recorder_close_logs_and_swallows_an_unwritable_directory(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Owner request 2026-09-13 -- a failed write is logged, never raised.

    close() runs inside `BridgeSession.close()`, which the server wraps so a
    raise becomes the call's ending reason (S3-Q9). A recording failure must
    not relabel a real call as an error: the transcript, analysis and brief are
    worth more than the audio, and they are delivered after this returns.
    """
    missing = tmp_path / "no-such-dir"
    recorder = CallRecorder(
        caller_path=missing / "CA4.caller.wav",
        model_path=missing / "CA4.model.wav",
    )
    recorder.caller(CALLER_BYTES)

    with caplog.at_level(logging.ERROR, logger="decana.bridge.recording"):
        recorder.close()

    assert not missing.exists()
    assert any("CA4.caller.wav" in r.getMessage() for r in caplog.records)
