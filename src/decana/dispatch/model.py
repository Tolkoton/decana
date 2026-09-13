"""The two frozen value objects this slice produces.

WHAT: `StageOutcome` is how one of the five effects reports itself;
`DispatchReport` is what `dispatch` returns.

WHAT THIS DOES NOT DO: it knows nothing about Twilio, SMTP, or the filesystem.
`StageOutcome.status` is the discriminant -- `detail` is payload, and no reader
may branch on its text (S5-Q19; an earlier design encoded the distinction as a
`"skipped: "` / `"failed: "` prefix, which put the operator-facing wording in a
string convention enforced by nothing).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

__all__ = ["DispatchReport", "StageOutcome"]

Status = Literal["ok", "skipped", "failed"]


@dataclass(frozen=True)
class StageOutcome:
    """How one of the five effects ended.

    `detail` by `status`:
      ok      + sms    -> the message sid
      ok      + others -> ""            (the status IS the outcome)
      skipped          -> "<why>"       (sms ONLY -- no other stage is ever skipped)
      failed           -> "<ExceptionType>: <msg>"
    """

    status: Status
    detail: str


@dataclass(frozen=True)
class DispatchReport:
    """What one call's dispatch produced.

    `errors` is a tuple, not a list: this crosses out of the function that built
    it, and a frozen dataclass holding a mutable field is frozen in name only.

    There is deliberately no `analysis_path`: Edge S7 "what it reads" lists
    `.jsonl` / `.transcript.txt` / `.brief.md` only. `analysis.json` is written
    for a human debugging a bad outcome, not consumed by S7.
    """

    transcript_path: Path
    brief_path: Path
    sms_sid: str | None
    email_sent: bool
    errors: tuple[str, ...]
