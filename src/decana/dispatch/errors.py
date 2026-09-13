"""The one exception this slice raises on its own behalf.

WHAT: `DispatchError` marks a side effect that could not be attempted or could
not be believed. It has exactly three raisers -- a Twilio response carrying no
message sid (S5-Q2), and each of the two Unconfigured senders (S5-Q23).

WHY ONE CLASS: every raiser lands in the same place -- `dispatch`'s per-stage
wrapper, which records `"<stage>: <ExceptionType>: <msg>"` and carries on. A
finer hierarchy would be read by nothing.
"""

__all__ = ["DispatchError"]


class DispatchError(RuntimeError):
    """A side effect could not be attempted, or its result could not be trusted."""
