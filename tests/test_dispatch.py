"""S5 dispatch. Every test's docstring opens with its ratified behavior id.

Ids are ratified in `.claude/overseer/slice/dispatch.md`; `scripts/check_ids.py`
diffs this file against that table in both directions.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Self

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


def test_failed_send_reads_differently_from_a_skip(tmp_path: Path) -> None:
    """D8.a a FAILED send is reported differently from a deliberate skip, by status."""
    # (1) the renderer branches on `status`, never on `detail`'s text. The last case
    # is deliberately adversarial: a SKIPPED outcome whose detail begins "failed: "
    # must still read "not sent" -- that is what kills a prefix-parsing renderer.
    cases = [
        (StageOutcome(status="ok", detail="SM999"), "- SMS: sent (SM999)"),
        (
            StageOutcome(status="skipped", detail="no template for 'x'"),
            "- SMS: not sent — no template for 'x'",
        ),
        (
            StageOutcome(status="failed", detail="TimeoutError: slow"),
            "- SMS: FAILED — TimeoutError: slow",
        ),
        (
            StageOutcome(status="skipped", detail="failed: not really"),
            "- SMS: not sent — failed: not really",
        ),
    ]
    for outcome, expected in cases:
        assert expected in _render(sms=outcome)

    # (2) and the value is asserted where dispatch COMPUTES it, not only where a
    # hand-built fixture supplies it -- a fake cannot be evidence for the contract
    # the fake implements. A real send failure must read FAILED, and a real skip
    # must read "not sent"; a conversion that labelled failures as skips passed
    # every assertion above until this half existed.
    failed = _dispatch(tmp_path, sms=FakeSms(exc=TimeoutError("slow")))
    assert "- SMS: FAILED — TimeoutError: slow" in failed.brief_path.read_text(
        encoding="utf-8"
    )

    skipped = _dispatch(tmp_path / "b", analysis=make_analysis(outcome="not_eligible"))
    assert "- SMS: not sent — no SMS template" in skipped.brief_path.read_text(
        encoding="utf-8"
    )


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


# --- senders.py -------------------------------------------------------------


class _FakeMessages:
    """Stands in for `client.messages`. Records the kwargs it was handed."""

    def __init__(self, sid: object) -> None:
        self._sid = sid
        self.calls: list[dict[str, object]] = []

    def create(self, **kw: object) -> object:
        self.calls.append(kw)
        return SimpleNamespace(sid=self._sid)


class _FakeClient:
    """Stands in for `twilio.rest.Client`, monkeypatched into the module.

    Injection is NOT used here: `TwilioSmsSender.__init__`'s parameter list is
    ratified, and widening it so tests can reach in is the same trade S3 already
    refused for `BridgeSession` (PROGRESS.md, S3 "Decided alone").
    """

    def __init__(self, sid: object) -> None:
        self.messages = _FakeMessages(sid)

    def __call__(self, account_sid: str, auth_token: str) -> Self:
        self.account_sid = account_sid
        self.auth_token = auth_token
        return self


def test_twilio_sender_raises_when_sdk_returns_no_sid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D9.a `TwilioSmsSender.send` raises when the SDK returns `sid=None`."""
    from decana.dispatch import senders
    from decana.dispatch.errors import DispatchError

    fake = _FakeClient(sid=None)
    monkeypatch.setattr(senders, "Client", fake)
    sender = senders.TwilioSmsSender("AC" + "0" * 32, "tok")
    with pytest.raises(DispatchError):
        sender.send(to="+447700900123", sender_id="BrokerSMS", body="hi")


class _FakeSmtp:
    """A context-managed stand-in for `smtplib.SMTP` / `SMTP_SSL`."""

    def __init__(self, host: str, port: int, timeout: float = 0.0) -> None:
        self.host = host
        self.port = port
        self.starttls_called = False
        self.logged_in: tuple[str, str] | None = None
        self.sent: list[object] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def starttls(self) -> None:
        self.starttls_called = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def send_message(self, msg: object) -> None:
        self.sent.append(msg)


