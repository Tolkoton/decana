"""The process entry point: read the environment, wire the app, run uvicorn.

WHAT THIS IS: wiring only. No logic, no branching beyond what the ratified
composition-root sketch contains. Everything it composes is tested elsewhere; what
this file guarantees is that the pieces are joined correctly, which only a real
process start can show.

WHY that matters: every unit test constructs `create_app` itself, so a `main()`
that passes `live_factory` without its `api_key` partial, or forgets `root=` on
`load_profile`, or orders the arguments wrongly, is invisible to all of them. On a
deploy it is a container that will not boot.
"""

from __future__ import annotations

import logging
from functools import partial

import uvicorn

from decana.gemini.live import open_live_session
from decana.profile.load import load_profile
from decana.settings import Settings
from decana.twilio.records import CallRecord
from decana.twilio.server import create_app

__all__ = ["main"]

logger = logging.getLogger(__name__)


async def log_only_on_call_end(record: CallRecord) -> None:
    """The tracer's `on_call_end`: record the summary, dispatch nothing.

    S5 replaces this with the real post-call handler. Until then a call that
    completes must still leave a trace, or the tracer has nothing to read back.
    """
    logger.info(
        "call ended sid=%s reason=%s turns=%d timing=%s",
        record.call_sid,
        record.ended_reason,
        len(record.transcript),
        record.timing_path,
    )


def main() -> None:
    """Flow: read env -> load profile -> build app -> serve."""
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    profile = load_profile(settings.profile, root=settings.profiles_root)

    app = create_app(
        profile,
        partial(open_live_session, api_key=settings.gemini_api_key),
        log_only_on_call_end,
        public_wss_url=settings.public_wss_url,
        artifact_dir=settings.artifact_dir,
    )
    uvicorn.run(app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
