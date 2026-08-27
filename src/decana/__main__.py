"""The `decana` console entry point: wiring, and nothing else.

WHAT: reads the environment once, loads the profile, builds the real Live
session factory, and serves the app. This is the process the Dockerfile's CMD
starts.

WHY it holds no logic: every unit test in this slice constructs `create_app`
itself, so nothing else exercises the composition. A branch here is a branch no
test covers. Its one job is to be the place where the real collaborators meet
the app, and Seam 17 checks it by starting the actual process.

WHAT THIS DOES NOT DO: no argument parsing, no defaulting (that is `Settings`),
no post-call work (`build_on_call_end` is the log-only no-op until S5).
"""

from functools import partial

import uvicorn

from decana.gemini.live import open_live_session
from decana.profile.load import load_profile
from decana.settings import Settings
from decana.twilio.server import build_on_call_end, create_app

__all__ = ["main"]


def main() -> None:
    """Flow: read env -> load profile -> build app -> serve."""
    settings = Settings.from_env()
    profile = load_profile(settings.profile_name, root=settings.profiles_root)
    app = create_app(
        profile,
        partial(open_live_session, api_key=settings.gemini_api_key),
        build_on_call_end(),
        public_wss_url=settings.public_wss_url,
        artifact_dir=settings.artifact_dir,
    )
    uvicorn.run(app, host="0.0.0.0", port=settings.port)  # noqa: S104


if __name__ == "__main__":
    main()
