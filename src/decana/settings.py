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

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None) -> Settings:
        """Flow: read the required three, then the optional four with defaults.

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
        )
