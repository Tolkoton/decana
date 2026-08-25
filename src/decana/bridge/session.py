"""Orchestration for one bridged call: Twilio <-> Gemini Live, both directions.

This is the only module that knows the ORDER of things. The codec, the
resampler and the timing recorder each do one job and know nothing about each
other; BridgeSession composes them into the two directional pipelines and owns
the two policies the slice contract ratified:

  * Q9 -- an empty resampler return is a no-op. Nothing was sent, so nothing is
    forwarded and nothing is recorded. The event names assert a forward
    happened; firing one on a no-op writes a falsehood into the artifact the
    exit criterion is computed from.
  * Q6 -- an AudioFrameError is caught at the handler's top level, recorded as
    `frame_error`, the frame is dropped, and the call continues. One corrupt
    frame off a real PSTN line must not burn a scarce test call.

Every dependency is injected. Nothing here constructs a client, a resampler, a
recorder or a clock, so the whole flow is exercisable without a network.

What this module does NOT do: caller-type routing, the compliance guardrail,
the production disclosure line, post-call dispatch, Calendly, or Q4's
interruption no-op (deferred with the Gemini client, whose event surface names
it). It also does not read the timing log back or compute gaps -- that is
offline analysis over the JSONL.
"""

from __future__ import annotations

import base64
import binascii
from typing import Protocol

from decana.bridge.codec import AudioFrameError, mulaw_decode, mulaw_encode
from decana.bridge.resampler import Resampler
from decana.bridge.timing import TimingRecorder


class TwilioMediaStreamClient(Protocol):
    """The one thing this session needs from the Twilio leg."""

    def send_media(self, base64_mulaw: str) -> None: ...


class GeminiLiveSessionClient(Protocol):
    """The one thing this session needs from the Gemini leg."""

    def send_audio(self, pcm16k: bytes) -> None: ...


def decode_base64_frame(payload: str) -> bytes:
    """Decode a Twilio media payload to raw mu-law bytes (Q15).

    validate=True on purpose. The permissive default does not merely tolerate
    stray characters -- it cannot detect them: it discards them and returns a
    well-formed byte string, which then decodes as mu-law into plausible
    garbage that reaches the caller's ear with nothing in the timing log. A
    loud drop beats a silent corruption; Q9 and Q14 made the same call about
    this slice's evidence.

    binascii.Error is translated rather than allowed to propagate: it subclasses
    ValueError, not AudioFrameError, so it would sail past the handler's Q6
    catch and end the call -- the identical defect Q12 part 2 fixed at the
    resampler boundary, here at the third and last boundary.
    """
    try:
        return base64.b64decode(payload, validate=True)
    except binascii.Error as exc:
        raise AudioFrameError(f"payload is not valid base64: {exc}") from exc


