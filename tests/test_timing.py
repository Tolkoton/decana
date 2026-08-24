"""Seam 3 -- TimingRecorder event-stream integrity.

The JSONL this writes is the sole evidence for the slice's exit criterion and
for PR-audio-bridge-latency, so these tests treat the FILE as the subject.
Every assertion re-reads from disk; none inspects an in-memory buffer. An
implementation that buffered until close() would pass an in-memory check and
lose the tail of a real call, which is exactly where a stall would show.

The fake clock returns a pre-scripted SEQUENCE, not a fixed value, and the
stamps are in 2001 so any real wall-clock leakage is unmistakable. The sequence
is load-bearing beyond timestamp checking: it also pins that record() calls the
clock exactly once. A second invocation would consume the next stamp and shift
every later event by one -- invisible with a constant-valued fake.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from decana.bridge.timing import TimingRecorder

# Distinguishable from any wall clock, and spaced UNEVENLY on purpose.
#
# DO NOT round these to tidy values or space them regularly. The irregularity is
# what makes a double clock call detectable: with evenly spaced stamps an
# off-by-one shift still produces a plausible-looking log, and with a
# constant-valued clock it is invisible entirely. These four values are a test
# fixture doing real work, not arbitrary numbers awaiting cleanup.
STAMPS = [
    datetime(2001, 1, 1, 12, 0, 0, tzinfo=UTC),
    datetime(2001, 1, 1, 12, 0, 0, tzinfo=UTC) + timedelta(milliseconds=137),
    datetime(2001, 1, 1, 12, 0, 0, tzinfo=UTC) + timedelta(milliseconds=1502),
    datetime(2001, 1, 1, 12, 0, 0, tzinfo=UTC) + timedelta(milliseconds=1611),
    datetime(2001, 1, 1, 12, 0, 0, tzinfo=UTC) + timedelta(milliseconds=4003),
]


def _sequence_clock(stamps: list[datetime]) -> Callable[[], datetime]:
    """A clock that hands out pre-scripted values, one per call."""
    remaining = iter(stamps)
    return lambda: next(remaining)


def _read_lines(sink: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in sink.read_text().splitlines()]


def test_timing_recorder_event_stream_integrity_line_per_call(tmp_path: Path) -> None:
    """B1: one line per call, in call order, with exact event names.

    Event names are the real ones from the Seam, including the two whose
    consecutive timestamps the exit criterion computes gaps between -- a
    generic or swapped name here would corrupt that analysis silently.
    """
    sink = tmp_path / "call1.jsonl"
    recorder = TimingRecorder(_sequence_clock(STAMPS), sink)

    recorder.record("call_answered")
    recorder.record("frame_forwarded_to_gemini")
    recorder.record("chunk_forwarded_to_twilio")
    recorder.record("chunk_forwarded_to_twilio")

    lines = _read_lines(sink)
    assert len(lines) == 4
    assert [line["event"] for line in lines] == [
        "call_answered",
        "frame_forwarded_to_gemini",
        "chunk_forwarded_to_twilio",
        "chunk_forwarded_to_twilio",
    ]


def test_timing_recorder_event_stream_integrity_timestamps(tmp_path: Path) -> None:
    """B2: each line carries the injected clock's value for that call.

    Five calls against five stamps, so a record() that invoked the clock twice
    would exhaust the sequence and raise StopIteration rather than quietly
    shifting -- and if it somehow did not, the uneven spacing means the shifted
    values could not still match.
    """
    sink = tmp_path / "call2.jsonl"
    recorder = TimingRecorder(_sequence_clock(STAMPS), sink)

    for event in (
        "call_answered",
        "frame_forwarded_to_gemini",
        "chunk_forwarded_to_twilio",
        "frame_error",
        "chunk_forwarded_to_twilio",
    ):
        recorder.record(event)

    recorded = [
        datetime.fromisoformat(str(line["timestamp"])) for line in _read_lines(sink)
    ]
    assert recorded == STAMPS


def test_timing_recorder_event_stream_integrity_detail(tmp_path: Path) -> None:
    """B3: **detail reaches the line verbatim, flat alongside event/timestamp.

    The frame_error payload is the one Seam 3 names explicitly -- it is what
    makes a Q6 dropped frame diagnosable after the fact, so silently discarding
    **detail would leave a gap in the log with no explanation beside it.
    """
    sink = tmp_path / "call3.jsonl"
    recorder = TimingRecorder(_sequence_clock(STAMPS), sink)

    recorder.record("frame_error", detail="simulated decode error")
    recorder.record("chunk_forwarded_to_twilio", sample_count=1660)

    lines = _read_lines(sink)
    assert lines[0]["detail"] == "simulated decode error"
    assert lines[1]["sample_count"] == 1660


def test_timing_recorder_event_stream_integrity_flushes_each_call(
    tmp_path: Path,
) -> None:
    """B4: every line is on disk before the next call, with no close().

    Read between calls, deliberately. A recorder that buffered and flushed on
    close() would satisfy every other test here and still lose the tail of a
    call that ended unexpectedly -- which is precisely when the log matters.
    """
    sink = tmp_path / "call4.jsonl"
    recorder = TimingRecorder(_sequence_clock(STAMPS), sink)

    recorder.record("call_answered")
    assert len(_read_lines(sink)) == 1

    recorder.record("frame_forwarded_to_gemini")
    assert len(_read_lines(sink)) == 2

    recorder.record("chunk_forwarded_to_twilio")
    assert len(_read_lines(sink)) == 3


def test_timing_recorder_creates_parent_directories(tmp_path: Path) -> None:
    """B5 (Q13): parents exist after construction, before any record().

    The real sink lives under .claude/artifacts/spikes/, absent in a fresh
    clone. Creating it lazily at first write would move the failure into the
    middle of a real PSTN call, where the log cannot be reconstructed and the
    call cannot be retried cheaply. Asserting before record() is the point.
    """
    sink = tmp_path / "artifacts" / "spikes" / "call5.jsonl"
    assert not sink.parent.exists()

    recorder = TimingRecorder(_sequence_clock(STAMPS), sink)

    assert sink.parent.is_dir()
    recorder.record("call_answered")
    assert len(_read_lines(sink)) == 1


@pytest.mark.parametrize(
    ("reserved", "expected"),
    [("event", TypeError), ("timestamp", ValueError)],
)
def test_timing_recorder_rejects_reserved_detail_keys(
    tmp_path: Path, reserved: str, expected: type[Exception]
) -> None:
    """B6 (Q14): neither reserved field can be shadowed via **detail.

    The two are rejected by different mechanisms, which is why the expected
    type is parametrized rather than assumed uniform:

      * "event" is a named positional parameter, so Python rejects the call
        with TypeError ("got multiple values for argument") before the body
        runs. It can never reach _reject_reserved_keys.
      * "timestamp" has no such protection and reaches the guard, which raises
        ValueError.

    ValueError, not AudioFrameError, on purpose: this is a defect at the call
    site, not a wire condition, so it must propagate past the handlers' Q6
    catch-drop-continue rather than be logged as a recoverable frame error.
    Letting the base dict silently win would be worse than crashing -- it
    yields a plausible-looking log that measures the wrong thing, and this file
    is the sole evidence for the exit criterion.
    """
    sink = tmp_path / "call6.jsonl"
    recorder = TimingRecorder(_sequence_clock(STAMPS), sink)

    with pytest.raises(expected):
        recorder.record("frame_error", **{reserved: "hijacked"})

    # Nothing half-written: the guard runs before the line is composed.
    assert not sink.exists() or sink.read_text() == ""
