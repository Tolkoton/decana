"""The composition of the real `OnCallEnd`.

WHY THIS FILE EXISTS, AND NOT `twilio/server.py` (S5-Q24): `build_on_call_end`
must construct `post_call`, `GeminiAnalysisClient` and the two senders. Leaving
it in `server.py` would make S3 import S4 and S5, which the ratified Edge S3
text forbids in terms ("S3 does not import S4/S5 -- same DI convention as
`TwilioMediaStreamClient`/`GeminiLiveSessionClient`"). S3's own note that the
function "lives in `server.py`" is recorded in PROGRESS.md under "Decided alone
(one line each, overrule if wrong)" -- the weaker of the two statements, so it
is the one that moved.

`__main__` still holds no logic: it imports from here and calls once.

WHAT THIS DOES NOT DO: it does not read the environment. `Settings` did that.
"""

import logging
from functools import partial

from decana.analysis.gemini_client import GeminiAnalysisClient
from decana.dispatch.dispatch import post_call
from decana.dispatch.senders import (
    EmailSender,
    SmsSender,
    SmtpEmailSender,
    TwilioSmsSender,
    UnconfiguredEmailSender,
    UnconfiguredSmsSender,
)
from decana.profile.model import Profile
from decana.settings import Settings
from decana.twilio.records import OnCallEnd

__all__ = ["build_on_call_end"]

logger = logging.getLogger(__name__)


def _sms_sender(settings: Settings) -> SmsSender:
    """Real sender iff BOTH Twilio credentials are present."""
    if settings.has_twilio:
        assert settings.twilio_account_sid is not None
        assert settings.twilio_auth_token is not None
        return TwilioSmsSender(settings.twilio_account_sid, settings.twilio_auth_token)
    logger.warning(
        "TWILIO_* not set: SMS will be recorded as failed, other effects unaffected"
    )
    return UnconfiguredSmsSender()


def _email_sender(settings: Settings) -> EmailSender:
    """Real sender iff ALL FIVE SMTP settings are present."""
    if settings.has_smtp:
        assert settings.smtp_host is not None
        assert settings.smtp_port is not None
        assert settings.smtp_user is not None
        assert settings.smtp_password is not None
        assert settings.smtp_from is not None
        return SmtpEmailSender(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_user,
            settings.smtp_password,
            settings.smtp_from,
        )
    logger.warning(
        "SMTP_* not set: email will be recorded as failed, other effects unaffected"
    )
    return UnconfiguredEmailSender()


def build_on_call_end(settings: Settings, profile: Profile) -> OnCallEnd:
    """The real post-call handler. Always `post_call` -- there is no log-only fallback.

    The two credential groups gate INDEPENDENTLY, and neither gates `post_call`
    itself (S5-Q23): analysis, the two evidence files and the brief need no
    optional credential, so a missing Twilio secret must not cost a real call its
    entire record. A group that is absent yields a sender that raises, which the
    brief and `DispatchReport.errors` both report.
    """
    return partial(
        post_call,
        profile=profile,
        analysis_client=GeminiAnalysisClient(api_key=settings.gemini_api_key),
        sms=_sms_sender(settings),
        email=_email_sender(settings),
        artifact_dir=settings.artifact_dir,
    )
