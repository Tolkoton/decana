"""Turn one finished call into operator-visible output.

WHAT: `dispatch` performs the five ratified effects in order -- transcript file,
analysis JSON, SMS, email, brief -- and reports each. `post_call` composes S4's
`analyse` with it, and is the real `OnCallEnd`.

THE ORDERING IS THE CONTRACT (guarantee (a)+(b)):
  1. {call_sid}.transcript.txt
  2. {call_sid}.analysis.json   (= analysis.raw)
  3. SMS, conditional -- the {call_sid}.sms-sent marker is created FIRST
  4. email, always attempted -- body = render_brief(..., email=None)
  5. {call_sid}.brief.md = render_brief(..., email=<outcome>) -- LAST, so it can
     state the email's own outcome

WHAT THIS DOES NOT DO: retry, queue, schedule, store to the cloud, send HTML
email, or send more than one SMS per call.

EVERY ONE OF THE FIVE IS WRAPPED INDEPENDENTLY and `dispatch` never raises for
any of them (guarantee (d) as amended 2026-09-12). A disk failure must not take
the operator's email with it -- that would make a real call reach nobody, which
is the failure mode the amendment exists to prevent.
"""

import asyncio
import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from decana.analysis.analyse import AnalysisClient, analyse, render_transcript
from decana.analysis.model import Analysis
from decana.dispatch.brief import render_brief
from decana.dispatch.model import DispatchReport, StageOutcome
from decana.dispatch.senders import EmailSender, SmsSender
from decana.profile.model import Profile
from decana.twilio.records import CallRecord

__all__ = ["dispatch", "post_call"]

logger = logging.getLogger(__name__)

_OK = StageOutcome(status="ok", detail="")


def _failed(exc: BaseException) -> StageOutcome:
    """A failure carries its exception TYPE, not just its message.

    The type is what distinguishes an `OSError` from an `SMTPAuthenticationError`
    in the brief, and it is what an operator needs to know who to call.
    """
    return StageOutcome(status="failed", detail=f"{type(exc).__name__}: {exc}")


def _run(stage: str, work: Callable[[], None], errors: list[str]) -> StageOutcome:
    """Run one effect, converting any failure into an outcome plus an error line.

    Scoped to `Exception`, never `BaseException`: `post_call` runs inside S3's
    teardown path, and swallowing `CancelledError` here would cost that teardown
    the ability to cancel at all -- the one-word defect S4 recorded.
    """
    try:
        work()
    except Exception as exc:  # noqa: BLE001 - guarantee (d): this stage must not raise
        outcome = _failed(exc)
        errors.append(f"{stage}: {outcome.detail}")
        return outcome
    return _OK


def _write(path: Path, text: str) -> None:
    """Write UTF-8 explicitly.

    `write_text` defaults to the locale encoding. A caller named "Siobhán" is
    ordinary on this line, and on a non-UTF-8 locale the default either raises or
    mangles -- a per-environment failure no test on a UTF-8 box would catch.
    """
    path.write_text(text, encoding="utf-8")


def _copy_timing_log(timing_path: Path, artifact_dir: Path) -> None:
    """Bring the per-chunk timing log next to the other artifacts, ONCE.

    S3 appends that log many times a second, so in production it lives on local
    disk (`Settings.timing_dir`) while `artifact_dir` is a Cloud Storage mount
    that tolerates about one write per second per object. One copy at call end
    is the compromise: the turnlog S7 judges latency on reaches the bucket, and
    the hot path never touches it. A no-op when both are the same directory
    (every local run), or when S3 never wrote the file.
    """
    if not timing_path.is_file():
        return
    target = artifact_dir / timing_path.name
    if target.resolve() == timing_path.resolve():
        return
    shutil.copyfile(timing_path, target)


