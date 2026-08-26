"""Value objects carrying everything that makes one vertical differ from another.

A Profile is what turns this codebase from "a voice bridge" into "a UK mortgage
broker intake line" -- models, phone number, outcomes, SMS templates and the
three prompt texts. Feature acceptance A4 is that swapping verticals is a
directory swap plus one env var, never a code change, so every vertical-specific
value a caller could want lives on this type and nowhere else.

Both types are frozen. A Profile is loaded once by the composition root (S3) and
read for the process lifetime by S2, S3, S4 and S5; nothing mutates it, and
`frozen=True` plus the copying done in `load.py` is what makes that true rather
than merely intended (Q9).

Hashability is a documented non-feature (Q9, test V3): `sms` and `links` are
dict-backed, so `hash(profile)` raises TypeError and neither mypy nor ruff will
say so. A future caller reaching for `@lru_cache` or a `set` finds an explicit
test rather than a landmine.

What this module does NOT do: read files, parse TOML, validate anything, or
render a template. Construction and validation are `load.py`'s job; rendering
`SmsTemplate.text` against its links is S5's -- the text is stored unrendered.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class SmsTemplate:
    """One outcome's SMS body, plus the URLs its placeholders resolve to.

    `links` is open by design (Q2): link keys are per-vertical, which is the
    whole reason this is a mapping rather than a fixed set of fields. The loader
    guarantees the two halves agree -- every `{placeholder}` in `text` is a key
    in `links`, and every key in `links` is referenced by `text` (Q4, no dead
    links) -- so S5 can call `text.format(**links)` without a KeyError.
    """

    text: str
    """The SMS body, stored verbatim -- the author's spacing is intentional (Q10)."""

    links: Mapping[str, str]
    """Placeholder name -> URL. Values are stored stripped (Seam 5)."""


@dataclass(frozen=True)
class Profile:
    """One vertical's complete configuration, validated at load time."""

    name: str
    """Directory slug, e.g. "mortgage-broker" -- identity.

    Comes from the `load_profile` argument (ultimately `DECANA_PROFILE`), never
    from the TOML (Q12). This is what A4's `git diff` and the artifact filenames
    key on, and it is machine-safe by construction (Q8 bans path separators).
    """

    display_name: str
    """Human label from `[vertical] name`, e.g. "UK mortgage broker intake".

    Operator-facing text only -- S5's email subject. Never an identifier, and
    deliberately not cross-checked against `name`: they are different things and
    disagreement is not an error (Q12).
    """

    live_model: str
    """Gemini Live model id for the in-call conversation (S2)."""

    analysis_model: str
    """Gemini model id for post-call analysis (S4)."""

    phone_number: str
    """E.164 -- the Twilio number this profile answers on."""

    sms_sender_id: str
    """Alphanumeric sender id for outbound SMS (S5)."""

    operator_email: str
    """Where the post-call brief is sent (S5)."""

    outcomes: tuple[str, ...]
    """Allowed outcome labels.

    A tuple, not the parsed list: `outcomes` must not alias the TOML S4 was
    parsed from (Seam 4). "unclassified" is implicit -- S4's fallback -- and is
    banned from this tuple so the fallback stays distinguishable from a real
    classification (Q-seam case 9).
    """

    sms: Mapping[str, SmsTemplate]
    """Outcome -> template, keys a subset of `outcomes`.

    Optional and possibly partial: a vertical that defines no template for an
    outcome sends no SMS for it (A2). An empty mapping is valid.
    """

    disclosure: str
    """`disclosure.md`, stripped (Q10).

    Spoken verbatim by Twilio TTS inside `<Say>` before the model stream opens,
    which is why it is the one prompt whose surrounding whitespace is removed --
    a leading newline is an audible pause.
    """

    conversation: str
    """`conversation.md`, verbatim -- the Live session's system instruction (S2)."""

    analysis: str
    """`analysis.md`, verbatim -- the post-call analysis system instruction (S4)."""
