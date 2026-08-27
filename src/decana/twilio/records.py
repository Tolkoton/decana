"""Call records handed from the Twilio server to post-call slices.

WHAT: the two frozen value objects S4 and S5 consume -- one transcript turn, and
the record of one finished call.

WHAT THIS DOES NOT DO: it does not know about Gemini. `TranscriptTurn` carries the
same role values as S2's `Transcript` but is a separate type on purpose, so S4/S5
never import `decana.gemini` (ratified feature contract, Edge S3 -> S4,S5).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

__all__ = ["CallRecord", "OnCallEnd", "TranscriptTurn"]


@dataclass(frozen=True)
class TranscriptTurn:
    """One whole turn of the conversation, in arrival order."""

    role: Literal["caller", "model"]
    text: str


@dataclass(frozen=True)
class CallRecord:
    """Everything a post-call slice needs about one finished call.

    `transcript` is a tuple, not a list: the record is handed to an injected
    callback this slice does not control, and a frozen dataclass holding a mutable
    field is frozen in name only.
    """

    call_sid: str
    caller_number: str
    profile_name: str
    started_at: datetime
    ended_at: datetime
    transcript: tuple[TranscriptTurn, ...]
    timing_path: Path
    ended_reason: str


OnCallEnd = Callable[[CallRecord], Awaitable[None]]
