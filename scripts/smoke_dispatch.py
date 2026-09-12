"""Real-environment check for the dispatch slice. Three tiers, two of which park.

TIER 1 always runs and needs NO credentials. The environment S5 actually touches
is the filesystem, and this exercises the real one: a real temp `artifact_dir`,
the real `dispatch`, real `Path.open("x")`, real `asyncio.to_thread`, with fake
senders. Every assertion is machine-checkable -- NO HUMAN ORACLE -- so it runs to
completion and its output goes in the transcript.

TIER 2 PARKS without SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/SMTP_FROM.
TIER 3 PARKS without TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN, and COSTS MONEY -- it
spends the `_budget` cap BEFORE opening any socket, so a crash-loop cannot exceed
it, and needs DECANA_SMOKE_SMS_TO to say where to send.

Until 2 and 3 run, `SmtpEmailSender` and `TwilioSmsSender` are verified only by
fakes they implement -- which this project has recorded as no evidence at all.

Usage:  uv run python scripts/smoke_dispatch.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _budget import Budget

from decana.analysis.model import Analysis
from decana.dispatch.dispatch import dispatch
from decana.dispatch.model import DispatchReport
from decana.profile.load import load_profile
from decana.twilio.records import CallRecord, TranscriptTurn

REPO_ROOT = Path(__file__).resolve().parent.parent
SID = "SMOKE_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

FIXTURE = (
    TranscriptTurn(role="model", text="Hello, thanks for calling. How can I help?"),
    TranscriptTurn(
        role="caller", text="I want to remortgage my flat in Manchester — I'm Siobhán."
    ),
    TranscriptTurn(
        role="model", text="How much is outstanding on the current mortgage?"
    ),
    TranscriptTurn(role="caller", text="About 180 thousand."),
)


class _Watcher:
    """Snapshots which artifacts exist at the moment it is called."""

    def __init__(self, watch: Path) -> None:
        self.watch = watch
        self.seen: dict[str, bool] = {}

    def _snapshot(self) -> None:
        self.seen = {
            suffix: (self.watch / f"{SID}.{suffix}").exists()
            for suffix in ("transcript.txt", "analysis.json", "brief.md")
        }


class _FakeSms(_Watcher):
    """Satisfies `SmsSender`: returns a sid."""

    def __init__(self, watch: Path, sid: str = "SM_SMOKE") -> None:
        super().__init__(watch)
        self.sid = sid
        self.calls: list[dict[str, str]] = []

    def send(self, *, to: str, sender_id: str, body: str) -> str:
        self.calls.append({"to": to, "sender_id": sender_id, "body": body})
        self._snapshot()
        return self.sid


class _FakeEmail(_Watcher):
    """Satisfies `EmailSender`: returns None. Split from the SMS fake because one
    class cannot satisfy both Protocols -- mypy --strict caught the conflation."""

    def __init__(self, watch: Path) -> None:
        super().__init__(watch)
        self.calls: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.calls.append({"to": to, "subject": subject, "body": body})
        self._snapshot()


def _record(tmp: Path) -> CallRecord:
    return CallRecord(
        call_sid=SID,
        caller_number="+447700900123",
        profile_name="mortgage-broker",
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        transcript=FIXTURE,
        timing_path=tmp / f"{SID}.jsonl",
        ended_reason="twilio_stop",
    )


def _analysis() -> Analysis:
    """Outcome drawn from the REAL profile's vocabulary, not a synthetic one.

    The unit suite uses a fabricated profile, so nothing there meets the shipped
    `outcomes` tuple or the single `sms` key it actually carries. This is the only
    place the two meet -- and on the first run they did not: the fixture said
    `qualified_lead`, which is not in the vocabulary, so the SMS gate correctly
    skipped and the smoke reported a missing marker.
    """
    return Analysis(
        outcome="new_client",
        compliance_notes=("Did not restate the recording notice.",),
        summary="Caller wants to remortgage a flat in Manchester, ~180k outstanding.",
        raw='{"outcome": "new_client"}',
    )


def tier1() -> int:
    """The filesystem half, end to end, against the real tree."""
    profile = load_profile("mortgage-broker", root=REPO_ROOT / "profiles")
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(
            f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}"
        )
        if not ok:
            failures.append(label)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        sms, email = _FakeSms(tmp), _FakeEmail(tmp)
        record, analysis = _record(tmp), _analysis()

        report: DispatchReport = asyncio.run(
            dispatch(record, analysis, profile, sms=sms, email=email, artifact_dir=tmp)
        )

        print(f"\nTIER 1 — real filesystem, fake senders (artifact_dir={tmp})")
        check(
            "all three files exist",
            all(
                (tmp / f"{SID}.{s}").exists()
                for s in ("transcript.txt", "analysis.json", "brief.md")
            ),
        )
        check(
            "evidence existed BEFORE the email was sent",
            email.seen.get("transcript.txt") is True
            and email.seen.get("analysis.json") is True,
        )
        check(
            "brief did NOT exist when the email was sent",
            email.seen.get("brief.md") is False,
        )
        check("marker written", (tmp / f"{SID}.sms-sent").exists())

        brief = (tmp / f"{SID}.brief.md").read_text(encoding="utf-8")
        body = email.calls[0]["body"]
        diff = [ln for ln in brief.splitlines() if ln not in body.splitlines()]
        check(
            "email body is the brief minus exactly one line", len(diff) == 1, repr(diff)
        )
        check(
            "the omitted line is the Email: line",
            diff[:1] == [f"- Email: sent to {profile.operator_email}"]
            if diff
            else False,
        )
        check("brief carries the summary", analysis.summary in brief)
        check(
            "brief carries the compliance note",
            "Did not restate the recording notice." in brief,
        )
        check(
            "brief carries the outcome in the body",
            "## Outcome\nnew_client" in brief,
        )
        check(
            "non-ASCII survived the transcript round-trip",
            "Siobhán" in (tmp / f"{SID}.transcript.txt").read_text(encoding="utf-8"),
        )
        check("SMS body has links substituted", "{" not in sms.calls[0]["body"])
        check("no errors on the happy path", report.errors == (), repr(report.errors))

        # at-most-once: a second dispatch must not re-send
        sms2 = _FakeSms(tmp)
        asyncio.run(
            dispatch(
                record,
                analysis,
                profile,
                sms=sms2,
                email=_FakeEmail(tmp),
                artifact_dir=tmp,
            )
        )
        check("second dispatch sent no second SMS", sms2.calls == [])

    print(f"\nTIER 1: {'PASSED' if not failures else 'FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


def tier2() -> int:
    """The real SMTP adapter against a real server."""
    need = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        print(f"\nTIER 2: PARKED — needs {', '.join(missing)}")
        return 0

    from decana.dispatch.senders import SmtpEmailSender

    profile = load_profile("mortgage-broker", root=REPO_ROOT / "profiles")
    sender = SmtpEmailSender(
        os.environ["SMTP_HOST"],
        int(os.environ["SMTP_PORT"]),
        os.environ["SMTP_USER"],
        os.environ["SMTP_PASSWORD"],
        os.environ["SMTP_FROM"],
    )
    sender.send(
        to=profile.operator_email,
        subject=f"[smoke] dispatch {SID}",
        body="smoke tier 2",
    )
    print(
        f"\nTIER 2: PASSED — one email sent to {profile.operator_email} via port {os.environ['SMTP_PORT']}"
    )
    return 0


def tier3() -> int:
    """The real Twilio adapter. Costs money; budget is spent before the socket opens."""
    missing = [
        k for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN") if not os.environ.get(k)
    ]
    to = os.environ.get("DECANA_SMOKE_SMS_TO")
    if missing or not to:
        print(
            f"\nTIER 3: PARKED — needs {', '.join(missing + ([] if to else ['DECANA_SMOKE_SMS_TO']))}"
        )
        return 0

    budget = Budget(REPO_ROOT / ".claude/overseer/.api-budget.json")
    if not budget.try_spend("smoke_dispatch"):
        print("\nTIER 3: PARKED — daily budget spent")
        return 0

    from decana.dispatch.senders import TwilioSmsSender

    profile = load_profile("mortgage-broker", root=REPO_ROOT / "profiles")
    sid = TwilioSmsSender(
        os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]
    ).send(to=to, sender_id=profile.sms_sender_id, body=f"decana smoke {SID}")
    print(
        f"\nTIER 3: PASSED — sid={sid!r} (non-empty str, so P2's narrowing holds on a REAL response)"
    )
    return 0


def main() -> int:
    print("=" * 72)
    print(
        "smoke_dispatch — S5. Tier 1 always runs; tiers 2 and 3 park without credentials."
    )
    print("=" * 72)
    return tier1() or tier2() or tier3()


if __name__ == "__main__":
    raise SystemExit(main())
