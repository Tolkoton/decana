"""Read one vertical's profile directory and validate it before any call is placed.

A profile is hand-edited TOML plus three prompt files. Every failure it can
contain -- a typo'd key, a placeholder with no URL behind it, a missing prompt
file -- is caught HERE, at startup, rather than at the moment a caller is on the
line. That is the same fail-early rule the bridge slice ratified for the timing
directory (Q13 there): a profile that would break a call must break the process
first, when nobody is listening.

Validation is strict in both directions (Q2). Missing required keys fail, and so
do unknown ones: `phone_numbr = "..."` under a permissive loader validates fine
and then fails on the first real SMS. The one deliberately open region is
`[sms.<outcome>]` beyond its `text` key, because link names are per-vertical by
design.

Every failure raises `ProfileError` naming the offending dotted field or file
(Q6). First failure wins -- no aggregation (Q5).

What this module does NOT do: read `os.environ` (S3's `Settings` owns that),
render templates (S5), author prompt content (the owner, before S7), construct
any Gemini/Twilio/SMTP client (S2/S4/S5), or migrate schema versions (deferred).
"""

from __future__ import annotations

import re
import string
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from decana.profile.model import Profile, SmsTemplate

_TOML_FILE = "profile.toml"
_PROMPT_FILES = ("disclosure", "conversation", "analysis")
_OPTIONAL_TABLE = "sms"
_LIST_TABLE = "outcomes"
_TEXT_KEY = "text"
_PATH_SEPARATORS = ("/", "\\")
# S4 falls back to this label when it cannot classify a call. Keeping it out of
# the allowed set is what keeps "the model could not decide" distinguishable
# from "the model decided this".
_IMPLICIT_OUTCOME = "unclassified"
# A prompt file may open with an HTML comment -- the Q11 DRAFT marker today.
# Anchored to the start and non-greedy: a comment further into the prose is the
# author's text and is left alone (Q15, W8).
_LEADING_COMMENT = re.compile(r"\A\s*<!--.*?-->[ \t]*\r?\n?", re.DOTALL)


class ProfileError(ValueError):
    """A profile directory could not be loaded, or is not valid.

    One type, not a hierarchy (Q6): the only caller is `__main__`, which prints
    the message and exits -- nothing branches on the cause. The message always
    names the offending dotted TOML path (`twilio.phone_number`) or file
    (`profiles/<name>/disclosure.md`), which is the stronger assertion for tests
    than a subtype would be. Subclasses ValueError to match `AudioFrameError` in
    the bridge.
    """


SCHEMA: Mapping[str, frozenset[str]] = {
    "vertical": frozenset({"name"}),
    "gemini": frozenset({"live_model", "analysis_model"}),
    "twilio": frozenset({"phone_number", "sms_sender_id"}),
    "operator": frozenset({"email"}),
    "outcomes": frozenset({"allowed"}),
}
"""The fixed-table allow-list, held as DATA so the loader can name an unknown key.

Public (named in the slice's Seam) because the unknown-key tests parametrize
over it: a per-table copy-paste bug in any of the five is caught, and a table
added here later is tested automatically without editing the test.

`sms` is deliberately absent -- it is the open region (Q2) and is validated by
different rules, not by a key allow-list.
"""


def load_profile(name: str, root: Path = Path("profiles")) -> Profile:
    """Load and validate the profile directory `root/name`.

    Flow: locate the directory -> parse the TOML -> validate its shape -> read
    each region -> build. Ordering is deliberate but not contractual: every row
    in the test suite is a single fault, so which check fires first when several
    faults coexist is unspecified (Q5) and reordering is not a regression.

    The `root` default exists for REPL and `scripts/` convenience only. No
    production call site relies on it: `__main__` passes `settings.profiles_root`
    explicitly, because a CWD-relative default would make the container's WORKDIR
    a load-bearing, untested assumption (Q7).
    """
    directory = _locate(name, root)
    data = _parse_toml(directory / _TOML_FILE)
    tables = _read_tables(data)
    scalars = _read_scalars(tables)
    outcomes = _read_outcomes(tables[_LIST_TABLE])
    sms = _read_sms(data.get(_OPTIONAL_TABLE), outcomes)
    prompts = _read_prompts(directory)
    return Profile(
        name=name,
        display_name=scalars["vertical.name"],
        live_model=scalars["gemini.live_model"],
        analysis_model=scalars["gemini.analysis_model"],
        phone_number=scalars["twilio.phone_number"],
        sms_sender_id=scalars["twilio.sms_sender_id"],
        operator_email=scalars["operator.email"],
        outcomes=outcomes,
        sms=sms,
        disclosure=prompts["disclosure"],
        conversation=prompts["conversation"],
        analysis=prompts["analysis"],
    )