async def dispatch(
    record: CallRecord,
    analysis: Analysis,
    profile: Profile,
    *,
    sms: SmsSender,
    email: EmailSender,
    artifact_dir: Path,
) -> DispatchReport:
    """Flow: evidence -> SMS -> email -> brief. Never raises for any of the five."""
    errors: list[str] = []
    artifact_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = artifact_dir / f"{record.call_sid}.transcript.txt"
    analysis_path = artifact_dir / f"{record.call_sid}.analysis.json"
    brief_path = artifact_dir / f"{record.call_sid}.brief.md"

    transcript_outcome = _run(
        "transcript",
        lambda: _write(transcript_path, render_transcript(record.transcript)),
        errors,
    )
    analysis_outcome = _run(
        "analysis", lambda: _write(analysis_path, analysis.raw), errors
    )
    _run("timing", lambda: _copy_timing_log(record.timing_path, artifact_dir), errors)

    sms_outcome = await _send_sms(
        record, analysis, profile, sms=sms, artifact_dir=artifact_dir, errors=errors
    )

    email_body_parts = {
        "transcript": transcript_outcome,
        "analysis_file": analysis_outcome,
        "sms": sms_outcome,
    }
    email_outcome = await _send_email(
        record, analysis, profile, email=email, errors=errors, **email_body_parts
    )

    brief_outcome = _run(
        "brief",
        lambda: _write(
            brief_path,
            render_brief(
                record, analysis, profile, email=email_outcome, **email_body_parts
            ),
        ),
        errors,
    )
    del (
        brief_outcome
    )  # the brief cannot report its own write failure; `errors` carries it

    return DispatchReport(
        transcript_path=transcript_path,
        brief_path=brief_path,
        sms_sid=sms_outcome.detail if sms_outcome.status == "ok" else None,
        email_sent=email_outcome.status == "ok",
        errors=tuple(errors),
    )


async def _send_sms(
    record: CallRecord,
    analysis: Analysis,
    profile: Profile,
    *,
    sms: SmsSender,
    artifact_dir: Path,
    errors: list[str],
) -> StageOutcome:
    """Three independent suppressions, then at-most-once send."""
    template = profile.sms.get(analysis.outcome)
    if template is None:
        return StageOutcome(
            status="skipped", detail=f"no SMS template for '{analysis.outcome}'"
        )
    if not record.caller_number:
        return StageOutcome(status="skipped", detail="caller number withheld")

    marker = artifact_dir / f"{record.call_sid}.sms-sent"
    try:
        with marker.open("x", encoding="utf-8") as fh:
            fh.write(record.call_sid)
    except FileExistsError:
        return StageOutcome(status="skipped", detail="already sent for this call")

    sid: list[str] = []

    def _go() -> None:
        sid.append(
            sms.send(
                to=record.caller_number,
                sender_id=profile.sms_sender_id,
                body=template.text.format(**template.links),
            )
        )

    outcome = await asyncio.to_thread(_run, "sms", _go, errors)
    return (
        StageOutcome(status="ok", detail=sid[0]) if outcome.status == "ok" else outcome
    )


async def _send_email(
    record: CallRecord,
    analysis: Analysis,
    profile: Profile,
    *,
    email: EmailSender,
    errors: list[str],
    transcript: StageOutcome,
    analysis_file: StageOutcome,
    sms: StageOutcome,
) -> StageOutcome:
    """Always attempted. Body is the brief minus its own outcome line.

    `render_brief` is called INSIDE the wrapper, not before it (Q18): the stage
    boundary spans the work that PRODUCES the thing as well as the send, so a
    rendering bug is reported as an `email:` failure rather than escaping
    `dispatch` entirely. Getting this wrong was caught by `D14.a`.
    """

    def _go() -> None:
        body = render_brief(
            record,
            analysis,
            profile,
            transcript=transcript,
            analysis_file=analysis_file,
            sms=sms,
            email=None,
        )
        subject = (
            f"[{profile.display_name}] {analysis.outcome} — {record.caller_number}"
        )
        email.send(to=profile.operator_email, subject=subject, body=body)

    return await asyncio.to_thread(_run, "email", _go, errors)


async def post_call(
    record: CallRecord,
    *,
    profile: Profile,
    analysis_client: AnalysisClient,
    sms: SmsSender,
    email: EmailSender,
    artifact_dir: Path,
) -> None:
    """The real `OnCallEnd`: analyse, then dispatch. Never raises; never swallows cancellation.

    `analyse` never raises and `dispatch` never raises for its five effects, so
    this guards what is genuinely left over -- `artifact_dir.mkdir` failing, which
    runs before any stage exists to own it. Scoped to `Exception`: `post_call`
    runs inside S3's teardown, and `except BaseException` here would cost that
    teardown the ability to cancel at all (the one-word defect S4 recorded).
    """
    try:
        analysis = await analyse(record.transcript, profile, client=analysis_client)
        await dispatch(
            record, analysis, profile, sms=sms, email=email, artifact_dir=artifact_dir
        )
    except Exception:
        logger.exception("post-call dispatch failed for %s", record.call_sid)
