"""Seam 4 -- BridgeSession orchestration, error resilience, and teardown.

BridgeSession owns the two policies the slice contract ratified, and both are
policies about what reaches the TIMING LOG:

  * Q9 -- an empty resampler return is a no-op: no forward, no event.
  * Q6 -- an AudioFrameError is caught at the handler's top level, recorded as
    `frame_error`, the frame dropped, and the call continued.

So these tests assert against the JSONL on disk, re-read after the call, using
a real TimingRecorder and a real temp file -- the discipline Seam 3 established
and the Critic note for this seam resolved to on 2026-08-25. A spy would assert
on calls the handler made; the exit criterion is computed from the file, so the
file is the subject here too. It also keeps Q9 honest end-to-end: "no event
recorded" is checked as a line ABSENT FROM DISK, not as a method not called on
a double.

The clients are fakes rather than mocks: they record what they were handed so a
test can assert on the actual bytes crossing the seam.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from decana.bridge.codec import AudioFrameError, mulaw_decode, mulaw_encode
from decana.bridge.resampler import (
    GEMINI_OUTPUT_RATE_HZ,
    TWILIO_RATE_HZ,
    Resampler,
    inbound_resampler,
    outbound_resampler,
)
from decana.bridge.session import BridgeSession, decode_base64_frame
from decana.bridge.timing import TimingRecorder

# A payload chosen to be hostile to sloppy decoding: 0xFF and 0x00 are the two
# mu-law codes Seam 1 pins to opposite extremes, and 0x80/0x7F straddle the sign
# bit. A decoder that mangles high bytes or drops bytes fails here rather than
# passing on an all-zero fixture.
RAW_FRAME = bytes([0xFF, 0x7F, 0x00, 0x80, 0x01, 0xFE])

# Same discipline as Seam 3's fixture: stamps sit in 2001 so any wall-clock
# leakage is unmistakable, and they are spaced UNEVENLY so an extra or missing
# clock call shifts every later event into a value no test expects. Do not
# tidy these into a regular series -- the irregularity is the detector.
_EPOCH = datetime(2001, 1, 1, 12, 0, 0, tzinfo=UTC)
STAMPS = [
    _EPOCH,
    _EPOCH + timedelta(milliseconds=137),
    _EPOCH + timedelta(milliseconds=1502),
    _EPOCH + timedelta(milliseconds=1611),
    _EPOCH + timedelta(milliseconds=4003),
    _EPOCH + timedelta(milliseconds=4110),
    _EPOCH + timedelta(milliseconds=5817),
    _EPOCH + timedelta(milliseconds=6004),
]


# Same constant and same helper as Seam 2, deliberately duplicated rather than
# imported across test modules. Audio compared between two soxr instances is
# equal to within dither-scale noise, not bit-for-bit (see T1's docstring).
#
# VALID IN RAW PCM16 SPACE ONLY. Premise 6 was written before any test compared
# audio AFTER mu-law encoding, and its consequence clause named this constant
# without naming a space. It does not hold in mu-law-decoded space -- see the
# block below and the amended Premise 6.
MAX_RMS_ERROR = 1e-3

# NEVER COMPARE MU-LAW BYTES ACROSS TWO SOXR INSTANCES. There is no valid
# tolerance for it -- not an RMS bound, not a byte count -- and this is the
# measured reason, recorded so the attempt is not repeated.
#
# Mu-law AMPLIFIES soxr's cross-instance dither instead of swamping it. The
# dither is +-2 LSB (Premise 6); when a sample sits beside a mu-law quantizer
# bucket boundary that dither flips the code, and at high segments ONE code
# step is 512 LSB. So a few bytes differ by a lot rather than every byte
# differing by a little, which makes every frame-level statistic heavy-tailed.
#
# Measured 2026-08-25, 4-chunk outbound fixture, paired independent instances:
#
#     RMS, raw PCM16 space      : max 2.29e-05   (43x inside MAX_RMS_ERROR)
#     RMS, mu-law-decoded space : max 7.90e-04 over 60 pairs
#                                 -- but a live suite run hit 1.58e-03, BREACH
#     bytes differing of 490    : 0 in 999 of 1000 pairs, 4 in the other one
#                                 -- but a live suite run hit 7
#
# Both bounds were derived from large standalone samples and both were then
# exceeded inside the suite: the divergence varies with process state, so a
# threshold fitted to any sample is a guess at a tail that sample did not show.
# The first attempt here was MAX_MULAW_BYTE_DIVERGENCE = 5, falsified at 7.
#
# The fix is not a looser bound, it is not comparing across instances at all.
# G1/G4 assert mu-law bytes against the SAME instance's output (exact, no
# tolerance -- mulaw_encode and b64encode are pure), and use the independent
# reference only in raw PCM16 space, where the tolerance genuinely holds.


class RecordingResampler(Resampler):
    """A Resampler that remembers what it emitted.

    Injected by G1/G4 so the test can assert on the PCM the handler actually
    received, BEFORE mu-law encoding compresses it. That is the only space in
    which Premise 6's MAX_RMS_ERROR is valid, and there is no other way to see
    those bytes: the handler encodes and base64-frames them before they reach
    the Twilio fake, and mu-law is lossy so decoding does not recover them.

    A subclass rather than a change to the Seam: `build_harness` already
    injects both resamplers, so this needs no production code to know it
    exists.
    """

    def __init__(self, in_rate: int, out_rate: int) -> None:
        super().__init__(in_rate, out_rate)
        self.emitted: list[bytes] = []

    def push(self, pcm16: bytes, *, last: bool = False) -> bytes:
        emitted = super().push(pcm16, last=last)
        if emitted:
            self.emitted.append(emitted)
        return emitted


def _rms_error(actual: np.ndarray, expected: np.ndarray) -> float:
    """RMS difference over the overlapping span, as a fraction of full scale."""
    n = min(len(actual), len(expected))
    if n == 0:
        return float("inf")
    diff = actual[:n].astype(np.float64) - expected[:n].astype(np.float64)
    return float(np.sqrt(np.mean(diff**2)) / 32768.0)


def _sequence_clock(stamps: list[datetime]) -> Callable[[], datetime]:
    """A clock handing out pre-scripted values, one per call."""
    remaining = iter(stamps)
    return lambda: next(remaining)


class FakeTwilioClient:
    """Records the base64 mu-law strings handed to the Twilio leg."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_media(self, base64_mulaw: str) -> None:
        self.sent.append(base64_mulaw)