def _locate(name: str, root: Path) -> Path:
    """Resolve `name` to a profile directory, or say why it is not one."""
    _reject_non_bare_name(name)
    directory = root / name
    if not directory.is_dir():
        raise ProfileError(f"profile directory not found: {directory}")
    return directory


def _reject_non_bare_name(name: str) -> None:
    """Guard: `name` must be a bare directory name, not a path (Q8).

    `name` originates in the DECANA_PROFILE env var, set by a human. Without
    this, `load_profile("../secrets")` is a directory walk that surfaces as a
    confusing FileNotFoundError instead of a ProfileError naming the argument.

    `"."` is banned explicitly: `root / "."` normalises to `root` itself, so it
    would otherwise fall through to a "profile.toml missing" error while the
    loader was searching the profiles root as though it were a profile.
    """
    if not name.strip():
        raise ProfileError(f"profile name is empty or whitespace, got {name!r}")
    if any(sep in name for sep in _PATH_SEPARATORS) or name in {".", ".."}:
        raise ProfileError(f"profile name must be a bare directory name, got {name!r}")


def _read_utf8(path: Path) -> str:
    """Read one file as UTF-8, naming *that* file if the bytes are not UTF-8.

    Shared by the TOML and the prompt reads. Both can raise UnicodeDecodeError
    and the message must distinguish them, which is a property of the argument,
    not of the call site.
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ProfileError(f"{path} is not valid UTF-8: {exc}") from exc


def _parse_toml(path: Path) -> dict[str, Any]:
    """Read and parse profile.toml, or say which of the two steps failed."""
    if not path.is_file():
        raise ProfileError(f"{path} is missing")
    text = _read_utf8(path)
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{path} is not valid TOML: {exc}") from exc


def _read_tables(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flow: reject unknown tables -> require each fixed table -> reject unknown keys."""
    _reject_unknown_tables(data)
    tables = _require_tables(data)
    _reject_unknown_keys(tables)
    return tables


def _reject_unknown_tables(data: dict[str, Any]) -> None:
    """Guard: no top-level table outside the schema (Q2).

    Diffed against data.keys() rather than checked by walking the five known
    names -- the latter admits a wholly unknown `[bogus]` table without noticing.
    """
    unknown = sorted(set(data) - set(SCHEMA) - {_OPTIONAL_TABLE})
    if unknown:
        raise ProfileError(f"unknown table(s) in {_TOML_FILE}: {', '.join(unknown)}")