def _patch_smtp(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[_FakeSmtp]]:
    """Record which transport class the sender reached for."""
    made: dict[str, list[_FakeSmtp]] = {"SMTP": [], "SMTP_SSL": []}

    def mk(kind: str):  # type: ignore[no-untyped-def]
        def factory(host: str, port: int, timeout: float = 0.0) -> _FakeSmtp:
            inst = _FakeSmtp(host, port, timeout)
            made[kind].append(inst)
            return inst

        return factory

    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", mk("SMTP"))
    monkeypatch.setattr(smtplib, "SMTP_SSL", mk("SMTP_SSL"))
    return made


def test_port_465_uses_implicit_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    """D11.a port 465 -> `SMTP_SSL`, and `starttls` is NOT called."""
    from decana.dispatch.senders import SmtpEmailSender

    made = _patch_smtp(monkeypatch)
    SmtpEmailSender("smtp.test", 465, "u", "p", "from@example.test").send(
        to="ops@example.test", subject="s", body="b"
    )
    assert len(made["SMTP_SSL"]) == 1
    assert made["SMTP"] == []
    assert made["SMTP_SSL"][0].starttls_called is False
    assert made["SMTP_SSL"][0].sent != []


def test_port_587_upgrades_with_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    """D11.b port 587 -> `SMTP` + `starttls` called."""
    from decana.dispatch.senders import SmtpEmailSender

    made = _patch_smtp(monkeypatch)
    SmtpEmailSender("smtp.test", 587, "u", "p", "from@example.test").send(
        to="ops@example.test", subject="s", body="b"
    )
    assert len(made["SMTP"]) == 1
    assert made["SMTP_SSL"] == []
    assert made["SMTP"][0].starttls_called is True
    assert made["SMTP"][0].logged_in == ("u", "p")


# --- dispatch.py ------------------------------------------------------------


class FakeSms:
    """Records what it was handed, and optionally raises or inspects the tree."""

    def __init__(
        self,
        sid: str = "SM_OK",
        exc: Exception | None = None,
        watch: Path | None = None,
    ) -> None:
        self.sid = sid
        self.exc = exc
        self.watch = watch
        self.calls: list[dict[str, str]] = []
        self.seen_at_call: dict[str, bool] = {}

    def send(self, *, to: str, sender_id: str, body: str) -> str:
        self.calls.append({"to": to, "sender_id": sender_id, "body": body})
        if self.watch is not None:
            self.seen_at_call = {p.name: p.exists() for p in _expected(self.watch)}
        if self.exc is not None:
            raise self.exc
        return self.sid


class FakeEmail:
    def __init__(self, exc: Exception | None = None, watch: Path | None = None) -> None:
        self.exc = exc
        self.watch = watch
        self.calls: list[dict[str, str]] = []
        self.seen_at_call: dict[str, bool] = {}

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.calls.append({"to": to, "subject": subject, "body": body})
        if self.watch is not None:
            self.seen_at_call = {p.name: p.exists() for p in _expected(self.watch)}
        if self.exc is not None:
            raise self.exc


def _expected(d: Path) -> list[Path]:
    sid = "CA_TEST_1"
    return [
        d / f"{sid}.transcript.txt",
        d / f"{sid}.analysis.json",
        d / f"{sid}.brief.md",
    ]


def _dispatch(tmp: Path, **over: object):  # type: ignore[no-untyped-def]
    """Sync wrapper: this repo runs coroutines with `asyncio.run` in sync tests
    (see tests/test_analysis.py) rather than depending on pytest-asyncio."""
    from decana.dispatch.dispatch import dispatch

    kw: dict[str, object] = {
        "record": make_record(),
        "analysis": make_analysis(),
        "profile": make_profile(),
        "sms": FakeSms(),
        "email": FakeEmail(),
        "artifact_dir": tmp,
    }
    kw.update(over)
    return asyncio.run(
        dispatch(
            kw.pop("record"),  # type: ignore[arg-type]
            kw.pop("analysis"),  # type: ignore[arg-type]
            kw.pop("profile"),  # type: ignore[arg-type]
            **kw,  # type: ignore[arg-type]
        )
    )


def test_transcript_file_is_render_transcript_output(tmp_path: Path) -> None:
    """D22.a `transcript.txt` equals `render_transcript(record.transcript)` exactly."""
    from decana.analysis.analyse import render_transcript

    record = make_record()
    _dispatch(tmp_path, record=record)
    written = (tmp_path / "CA_TEST_1.transcript.txt").read_text(encoding="utf-8")
    assert written == render_transcript(record.transcript)