class BridgeSession:
    """One live call. Constructed at answer, closed at hang-up."""

    def __init__(
        self,
        twilio: TwilioMediaStreamClient,
        gemini: GeminiLiveSessionClient,
        timing: TimingRecorder,
        inbound: Resampler,
        outbound: Resampler,
    ) -> None:
        self._twilio = twilio
        self._gemini = gemini
        self._timing = timing
        self._inbound = inbound
        self._outbound = outbound

    def start(self) -> None:
        """Record `call_answered`, the first event of every call (Q16).

        Separate from __init__ on purpose: Q13 puts construction deliberately
        BEFORE the call is placed, so stamping here in the constructor would
        measure setup-to-dial time as answer latency.
        """
        self._timing.record("call_answered")

    def handle_twilio_frame(self, base64_payload: str) -> None:
        """Caller -> AI: base64 -> mu-law decode -> 8k->16k -> Gemini.

        Flow: decode -> resample -> forward -> record. An empty push is a
        no-op (Q9): soxr batches, so most real frames emit nothing, and
        recording a forward that did not happen would write a falsehood into
        the artifact the exit criterion is computed from.

        An AudioFrameError anywhere in the conversion is caught here, recorded
        with the stage that raised it, and the frame dropped -- the call
        continues (Q6). ONE top-level catch, with `stage` reassigned as the
        flow advances (Q18): per-step try blocks would tag stages equally well
        but would reintroduce the narrow catch that T4 exists to rule out, and
        a catch narrower than it looks is this slice's repeat defect
        (struct.error at the codec, ValueError from np.frombuffer at Q12,
        binascii.Error at Q15).

        `stage="resample"` is unreachable on this leg: mulaw_decode packs one
        16-bit sample per input byte, so its output is always even-length and
        reject_partial_pcm16 cannot fire here. Kept, not pruned -- unlike
        Q14's `event` key, which Python's argument binding makes unreachable
        as a matter of language, this branch is inert only while the pipeline
        keeps its current order. Reorder it and the branch goes live. See the
        Q18 correction in the slice artifact.
        """
        stage = "base64"
        try:
            mulaw = decode_base64_frame(base64_payload)
            stage = "codec"
            pcm8k = mulaw_decode(mulaw)
            stage = "resample"
            pcm16k = self._inbound.push(pcm8k)
            self._forward_to_gemini(pcm16k)
        except AudioFrameError as exc:
            self._timing.record("frame_error", stage=stage, detail=str(exc))
            return

    def handle_gemini_chunk(self, pcm24k_bytes: bytes) -> None:
        """AI -> caller: 24k->8k -> mu-law encode -> base64 -> Twilio.

        Flow: resample -> encode -> frame -> forward -> record. The empty-push
        guard is Q9 again, and here it is load-bearing beyond suppressing a
        false event: `mulaw_encode(b"")` raises on an empty frame, so without
        the guard soxr's ordinary batching -- 3 of every 4 real chunks -- would
        surface as a stream of frame_errors on a healthy call.

        An AudioFrameError anywhere in the conversion is caught here, recorded
        with the stage that raised it, and the chunk dropped -- the call
        continues (Q6). ONE top-level catch with `stage` reassigned as the flow
        advances, exactly as inbound (Q18).

        This is the leg the catch actually protects. Inbound is structurally
        safe at the resampler, but nothing upstream guarantees Gemini's chunk
        is a whole number of PCM16 samples, so `reject_partial_pcm16` is a live
        raise site here -- that is Q12 part 2's whole finding.

        `stage="codec"` is unreachable: soxr's int16 output is always
        even-length, and the Q9 guard has already returned on empty, so neither
        of mulaw_encode's guards can fire. Kept, not pruned -- inert only while
        the pipeline keeps its current order, unlike Q14's `event` key which
        Python's argument binding makes unreachable as a matter of language.
        See the Q18 correction in the slice artifact.
        """
        stage = "resample"
        try:
            pcm8k = self._outbound.push(pcm24k_bytes)
            stage = "codec"
            self._forward_to_twilio(pcm8k)
        except AudioFrameError as exc:
            self._timing.record("frame_error", stage=stage, detail=str(exc))
            return

    def _forward_to_gemini(self, pcm16k: bytes) -> None:
        """Send one inbound payload upstream and record the forward.

        Shared by the handler and by close()'s teardown flush, so Q9's guard and
        the event name each exist in exactly ONE place. Duplicating the name
        across two call sites is how a later rename reaches one and not the
        other, leaving the offline gap analysis reading two vocabularies for the
        same event -- the drift argument Q12 part 3 already made about
        reject_partial_pcm16.
        """
        if not pcm16k:
            return
        self._gemini.send_audio(pcm16k)
        self._timing.record("frame_forwarded_to_gemini")

    def _forward_to_twilio(self, pcm8k: bytes) -> None:
        """Encode, frame and send one outbound payload, recording the forward.

        The outbound twin of _forward_to_gemini, with the two extra steps that
        leg carries. The Q9 guard sits BEFORE mulaw_encode and must stay there:
        mulaw_encode raises AudioFrameError on an empty frame, so a guard moved
        after it would turn 3 of every 4 healthy chunks into frame_error noise
        in the artifact the exit criterion is computed from.

        Called from INSIDE handle_gemini_chunk's try, deliberately. The encode
        is a conversion step whose `stage="codec"` branch must stay under the
        catch -- pulling this call out would narrow the catch to the resample
        step alone, which is precisely the defect T4 exists to rule out and the
        pruning Q18's correction warns against.

        That does put send_media and record under the catch as well, which the
        pre-refactor shape did not. Checked rather than assumed: no transmission
        path raises AudioFrameError (it is the codec's own type), and
        TimingRecorder's reserved-key guard raises a plain ValueError, which is
        AudioFrameError's PARENT and so is not caught by this clause.
        """
        if not pcm8k:
            return
        mulaw = mulaw_encode(pcm8k)
        self._twilio.send_media(base64.b64encode(mulaw).decode("ascii"))
        self._timing.record("chunk_forwarded_to_twilio")

    def close(self) -> None:
        """Teardown flush (Q10): recover each direction's stranded tail.

        Once per call, not per chunk -- last=True finalizes the stream and would
        destroy the cross-chunk filter history if called per frame. Outbound,
        the stranded tail is the end of the AI's final utterance.

        A recovered tail is forwarded and recorded under the NORMAL forward
        event name: a forward happened, and the offline gap analysis has no
        reason to treat the last chunk of a call differently from any other. An
        empty flush is the Q9 no-op again -- nothing sent, nothing recorded.
        """
        self._forward_to_gemini(self._inbound.push(b"", last=True))
        self._forward_to_twilio(self._outbound.push(b"", last=True))


__all__ = [
    "BridgeSession",
    "GeminiLiveSessionClient",
    "TwilioMediaStreamClient",
    "decode_base64_frame",
]
