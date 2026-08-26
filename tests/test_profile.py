"""Slice profile-loader -- a bad profile must fail before a call is placed.

Every test here goes through the real entry point, `load_profile`, against a
directory written to `tmp_path`. There are no bare-helper tests of the internal
guards: the guarantee the rest of the system consumes is "loading this directory
either yields a valid Profile or raises ProfileError naming the problem", and a
helper tested in isolation can be correct while never being reached.

Behavior ids (E/G/P/V/W) come from the slice artifact's ratified behavior list,
`.claude/overseer/slice/profile-loader.md`. The mapping is one id to one pytest
NODE: a parametrized row carries its id via `pytest.param(..., id=...)` and its
function's docstring opens with the range it spans; a plain function carries its
single id as the first token of its docstring. A test with no id, or an id with
no test, is a finding -- checked by diffing `pytest --collect-only -q` against
that list, in both directions.
"""

from __future__ import annotations

import dataclasses
import json
import re
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from decana.profile.load import (
    SCHEMA,
    ProfileError,
    _placeholder_fields,
    load_profile,
)
from decana.profile.model import Profile

_NAME = "broker"
_TOML = "profile.toml"
_LINK = "https://calendly.com/decana/intro"
# The Q11 review marker. Metadata for whoever opens the file, never content:
# disclosure.md is spoken verbatim by Twilio <Say>, so a marker that survived
# into the stored text would be read aloud to the caller (Q15).
_DRAFT_MARKER = "<!-- DRAFT — owner to review before S7 -->"
_MARKED = (
    f"{_DRAFT_MARKER}\nReal content the caller must hear.\n\nAn <!-- aside --> here.\n"
)
# No leading comment, but one further in: nothing here may be removed.
_UNMARKED = "First line of prose.\n\nStill here <!-- an aside --> and after.\n"

_PROMPTS = {
    "disclosure": "This call is handled by an AI assistant and is recorded.",
    "conversation": "You are an intake assistant. The disclosure has been given.",
    "analysis": "Classify the call into exactly one of the allowed outcomes.",
}


class _Inline(dict[str, Any]):
    """A dict the writer emits inline (`allowed = {}`) rather than as a table.

    TOML has two spellings for a mapping and the loader must reject one of them
    in a place it accepts the other, so the test writer cannot guess.
    """


def _good_data() -> dict[str, Any]:
    """A profile that must load. Every failure row below is one mutation of this."""
    return {
        "vertical": {"name": "UK mortgage broker intake"},
        "gemini": {
            "live_model": "gemini-2.5-flash-native-audio-preview-12-2025",
            "analysis_model": "gemini-2.5-flash",
        },
        "twilio": {"phone_number": "+441234567890", "sms_sender_id": "Decana"},
        "operator": {"email": "ops@example.com"},
        "outcomes": {"allowed": ["new_client", "not_qualified", "callback"]},
        "sms": {
            "new_client": {
                "text": "Thanks for calling. Book here: {calendly_url}",
                "calendly_url": _LINK,
            }
        },
    }


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        # TOML basic strings share JSON's escape grammar for everything this
        # suite writes (quotes, backslashes, newlines).
        return json.dumps(value)
    if isinstance(value, bool):  # before int -- bool is an int subclass
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{" + ", ".join(f"{k} = {_toml_value(v)}" for k, v in value.items()) + "}"
        )
    raise TypeError(f"test writer cannot serialize {type(value).__name__}")


def _dump(prefix: str | None, table: dict[str, Any], out: list[str]) -> None:
    """Emit one table: header, then its scalars, then its sub-tables.

    Scalars before sub-tables is not cosmetic -- TOML binds a bare key to the
    most recent header, so emitting them after would move them into the wrong
    table.
    """
    if prefix is not None:
        out.append(f"[{prefix}]")
    subtables: dict[str, dict[str, Any]] = {}
    for key, value in table.items():
        if isinstance(value, dict) and not isinstance(value, _Inline):
            subtables[key] = value
        else:
            out.append(f"{key} = {_toml_value(value)}")
    for key, value in subtables.items():
        _dump(key if prefix is None else f"{prefix}.{key}", value, out)