def test_transcript_preserves_roles_and_order(tmp_path: Path) -> None:
    """D22.b role labels and turn ORDER are preserved (a reversed transcript fails)."""
    _dispatch(tmp_path)
    lines = (
        (tmp_path / "CA_TEST_1.transcript.txt").read_text(encoding="utf-8").splitlines()
    )
    assert lines == [
        "MODEL: Hello, how can I help?",
        "CALLER: I want to remortgage.",
        "MODEL: How much is outstanding?",
    ]


def test_non_ascii_transcript_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D22.c a non-ASCII transcript round-trips: the file reads back as UTF-8 unmangled."""
    import io as _io

    record = make_record(
        transcript=(TranscriptTurn(role="caller", text="I'm Siobhán — café, 200 £"),)
    )
    # Force a non-UTF-8 process default. `io.text_encoding` is what a bare
    # `write_text(...)` consults; an explicit `encoding="utf-8"` never reaches it.
    # Without this the test passes on any UTF-8 dev box whether or not the code
    # names its encoding -- verified: the mutation that drops the kwarg SURVIVED
    # until this patch was added.
    # Honour an explicit encoding and substitute only the DEFAULT -- `write_text`
    # calls `io.text_encoding(encoding)` unconditionally, so a lambda that ignored
    # its argument would override the explicit "utf-8" too and prove nothing.
    monkeypatch.setattr(
        _io, "text_encoding", lambda encoding=None, stacklevel=2: encoding or "ascii"
    )
    report = _dispatch(tmp_path, record=record)

    back = (tmp_path / "CA_TEST_1.transcript.txt").read_text(encoding="utf-8")
    assert "Siobhán" in back
    assert "café" in back
    assert "£" in back
    assert not [e for e in report.errors if e.startswith("transcript:")], report.errors


def test_evidence_exists_before_any_send(tmp_path: Path) -> None:
    """D5.a transcript + analysis.json exist ON DISK at the moment a sender is called."""
    sms = FakeSms(watch=tmp_path)
    email = FakeEmail(watch=tmp_path)
    _dispatch(tmp_path, sms=sms, email=email)
    assert sms.seen_at_call["CA_TEST_1.transcript.txt"] is True
    assert sms.seen_at_call["CA_TEST_1.analysis.json"] is True
    assert email.seen_at_call["CA_TEST_1.transcript.txt"] is True


def test_brief_is_written_last(tmp_path: Path) -> None:
    """D6.a brief does NOT exist when the email is sent, and DOES after `dispatch` returns."""
    email = FakeEmail(watch=tmp_path)
    report = _dispatch(tmp_path, email=email)
    assert email.seen_at_call["CA_TEST_1.brief.md"] is False
    assert report.brief_path.exists() is True


def _marker(tmp: Path) -> Path:
    return tmp / "CA_TEST_1.sms-sent"


def test_no_sms_when_outcome_has_no_template(tmp_path: Path) -> None:
    """D4.a no SMS when `analysis.outcome` has no template; detail says so; email still sent."""
    sms, email = FakeSms(), FakeEmail()
    report = _dispatch(
        tmp_path, analysis=make_analysis(outcome="not_eligible"), sms=sms, email=email
    )
    assert sms.calls == []
    assert email.calls != []
    assert report.brief_path.exists()
    assert (
        "- SMS: not sent — no SMS template for 'not_eligible'"
        in report.brief_path.read_text(encoding="utf-8")
    )


def test_no_sms_when_caller_number_withheld(tmp_path: Path) -> None:
    """D4.b no SMS when `caller_number` is empty; detail says so; email still sent."""
    sms, email = FakeSms(), FakeEmail()
    report = _dispatch(
        tmp_path, record=make_record(caller_number=""), sms=sms, email=email
    )
    assert sms.calls == []
    assert email.calls != []
    assert "- SMS: not sent — caller number withheld" in report.brief_path.read_text(
        encoding="utf-8"
    )


def test_no_sms_when_marker_already_exists(tmp_path: Path) -> None:
    """D4.c no SMS when the marker already exists; detail says so; email still sent."""
    _marker(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    _marker(tmp_path).write_text("prior", encoding="utf-8")
    sms, email = FakeSms(), FakeEmail()
    report = _dispatch(tmp_path, sms=sms, email=email)
    assert sms.calls == []
    assert email.calls != []
    assert (
        "- SMS: not sent — already sent for this call"
        in report.brief_path.read_text(encoding="utf-8")
    )


def test_marker_survives_a_failed_send(tmp_path: Path) -> None:
    """D2.a a send that RAISES still leaves the marker on disk."""
    _dispatch(tmp_path, sms=FakeSms(exc=RuntimeError("twilio down")))
    assert _marker(tmp_path).exists()


def test_second_dispatch_sends_no_second_sms(tmp_path: Path) -> None:
    """D2.b a second `dispatch` sends no second SMS, but STILL emails and writes the brief."""
    _dispatch(tmp_path, sms=FakeSms(exc=RuntimeError("twilio down")))
    sms2, email2 = FakeSms(), FakeEmail()
    report = _dispatch(tmp_path, sms=sms2, email=email2)
    assert sms2.calls == []
    assert email2.calls != []
    assert report.brief_path.exists()


def test_successful_send_sets_sms_sid(tmp_path: Path) -> None:
    """D8.b a real send sets `sms_sid` to the sid returned."""
    report = _dispatch(tmp_path, sms=FakeSms(sid="SM_REAL_9"))
    assert report.sms_sid == "SM_REAL_9"


def test_sidless_send_becomes_one_error(tmp_path: Path) -> None:
    """D9.b `dispatch` turns a sid-less send into one `sms:` error with `sms_sid is None`."""
    from decana.dispatch.errors import DispatchError

    report = _dispatch(tmp_path, sms=FakeSms(exc=DispatchError("returned no sid")))
    assert report.sms_sid is None
    assert [e for e in report.errors if e.startswith("sms:")] == [
        "sms: DispatchError: returned no sid"
    ]


def test_email_subject_is_exact(tmp_path: Path) -> None:
    """D16.a subject is exactly `[{display_name}] {outcome} — {caller_number}`."""
    email = FakeEmail()
    _dispatch(tmp_path, email=email)
    assert (
        email.calls[0]["subject"]
        == "[UK mortgage broker intake] qualified_lead — +447700900123"
    )


def test_sms_body_has_links_substituted(tmp_path: Path) -> None:
    """D17.a SMS body has links substituted and contains no `{`."""
    sms = FakeSms()
    _dispatch(tmp_path, sms=sms)
    body = sms.calls[0]["body"]
    assert body == "Thanks! Book here: https://book.test/x"
    assert "{" not in body


def test_sender_kwargs_come_from_the_right_fields(tmp_path: Path) -> None:
    """D21.e the SMS sender is called with `to=caller_number`, `sender_id=sms_sender_id`."""
    sms = FakeSms()
    _dispatch(tmp_path, sms=sms)
    assert sms.calls[0]["to"] == "+447700900123"
    assert sms.calls[0]["sender_id"] == "BrokerSMS"


def test_email_goes_to_operator(tmp_path: Path) -> None:
    """D21.f the email sender is called with `to=profile.operator_email`."""
    email = FakeEmail()
    _dispatch(tmp_path, email=email)
    assert email.calls[0]["to"] == "ops@example.test"


def test_sms_failure_does_not_block_email(tmp_path: Path) -> None:
    """D7.a SMS fails -> one `sms:` error, email still sent."""
    email = FakeEmail()
    report = _dispatch(tmp_path, sms=FakeSms(exc=TimeoutError("slow")), email=email)
    assert [e for e in report.errors if e.startswith("sms:")] == [
        "sms: TimeoutError: slow"
    ]
    assert email.calls != []


def test_email_failure_does_not_block_sms(tmp_path: Path) -> None:
    """D7.b email fails -> one `email:` error, SMS still sent."""
    sms = FakeSms()
    report = _dispatch(tmp_path, sms=sms, email=FakeEmail(exc=OSError("no route")))
    assert [e for e in report.errors if e.startswith("email:")] == [
        "email: OSError: no route"
    ]
    assert sms.calls != []
    assert report.email_sent is False


def test_email_sent_flag_tracks_reality(tmp_path: Path) -> None:
    """D23.a `email_sent` is True only on a real send, False when the email raised."""
    assert _dispatch(tmp_path).email_sent is True
    assert _dispatch(tmp_path, email=FakeEmail(exc=OSError("x"))).email_sent is False


def test_empty_transcript_still_produces_everything(tmp_path: Path) -> None:
    """D18.a an empty transcript still produces all three files and an email."""
    email = FakeEmail()
    report = _dispatch(
        tmp_path,
        record=make_record(transcript=()),
        analysis=make_analysis(outcome="unclassified", summary="empty transcript"),
        email=email,
    )
    for path in _expected(tmp_path):
        assert path.exists(), path
    assert email.calls != []
    assert report.brief_path.exists()


def test_evidence_written_even_when_both_senders_raise(tmp_path: Path) -> None:
    """D5.b both evidence files exist even when both senders raise."""
    _dispatch(
        tmp_path,
        sms=FakeSms(exc=RuntimeError("a")),
        email=FakeEmail(exc=RuntimeError("b")),
    )
    assert (tmp_path / "CA_TEST_1.transcript.txt").exists()
    assert (tmp_path / "CA_TEST_1.analysis.json").exists()


def test_loop_stays_responsive_while_a_sender_blocks(tmp_path: Path) -> None:
    """D1.a the event loop stays responsive while a sender is blocked (`to_thread`)."""
    from decana.dispatch.dispatch import dispatch

    release = threading.Event()
    outcome: dict[str, bool] = {}

    class Blocking:
        def send(self, *, to: str, sender_id: str, body: str) -> str:
            # If the loop is BLOCKED by this call, the releaser coroutine below can
            # never run, so this wait times out and `released` is False. If the call
            # is on a worker thread, the loop runs the releaser and this returns True.
            # A binary, with no tick threshold to tune.
            outcome["released"] = release.wait(1.5)
            return "SM_SLOW"

    async def go() -> None:
        task = asyncio.create_task(
            dispatch(
                make_record(),
                make_analysis(),
                make_profile(),
                sms=Blocking(),
                email=FakeEmail(),
                artifact_dir=tmp_path,
            )
        )
        await asyncio.sleep(0.05)
        release.set()
        await task

    asyncio.run(go())
    assert outcome["released"] is True


def test_transcript_failure_still_emails_and_briefs(tmp_path: Path) -> None:
    """D12.a a failed transcript write still emails, writes the brief, and names it in both."""
    (tmp_path / "CA_TEST_1.transcript.txt").mkdir(parents=True)
    email = FakeEmail()
    report = _dispatch(tmp_path, email=email)
    assert email.calls != []
    assert report.brief_path.exists()
    line_fragment = "- Transcript file: FAILED — IsADirectoryError"
    assert line_fragment in email.calls[0]["body"]
    assert line_fragment in report.brief_path.read_text(encoding="utf-8")
    assert any(e.startswith("transcript: IsADirectoryError") for e in report.errors)


def _one_stage_fails(tmp_path: Path, stage: str) -> tuple[object, FakeEmail]:
    """Make exactly ONE stage fail; return the report and the email spy.

    Five ids call this, one per stage -- deliberately five separate test
    functions rather than one parametrized case, because `check_ids.py` reads the
    FIRST id in a docstring and a single parametrized test can only declare one.
    Counting the family is the point (Seam 13).
    """
    over: dict[str, object] = {}
    if stage in {"transcript", "analysis", "brief"}:
        suffix = {
            "transcript": "transcript.txt",
            "analysis": "analysis.json",
            "brief": "brief.md",
        }[stage]
        (tmp_path / f"CA_TEST_1.{suffix}").mkdir(parents=True)
    elif stage == "sms":
        over["sms"] = FakeSms(exc=RuntimeError("boom"))
    else:
        over["email"] = FakeEmail(exc=RuntimeError("boom"))

    email = over.get("email") or FakeEmail()
    over["email"] = email
    report = _dispatch(tmp_path, **over)
    assert isinstance(email, FakeEmail)
    return report, email


def _assert_stage_isolated(report: object, email: FakeEmail, stage: str) -> None:
    errors = report.errors  # type: ignore[attr-defined]
    brief_path = report.brief_path  # type: ignore[attr-defined]
    assert any(e.startswith(f"{stage}:") for e in errors), errors
    if stage != "email":
        assert email.calls != []
    if stage == "brief":
        assert not brief_path.is_file()
    else:
        assert brief_path.is_file()


def test_transcript_stage_fails_alone(tmp_path: Path) -> None:
    """D13.a transcript stage fails -> report returned, later stages ran, brief written."""
    report, email = _one_stage_fails(tmp_path, "transcript")
    _assert_stage_isolated(report, email, "transcript")


def test_analysis_stage_fails_alone(tmp_path: Path) -> None:
    """D13.b analysis stage fails -> report returned, later stages ran, brief written."""
    report, email = _one_stage_fails(tmp_path, "analysis")
    _assert_stage_isolated(report, email, "analysis")


def test_sms_stage_fails_alone(tmp_path: Path) -> None:
    """D13.c sms stage fails -> report returned, later stages ran, brief written."""
    report, email = _one_stage_fails(tmp_path, "sms")
    _assert_stage_isolated(report, email, "sms")


def test_email_stage_fails_alone(tmp_path: Path) -> None:
    """D13.d email stage fails -> report returned, later stages ran, brief written."""
    report, email = _one_stage_fails(tmp_path, "email")
    _assert_stage_isolated(report, email, "email")


def test_brief_stage_fails_alone(tmp_path: Path) -> None:
    """D13.e brief stage fails -> report returned, `errors` names `brief`, file absent."""
    report, email = _one_stage_fails(tmp_path, "brief")
    _assert_stage_isolated(report, email, "brief")


def test_render_brief_failure_is_attributed_to_the_right_stage(tmp_path: Path) -> None:
    """D14.a `render_brief` raising on the FIRST call is an `email:` error; brief still written."""
    from decana.dispatch import dispatch as mod

    real = getattr(mod, "render_brief")  # noqa: B009 - avoids no-implicit-reexport
    calls = {"n": 0}

    def flaky(*a: object, **k: object) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("render blew up")
        out = real(*a, **k)
        assert isinstance(out, str)
        return out

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "render_brief", flaky)
        report = _dispatch(tmp_path)
    assert any(e.startswith("email: ValueError") for e in report.errors), report.errors
    assert report.brief_path.exists()


def test_render_brief_failure_on_second_call_is_brief_stage(tmp_path: Path) -> None:
    """D14.b `render_brief` raising on the SECOND call is a `brief:` error; email still sent."""
    from decana.dispatch import dispatch as mod

    real = getattr(mod, "render_brief")  # noqa: B009 - avoids no-implicit-reexport
    calls = {"n": 0}

    def flaky(*a: object, **k: object) -> str:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("render blew up late")
        out = real(*a, **k)
        assert isinstance(out, str)
        return out

    email = FakeEmail()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "render_brief", flaky)
        report = _dispatch(tmp_path, email=email)
    assert any(e.startswith("brief: ValueError") for e in report.errors), report.errors
    assert email.calls != []


class FakeAnalysisClient:
    def __init__(self, exc: BaseException | None = None) -> None:
        self.exc = exc

    async def generate_json(
        self, *, model: str, system: str, user: str, schema: dict[str, object]
    ) -> str:
        if self.exc is not None:
            raise self.exc
        return '{"outcome": "qualified_lead", "compliance_notes": [], "summary": "ok"}'


def test_post_call_swallows_a_directory_failure(tmp_path: Path) -> None:
    """D10.a `post_call` returns None (does not raise) when `artifact_dir` cannot be created."""
    from decana.dispatch.dispatch import post_call

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file", encoding="utf-8")

    assert (
        asyncio.run(
            post_call(
                make_record(),
                profile=make_profile(),
                analysis_client=FakeAnalysisClient(),  # type: ignore[arg-type]
                sms=FakeSms(),
                email=FakeEmail(),
                artifact_dir=blocker,
            )
        )
        is None
    )


def test_post_call_lets_cancellation_propagate(tmp_path: Path) -> None:
    """D10.b `post_call` lets `CancelledError` PROPAGATE."""
    from decana.dispatch.dispatch import post_call

    async def go() -> None:
        await post_call(
            make_record(),
            profile=make_profile(),
            analysis_client=FakeAnalysisClient(exc=asyncio.CancelledError()),  # type: ignore[arg-type]
            sms=FakeSms(),
            email=FakeEmail(),
            artifact_dir=tmp_path,
        )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(go())


# --- wiring.py --------------------------------------------------------------


def _settings(tmp: Path, **over: str) -> object:
    """Settings built from a fake env, with both credential groups present."""
    from decana.settings import Settings

    env = {
        "DECANA_PROFILE": "broker-slug",
        "GEMINI_API_KEY": "gk",
        "PUBLIC_WSS_URL": "wss://x.test",
        "DECANA_ARTIFACT_DIR": str(tmp),
        "TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
        "TWILIO_AUTH_TOKEN": "tok",
        "SMTP_HOST": "smtp.test",
        "SMTP_PORT": "587",
        "SMTP_USER": "u",
        "SMTP_PASSWORD": "p",
        "SMTP_FROM": "from@example.test",
    }
    env.update(over)
    for k in [k for k, v in env.items() if v == ""]:
        del env[k]
    return Settings.from_env(env)


def _run_handler(tmp: Path, **over: str) -> tuple[list[str], Path]:
    """Build the real handler, await it on a record, and report what it did."""
    from decana.dispatch.wiring import build_on_call_end

    seen: list[str] = []

    class RecordingSms:
        def send(self, *, to: str, sender_id: str, body: str) -> str:
            seen.append("sms")
            return "SM_WIRED"

    class RecordingEmail:
        def send(self, *, to: str, subject: str, body: str) -> None:
            seen.append("email")

    # Patch the names in WIRING's namespace: it imports them directly, so patching
    # the senders module would leave its references untouched.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "decana.dispatch.wiring.TwilioSmsSender", lambda *a, **k: RecordingSms()
        )
        mp.setattr(
            "decana.dispatch.wiring.SmtpEmailSender", lambda *a, **k: RecordingEmail()
        )
        mp.setattr(
            "decana.dispatch.wiring.GeminiAnalysisClient",
            lambda **k: FakeAnalysisClient(),
        )
        handler = build_on_call_end(_settings(tmp, **over), make_profile())  # type: ignore[arg-type]
        coro = handler(make_record())
        assert asyncio.iscoroutine(coro)
        asyncio.run(coro)
    return seen, tmp / "CA_TEST_1.brief.md"


def test_handler_invokes_analysis_and_both_senders(tmp_path: Path) -> None:
    """D15.a `build_on_call_end` returns a handler that actually invokes analysis + BOTH senders."""
    seen, brief = _run_handler(tmp_path)
    assert "sms" in seen
    assert "email" in seen
    assert brief.exists()


def test_twilio_absent_still_emails(tmp_path: Path) -> None:
    """D15.c Twilio absent / SMTP present: the email is STILL sent; sms stage names the gap."""
    seen, brief = _run_handler(tmp_path, TWILIO_ACCOUNT_SID="", TWILIO_AUTH_TOKEN="")
    assert "email" in seen
    assert "sms" not in seen
    assert "no Twilio credentials configured" in brief.read_text(encoding="utf-8")


def test_smtp_absent_still_sends_sms(tmp_path: Path) -> None:
    """D15.d SMTP absent / Twilio present: the SMS still goes; the brief records the email failure."""
    seen, brief = _run_handler(tmp_path, SMTP_HOST="", SMTP_USER="")
    assert "sms" in seen
    assert "email" not in seen
    assert "no SMTP credentials configured" in brief.read_text(encoding="utf-8")


def test_both_credential_groups_absent(tmp_path: Path) -> None:
    """D15.e both groups absent: all three files are still written and the brief names both."""
    seen, brief = _run_handler(
        tmp_path,
        TWILIO_ACCOUNT_SID="",
        TWILIO_AUTH_TOKEN="",
        SMTP_HOST="",
        SMTP_USER="",
    )
    assert seen == []
    for path in _expected(tmp_path):
        assert path.exists(), path
    text = brief.read_text(encoding="utf-8")
    assert "no Twilio credentials configured" in text
    assert "no SMTP credentials configured" in text


def test_server_does_not_import_dispatch_or_analysis() -> None:
    """D24.a `decana.twilio.server` imports nothing from `decana.dispatch`/`decana.analysis`."""
    import ast
    from pathlib import Path as _P

    src = _P("src/decana/twilio/server.py").read_text(encoding="utf-8")
    named: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            named += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            named.append(node.module)
    offenders = [
        m for m in named if m.startswith(("decana.dispatch", "decana.analysis"))
    ]
    assert offenders == [], offenders
