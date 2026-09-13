"""The `decana` console entry point: wiring, and nothing else.

WHAT: reads the environment once, loads the profile, builds the real Live
session factory, and serves the app. This is the process the Dockerfile's CMD
starts.

WHY it holds no logic: every unit test in this slice constructs `create_app`
itself, so nothing else exercises the composition. A branch here is a branch no
test covers. Its one job is to be the place where the real collaborators meet
the app, and Seam 17 checks it by starting the actual process.

WHAT THIS DOES NOT DO: no argument parsing, no defaulting (that is `Settings`),
no post-call work (`build_on_call_end` lives in `decana.dispatch.wiring` -- S5-Q24,
moved there so S3 never imports S4/S5).
"""

import logging
from functools import partial

import uvicorn

from decana.bridge.gain import PHONE_INBOUND_GAIN_DB, db_to_linear
from decana.dispatch.wiring import build_on_call_end
from decana.gemini.live import open_live_session
from decana.profile.load import load_profile
from decana.settings import Settings
from decana.twilio.server import create_app

__all__ = ["main"]


def main() -> None:
    """Flow: configure logging -> read env -> load profile -> build app -> serve.

    `basicConfig` is wiring, not logic: without a root handler Python's
    last-resort handler drops everything below WARNING, and the first real
    Cloud Run call (2026-09-13) produced no `call_sid`, no barge-in and no
    socket-lifecycle line at all. INFO to stderr is what Cloud Logging ingests.
    """
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    settings = Settings.from_env()
    profile = load_profile(settings.profile_name, root=settings.profiles_root)
    app = create_app(
        profile,
        partial(open_live_session, api_key=settings.gemini_api_key),
        build_on_call_end(settings, profile),
        public_wss_url=settings.public_wss_url,
        artifact_dir=settings.timing_dir,
        # The bucket, not the timing dir: recordings are written once per call
        # at teardown, so the FUSE mount is safe and the files land beside the
        # transcript where the owner can fetch them.
        recording_dir=settings.artifact_dir,
        # 0 dB today (a no-op): every lift tried made real calls worse because
        # the speech detection stopped seeing ends of turns. See `gain.py`.
        inbound_gain=db_to_linear(PHONE_INBOUND_GAIN_DB),
    )
    uvicorn.run(app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
