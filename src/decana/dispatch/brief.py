"""The operator-facing brief, and the email body that is the same text minus one line.

WHAT: `render_brief` turns one finished call into the Markdown a human reads.

WHY ONE FUNCTION, CALLED TWICE: the ratified contract says the email body is
"the same brief text minus the email-outcome line". Passing `email=None` omits
exactly that line, so the two are the same function of the same inputs and
cannot drift (S5-Q8). Two renderers would make that a discipline rather than a
mechanism, and nothing would fail when they diverged.

WHAT THIS DOES NOT DO: no I/O. It never branches on `StageOutcome.detail`'s
text -- `status` is the discriminant (S5-Q19).
"""

from decana.analysis.model import Analysis
from decana.dispatch.model import StageOutcome
from decana.profile.model import Profile
from decana.twilio.records import CallRecord

__all__ = ["render_brief"]

_WITHHELD = "withheld"


def _file_line(label: str, outcome: StageOutcome) -> str:
    """One evidence-file status line. Never skipped -- only written or failed."""
    if outcome.status == "ok":
        return f"- {label}: written"
    return f"- {label}: FAILED — {outcome.detail}"


def _sms_line(outcome: StageOutcome) -> str:
    """The SMS status line, chosen by `status` and never by `detail`'s text."""
    if outcome.status == "ok":
        return f"- SMS: sent ({outcome.detail})"
    if outcome.status == "skipped":
        return f"- SMS: not sent — {outcome.detail}"
    return f"- SMS: FAILED — {outcome.detail}"


def _email_line(outcome: StageOutcome, operator_email: str) -> str:
    """The one line omitted from the email body (S5-Q8/Q19)."""
    if outcome.status == "ok":
        return f"- Email: sent to {operator_email}"
    return f"- Email: FAILED — {outcome.detail}"


def _compliance_block(notes: tuple[str, ...]) -> list[str]:
    """Every note, one per line; the literal `none` when there are no notes.

    Rendered unconditionally (S5-Q19): an absent section and a section saying
    `none` are indistinguishable to an operator scanning for risk, and the
    absent one is also what a DROPPED `compliance_notes` looks like.
    """
    if not notes:
        return ["none"]
    return [f"- {note}" for note in notes]


def _header(record: CallRecord, profile: Profile) -> list[str]:
    """Who called, when, on which profile, and how the call ended."""
    caller = record.caller_number or _WITHHELD
    return [
        f"# Call brief — {record.call_sid}",
        "",
        f"Caller:  {caller}",
        f"When:    {record.started_at.isoformat()} – {record.ended_at.isoformat()} (UTC)",
        f"Profile: {profile.display_name}",
        f"Ended:   {record.ended_reason}",
    ]


def render_brief(
    record: CallRecord,
    analysis: Analysis,
    profile: Profile,
    *,
    transcript: StageOutcome,
    analysis_file: StageOutcome,
    sms: StageOutcome,
    email: StageOutcome | None,
) -> str:
    """Flow: header -> what the call was -> what was dispatched.

    `email=None` omits the `- Email:` line and nothing else; that exact string is
    the email body. `transcript` and `analysis_file` are known before the email
    is sent, so they render identically in both passes -- which is what keeps the
    difference at exactly one line.
    """
    lines: list[str] = [
        *_header(record, profile),
        "",
        "## Outcome",
        analysis.outcome,
        "",
        "## Summary",
        analysis.summary,
        "",
        "## Compliance notes",
        *_compliance_block(analysis.compliance_notes),
        "",
        "## Transcript",
        f"{len(record.transcript)} turns — full text in {record.call_sid}.transcript.txt",
        "",
        "## Dispatch",
        _file_line("Transcript file", transcript),
        _file_line("Analysis file", analysis_file),
        _sms_line(sms),
    ]
    if email is not None:
        lines.append(_email_line(email, profile.operator_email))
    return "\n".join(lines) + "\n"
