"""Every environment variable this process reads, in exactly one place.

WHAT: `Settings.from_env()` -- a frozen snapshot of the process configuration,
built once at startup. A missing required variable exits 2 naming the variable.

WHY one place: it is what lets `create_app` be driven entirely by fakes, which
is this slice's whole exit criterion. A module that reads `os.environ` at the
point of use cannot be tested without mutating the process environment, and the
first thing that goes wrong in a container is a variable nobody read.

WHAT THIS DOES NOT DO: it does not validate the VALUES (that a URL is reachable
or a key is live) -- only that the required ones are present. The Twilio and
SMTP variables are deliberately absent: the feature's env table marks them
"tracer: optional, unused", and S5 adds them when it needs them.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import decana

__all__ = ["Settings"]

# Cloud Run injects PORT; 8080 is its own default, so a local run matches it.
_DEFAULT_PORT = 8080
_DEFAULT_ARTIFACT_DIR = Path(".claude/artifacts/calls")


def _repo_profiles_root() -> Path:
    """`<repo root>/profiles`, resolved from the package, never from CWD.

    profile-loader Q7: a CWD-relative default would make the container's WORKDIR
    a load-bearing, untested assumption. W-1 stands -- this resolution assumes an
    editable install, so a non-editable image must set DECANA_PROFILES_ROOT.
    """
    return Path(decana.__file__).resolve().parents[2] / "profiles"


def _require(env: Mapping[str, str], name: str) -> str:
    """Read a required variable, or exit 2 naming it.

    Exits here rather than raising for `__main__` to catch, because `__main__`
    is wiring only: giving it a branch would be the first crack in that rule.
    """
    value = env.get(name, "")
    if not value:
        print(f"decana: missing required environment variable: {name}", file=sys.stderr)
        raise SystemExit(2)
    return value


@dataclass(frozen=True)
class Settings:
    """The configuration this process was started with."""

    profile_name: str
    gemini_api_key: str
    public_wss_url: str
    profiles_root: Path
    artifact_dir: Path
    port: int

    # Optional-until-present (S5-Q9). Ratified so the tracer build never requires
    # secrets it does not use; S5 reads them and degrades per GROUP, never globally.
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    @property
    def has_twilio(self) -> bool:
        """Both Twilio credentials present. Gates the SMS sender and NOTHING else."""
        return bool(self.twilio_account_sid and self.twilio_auth_token)

    @property
    def has_smtp(self) -> bool:
        """All five SMTP settings present. Gates the email sender and NOTHING else.

        The two groups are deliberately independent (S5-Q23): a single
        `all(seven)` gate would let a missing Twilio credential disable the
        operator's email, which ratified guarantee (c) promises unconditionally.
        """
        return all(
            v is not None
            for v in (
                self.smtp_host,
                self.smtp_port,
                self.smtp_user,
                self.smtp_password,
                self.smtp_from,
            )
        )

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None) -> Settings:
        """Flow: read the required three, the optional four with defaults, then the
        seven optional credentials S5 added (none of which this process requires).

        `env` is injectable so the failure path is testable without mutating the
        real process environment -- the one thing a test of "what happens when a
        variable is missing" must not do to its own runner.
        """
        env = os.environ if env is None else env
        return Settings(
            profile_name=_require(env, "DECANA_PROFILE"),
            gemini_api_key=_require(env, "GEMINI_API_KEY"),
            public_wss_url=_require(env, "PUBLIC_WSS_URL"),
            profiles_root=Path(
                env.get("DECANA_PROFILES_ROOT") or _repo_profiles_root()
            ),
            artifact_dir=Path(env.get("DECANA_ARTIFACT_DIR") or _DEFAULT_ARTIFACT_DIR),
            port=int(env.get("PORT") or _DEFAULT_PORT),
            twilio_account_sid=env.get("TWILIO_ACCOUNT_SID"),
            twilio_auth_token=env.get("TWILIO_AUTH_TOKEN"),
            smtp_host=env.get("SMTP_HOST"),
            smtp_port=int(env["SMTP_PORT"]) if env.get("SMTP_PORT") else None,
            smtp_user=env.get("SMTP_USER"),
            smtp_password=env.get("SMTP_PASSWORD"),
            smtp_from=env.get("SMTP_FROM"),
        )
