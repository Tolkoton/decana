"""S5 dispatch: turn one finished call into operator-visible output.

WHAT: after a call ends, S3 hands a `CallRecord` to an injected `on_call_end`.
This package supplies the real one -- analyse the transcript (S4), write the
evidence files, send at most one SMS to the caller, send one email to the
operator, and write the brief.

WHAT THIS DOES NOT DO: retry, queue, schedule, store to the cloud, send HTML
email, or send more than one SMS per call. Contract:
`.claude/overseer/slice/dispatch.md`.
"""