def _require_tables(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Guard: every fixed table is present AND is actually a table.

    The isinstance check is not redundant with the presence check: TOML accepts
    `vertical = "x"` at the top level, which a key-set diff sees as the table
    being present and which then fails as a TypeError on the first descent.
    """
    tables: dict[str, dict[str, Any]] = {}
    for table in SCHEMA:
        if table not in data:
            raise ProfileError(f"missing required table: {table}")
        value = data[table]
        if not isinstance(value, dict):
            raise ProfileError(f"{table} must be a table, got {type(value).__name__}")
        tables[table] = value
    return tables


def _reject_unknown_keys(tables: dict[str, dict[str, Any]]) -> None:
    """Guard: no unknown key inside a fixed table -- typos fail, they do not no-op.

    The opposite failure direction from the missing-key check, and the reason
    SCHEMA is data: a loader that validates required keys by lookup accepts
    `phone_numbr` silently and fails on the first real SMS instead.
    """
    for table, allowed in SCHEMA.items():
        unknown = sorted(set(tables[table]) - allowed)
        if unknown:
            named = ", ".join(f"{table}.{key}" for key in unknown)
            raise ProfileError(f"unknown key(s) in [{table}]: {named}")


def _read_scalars(tables: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Read every required scalar, keyed by its dotted path."""
    return {
        f"{table}.{key}": _read_scalar(tables[table], table, key)
        for table in SCHEMA
        if table != _LIST_TABLE
        for key in sorted(SCHEMA[table])
    }


def _read_scalar(table: dict[str, Any], table_name: str, key: str) -> str:
    """Read one required non-empty string.

    Emptiness is judged after stripping: a type-only isinstance check passes
    `phone_number = "  "` and ships it to Twilio, which is the late failure this
    whole module exists to prevent.
    """
    dotted = f"{table_name}.{key}"
    if key not in table:
        raise ProfileError(f"missing required key: {dotted}")
    value = table[key]
    if not isinstance(value, str):
        raise ProfileError(f"{dotted} must be a string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        raise ProfileError(f"{dotted} must not be empty")
    return stripped


def _read_outcomes(table: dict[str, Any]) -> tuple[str, ...]:
    """Read the allowed outcome labels as a tuple, not the parsed list."""
    dotted = f"{_LIST_TABLE}.allowed"
    if "allowed" not in table:
        raise ProfileError(f"missing required key: {dotted}")
    raw = table["allowed"]
    if not isinstance(raw, list):
        raise ProfileError(
            f"{dotted} must be a list of strings, got {type(raw).__name__}"
        )
    outcomes = tuple(
        _read_outcome(dotted, index, item) for index, item in enumerate(raw)
    )
    _reject_unusable_outcome_set(dotted, outcomes)
    return outcomes


def _read_outcome(dotted: str, index: int, item: Any) -> str:
    """Read one outcome label.

    The emptiness check is load-bearing: an outcome named "" is addressable as
    `[sms.""]`, so a type-only check admits a template nothing can ever select.
    """
    at = f"{dotted}[{index}]"
    if not isinstance(item, str):
        raise ProfileError(f"{at} must be a string, got {type(item).__name__}")
    label = item.strip()
    if not label:
        raise ProfileError(f"{at} must not be empty")
    return label


def _reject_unusable_outcome_set(dotted: str, outcomes: tuple[str, ...]) -> None:
    """Guard: properties of the set as a whole, not of any one label."""
    if not outcomes:
        raise ProfileError(f"{dotted} must not be empty")
    duplicates = sorted({label for label in outcomes if outcomes.count(label) > 1})
    if duplicates:
        raise ProfileError(f"{dotted} contains duplicates: {', '.join(duplicates)}")
    if _IMPLICIT_OUTCOME in outcomes:
        raise ProfileError(
            f"{dotted} must not contain {_IMPLICIT_OUTCOME!r}: it is implicit, "
            "and S4 uses it for the calls it cannot classify"
        )


def _read_sms(raw: Any, outcomes: tuple[str, ...]) -> dict[str, SmsTemplate]:
    """Read the optional per-outcome SMS templates.

    Absent is valid and means "this vertical sends no SMS" (A2); partial
    coverage is valid and means "no SMS for the outcomes it omits".
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ProfileError(
            f"{_OPTIONAL_TABLE} must be a table, got {type(raw).__name__}"
        )
    return {
        outcome: _read_sms_template(outcome, value, outcomes)
        for outcome, value in raw.items()
    }


def _read_sms_template(
    outcome: str, value: Any, outcomes: tuple[str, ...]
) -> SmsTemplate:
    """Read one [sms.<outcome>] table.

    The table check precedes the membership check on purpose: a non-table value
    directly under [sms] is a shape error naming `sms.<key>` whatever the key is,
    so there is one branch rather than a tiebreak that depends on the name.
    """
    dotted = f"{_OPTIONAL_TABLE}.{outcome}"
    if not isinstance(value, dict):
        raise ProfileError(f"{dotted} must be a table, got {type(value).__name__}")
    if outcome not in outcomes:
        raise ProfileError(f"{dotted} is not an allowed outcome: {outcomes}")
    text = _read_text(dotted, value)
    links = _read_links(dotted, value)
    _reject_placeholder_mismatch(dotted, text, links)
    return SmsTemplate(text=text, links=links)


def _placeholder_fields(text: str) -> frozenset[str]:
    """The field names str.format would resolve in `text` (Q3).

    Uses str.format's own parser rather than a regex, because str.format is what
    S5 actually calls: `{{` escapes, format specs and conversions all have to be
    read the way the renderer reads them. `.parse()` yields raw field names
    without classifying them, so `"0"`, `""`, `"a.b"` and `"a[0]"` all arrive
    here as strings and are rejected by the caller's identifier check.

    Raises ValueError on an unbalanced brace; the caller translates it.
    """
    return frozenset(
        field for _, field, _, _ in string.Formatter().parse(text) if field is not None
    )


def _extract_fields(dotted: str, text: str) -> frozenset[str]:
    """Extract placeholder names, rejecting any str.format could not resolve.

    Positional (`{}`, `{0}`), attribute (`{a.b}`) and index (`{a[0]}`) fields
    are all unsupported: links are a flat name->URL mapping, so anything that is
    not a plain identifier has no possible referent.
    """
    try:
        fields = _placeholder_fields(text)
    except ValueError as exc:
        raise ProfileError(f"{dotted} is not a valid template: {exc}") from exc
    unsupported = sorted(field for field in fields if not field.isidentifier())
    if unsupported:
        raise ProfileError(
            f"{dotted} uses unsupported placeholder {{{unsupported[0]}}}"
        )
    return fields


def _reject_placeholder_mismatch(dotted: str, text: str, links: dict[str, str]) -> None:
    """Guard: text and links must agree in BOTH directions.

    A placeholder with no link is an unrenderable SMS. A link no placeholder
    references is the quieter bug and is equally an error (Q4): renaming a
    placeholder would otherwise drop the Calendly URL from every message with
    nothing anywhere to show for it.
    """
    at = f"{dotted}.{_TEXT_KEY}"
    fields = _extract_fields(at, text)
    missing = sorted(fields - set(links))
    if missing:
        raise ProfileError(f"{at} uses {{{missing[0]}}} with no matching link key")
    dead = sorted(set(links) - fields)
    if dead:
        raise ProfileError(f"{dotted}.{dead[0]} is never referenced by {at}")


def _read_text(dotted: str, table: dict[str, Any]) -> str:
    """Read one template body.

    Stored verbatim -- it is rendered into an SMS where the author's spacing is
    intentional (Q10) -- but rejected when it is nothing but whitespace, which
    would ship an empty message. The isinstance check catches `text = 3`, which
    a `not text` truthiness check accepts.
    """
    if _TEXT_KEY not in table:
        raise ProfileError(f"missing required key: {dotted}.{_TEXT_KEY}")
    text = table[_TEXT_KEY]
    if not isinstance(text, str):
        raise ProfileError(
            f"{dotted}.{_TEXT_KEY} must be a string, got {type(text).__name__}"
        )
    if not text.strip():
        raise ProfileError(f"{dotted}.{_TEXT_KEY} must not be empty")
    return text


def _read_links(dotted: str, table: dict[str, Any]) -> dict[str, str]:
    """Read every non-`text` key as a link.

    This is the open region (Q2): link names are per-vertical by design, so they
    are validated as values rather than checked against an allow-list.
    """
    links: dict[str, str] = {}
    for key, value in table.items():
        if key == _TEXT_KEY:
            continue
        at = f"{dotted}.{key}"
        if not isinstance(value, str):
            raise ProfileError(f"{at} must be a string, got {type(value).__name__}")
        stripped = value.strip()
        if not stripped:
            raise ProfileError(f"{at} must not be empty")
        links[key] = stripped
    return links


def _read_prompts(directory: Path) -> dict[str, str]:
    """Read the three prompt files, applying Q10's per-file whitespace policy.

    Stripping is applied HERE, to what is stored -- not only to what is checked
    for emptiness. Validating on the stripped text while storing the raw text
    passes every rejection test in the suite and still hands Twilio a padded
    value, which is the failure this loader exists to make impossible.
    """
    texts = {stem: _read_prompt(directory / f"{stem}.md") for stem in _PROMPT_FILES}
    # disclosure alone: it is spoken inside <Say>, where a leading newline is an
    # audible pause. The other two are system text, where the layout is the
    # author's and the model is indifferent to it.
    texts["disclosure"] = texts["disclosure"].strip()
    return texts


def _read_prompt(path: Path) -> str:
    """Read one prompt file, rejecting missing, non-UTF-8, and contentless.

    The comment is removed BEFORE the emptiness check, not after: a file holding
    nothing but a review marker has no content, and checking first would let it
    through as "".
    """
    if not path.is_file():
        raise ProfileError(f"{path} is missing")
    text = _strip_leading_comment(_read_utf8(path))
    if not text.strip():
        raise ProfileError(f"{path} is empty")
    return text


def _strip_leading_comment(text: str) -> str:
    """Drop a leading HTML comment block -- file metadata, not prompt content.

    Q11 marks every shipped prompt as DRAFT and P5 keeps the marker there, but
    `disclosure` is spoken verbatim inside TwiML <Say>: without this the caller
    hears "less than exclamation dash dash DRAFT..." before the compliance line,
    and P5 would have kept it there long after the draft text was replaced (Q15).

    Applied to all three files, not just the spoken one -- one rule, and a review
    marker is noise at the head of a system instruction too.
    """
    return _LEADING_COMMENT.sub("", text, count=1)