def _toml_dumps(data: dict[str, Any]) -> str:
    out: list[str] = []
    _dump(None, data, out)
    return "\n".join(out) + "\n"


def _write_profile(
    directory: Path,
    data: dict[str, Any] | None = None,
    prompts: dict[str, str] | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = _good_data() if data is None else data
    (directory / _TOML).write_text(_toml_dumps(payload), encoding="utf-8")
    for stem, text in (_PROMPTS if prompts is None else prompts).items():
        (directory / f"{stem}.md").write_text(text, encoding="utf-8")


def _case(
    *,
    mutate: Callable[[dict[str, Any]], Any] | None = None,
    after: Callable[[Path], Any] | None = None,
    name: str = _NAME,
) -> Callable[[Path], str]:
    """Build one single-fault failure row.

    Single-fault against a known-good profile is the point: which error wins
    when several faults coexist is implementation-order-determined and
    deliberately unspecified (Q5), so reordering checks in a refactor must not
    show up here as a regression.

    `mutate` edits the TOML data before it is written; `after` touches the
    written directory (for the byte-level and missing-file rows); `name` is the
    argument handed to `load_profile`, which for the E1/E2 rows is the fault.
    """

    def prepare(root: Path) -> str:
        data = _good_data()
        if mutate is not None:
            mutate(data)
        _write_profile(root / _NAME, data)
        if after is not None:
            after(root / _NAME)
        return name

    return prepare


def _add_extra_key(table: str) -> Callable[[dict[str, Any]], None]:
    """Closure per table -- a comprehension over SCHEMA would late-bind `table`."""

    def mutate(data: dict[str, Any]) -> None:
        data[table]["extra"] = "x"

    return mutate


def _pop_key(table: str, key: str) -> Callable[[dict[str, Any]], None]:
    """Closure per (table, key) -- same late-binding reason as _add_extra_key."""

    def mutate(data: dict[str, Any]) -> None:
        data[table].pop(key)

    return mutate


def _set_scalar(table: str, key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(data: dict[str, Any]) -> None:
        data[table][key] = value

    return mutate


def _set_allowed(value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(data: dict[str, Any]) -> None:
        data["outcomes"]["allowed"] = value

    return mutate


def _set_sms(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(data: dict[str, Any]) -> None:
        data["sms"]["new_client"][key] = value

    return mutate


# The six required scalars, as (table, key, dotted path). Used to generate the
# E6 missing-key rows and the E8 empty/whitespace rows, so adding a required
# scalar to the schema cannot leave either direction untested.
_REQUIRED_SCALARS = [
    ("vertical", "name", "vertical.name"),
    ("gemini", "live_model", "gemini.live_model"),
    ("gemini", "analysis_model", "gemini.analysis_model"),
    ("twilio", "phone_number", "twilio.phone_number"),
    ("twilio", "sms_sender_id", "twilio.sms_sender_id"),
    ("operator", "email", "operator.email"),
]
_SCALAR_IDS = {
    "vertical.name": "vertical_name",
    "gemini.live_model": "live_model",
    "gemini.analysis_model": "analysis_model",
    "twilio.phone_number": "phone_number",
    "twilio.sms_sender_id": "sms_sender_id",
    "operator.email": "operator_email",
}

_E1_BAD_NAMES = [
    ("../x", "dotdot_slash"),
    ("..", "dotdot"),
    (".", "dot"),
    ("sub/dir", "slash"),
    ("a\\b", "backslash"),
    ("", "empty"),
    ("  ", "whitespace"),
]

_E7_GENERATED = [
    pytest.param(
        _case(mutate=_add_extra_key(table)), f"{table}.extra", id=f"E7-extra_{table}"
    )
    for table in SCHEMA
]
# The five E7 table ids are ratified in the slice artifact. Generating them from
# the loader's own SCHEMA is what makes a per-table copy-paste bug impossible to
# miss and tests a table added later automatically; this assertion is the tie
# back to the ratified list, and fails at import if the two ever diverge.
assert {param.id for param in _E7_GENERATED} == {
    "E7-extra_vertical",
    "E7-extra_gemini",
    "E7-extra_twilio",
    "E7-extra_operator",
    "E7-extra_outcomes",
}

_ERROR_CASES = [
    # E1 -- `name` is not a plain directory name. The profile on disk is valid;
    # the argument is the fault, so the message must name the argument.
    *[
        pytest.param(_case(name=bad), repr(bad), id=f"E1-{slug}")
        for bad, slug in _E1_BAD_NAMES
    ],
    # E2 -- root/name is not a directory.
    pytest.param(_case(name="nonexistent"), "nonexistent", id="E2-nonexistent"),
    pytest.param(
        _case(
            name="afile",
            after=lambda d: (d.parent / "afile").write_text("x", encoding="utf-8"),
        ),
        "afile",
        id="E2-regular_file",
    ),
    # E3 -- profile.toml missing.
    pytest.param(
        _case(after=lambda d: (d / _TOML).unlink()), _TOML, id="E3-toml_missing"
    ),
    # E4 -- profile.toml unreadable. Two distinct exception types from two
    # distinct call sites: TOMLDecodeError from the parse, UnicodeDecodeError
    # from the read. Both must name profile.toml and not conversation.md.
    pytest.param(
        _case(after=lambda d: (d / _TOML).write_text("not = = toml", encoding="utf-8")),
        _TOML,
        id="E4-bad_syntax",
    ),
    pytest.param(
        _case(after=lambda d: (d / _TOML).write_bytes(b"\xff\xfe[vertical]")),
        _TOML,
        id="E4-bad_utf8",
    ),
    # E5 -- a required table is missing, or is present as a scalar. The scalar
    # rows matter because tomllib parses them happily; only an isinstance check
    # before descending catches them, and a key-set diff never can.
    pytest.param(
        _case(mutate=lambda d: d.pop("twilio")), "twilio", id="E5-twilio_missing"
    ),
    pytest.param(
        _case(mutate=lambda d: d.update(vertical="not a table")),
        "vertical",
        id="E5-vertical_scalar",
    ),
    pytest.param(_case(mutate=lambda d: d.update(sms="x")), "sms", id="E5-sms_scalar"),
    pytest.param(
        _case(mutate=_set_scalar("sms", "new_client", "x")),
        "sms.new_client",
        id="E5-sms_outcome_scalar",
    ),
    # E6 -- a required key is missing. One row per required key.
    *[
        pytest.param(
            _case(mutate=_pop_key(table, key)),
            dotted,
            id=f"E6-{_SCALAR_IDS[dotted]}",
        )
        for table, key, dotted in _REQUIRED_SCALARS
    ],
    pytest.param(
        _case(mutate=lambda d: d["outcomes"].pop("allowed")),
        "outcomes.allowed",
        id="E6-outcomes_allowed",
    ),
    # E7 -- an unknown key or table. The opposite failure direction from E6: a
    # loader that validates required keys by lookup passes every E6 row and
    # still ships `phone_numbr` silently.
    *_E7_GENERATED,
    pytest.param(
        _case(mutate=lambda d: d.update(bogus={"k": "v"})), "bogus", id="E7-bogus_table"
    ),
    # E8 -- wrong type, or empty after stripping. The empty rows are the ones a
    # type-only isinstance(str) validator waves through, shipping
    # Profile(phone_number="") to Twilio -- the late failure the goal forbids.
    pytest.param(
        _case(mutate=_set_scalar("twilio", "phone_number", 44)),
        "twilio.phone_number",
        id="E8-phone_number_int",
    ),
    *[
        pytest.param(
            _case(mutate=_set_scalar(table, key, blank)),
            dotted,
            id=f"E8-{_SCALAR_IDS[dotted]}_{slug}",
        )
        for table, key, dotted in _REQUIRED_SCALARS
        for blank, slug in (("", "empty"), ("  ", "ws"))
    ],
    pytest.param(
        _case(mutate=_set_sms("calendly_url", "")),
        "sms.new_client.calendly_url",
        id="E8-link_empty",
    ),
    pytest.param(
        _case(mutate=_set_allowed("x")), "outcomes.allowed", id="E8-allowed_string"
    ),
    pytest.param(
        _case(mutate=_set_allowed(_Inline())), "outcomes.allowed", id="E8-allowed_table"
    ),
    pytest.param(
        _case(mutate=_set_allowed(["new_client", 1])),
        "outcomes.allowed[1]",
        id="E8-allowed_int_elem",
    ),
    pytest.param(
        _case(mutate=_set_allowed(["new_client", ""])),
        "outcomes.allowed[1]",
        id="E8-allowed_empty_elem",
    ),
    pytest.param(
        _case(mutate=_set_allowed(["new_client", "  "])),
        "outcomes.allowed[1]",
        id="E8-allowed_ws_elem",
    ),
    # E9 -- the outcome set itself is unusable.
    pytest.param(
        _case(mutate=_set_allowed([])), "outcomes.allowed", id="E9-allowed_empty"
    ),
    pytest.param(
        _case(mutate=_set_allowed(["new_client", "new_client"])),
        "outcomes.allowed",
        id="E9-allowed_dup",
    ),
    pytest.param(
        _case(mutate=_set_allowed(["new_client", "unclassified"])),
        "unclassified",
        id="E9-allowed_unclassified",
    ),
    # E10 -- a template for an outcome that is not allowed.
    pytest.param(
        _case(mutate=_set_scalar("sms", "bogus", {"text": "hi"})),
        "sms.bogus",
        id="E10-sms_bogus",
    ),
    # E11 -- the template itself is malformed. `text = 3` is the row a `not
    # text` truthiness check waves through.
    pytest.param(
        _case(mutate=lambda d: d["sms"]["new_client"].pop("text")),
        "sms.new_client.text",
        id="E11-text_missing",
    ),
    pytest.param(
        _case(mutate=_set_sms("text", "")), "sms.new_client.text", id="E11-text_empty"
    ),
    pytest.param(
        _case(mutate=_set_sms("text", 3)), "sms.new_client.text", id="E11-text_int"
    ),
    pytest.param(
        _case(mutate=_set_sms("calendly_url", 3)),
        "sms.new_client.calendly_url",
        id="E11-link_int",
    ),
    # E12 -- text and links disagree. Both directions are errors: a placeholder
    # with no link behind it, and a link no placeholder references. The second
    # is the one that silently drops the Calendly URL from every SMS when a
    # placeholder is renamed.
    pytest.param(
        _case(mutate=_set_sms("text", "Book here: {booking_url}")),
        "booking_url",
        id="E12-missing_placeholder",
    ),
    pytest.param(
        _case(mutate=_set_sms("extra_url", "https://example.com/extra")),
        "sms.new_client.extra_url",
        id="E12-unused_link",
    ),
    # E13 -- a prompt file is missing, not UTF-8, or has no content.
    pytest.param(
        _case(after=lambda d: (d / "analysis.md").unlink()),
        "analysis.md",
        id="E13-analysis_missing",
    ),
    pytest.param(
        _case(after=lambda d: (d / "conversation.md").write_bytes(b"\xff\xfe")),
        "conversation.md",
        id="E13-conversation_bad_utf8",
    ),
    pytest.param(
        _case(
            after=lambda d: (d / "disclosure.md").write_text("   \n", encoding="utf-8")
        ),
        "disclosure.md",
        id="E13-disclosure_ws_only",
    ),
    pytest.param(
        _case(
            after=lambda d: (d / "disclosure.md").write_text(
                f"{_DRAFT_MARKER}\n", encoding="utf-8"
            )
        ),
        "disclosure.md",
        id="E13-comment_only",
    ),
]


# --------------------------------------------------------------------------
# Seam 2 -- failure translation (E1-E13) and positive paths (E14, E15)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("prepare", "expected"), _ERROR_CASES)
def test_profile_error(
    tmp_path: Path, prepare: Callable[[Path], str], expected: str
) -> None:
    """E1-E13: every enumerated failure raises ProfileError naming its location.

    The exact-type assertion rules out a blanket `except Exception as e: raise
    ProfileError(str(e))` wrapper at the top of the loader: that would satisfy
    an isinstance check while being unable to name `twilio.phone_number` for a
    KeyError('phone_number'), and would relabel a programmer bug in the loader
    as a profile error. The location assertion is what forces the schema to be
    held as data rather than as a sequence of lookups.
    """
    name = prepare(tmp_path)

    with pytest.raises(ProfileError) as caught:
        load_profile(name, root=tmp_path)

    assert type(caught.value) is ProfileError
    assert expected in str(caught.value)


def test_sms_table_is_optional(tmp_path: Path) -> None:
    """E14: a profile with no [sms] table loads, with an empty sms mapping.

    A validator that reads the seam's "sms must be a table if present" as "sms
    is required" passes every failure-direction row below and still breaks A2's
    "no SMS unless the profile defines a template" for the first vertical that
    omits one.
    """
    data = _good_data()
    del data["sms"]
    _write_profile(tmp_path / _NAME, data)

    profile = load_profile(_NAME, root=tmp_path)

    assert profile.sms == {}


def test_sms_coverage_may_be_partial(tmp_path: Path) -> None:
    """E15: templates for a subset of the outcomes load with exactly those keys."""
    data = _good_data()
    assert len(data["outcomes"]["allowed"]) > len(
        data["sms"]
    )  # partial by construction
    _write_profile(tmp_path / _NAME, data)

    profile = load_profile(_NAME, root=tmp_path)

    assert set(profile.sms) == {"new_client"}
    assert profile.sms["new_client"].text == data["sms"]["new_client"]["text"]
    assert profile.sms["new_client"].links == {"calendly_url": _LINK}


# --------------------------------------------------------------------------
# Seam 1 -- placeholder grammar (G1-G8)
# --------------------------------------------------------------------------

_NAIVE_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _naive_regex_fields(text: str) -> frozenset[str]:
    """The obvious wrong implementation, kept as an executable foil.

    G1 asserts this disagrees with the real extractor on G1's text. Keeping the
    foil here means that if someone later "simplifies" G1's string to something
    the regex happens to get right, the discrimination property fails loudly
    rather than quietly ceasing to test anything.
    """
    return frozenset(_NAIVE_PLACEHOLDER.findall(text))


@dataclasses.dataclass(frozen=True)
class _Grammar:
    text: str
    links: dict[str, str]
    fields: frozenset[str] | None  # None -> the template must be rejected
    naive_differs: bool = False


_GRAMMAR_CASES = [
    pytest.param(
        _Grammar(
            text="{{calendly_url}} details at {booking_url}",
            links={"booking_url": _LINK},
            fields=frozenset({"booking_url"}),
            naive_differs=True,
        ),
        id="G1",
    ),
    pytest.param(_Grammar("{0}", {}, None), id="G2"),
    pytest.param(_Grammar("{}", {}, None), id="G3"),
    pytest.param(_Grammar("{calendly_url.host}", {}, None), id="G4"),
    pytest.param(_Grammar("{links[0]}", {}, None), id="G5"),
    pytest.param(
        _Grammar(
            "{calendly_url:>10}", {"calendly_url": _LINK}, frozenset({"calendly_url"})
        ),
        id="G6",
    ),
    pytest.param(
        _Grammar(
            "{calendly_url!r}", {"calendly_url": _LINK}, frozenset({"calendly_url"})
        ),
        id="G7",
    ),
    pytest.param(_Grammar("{calendly_url", {"calendly_url": _LINK}, None), id="G8"),
]


@pytest.mark.parametrize("case", _GRAMMAR_CASES)
def test_placeholder_grammar(tmp_path: Path, case: _Grammar) -> None:
    """G1-G8: placeholders are read with str.format's grammar, not a regex.

    Every row goes through load_profile against a real directory: str.format is
    what S5 will actually call, so the check has to use str.format's own parser.
    Escaped braces, positional fields, attribute and index access, format specs
    and conversions are all cases where a `\\{(\\w+)\\}` regex is wrong in one
    direction or the other -- G1 pins that disagreement down explicitly.
    """
    data = _good_data()
    data["sms"]["new_client"] = {"text": case.text, **case.links}
    _write_profile(tmp_path / _NAME, data)

    if case.fields is None:
        with pytest.raises(ProfileError) as caught:
            load_profile(_NAME, root=tmp_path)
        assert type(caught.value) is ProfileError
        assert "sms.new_client.text" in str(caught.value)
        return

    profile = load_profile(_NAME, root=tmp_path)

    assert profile.sms["new_client"].text == case.text
    assert _placeholder_fields(case.text) == case.fields
    if case.naive_differs:
        assert _naive_regex_fields(case.text) != _placeholder_fields(case.text)


# --------------------------------------------------------------------------
# Seam 4 -- value-object integrity (V1-V4)
# --------------------------------------------------------------------------


def _capture_parse(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Spy on the TOML parse so a test can hold the dict the loader was built from.

    Patching the real parser rather than adding a seam to the loader: a
    production hook that exists only for this test would be the very coupling
    the frozen dataclass is meant to avoid.
    """
    captured: list[dict[str, Any]] = []
    real = tomllib.loads

    def spy(text: str) -> dict[str, Any]:
        parsed = real(text)
        captured.append(parsed)
        return parsed

    monkeypatch.setattr(tomllib, "loads", spy)
    return captured


def test_profile_does_not_alias_parsed_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V1: mutating the parsed TOML after load leaves the Profile unchanged.

    The wrong implementation this rules out is `SmsTemplate(text=entry.pop("text"),
    links=entry)`, whose links alias the parsed sub-dict -- mypy accepts it,
    because the TOML value is Any, and every other seam passes untouched, since
    none of them mutate after construction. It would make frozen=True a lie:
    anyone still holding the parsed dict could rewrite a live profile's SMS
    links with nothing to show for it.
    """
    captured = _capture_parse(monkeypatch)
    _write_profile(tmp_path / _NAME)
    profile = load_profile(_NAME, root=tmp_path)
    (parsed,) = captured

    parsed["sms"]["new_client"]["calendly_url"] = "hacked"
    parsed["sms"]["new_client"]["extra"] = "https://example.com/extra"
    parsed["outcomes"]["allowed"].append("hacked")

    assert profile.sms["new_client"].links == {"calendly_url": _LINK}
    assert set(profile.sms) == {"new_client"}
    assert profile.outcomes == ("new_client", "not_qualified", "callback")


def test_profile_rejects_attribute_assignment(tmp_path: Path) -> None:
    """V2: Profile is frozen -- attribute assignment raises FrozenInstanceError."""
    _write_profile(tmp_path / _NAME)
    profile = load_profile(_NAME, root=tmp_path)

    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.phone_number = "+440000000000"  # type: ignore[misc]


def test_profile_is_not_hashable(tmp_path: Path) -> None:
    """V3: hash(profile) raises TypeError -- a documented non-feature (Q9).

    Asserted rather than left to be discovered: sms and links are dict-backed,
    so neither mypy --strict nor ruff will ever mention it, and S2-S5 all consume
    this type. A future @lru_cache or set user should find a test, not a landmine.
    """
    _write_profile(tmp_path / _NAME)
    profile = load_profile(_NAME, root=tmp_path)

    with pytest.raises(TypeError):
        hash(profile)


def test_profile_copies_parsed_containers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V4: the Profile's containers are new objects, not the parsed ones.

    The tuple assertion is the half only identity can catch: tomllib returns
    dict[str, Any], so `outcomes=parsed["outcomes"]["allowed"]` stored raw passes
    mypy --strict and every value-equality assertion in this file.
    """
    captured = _capture_parse(monkeypatch)
    _write_profile(tmp_path / _NAME)
    profile = load_profile(_NAME, root=tmp_path)
    (parsed,) = captured

    assert profile.sms is not parsed["sms"]
    assert profile.sms["new_client"].links is not parsed["sms"]["new_client"]
    assert isinstance(profile.outcomes, tuple)
    assert profile.outcomes is not parsed["outcomes"]["allowed"]


# --------------------------------------------------------------------------
# Seam 5 -- whitespace policy, observable in what is STORED (W1-W6)
# --------------------------------------------------------------------------

_PADDED = "\n\n  TEXT  \n\n"


def test_disclosure_is_stripped(tmp_path: Path) -> None:
    """W1: disclosure.md is stored stripped -- it is spoken inside TwiML <Say>.

    Leading and trailing newlines there are audible pauses before the compliance
    line, which is the one prompt whose surrounding whitespace is not the
    author's to keep.
    """
    _write_profile(tmp_path / _NAME, prompts=dict.fromkeys(_PROMPTS, _PADDED))

    profile = load_profile(_NAME, root=tmp_path)

    assert profile.disclosure == "TEXT"


def test_model_prompts_are_verbatim(tmp_path: Path) -> None:
    """W2: conversation.md and analysis.md are stored byte-for-byte.

    They go to the model as system text, where the layout is the author's -- a
    deliberate trailing blank line separating sections is theirs to keep, and
    the model does not care either way.
    """
    _write_profile(tmp_path / _NAME, prompts=dict.fromkeys(_PROMPTS, _PADDED))

    profile = load_profile(_NAME, root=tmp_path)

    assert profile.conversation == _PADDED
    assert profile.analysis == _PADDED


def test_required_scalars_are_stripped(tmp_path: Path) -> None:
    """W3: every required scalar is STORED stripped, not merely validated stripped.

    The wrong implementation this rules out is validate-on-stripped/store-raw:
    every rejection row in this file still passes, and a padded "  +44...  "
    reaches Twilio -- the late failure the whole module exists to prevent.
    """
    data = _good_data()
    expected = {dotted: data[table][key] for table, key, dotted in _REQUIRED_SCALARS}
    for table, key, _ in _REQUIRED_SCALARS:
        data[table][key] = f"  {data[table][key]}  "
    _write_profile(tmp_path / _NAME, data)

    profile = load_profile(_NAME, root=tmp_path)

    assert profile.display_name == expected["vertical.name"]
    assert profile.live_model == expected["gemini.live_model"]
    assert profile.analysis_model == expected["gemini.analysis_model"]
    assert profile.phone_number == expected["twilio.phone_number"]
    assert profile.sms_sender_id == expected["twilio.sms_sender_id"]
    assert profile.operator_email == expected["operator.email"]


def test_outcomes_are_stripped(tmp_path: Path) -> None:
    """W4: every outcome label is stored stripped.

    A padded label is also unmatchable: `[sms.new_client]` would no longer name
    any allowed outcome, and S4's structured output could never return one.
    """
    data = _good_data()
    original = list(data["outcomes"]["allowed"])
    data["outcomes"]["allowed"] = [f"  {label}  " for label in original]
    _write_profile(tmp_path / _NAME, data)

    profile = load_profile(_NAME, root=tmp_path)

    assert profile.outcomes == tuple(original)


def test_link_values_are_stripped(tmp_path: Path) -> None:
    """W5: every link value is stored stripped -- a padded URL ships a broken SMS."""
    data = _good_data()
    data["sms"]["new_client"]["calendly_url"] = f"  {_LINK}  "
    _write_profile(tmp_path / _NAME, data)

    profile = load_profile(_NAME, root=tmp_path)

    assert profile.sms["new_client"].links["calendly_url"] == _LINK


def test_sms_text_is_verbatim(tmp_path: Path) -> None:
    """W6: SmsTemplate.text is stored verbatim -- the author's spacing is intentional."""
    data = _good_data()
    padded = "  Hi {calendly_url}  "
    data["sms"]["new_client"]["text"] = padded
    _write_profile(tmp_path / _NAME, data)

    profile = load_profile(_NAME, root=tmp_path)

    assert profile.sms["new_client"].text == padded


# --------------------------------------------------------------------------
# Seam 3 -- the shipped profile directories (P1-P5)
# --------------------------------------------------------------------------

# Derived from __file__, never from the CWD: these tests must mean the same
# thing run from the repo root, from tests/, or from an IDE.
_SHIPPED_ROOT = Path(__file__).resolve().parents[1] / "profiles"
_SHIPPED = ("mortgage-broker", "eco-consultant")
# The two model names may legitimately coincide across verticals, and `name` is
# the argument rather than profile content, so all three are excluded from the
# differs-loop. Everything else on Profile must differ.
_MAY_COINCIDE = {"name", "live_model", "analysis_model"}


def test_shipped_profiles_load() -> None:
    """P1: both shipped directories load through the real loader, not by inspection.

    Validating the shipped data with the same code path the service uses is what
    stops the two directories drifting into invalidity while a suite of
    synthetic tmp_path fixtures stays green.
    """
    for name in _SHIPPED:
        load_profile(name, root=_SHIPPED_ROOT)


def test_shipped_profiles_differ_in_every_vertical_field() -> None:
    """P2: every vertical-specific field differs between the two shipped profiles.

    A loop over dataclasses.fields rather than a hand-written list, so a field
    added to Profile later is covered without anyone remembering to add it here.
    Rules out an eco-consultant that is the broker profile with one word changed,
    which would make A4's profile-swap demonstration vacuous.
    """
    broker = load_profile("mortgage-broker", root=_SHIPPED_ROOT)
    eco = load_profile("eco-consultant", root=_SHIPPED_ROOT)

    for field in dataclasses.fields(Profile):
        if field.name in _MAY_COINCIDE:
            continue
        assert getattr(broker, field.name) != getattr(eco, field.name), field.name

    broker_urls = {url for t in broker.sms.values() for url in t.links.values()}
    eco_urls = {url for t in eco.sms.values() for url in t.links.values()}
    assert broker_urls and eco_urls
    assert broker_urls.isdisjoint(eco_urls)


def test_shipped_sms_coverage_is_partial() -> None:
    """P3: the shipped data exercises partial [sms] coverage, not just full.

    eco-consultant deliberately defines a template for only some of its
    outcomes, so the optional-and-partial path E14/E15 prove on synthetic data
    is also exercised by the directories that actually ship.
    """
    broker = load_profile("mortgage-broker", root=_SHIPPED_ROOT)
    eco = load_profile("eco-consultant", root=_SHIPPED_ROOT)

    assert set(broker.sms) == {"new_client"}
    assert set(eco.sms) < set(eco.outcomes)


def test_shipped_profile_name_is_the_argument() -> None:
    """P4: Profile.name is the directory slug; display_name is a distinct label.

    The equality against the argument is the whole test. A loader that derived
    `name` from `[vertical] name` -- the conflation Q12 corrected -- still yields
    two different names across the two profiles, so it passes P2's differs-loop
    untouched; only this assertion catches it.
    """
    for name in _SHIPPED:
        profile = load_profile(name, root=_SHIPPED_ROOT)

        assert profile.name == name
        assert profile.display_name != profile.name


def test_shipped_prompts_are_marked_draft() -> None:
    """P5: every shipped .md opens with the DRAFT marker (Q11).

    Test-backed rather than eyeballed, so a later reader cannot mistake drafted
    prose for owner-approved compliance wording.
    """
    for name in _SHIPPED:
        for stem in _PROMPTS:
            path = _SHIPPED_ROOT / name / f"{stem}.md"
            assert path.read_text(encoding="utf-8").startswith(_DRAFT_MARKER), path


def test_leading_comment_is_stripped_from_prompts(tmp_path: Path) -> None:
    """W7: a leading HTML comment block is absent from all three stored prompts.

    Q11 puts a review marker at the top of every shipped prompt file, and P5
    keeps it there. But disclosure.md is spoken verbatim by Twilio <Say>, so
    without this the caller hears the marker read out -- and P5 would have made
    that permanent, outliving the draft text it was written for (Q15).
    """
    _write_profile(tmp_path / _NAME, prompts=dict.fromkeys(_PROMPTS, _MARKED))

    profile = load_profile(_NAME, root=tmp_path)

    for text in (profile.disclosure, profile.conversation, profile.analysis):
        assert _DRAFT_MARKER not in text
        assert text.startswith("Real content the caller must hear.")
        # Only the LEADING block goes. The second comment is the author's prose
        # and must survive -- a greedy `<!--.*-->` under DOTALL runs to the LAST
        # `-->` in the file, deleting the sentence between the two on its way.
        # That pattern passed the entire suite until this line existed.
        assert "<!-- aside -->" in text


def test_prompt_without_leading_comment_is_unchanged(tmp_path: Path) -> None:
    """W8: a prompt file with no leading comment is stored byte-for-byte.

    The direction that matters. A pattern that strips too much -- a comment
    anywhere in the prose, or simply the first line of any file -- passes W7 and
    every other row in this suite while quietly deleting what the author wrote.
    Only disclosure differs here, and only by Q10's strip.
    """
    _write_profile(tmp_path / _NAME, prompts=dict.fromkeys(_PROMPTS, _UNMARKED))

    profile = load_profile(_NAME, root=tmp_path)

    assert profile.conversation == _UNMARKED
    assert profile.analysis == _UNMARKED
    assert profile.disclosure == _UNMARKED.strip()
