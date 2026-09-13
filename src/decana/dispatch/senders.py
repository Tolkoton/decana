"""The two outbound side effects, and the pair that stands in when unconfigured.

WHAT: thin adapters over `twilio.rest` and `smtplib`, behind the two Protocols
`dispatch` consumes.

WHY BOTH ARE SYNC: `dispatch` awaits them via `asyncio.to_thread`. Both vendor
libraries block, and `post_call` runs on the event loop that is forwarding audio
for every other live call -- a blocking `sendmail` is dead air on a stranger's
call (S5-Q5).

WHAT THIS DOES NOT DO: no retry, no backoff, no connection reuse across calls.
One attempt each; `dispatch` records the outcome.
"""

import smtplib
from email.message import EmailMessage
from typing import Protocol

from twilio.rest import Client

from decana.dispatch.errors import DispatchError

__all__ = [
    "EmailSender",
    "SmsSender",
    "SmtpEmailSender",
    "TwilioSmsSender",
    "UnconfiguredEmailSender",
    "UnconfiguredSmsSender",
]

_SMTP_TIMEOUT_S = 30.0
"""Bounded on purpose: an unbounded connect blocks the thread `to_thread` lent us."""


class SmsSender(Protocol):
    """What `dispatch` needs to send one SMS. Returns the message sid."""

    def send(self, *, to: str, sender_id: str, body: str) -> str: ...


class EmailSender(Protocol):
    """What `dispatch` needs to send one email."""

    def send(self, *, to: str, subject: str, body: str) -> None: ...


class TwilioSmsSender:
    """One SMS via `twilio.rest`.

    The SDK is untyped (no `py.typed`), so everything it returns is `Any` to
    mypy. `MessageInstance.sid` is `Optional[str]` -- set in `__init__` from the
    response payload, so it is absent from `dir()` and can be `None` at runtime
    (SDK source `message/__init__.py:119`). The ratified Protocol returns `str`,
    so this narrows at the boundary rather than passing `None` upwards as a sid
    the brief would then report as a success (S5-Q2).
    """

    def __init__(self, account_sid: str, auth_token: str) -> None:
        self._client = Client(account_sid, auth_token)

    def send(self, *, to: str, sender_id: str, body: str) -> str:
        """Send, then insist the response actually carried a sid."""
        message = self._client.messages.create(to=to, from_=sender_id, body=body)
        sid = message.sid
        if not isinstance(sid, str) or not sid:
            raise DispatchError("twilio accepted the message but returned no sid")
        return sid


class SmtpEmailSender:
    """One email via `smtplib`.

    Transport is chosen by PORT: 465 means implicit TLS (`SMTP_SSL`), anything
    else means connect plaintext and upgrade with `starttls()` (S5-Q3). This
    needs no extra config key, and the stdlib pins `SMTP_SSL_PORT = 465`.

    The "465 is implicit-TLS everywhere" half of that is ASSUMED, not measured --
    falsified by any provider this is pointed at that wants STARTTLS on 465. It
    would surface in S6's deploy doc, and it is recorded as an open assumption in
    the slice artifact rather than presented as verified.

    There is deliberately no plaintext fallback: a server that does not offer
    STARTTLS makes `starttls()` raise, and that failure is recorded rather than
    silently downgraded. This line carries call transcripts.
    """

    def __init__(
        self, host: str, port: int, user: str, password: str, from_addr: str
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from = from_addr

    def send(self, *, to: str, subject: str, body: str) -> None:
        """Flow: build the message -> open the right transport -> authenticate -> send."""
        message = self._build(to=to, subject=subject, body=body)
        if self._port == smtplib.SMTP_SSL_PORT:
            with smtplib.SMTP_SSL(
                self._host, self._port, timeout=_SMTP_TIMEOUT_S
            ) as conn:
                conn.login(self._user, self._password)
                conn.send_message(message)
            return
        with smtplib.SMTP(self._host, self._port, timeout=_SMTP_TIMEOUT_S) as conn:
            conn.starttls()
            conn.login(self._user, self._password)
            conn.send_message(message)

    def _build(self, *, to: str, subject: str, body: str) -> EmailMessage:
        """One plain-text message. No HTML, no attachments -- both are out of scope."""
        message = EmailMessage()
        message["From"] = self._from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        return message


class UnconfiguredSmsSender:
    """Stands in when the Twilio credentials are absent (S5-Q23).

    It RAISES rather than silently no-op'ing, so the stage records `failed` with
    the reason and the brief tells the operator an SMS was owed and not sent.
    Reported as `failed` rather than `skipped` on purpose: a skip means a
    deliberate policy decision, and this is a deployment gap.
    """

    def send(self, *, to: str, sender_id: str, body: str) -> str:
        raise DispatchError("no Twilio credentials configured")


class UnconfiguredEmailSender:
    """Stands in when the SMTP settings are absent (S5-Q23)."""

    def send(self, *, to: str, subject: str, body: str) -> None:
        raise DispatchError("no SMTP credentials configured")
