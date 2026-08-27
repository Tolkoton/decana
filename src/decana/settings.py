"""The one place this project reads the environment.

WHAT: `Settings.from_env()` reads every variable the process needs, validates that
the required ones are present, and hands back a frozen record.

WHY exactly one place: keeping the env read here is what lets `create_app` be
driven entirely by fakes, which is this slice's whole exit criterion. A module
that reads `os.environ` at import time cannot be tested without mutating the
process.

WHAT THIS DOES NOT DO: it does not read `.env`. Secrets come from the process
environment, exported by whatever supervises the process.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Settings"]

_DEFAULT_ARTIFACT_DIR = Path(".claude/artifacts/calls")


def _default_profiles_root() -> Path:
    """`<repo root>/profiles`, resolved from `decana.__file__` and never from CWD.

    profile-loader Q7 made `main()` responsible for passing `root` explicitly,
    because `load_profile`'s own default is CWD-relative and a service does not
    control its working directory. W-1 stands: this resolution assumes an editable
    install. If S6's Dockerfile installs non-editable, set `DECANA_PROFILES_ROOT`
    explicitly and record it in `docs/deploy.md`.
    """
    return Path(__file__).resolve().parent.parent.parent / "profiles"


@dataclass(frozen=True)
class Settings:
    """Everything the process needs, read once."""

    profile: str
    gemini_api_key: str
    public_wss_url: str
    profiles_root: Path
    artifact_dir: Path
    port: int

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        """Read and validate. A missing required variable exits 2, naming it.

        Exit 2 rather than an exception: this runs at process start, where a
        traceback is noise and the operator needs the variable's name. `env` is a
        parameter so the failure path is testable without mutating os.environ.
        """
        source = os.environ if env is None else env

        missing = [
            name
            for name in ("DECANA_PROFILE", "GEMINI_API_KEY", "PUBLIC_WSS_URL")
            if not source.get(name)
        ]
        if missing:
            print(
                f"decana: missing required environment variable(s): {', '.join(missing)}",
                file=sys.stderr,
            )
            raise SystemExit(2)

        root = source.get("DECANA_PROFILES_ROOT")
        return cls(
            profile=source["DECANA_PROFILE"],
            gemini_api_key=source["GEMINI_API_KEY"],
            public_wss_url=source["PUBLIC_WSS_URL"],
            profiles_root=Path(root) if root else _default_profiles_root(),
            artifact_dir=Path(source.get("DECANA_ARTIFACT_DIR", _DEFAULT_ARTIFACT_DIR)),
            port=int(source.get("PORT", "8080")),
        )