class FakeGeminiClient:
    """Records the PCM16 bytes handed to the Gemini leg."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send_audio(self, pcm16k: bytes) -> None:
        self.sent.append(pcm16k)


@dataclass(frozen=True)
class Harness:
    """One assembled session plus the fakes and the file to assert against."""

    session: BridgeSession
    twilio: FakeTwilioClient
    gemini: FakeGeminiClient
    sink: Path

    def lines(self) -> list[dict[str, object]]:
        """Re-read the JSONL from disk -- never an in-memory buffer.

        A missing file means no event was ever recorded, which is a legitimate
        and expected state under Q9 (an empty push forwards nothing and records
        nothing), not an error. Tests asserting "nothing was written" depend on
        this returning [] rather than raising.
        """
        if not self.sink.exists():
            return []
        return [json.loads(line) for line in self.sink.read_text().splitlines()]


def build_harness(
    tmp_path: Path,
    *,
    inbound: Resampler | None = None,
    outbound: Resampler | None = None,
) -> Harness:
    """Assemble a BridgeSession over real timing, real resamplers, fake clients.

    The resamplers are injectable so a test can hand in one that is already
    finalized -- the only honest way to make a teardown flush fail (C3).
    """
    sink = tmp_path / "call.jsonl"
    twilio = FakeTwilioClient()
    gemini = FakeGeminiClient()
    session = BridgeSession(
        twilio,
        gemini,
        TimingRecorder(_sequence_clock(STAMPS), sink),
        inbound if inbound is not None else inbound_resampler(),
        outbound if outbound is not None else outbound_resampler(),
    )
    return Harness(session=session, twilio=twilio, gemini=gemini, sink=sink)


def test_decode_base64_frame_returns_decoded_bytes() -> None:
    """D1: a valid Twilio media payload decodes to its raw bytes."""
    encoded = base64.b64encode(RAW_FRAME).decode("ascii")

    assert decode_base64_frame(encoded) == RAW_FRAME


def test_decode_base64_frame_rejects_non_alphabet_characters() -> None:
    """D2: a payload carrying non-base64 characters raises AudioFrameError.

    This is the behaviour `validate=True` buys, and it is the whole of Q15
    part 2. The permissive default does not merely tolerate the stray byte --
    it cannot SEE the corruption: it discards the character and returns bytes
    indistinguishable from an uncorrupted frame. The first assertion pins that
    danger in place, so if this test is ever weakened the reason it exists is
    still on the page.
    """
    clean = base64.b64encode(RAW_FRAME).decode("ascii")
    corrupted = clean[:4] + "!" + clean[4:]

    assert base64.b64decode(corrupted) == RAW_FRAME

    with pytest.raises(AudioFrameError):
        decode_base64_frame(corrupted)


def test_decode_base64_frame_rejects_malformed_padding() -> None:
    """D3: a truncated payload raises AudioFrameError, not bare binascii.Error.

    PASSED ON ARRIVAL -- this test never had a RED state, because D2's
    implementation had to add the binascii.Error translation to satisfy its own
    assertion, and padding failures route through that same except clause.
    Recorded here rather than quietly presented as a TDD cycle.

    It is kept, not deleted as redundant with D2, because it pins the SECOND
    entry path into that translation. The two causes report differently --
    "Only base64 data is allowed" vs "Incorrect padding" -- which is exactly
    what invites a later refactor into per-cause branches. Translate one and
    forget the other and this test goes red while D2 stays green. Same reason
    `event` stays in TimingRecorder._RESERVED_KEYS while being unreachable.
    """
    clean = base64.b64encode(RAW_FRAME).decode("ascii")

    with pytest.raises(AudioFrameError):
        decode_base64_frame(clean[:-1])


def test_start_records_call_answered_once(tmp_path: Path) -> None:
    """S1: start() writes exactly one `call_answered` line, and it is the first.

    Separate from construction on purpose (Q16). Q13 puts construction
    deliberately BEFORE the call is placed, so a `call_answered` stamped in
    __init__ would measure setup-to-dial time as answer latency. Building the
    harness and asserting the log is still empty is what pins that apart.
    """
    harness = build_harness(tmp_path)

    assert harness.lines() == []

    harness.session.start()

    assert harness.lines() == [
        {"event": "call_answered", "timestamp": STAMPS[0].isoformat()}
    ]


# One real Twilio media frame: 160 mu-law bytes == 20ms of audio at 8kHz.
TWILIO_FRAME_BYTES = 160

# MEASURED, NOT CHOSEN. This constant encodes soxr's internal batching schedule,
# so it is a fact about a third-party library, not a knob.
#
# Derivation (2026-08-25, 8kHz -> 16kHz, real 160-byte mu-law frames):
#
#     frame 1..5 -> push() returned 0 bytes
#     frame 6    -> push() returned 3320 bytes (1660 samples)
#
# matching the 1660-sample figure already recorded in PR-resampler-emits-per-chunk.
#
# Both T1 and T2 are defined RELATIVE to this number, in opposite directions:
# T1 feeds exactly this many frames because that is the fewest that produces one
# emission; T2 feeds FEWER, and "fewer than the batching threshold" is precisely
# what makes T2 a suppression test rather than a duplicate of T1.
#
# So if soxr's batching changes, T1 and T2 fail in opposite directions and
# neither failure message names the cause. It is this comment. Re-run the
# derivation above before concluding either test is wrong.
FRAMES_UNTIL_INBOUND_EMITS = 6


def twilio_frame(seed: int) -> str:
    """One realistic base64 Twilio media payload, varying with `seed`.

    The bytes vary rather than repeat so that a handler forwarding a wrong
    slice, a stale buffer, or silence fails here instead of matching a
    constant-valued fixture by accident.
    """
    raw = bytes((seed * 31 + i * 7) % 256 for i in range(TWILIO_FRAME_BYTES))
    return base64.b64encode(raw).decode("ascii")


def test_handle_twilio_frame_forwards_resampled_audio(tmp_path: Path) -> None:
    """T1: a frame whose push emits is forwarded to Gemini and recorded once.

    Six real-sized frames are fed because that is what the measured soxr
    batching requires to produce one emission; the first five are legitimately
    suppressed under Q9. So this asserts BOTH halves of the contract at the
    real cadence: exactly one forward, and exactly one line.

    The expected audio comes from an independent Resampler fed the same input.
    That deliberately does NOT re-verify resampling correctness -- Seam 2 owns
    that -- it verifies the handler forwards what the resampler returned,
    unsliced, unbuffered and not silence.

    Compared at Seam 2's RMS tolerance rather than byte-for-byte. Two soxr
    ResampleStream instances given byte-identical input do NOT produce
    byte-identical output once more than one chunk is streamed through them
    (measured 2026-08-25: 735-766 of 1660 samples differ, max 2 LSB, RMS 0.7
    LSB -- about -90 dBFS, and two orders of magnitude below the mu-law
    quantization this audio already carries). A single-chunk push IS
    reproducible, which is why this only shows up in a streamed fixture. The
    tolerance still discriminates by orders of magnitude: a wrong slice, a
    stale buffer or silence all miss by far more than 1e-3 of full scale.
    """
    harness = build_harness(tmp_path)
    payloads = [twilio_frame(seed) for seed in range(FRAMES_UNTIL_INBOUND_EMITS)]

    reference = inbound_resampler()
    expected = [
        emitted
        for payload in payloads
        if (emitted := reference.push(mulaw_decode(base64.b64decode(payload))))
    ]

    for payload in payloads:
        harness.session.handle_twilio_frame(payload)

    assert len(expected) == 1, "fixture no longer produces exactly one emission"
    assert len(harness.gemini.sent) == 1
    forwarded = np.frombuffer(harness.gemini.sent[0], dtype=np.int16)
    reference_audio = np.frombuffer(expected[0], dtype=np.int16)

    assert len(forwarded) == len(reference_audio)
    assert np.abs(forwarded).max() > 0, "forwarded silence, not audio"
    assert _rms_error(forwarded, reference_audio) < MAX_RMS_ERROR

    assert harness.lines() == [
        {
            "event": "frame_forwarded_to_gemini",
            "timestamp": STAMPS[0].isoformat(),
        }
    ]


def test_handle_twilio_frame_suppresses_empty_push(tmp_path: Path) -> None:
    """T2: a push that emits nothing forwards nothing and records nothing (Q9).

    Fed FEWER than FRAMES_UNTIL_INBOUND_EMITS frames, so every push is inside
    soxr's batching window and returns b"". Under Q9 that is a no-op, not an
    error: nothing was sent, so nothing may be claimed in the artifact the
    exit criterion is computed from.

    The absence is asserted against the FILE. `lines()` returns [] for a sink
    that was never created, so this distinguishes "no event recorded" from
    "a method was not called on a double" -- the latter is what a spy would
    have checked, and it would not notice a handler that wrote a line by some
    other route.

    PASSED ON ARRIVAL, and OVERLAPPING -- stated plainly rather than dressed
    up. T1's implementation already forced the suppression guard, so this test
    never had a RED state. Unlike D3, no mutation was found that this catches
    and T1 does not: three mutations of the Q9 guard (no guard; suppress the
    forward but still record; suppress the record but still forward) were each
    caught by BOTH tests (measured 2026-08-25).

    Kept for isolation, not for detection: it states the Q9 contract on its own
    terms, in the all-empty case, so the policy survives T1 being rewritten or
    its fixture drifting. If you are trimming this suite, this is the first
    test to reconsider -- and the reason is written here so that decision can
    be made on evidence rather than on a guess about coverage.
    """
    harness = build_harness(tmp_path)

    for seed in range(FRAMES_UNTIL_INBOUND_EMITS - 1):
        harness.session.handle_twilio_frame(twilio_frame(seed))

    assert harness.gemini.sent == []
    assert harness.lines() == []


def test_handle_twilio_frame_records_base64_failure_and_continues(
    tmp_path: Path,
) -> None:
    """T3: a malformed base64 payload is dropped and logged, not raised (Q6).

    The three assertions are the three halves of Q6's catch-drop-continue rule,
    and each fails differently: nothing propagates (the call survives), nothing
    was forwarded (the corrupt frame did not reach Gemini), and exactly one
    `frame_error` line names where it died.

    `stage="base64"` is the Q18 half and is not decoration. `detail=str(exc)`
    alone provably cannot identify the failing step -- `reject_partial_pcm16` is
    shared by `mulaw_encode` and `Resampler.push`, so two different stages emit
    a byte-identical message. The stage field is the only thing that makes a
    line in this log diagnosable after a call that cannot be replayed.
    """
    harness = build_harness(tmp_path)
    clean = twilio_frame(0)
    corrupted = clean[:4] + "!" + clean[4:]

    harness.session.handle_twilio_frame(corrupted)

    assert harness.gemini.sent == []

    lines = harness.lines()
    assert len(lines) == 1
    assert lines[0]["event"] == "frame_error"
    assert lines[0]["stage"] == "base64"
    assert lines[0]["timestamp"] == STAMPS[0].isoformat()

    detail = lines[0]["detail"]
    assert isinstance(detail, str)
    assert "base64" in detail


def test_handle_twilio_frame_tags_a_later_stage_failure(tmp_path: Path) -> None:
    """T4: a failure PAST the first step is caught too, and names its own stage.

    An empty payload is the reachable later-stage case on this leg: `""` is
    valid base64 and decodes cleanly to `b""`, so it survives the base64 step
    and dies one step further on, in `mulaw_decode`'s empty-frame guard.

    What this rules out is a catch that only *looks* top-level -- one wrapping
    the base64 call alone. That shape passes T3 perfectly and lets everything
    downstream of it propagate and end the call, which is the exact defect Q6
    exists to prevent. A catch narrower than it appears is this slice's repeat
    defect: `struct.error` at the codec, `ValueError` from `np.frombuffer` at
    Q12, `binascii.Error` at Q15. T4 is the assertion that it did not happen a
    fourth time.

    `stage == "codec"` -- not merely "some frame_error was written" -- is what
    gives the test its teeth. A single catch that reported a constant stage
    would satisfy every other assertion here while making the log say the frame
    died at a step it had already survived.

    PASSED ON ARRIVAL, and load-bearing anyway -- both halves stated plainly.
    There was no RED state: Q18's ratified shape (ONE top-level catch, `stage`
    reassigned as the flow advances) is what T3's implementation had to be, and
    that shape satisfies T4 for free. Writing a deliberately narrower T3 just to
    manufacture a RED here would have meant implementing a shape the contract
    forbids, so the cycle is reported as it happened rather than dressed up.

    Unlike T2 -- kept for isolation after no distinguishing mutation was found
    -- T4 was confirmed to detect defects T3 does not. Two mutations, measured
    2026-08-25, each killing T4 while leaving all 7 other tests green:

      1. narrow catch (try wrapping only the base64 call, rest outside):
         AudioFrameError escapes the handler -> the call ends.
      2. constant stage (`stage` assigned once, never reassigned):
         the log names "base64" for a frame that died in the codec.

    Restore was diff-verified identical to the pre-mutation file after each.
    Mutation 1 is the important one: it is the live shape of this slice's
    repeat defect, and T3 alone cannot see it.
    """
    harness = build_harness(tmp_path)

    harness.session.handle_twilio_frame("")

    assert harness.gemini.sent == []

    lines = harness.lines()
    assert len(lines) == 1
    assert lines[0]["event"] == "frame_error"
    assert lines[0]["stage"] == "codec"

    detail = lines[0]["detail"]
    assert isinstance(detail, str)
    assert "empty" in detail


def test_handle_twilio_frame_resumes_cleanly_after_a_dropped_frame(
    tmp_path: Path,
) -> None:
    """T5: a dropped frame costs the call nothing but that frame (Q6).

    The strong form, and the one worth asserting: audio after the error is
    compared against a reference resampler that NEVER SAW the bad frame. So the
    claim is not the weak "a later frame got through" but the actual Seam 4
    property -- the aborted frame contributed nothing to soxr's filter history,
    leaving the stream bit-for-bit (within tolerance) as if it had never
    arrived.

    That distinction has teeth because the tempting wrong fix is to "reset to be
    safe" and rebuild the resampler in the except branch. It looks defensive,
    passes T3 and T4 untouched, and silently destroys the cross-chunk filter
    history Q1 exists to preserve -- reintroducing the stateless bug for the
    rest of the call, on a leg where the only symptom is degraded audio nobody
    is measuring.

    The second log line is compared as an exact dict, not field by field: that
    pins the clock to exactly two calls total. A handler that recorded an extra
    event, or none, shifts this stamp to a value the fixture does not contain.

    Note the drop here lands at the base64 stage, which is BEFORE the resampler
    -- unavoidably so, since Q18's correction establishes that inbound cannot
    fail at the resample stage at all (`mulaw_decode` always emits even-length
    bytes). So on this leg the property holds somewhat trivially: the resampler
    was never called. G4 is where the same claim gets tested on the leg that can
    actually fail mid-resample, which is why the owner declined to cut it.

    PASSED ON ARRIVAL (third in a row -- T3's implementation of Q6/Q18 is one
    coherent mechanism, and building it satisfied T4 and T5 as a side effect).
    Confirmed load-bearing by mutation, measured 2026-08-25:

      3. "reset to be safe" -- `self._inbound = inbound_resampler()` added to
         the except branch. Kills this test ONLY; T1-T4 stay green.

    Restore diff-verified identical. That mutation is the reason the fixture
    primes the stream first: against a drop-at-frame-0 fixture the same defect
    passes cleanly, because a resampler with no history loses nothing when
    rebuilt. The first draft of this test had exactly that hole.
    """
    harness = build_harness(tmp_path)
    payloads = [twilio_frame(seed) for seed in range(FRAMES_UNTIL_INBOUND_EMITS)]
    clean = twilio_frame(99)
    corrupted = clean[:4] + "!" + clean[4:]

    reference = inbound_resampler()
    expected = [
        emitted
        for payload in payloads
        if (emitted := reference.push(mulaw_decode(base64.b64decode(payload))))
    ]

    # The bad frame lands MID-STREAM, not first, and that placement is the
    # whole test. Dropped as frame 0 the resampler holds no history yet, so
    # even a handler that rebuilt the resampler on error would pass -- there
    # would be nothing to destroy. Injected here, after real filter history has
    # accumulated, that same defect changes the output. Do not "tidy" this to
    # the front of the sequence.
    PRIMED_FRAMES = 3

    for payload in payloads[:PRIMED_FRAMES]:
        harness.session.handle_twilio_frame(payload)
    harness.session.handle_twilio_frame(corrupted)
    for payload in payloads[PRIMED_FRAMES:]:
        harness.session.handle_twilio_frame(payload)

    assert len(expected) == 1, "fixture no longer produces exactly one emission"
    assert len(harness.gemini.sent) == 1
    forwarded = np.frombuffer(harness.gemini.sent[0], dtype=np.int16)
    reference_audio = np.frombuffer(expected[0], dtype=np.int16)

    assert len(forwarded) == len(reference_audio)
    assert np.abs(forwarded).max() > 0, "forwarded silence, not audio"
    assert _rms_error(forwarded, reference_audio) < MAX_RMS_ERROR

    lines = harness.lines()
    assert len(lines) == 2
    assert lines[0]["event"] == "frame_error"
    assert lines[0]["stage"] == "base64"
    assert lines[0]["timestamp"] == STAMPS[0].isoformat()
    assert lines[1] == {
        "event": "frame_forwarded_to_gemini",
        "timestamp": STAMPS[1].isoformat(),
    }


# One realistic Gemini Live audio chunk: PCM16LE mono at 24kHz, 480 samples
# (960 bytes) == 20ms, matching the frame duration Twilio uses on the other leg.
GEMINI_CHUNK_SAMPLES = 480

# MEASURED, NOT CHOSEN -- the outbound twin of FRAMES_UNTIL_INBOUND_EMITS, and
# the same warning applies. This encodes soxr's batching schedule at 24k->8k,
# a fact about a third-party library rather than a knob.
#
# Derivation (2026-08-25, 24kHz -> 8kHz, real 960-byte Gemini chunks):
#
#     chunk 1..3 -> push() returned 0 bytes
#     chunk 4    -> push() returned 980 bytes (490 samples)
#
# consistent with the 489-490 sample figure recorded in
# PR-resampler-emits-per-chunk for this direction.
#
# G1 feeds exactly this many chunks because it is the fewest that produces one
# emission; G2 feeds FEWER, and "fewer than the batching threshold" is what
# makes G2 a suppression test rather than a duplicate of G1. If soxr's batching
# changes they fail in opposite directions and neither message names the cause.
# It is this comment. Re-run the derivation before concluding either is wrong.
CHUNKS_UNTIL_OUTBOUND_EMITS = 4


def gemini_chunk(seed: int) -> bytes:
    """One realistic Gemini PCM16 chunk, varying with `seed`.

    Bytes vary rather than repeat so a handler forwarding a wrong slice, a
    stale buffer or silence fails here instead of matching a constant fixture
    by accident.
    """
    return bytes((seed * 31 + i * 7) % 256 for i in range(GEMINI_CHUNK_SAMPLES * 2))


def test_handle_gemini_chunk_forwards_encoded_audio(tmp_path: Path) -> None:
    """G1: a chunk whose push emits is resampled, encoded, framed and sent.

    The outbound flow has two steps the inbound one does not -- mu-law encode
    and base64 -- so this asserts the whole chain lands intact at the Twilio
    seam: the fake receives a `str`, that string is valid base64, and what it
    decodes to is the audio the resampler produced, not silence and not a
    fragment.

    Comparison is at Seam 2's RMS tolerance, in mu-law-DECODED space, against a
    reference put through the identical encode. Byte-exact comparison is
    forbidden here even though it currently WOULD pass: measured 2026-08-25,
    this 4-chunk outbound fixture is bit-identical across two instances. That
    is precisely the trap Premise 6's falsification condition names -- "a green
    suite is not evidence the assumption holds", because a short fixture
    passes a bit-exact assertion that a longer one fails. Asserting equality
    here would encode an assumption already falsified on the inbound leg and
    would break on the first person who lengthens the fixture.

    Both sides are compared AFTER an identical mu-law round trip rather than in
    raw PCM: mu-law is a coarse nonlinear quantizer, so comparing raw resampler
    output against decoded output would measure the codec's quantization error,
    not the handler's correctness, and would not fit inside MAX_RMS_ERROR.

    DO NOT "simplify" this by comparing against `expected[0]` directly and
    dropping the round trip on the reference side. That is the obvious future
    cleanup and it is wrong: the two sides would then differ by the full mu-law
    quantization error, blowing MAX_RMS_ERROR by orders of magnitude with
    NEITHER side being incorrect. The round trip is on both sides so that the
    only remaining difference is the handler's own behaviour.
    """
    outbound = RecordingResampler(GEMINI_OUTPUT_RATE_HZ, TWILIO_RATE_HZ)
    harness = build_harness(tmp_path, outbound=outbound)
    chunks = [gemini_chunk(seed) for seed in range(CHUNKS_UNTIL_OUTBOUND_EMITS)]

    reference = outbound_resampler()
    expected = [emitted for chunk in chunks if (emitted := reference.push(chunk))]

    for chunk in chunks:
        harness.session.handle_gemini_chunk(chunk)

    assert len(expected) == 1, "fixture no longer produces exactly one emission"
    assert len(harness.twilio.sent) == 1

    # MAGNITUDE, in raw PCM16 space -- the only space Premise 6's tolerance is
    # valid in. This is the audio the handler was handed, before encoding.
    assert len(outbound.emitted) == 1
    raw_forwarded = np.frombuffer(outbound.emitted[0], dtype=np.int16)
    raw_reference = np.frombuffer(expected[0], dtype=np.int16)
    assert len(raw_forwarded) == len(raw_reference)
    assert np.abs(raw_forwarded).max() > 0, "resampled to silence, not audio"
    assert _rms_error(raw_forwarded, raw_reference) < MAX_RMS_ERROR

    # STRUCTURE, in mu-law space -- that the encode/base64/send chain carried
    # that audio through intact. Byte count, not RMS: see the derivation on
    # MAX_MULAW_BYTE_DIVERGENCE for why RMS is heavy-tailed here.
    payload = harness.twilio.sent[0]
    assert isinstance(payload, str), "Twilio's media message carries base64 as text"

    forwarded_mulaw = base64.b64decode(payload, validate=True)
    assert forwarded_mulaw == mulaw_encode(outbound.emitted[0])

    assert harness.lines() == [
        {"event": "chunk_forwarded_to_twilio", "timestamp": STAMPS[0].isoformat()}
    ]


def test_handle_gemini_chunk_suppresses_empty_push(tmp_path: Path) -> None:
    """G2: an empty outbound push encodes nothing, sends nothing, records nothing.

    Fed FEWER than CHUNKS_UNTIL_OUTBOUND_EMITS chunks, so every push is inside
    soxr's batching window and returns b"". Under Q9 that is a no-op, and the
    absence is asserted against the FILE -- `lines()` returns [] for a sink
    never created, so this distinguishes "no event recorded" from "a method was
    not called on a double".

    The "never reaches mulaw_encode" half needs no spy, and that is the one way
    this test is stronger than its inbound twin T2. `mulaw_encode` raises
    AudioFrameError on an empty frame, and this handler has no catch yet -- so
    an implementation that encoded before checking would not merely record a
    falsehood, it would raise out of the handler and fail this test loudly. The
    absence of a raise IS the evidence. That property disappears the moment G3
    adds the catch, at which point the same defect would surface as a
    frame_error line instead; the assertion on `lines() == []` is what keeps
    this test honest across that change.

    Outbound this matters more than inbound. soxr emits on 1 of every 4 real
    chunks here (measured), so a missing guard turns three quarters of a
    perfectly healthy call into either dropped frames or frame_error noise in
    the artifact the exit criterion is computed from.

    PASSED ON ARRIVAL, and OVERLAPPING -- the same status as T2, reached the
    same way and reported the same way rather than dressed up. G1's
    implementation already forced the guard, so this never had a RED state, and
    three mutations of it (no guard; suppress the send but still record; encode
    before checking) were each caught by BOTH G1 and G2 (measured 2026-08-25).
    No mutation was found that this test catches and G1 does not.

    Kept for isolation, not for detection: it states the Q9 contract on its own
    terms in the all-empty case, so the policy survives G1 being rewritten or
    its fixture drifting. If you are trimming this suite, this and T2 are the
    first two to reconsider -- and the evidence for that decision is written
    here rather than left to a guess about coverage.
    """
    harness = build_harness(tmp_path)

    for seed in range(CHUNKS_UNTIL_OUTBOUND_EMITS - 1):
        harness.session.handle_gemini_chunk(gemini_chunk(seed))

    assert harness.twilio.sent == []
    assert harness.lines() == []


def test_handle_gemini_chunk_records_resample_failure_and_continues(
    tmp_path: Path,
) -> None:
    """G3: an odd-length Gemini chunk is dropped and logged, not raised (Q6).

    This is the live path Q12 part 2 was ratified over, and the only reachable
    `stage="resample"` in the slice. The inbound leg is structurally protected
    -- `mulaw_decode` always emits an even number of bytes -- but nothing
    upstream of this handler guarantees Gemini's chunk is a whole number of
    PCM16 samples. Before Q12, `np.frombuffer` raised a bare `ValueError` here,
    which is not an `AudioFrameError` and would therefore propagate past the
    handler and END THE CALL on one malformed chunk. `reject_partial_pcm16` is
    what converts that into a recoverable drop.

    `stage="resample"` is asserted rather than just `frame_error`, and Q18 is
    why: `reject_partial_pcm16` is shared with `mulaw_encode`, so both emit the
    byte-identical message 'PCM16 payload must be a whole number of 2-byte
    samples, got N'. Without the stage field a line in the log cannot say which
    of the two steps dropped the chunk -- on a call that cannot be replayed,
    that is the difference between a diagnosable artifact and a useless one.
    """
    harness = build_harness(tmp_path)
    odd_length = gemini_chunk(0)[:-1]

    harness.session.handle_gemini_chunk(odd_length)

    assert harness.twilio.sent == []

    lines = harness.lines()
    assert len(lines) == 1
    assert lines[0]["event"] == "frame_error"
    assert lines[0]["stage"] == "resample"
    assert lines[0]["timestamp"] == STAMPS[0].isoformat()

    detail = lines[0]["detail"]
    assert isinstance(detail, str)
    assert "2-byte samples" in detail


def test_handle_gemini_chunk_resumes_cleanly_after_a_dropped_chunk(
    tmp_path: Path,
) -> None:
    """G4: a dropped chunk costs the call nothing but that chunk (Q6).

    T5's outbound mirror, and NOT redundant with it -- the owner declined to
    cut this when offered. T5 proves a recovery mechanism exists; G4 proves it
    covers the direction that actually needs it. On the inbound leg the drop
    happens at base64 or codec, always BEFORE the resampler, so T5's claim
    holds somewhat trivially: the resampler was never entered. Here the drop
    happens AT the resampler -- `reject_partial_pcm16` fires inside
    `Resampler.push` -- which is the only place in the slice where an
    exception is raised from inside the component that owns cross-chunk filter
    state. Proving the stream survives that is the non-trivial version of the
    claim, and it is provable only on this leg.

    As in T5, the bad chunk lands MID-STREAM so the resampler already holds
    real history, and the audio after it is compared against a reference that
    never saw it. Injected first, a handler that rebuilt the resampler on error
    would pass -- there would be nothing to destroy.
    """
    outbound = RecordingResampler(GEMINI_OUTPUT_RATE_HZ, TWILIO_RATE_HZ)
    harness = build_harness(tmp_path, outbound=outbound)
    chunks = [gemini_chunk(seed) for seed in range(CHUNKS_UNTIL_OUTBOUND_EMITS)]
    odd_length = gemini_chunk(99)[:-1]

    reference = outbound_resampler()
    expected = [emitted for chunk in chunks if (emitted := reference.push(chunk))]

    PRIMED_CHUNKS = 2

    for chunk in chunks[:PRIMED_CHUNKS]:
        harness.session.handle_gemini_chunk(chunk)
    harness.session.handle_gemini_chunk(odd_length)
    for chunk in chunks[PRIMED_CHUNKS:]:
        harness.session.handle_gemini_chunk(chunk)

    assert len(expected) == 1, "fixture no longer produces exactly one emission"
    assert len(harness.twilio.sent) == 1

    # Same two-assertion split as G1: magnitude in raw PCM16 space, structure
    # in mu-law space. Here the raw check is the load-bearing one -- it is what
    # proves the aborted chunk left soxr's filter history untouched.
    assert len(outbound.emitted) == 1
    raw_forwarded = np.frombuffer(outbound.emitted[0], dtype=np.int16)
    raw_reference = np.frombuffer(expected[0], dtype=np.int16)
    assert len(raw_forwarded) == len(raw_reference)
    assert np.abs(raw_forwarded).max() > 0, "resampled to silence, not audio"
    assert _rms_error(raw_forwarded, raw_reference) < MAX_RMS_ERROR

    forwarded_mulaw = base64.b64decode(harness.twilio.sent[0], validate=True)
    assert forwarded_mulaw == mulaw_encode(outbound.emitted[0])

    lines = harness.lines()
    assert len(lines) == 2
    assert lines[0]["event"] == "frame_error"
    assert lines[0]["stage"] == "resample"
    assert lines[0]["timestamp"] == STAMPS[0].isoformat()
    assert lines[1] == {
        "event": "chunk_forwarded_to_twilio",
        "timestamp": STAMPS[1].isoformat(),
    }


# MEASURED, NOT CHOSEN -- the teardown twins of FRAMES_UNTIL_INBOUND_EMITS and
# CHUNKS_UNTIL_OUTBOUND_EMITS, and the same warning applies. These encode what
# soxr strands in its buffer at the end of each fixture, so they are facts about
# a third-party library rather than knobs.
#
# Derivation (2026-08-25), running the C1 fixture exactly as the test does:
#
#     6 inbound frames  -> per-push [0,0,0,0,0,3320], flush 520 bytes (260 samples)
#     4 outbound chunks -> per-push [0,0,0,980],      flush 300 bytes (150 samples)
#
# consistent in kind with the 1060/170-sample figures Q10 measured over its own
# 50-frame probe: the exact counts follow the fixture length, the fact that a
# tail is stranded at all does not.
#
# C1 asserts both are non-empty because a flush that recovered nothing would let
# a close() that never passes last=True pass the test. C2 uses the OPPOSITE
# case -- a session that pushed nothing, where both flushes measure 0 bytes --
# which is what makes it a suppression test rather than a duplicate of C1.
INBOUND_TAIL_BYTES = 520
OUTBOUND_TAIL_BYTES = 300


def test_close_flushes_both_directions(tmp_path: Path) -> None:
    """C1: teardown recovers each direction's stranded tail and records it.

    Q10's whole reason for existing: soxr batches, so at the end of a call each
    stream is still holding audio it never emitted. Outbound that tail is the
    end of the AI's final utterance -- clipped off every call without this
    flush. The measured amounts for this fixture are above.

    The tails are asserted as AUDIO, not merely as two more log lines, and that
    distinction is what gives the test teeth. A close() that pushed `b""`
    WITHOUT `last=True` returns nothing and so records nothing -- caught by the
    line count. But a close() that flushed and then forwarded the wrong buffer,
    a slice of it, or silence would satisfy every count in this test; only the
    comparison against a reference stream fed the identical input catches that.

    Same two-space split as G1, for the same measured reason: magnitude in raw
    PCM16 space where Premise 6's tolerance is valid, structure in mu-law space
    against the SAME instance's output. Never compare mu-law bytes across two
    soxr instances -- see the block on MAX_RMS_ERROR.

    Event names are the normal forward names, not teardown-specific ones. That
    is the ratified contract (Q10) and it is correct: a forward happened, and
    the offline gap analysis that computes the exit criterion has no reason to
    treat the last chunk of a call differently from any other.
    """
    outbound = RecordingResampler(GEMINI_OUTPUT_RATE_HZ, TWILIO_RATE_HZ)
    harness = build_harness(tmp_path, outbound=outbound)
    frames = [twilio_frame(seed) for seed in range(FRAMES_UNTIL_INBOUND_EMITS)]
    chunks = [gemini_chunk(seed) for seed in range(CHUNKS_UNTIL_OUTBOUND_EMITS)]

    inbound_reference = inbound_resampler()
    for payload in frames:
        inbound_reference.push(mulaw_decode(base64.b64decode(payload)))
    expected_inbound_tail = inbound_reference.push(b"", last=True)

    outbound_reference = outbound_resampler()
    for chunk in chunks:
        outbound_reference.push(chunk)
    expected_outbound_tail = outbound_reference.push(b"", last=True)

    assert len(expected_inbound_tail) == INBOUND_TAIL_BYTES, "fixture strands less"
    assert len(expected_outbound_tail) == OUTBOUND_TAIL_BYTES, "fixture strands less"

    for payload in frames:
        harness.session.handle_twilio_frame(payload)
    for chunk in chunks:
        harness.session.handle_gemini_chunk(chunk)

    assert len(harness.gemini.sent) == 1
    assert len(harness.twilio.sent) == 1
    assert len(harness.lines()) == 2

    harness.session.close()

    # Inbound tail: raw PCM16 reaches the Gemini fake unencoded, so it can be
    # compared directly against the reference stream's own flush.
    assert len(harness.gemini.sent) == 2
    inbound_tail = np.frombuffer(harness.gemini.sent[1], dtype=np.int16)
    inbound_expected = np.frombuffer(expected_inbound_tail, dtype=np.int16)
    assert len(inbound_tail) == len(inbound_expected)
    assert np.abs(inbound_tail).max() > 0, "flushed silence, not the stranded tail"
    assert _rms_error(inbound_tail, inbound_expected) < MAX_RMS_ERROR

    # Outbound tail: MAGNITUDE in raw PCM16 space, seen through the recording
    # resampler because the handler encodes before the fake ever sees it.
    assert len(harness.twilio.sent) == 2
    assert len(outbound.emitted) == 2
    outbound_tail = np.frombuffer(outbound.emitted[1], dtype=np.int16)
    outbound_expected = np.frombuffer(expected_outbound_tail, dtype=np.int16)
    assert len(outbound_tail) == len(outbound_expected)
    assert np.abs(outbound_tail).max() > 0, "flushed silence, not the stranded tail"
    assert _rms_error(outbound_tail, outbound_expected) < MAX_RMS_ERROR

    # STRUCTURE in mu-law space: the encode/base64/send chain carried that tail
    # through intact.
    forwarded_mulaw = base64.b64decode(harness.twilio.sent[1], validate=True)
    assert forwarded_mulaw == mulaw_encode(outbound.emitted[1])

    lines = harness.lines()
    assert len(lines) == 4
    assert lines[2] == {
        "event": "frame_forwarded_to_gemini",
        "timestamp": STAMPS[2].isoformat(),
    }
    assert lines[3] == {
        "event": "chunk_forwarded_to_twilio",
        "timestamp": STAMPS[3].isoformat(),
    }


def test_close_on_an_idle_session_records_nothing(tmp_path: Path) -> None:
    """C2: a flush that recovers nothing forwards nothing and records nothing.

    Q9's contract at the one point it is easiest to get wrong. A session torn
    down having pushed nothing has nothing stranded -- both flushes measure 0
    bytes (see the derivation on INBOUND_TAIL_BYTES) -- and an empty flush is
    the same no-op an empty mid-call push is. Recording a forward here would put
    two events into the artifact for a call that carried no audio at all.

    The absence is asserted against the FILE. `lines()` returns [] for a sink
    never created, so this distinguishes "no event recorded" from "a method was
    not called on a double".

    PASSED ON ARRIVAL -- C1's implementation put the Q9 guard inside
    _forward_to_gemini/_forward_to_twilio, which satisfies this for free. No
    RED state, reported as it happened.

    UNLIKE T2 and G2, it is load-bearing anyway, and one specific mutation is
    why. Measured 2026-08-25, each restore diff-verified identical:

      a. guard dropped from _forward_to_twilio  -> 5 tests fail, C1 among them
      b. guard dropped from _forward_to_gemini  -> 5 tests fail, C1 among them
      c. Q9's REJECTED ALTERNATIVE at teardown -- close() suppresses the
         forward on an empty flush but records the event anyway
                                                 -> ONLY this test fails
                                                    (14 others green, C1 green)

    (a) and (b) were the first guesses and both were wrong about C1: an initial
    draft of this docstring claimed C1 stayed green under (a), and the
    measurement falsified it. Recorded rather than quietly corrected, since
    "confident claim, unmeasured" is this slice's repeat defect.

    (c) is the real reason to keep this test. It is not a hypothetical mutation
    -- it is verbatim the option Q9 considered and rejected, whose steelman was
    that a per-frame heartbeat keeps the event stream dense. C1 cannot see it,
    because C1's flushes are non-empty by construction, so its four lines are
    four genuine forwards either way. Only a teardown with nothing to flush
    exposes an event that claims a forward that did not happen -- and phantom
    events shrink apparent gaps, which is the false-PASS direction the exit
    criterion exists to catch.
    """
    harness = build_harness(tmp_path)

    harness.session.close()

    assert harness.gemini.sent == []
    assert harness.twilio.sent == []
    assert harness.lines() == []


def test_close_leaves_the_timing_log_intact_when_teardown_fails(
    tmp_path: Path,
) -> None:
    """C3: a failed teardown cannot damage the log written before it (Q19).

    THE CLAIM IS ABOUT THE LOG, not about the exception. Q19's behavior text is
    deliberate on this: propagation is the MEANS by which the property holds
    today, log integrity is what the slice actually needs. The JSONL is the sole
    evidence for the exit criterion and for PR-audio-bridge-latency; if a
    teardown on an already-broken session can truncate or corrupt it, three real
    PSTN calls prove nothing -- and that failure surfaces only when something
    has already gone wrong, which is when nobody is looking.

    The property holds by construction: TimingRecorder._append opens, writes and
    closes per call (Seam 3). But it holds SILENTLY, so this asserts the log's
    on-disk shape -- every line before the raise still there, still parseable,
    no torn final line -- rather than merely that something raised.

    PASSED ON ARRIVAL, for that same reason: close() has no catch and the
    recorder already flushes per call, so C1's implementation satisfied this
    without a RED state. Load-bearing anyway, and the mutations say precisely
    how far. Measured 2026-08-25, each restore diff-verified identical:

      a. close() wraps its flushes in `except Exception: pass`
         -- Q19's REJECTED option                 -> ONLY this test fails
      b. TimingRecorder._append buffers instead of
         writing per call                         -> 15 tests fail, including
                                                     Seam 3's own integrity test
      c. close() made "atomic": both flushes
         computed before either forward           -> NOTHING fails, all 16 green

    Read those honestly, because an earlier draft of this docstring claimed all
    three and only (a) survived contact:

    (a) is what this test uniquely defends, and it is exactly the change a
    future reader would make to stop teardown throwing. It looks tidy and it
    silently converts a double-teardown defect into a call whose evidence
    quietly stops at the last successful write.

    (b) is NOT this test's job after all -- Seam 3 already owns per-call flush
    and detects it first and louder. This test does not need to claim it.

    (c) is not caught, and on inspection is not a defect: with the inbound flush
    raising, the outbound tail is lost under either ordering, so the log is
    identical and C3 is right to pass. Named here so the next reader does not
    mistake a gap in coverage for a gap in the contract.

    The failure is real, not invented. soxr raises RuntimeError("Input after
    last input") on a second flush of the same stream (measured 2026-08-25), and
    Q19 names the live path: a close() reachable from BOTH a Twilio stop event
    and a hang-up path hits exactly this. The fixture injects an
    already-finalized inbound resampler, which is the honest way to reach that
    state -- no monkeypatching, no fake raising on cue, the actual library
    raising the actual error for the actual reason.

    RuntimeError, deliberately, not AudioFrameError: it is neither caught nor
    swallowed here. Catching it would need a broad `except Exception` in
    teardown -- the over-broad catch Q12 and Q15 both rejected -- and it would
    hide a genuine double-teardown defect instead of surfacing it.
    """
    finalized = inbound_resampler()
    finalized.push(b"", last=True)
    harness = build_harness(tmp_path, inbound=finalized)

    # Real events first, through the direction that still works. Without a
    # populated log there is nothing for a broken teardown to damage and the
    # test would pass on an empty file.
    harness.session.start()
    for seed in range(CHUNKS_UNTIL_OUTBOUND_EMITS):
        harness.session.handle_gemini_chunk(gemini_chunk(seed))

    assert len(harness.lines()) == 2, "fixture must leave real lines to protect"

    with pytest.raises(RuntimeError, match="Input after last input"):
        harness.session.close()

    # Every line written before the raise is still on disk, still parseable,
    # still in order, still carrying the stamps it was written with.
    assert harness.lines() == [
        {"event": "call_answered", "timestamp": STAMPS[0].isoformat()},
        {"event": "chunk_forwarded_to_twilio", "timestamp": STAMPS[1].isoformat()},
    ]

    # And the file is not merely parseable line-by-line -- it is not TORN. A
    # write interrupted mid-line would leave a final fragment that splitlines()
    # hands back as a short string; json.loads would reject it, but only if the
    # fragment is non-empty. The trailing-newline check is what pins that shut.
    raw = harness.sink.read_text()
    assert raw.endswith("\n"), "log ends mid-line -- a write was interrupted"
    for line in raw.splitlines():
        json.loads(line)
