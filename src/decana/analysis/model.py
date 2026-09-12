"""The structured result of analysing one finished call.

WHAT: the frozen value object S5 dispatches -- an outcome drawn from the profile's
vocabulary, any compliance notes, a short summary for the operator brief, and the
model's raw JSON.

WHAT THIS DOES NOT DO: it does not know about Gemini, about dispatch, or about
files. `raw` is carried so S5 can write `{call_sid}.analysis.json` and so a parse
failure leaves behind the evidence of what the model actually said.
"""

from dataclasses import dataclass

__all__ = ["Analysis"]


@dataclass(frozen=True)
class Analysis:
    """One call's analysis. Every field is populated on every path, including failure.

    `compliance_notes` is a tuple, not a list: a frozen dataclass holding a mutable
    field is frozen in name only, and this object crosses into S5.
    """

    outcome: str
    compliance_notes: tuple[str, ...]
    summary: str
    raw: str
