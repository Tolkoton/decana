"""Append-only timing event log for one bridged call.

Every latency number in the slice's exit criterion is computed offline from the
JSONL this writes, so the file is the artifact -- not a debugging aid. Two
properties follow from that and are load-bearing:

  * Each record() call writes and flushes immediately. Buffering until close()
    would silently lose the tail of any call that ends unexpectedly, and the
    tail is where a stall would show.
  * The clock is injected and owned HERE (slice decision Q7). Callers pass an
    event name and never a timestamp, so there is exactly one place that
    answers "what time is it" and exactly one call to it per record().

What this module does NOT do: read the log back, compute gaps, classify turn
boundaries, or decide what is worth recording. Gap analysis is offline work
against the JSONL; the caller decides which events happen (Q9 -- an event is
written only when a forward actually occurred).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any


class TimingRecorder:
    """Writes one JSON line per timing event, flushed on every call."""

    # Fields the recorder owns; **detail may not shadow them (Q14).
    #
    # "event" is unreachable through this guard today -- it is a named
    # positional parameter, so Python rejects record(..., event=...) with
    # TypeError before the body runs. It is listed anyway so the guard stays
    # correct if the signature is ever widened (e.g. to record(self, **kwargs)),
    # which would silently remove that protection.
    _RESERVED_KEYS = ("event", "timestamp")

    def __init__(self, clock: Callable[[], datetime], sink_path: Path) -> None:
        self._clock = clock
        self._sink_path = sink_path
        # Q13: eagerly, so a missing directory fails before a call is placed
        # rather than mid-call, when the log cannot be reconstructed.
        sink_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: str, **detail: Any) -> None:
        """Append one event to the sink, stamped with the injected clock."""
        self._reject_reserved_keys(detail)
        # Exactly one clock call per record() (Q7): stamped here, into a local,
        # never re-invoked while building the line.
        stamped_at = self._clock()
        self._append({"event": event, "timestamp": stamped_at.isoformat(), **detail})

    def _reject_reserved_keys(self, detail: dict[str, Any]) -> None:
        """Guard: detail must not shadow a field the recorder owns (Q14).

        Raises before the line is composed, so a rejected call writes nothing.
        """
        collisions = sorted(set(detail) & set(self._RESERVED_KEYS))
        if collisions:
            raise ValueError(
                f"detail may not override reserved timing fields: {collisions}"
            )

    def _append(self, line: dict[str, Any]) -> None:
        """Write one JSON line and flush it, so nothing is lost mid-call."""
        with self._sink_path.open("a", encoding="utf-8") as sink:
            sink.write(json.dumps(line) + "\n")
