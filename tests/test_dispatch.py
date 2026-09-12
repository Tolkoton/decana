"""S5 dispatch. Every test's docstring opens with its ratified behavior id.

Ids are ratified in `.claude/overseer/slice/dispatch.md`; `scripts/check_ids.py`
diffs this file against that table in both directions.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from decana.analysis.model import Analysis
from decana.dispatch.brief import render_brief
from decana.dispatch.model import StageOutcome
from decana.profile.model import Profile, SmsTemplate
from decana.twilio.records import CallRecord, TranscriptTurn

OK = StageOutcome(status="ok", detail="")


def make_profile(**over: object) -> Profile:
    """A profile whose every string field is DISTINCT, so a swapped field shows."""
    base: dict[str, object] = {
        "name": "broker-slug",
        "display_name": "UK mortgage broker intake",
        "live_model": "live-model-x",
        "analysis_model": "analysis-model-y",
        "phone_number": "+441234567890",
        "sms_sender_id": "BrokerSMS",
        "operator_email": "ops@example.test",
        "outcomes": ("qualified_lead", "not_eligible"),
        "sms": {
            "qualified_lead": SmsTemplate(
                text="Thanks! Book here: {booking}",
                links={"booking": "https://book.test/x"},
            )
        },
        "disclosure": "disclosure text",
        "conversation": "conversation prompt",
        "analysis": "analysis prompt",
    }
    base.update(over)
    return Profile(**base)  # type: ignore[arg-type]


def make_record(**over: object) -> CallRecord:
    base: dict[str, object] = {
        "call_sid": "CA_TEST_1",
        "caller_number": "+447700900123",
        "profile_name": "broker-slug",
        "started_at": datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 9, 12, 10, 4, 30, tzinfo=UTC),
        "transcript": (
            TranscriptTurn(role="model", text="Hello, how can I help?"),
            TranscriptTurn(role="caller", text="I want to remortgage."),
            TranscriptTurn(role="model", text="How much is outstanding?"),
        ),
        "timing_path": None,
        "ended_reason": "twilio_stop",
    }
    base.update(over)
    from pathlib import Path

    base.setdefault("timing_path", Path("/tmp/x.jsonl"))
    if base["timing_path"] is None:
        base["timing_path"] = Path("/tmp/x.jsonl")
    return CallRecord(**base)  # type: ignore[arg-type]


def make_analysis(**over: object) -> Analysis:
    base: dict[str, object] = {
        "outcome": "qualified_lead",
        "compliance_notes": (),
        "summary": "Caller wants to remortgage a flat in Manchester.",
        "raw": '{"outcome": "qualified_lead"}',
    }
    base.update(over)
    return Analysis(**base)  # type: ignore[arg-type]


def test_summary_appears_verbatim() -> None:
    """D20.a `analysis.summary` appears verbatim in the brief AND in the email body."""
    analysis = make_analysis(summary="A distinctive summary sentence.")
    full = render_brief(
        make_record(),
        analysis,
        make_profile(),
        transcript=OK,
        analysis_file=OK,
        sms=StageOutcome(status="ok", detail="SM123"),
        email=OK,
    )
    body = render_brief(
        make_record(),
        analysis,
        make_profile(),
        transcript=OK,
        analysis_file=OK,
        sms=StageOutcome(status="ok", detail="SM123"),
        email=None,
    )
    assert "A distinctive summary sentence." in full
    assert "A distinctive summary sentence." in body


def _render(**over: object) -> str:
    kw: dict[str, object] = {
        "record": make_record(),
        "analysis": make_analysis(),
        "profile": make_profile(),
        "transcript": OK,
        "analysis_file": OK,
        "sms": StageOutcome(status="ok", detail="SM123"),
        "email": OK,
    }
    kw.update(over)
    return render_brief(
        kw.pop("record"),  # type: ignore[arg-type]
        kw.pop("analysis"),  # type: ignore[arg-type]
        kw.pop("profile"),  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


def test_every_compliance_note_renders() -> None:
    """D20.b EVERY compliance note renders, one line each (>= 2, so truncation dies)."""
    out = _render(
        analysis=make_analysis(
            compliance_notes=(
                "Did not state the recording notice.",
                "Gave rate advice.",
            )
        )
    )
    assert "- Did not state the recording notice." in out
    assert "- Gave rate advice." in out


def test_empty_compliance_notes_render_none() -> None:
    """D20.c empty `compliance_notes` renders the literal `none`, not an absent section."""
    out = _render(analysis=make_analysis(compliance_notes=()))
    assert "## Compliance notes\nnone" in out


def test_outcome_appears_in_body() -> None:
    """D20.d `analysis.outcome` appears in the brief BODY, not only in the email subject."""
    out = _render(analysis=make_analysis(outcome="not_eligible"))
    assert "## Outcome\nnot_eligible" in out


def test_withheld_caller_number() -> None:
    """D21.a an empty `caller_number` renders the literal `withheld`, not an empty field."""
    assert "Caller:  withheld" in _render(record=make_record(caller_number=""))
    assert "Caller:  +447700900123" in _render()


def test_when_line_carries_both_times_and_utc() -> None:
    """D21.b the `When:` line carries `started_at`, `ended_at` AND the `(UTC)` label."""
    out = _render()
    assert "2026-09-12T10:00:00+00:00" in out
    assert "2026-09-12T10:04:30+00:00" in out
    assert "(UTC)" in out


def test_body_profile_line_uses_display_name() -> None:
    """D21.c the BODY `Profile:` line uses `display_name`, not `name`."""
    out = _render()
    assert "Profile: UK mortgage broker intake" in out
    assert "broker-slug" not in out


def test_ended_line_carries_ended_reason() -> None:
    """D21.d the `Ended:` line carries `record.ended_reason`."""
    assert "Ended:   ws_disconnect" in _render(
        record=make_record(ended_reason="ws_disconnect")
    )


def test_transcript_failure_line_renders() -> None:
    """D19.a a failed transcript write renders its ratified line in the EMAIL BODY too."""
    failed = StageOutcome(status="failed", detail="OSError: disk full")
    body = _render(transcript=failed, email=None)
    full = _render(transcript=failed)
    assert "- Transcript file: FAILED — OSError: disk full" in body
    assert "- Transcript file: FAILED — OSError: disk full" in full


def test_analysis_file_failure_line_renders() -> None:
    """D19.b a failed analysis-json write renders `- Analysis file: FAILED — ...` in both."""
    failed = StageOutcome(status="failed", detail="OSError: nope")
    assert "- Analysis file: FAILED — OSError: nope" in _render(
        analysis_file=failed, email=None
    )
    assert "- Analysis file: FAILED — OSError: nope" in _render(analysis_file=failed)


def test_evidence_lines_identical_across_passes() -> None:
    """D19.c transcript/analysis lines are byte-identical between the email body and brief."""
    failed = StageOutcome(status="failed", detail="OSError: x")
    body = _render(transcript=failed, analysis_file=failed, email=None).splitlines()
    full = _render(transcript=failed, analysis_file=failed).splitlines()
    evid = [
        ln for ln in body if ln.startswith(("- Transcript file:", "- Analysis file:"))
    ]
    assert evid == [
        ln for ln in full if ln.startswith(("- Transcript file:", "- Analysis file:"))
    ]
    assert len(evid) == 2


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (StageOutcome(status="ok", detail="SM999"), "- SMS: sent (SM999)"),
        (
            StageOutcome(status="skipped", detail="no template for 'x'"),
            "- SMS: not sent — no template for 'x'",
        ),
        (
            StageOutcome(status="failed", detail="TimeoutError: slow"),
            "- SMS: FAILED — TimeoutError: slow",
        ),
        # adversarial: a SKIPPED outcome whose detail begins "failed: " must still read
        # "not sent" -- this is what kills a prefix-parsing renderer.
        (
            StageOutcome(status="skipped", detail="failed: not really"),
            "- SMS: not sent — failed: not really",
        ),
    ],
)
def test_sms_line_branches_on_status_not_detail(
    outcome: StageOutcome, expected: str
) -> None:
    """D8.a a FAILED send is reported differently from a deliberate skip, by status."""
    assert expected in _render(sms=outcome)


def test_email_body_is_brief_minus_exactly_one_line_success() -> None:
    """D3.a email body == brief minus exactly one line (email succeeded)."""
    full = _render(email=OK).splitlines()
    body = _render(email=None).splitlines()
    assert len(full) - len(body) == 1
    assert [
        ln for ln in full if ln not in body or full.count(ln) != body.count(ln)
    ] == ["- Email: sent to ops@example.test"]


def test_email_body_is_brief_minus_exactly_one_line_failure() -> None:
    """D3.b email body == brief minus exactly one line (email failed)."""
    failed = StageOutcome(status="failed", detail="SMTPAuthenticationError: bad")
    full = _render(email=failed).splitlines()
    body = _render(email=None).splitlines()
    assert len(full) - len(body) == 1
    assert full[:-1] == body
