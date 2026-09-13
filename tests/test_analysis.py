"""Tests for the analysis slice.

Every test's docstring opens with its behavior id from the ratified id set in
`.claude/overseer/slice/analysis.md`. The exit criterion is a property over that
set in both directions: every id has a passing node, and no node here fails to
trace to an id.
"""

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from decana.analysis.analyse import UNCLASSIFIED, analyse, build_schema
from decana.analysis.gemini_client import GeminiAnalysisClient
from decana.analysis.model import Analysis
from decana.profile.load import load_profile
from decana.profile.model import Profile
from decana.twilio.records import TranscriptTurn

REPO_ROOT = Path(__file__).resolve().parent.parent

TURNS = (
    TranscriptTurn(role="caller", text="I want to remortgage."),
    TranscriptTurn(role="model", text="Happy to help."),
    TranscriptTurn(role="caller", text="My flat is in Manchester."),
    TranscriptTurn(role="model", text="Noted."),
)


@pytest.fixture
def profile() -> Profile:
    """A profile whose two model names DIFFER, so A1.c can discriminate them.

    The shipped profiles may legitimately use the same model for both; that would
    make an assertion about which one was passed vacuous.
    """
    loaded = load_profile("mortgage-broker", root=REPO_ROOT / "profiles")
    return replace(loaded, analysis_model="analysis-model-x", live_model="live-model-y")


class CapturingClient:
    """An `AnalysisClient` that records its kwargs and returns a canned response."""

    def __init__(self, response: str = "", raises: BaseException | None = None) -> None:
        self.response = response
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def generate_json(
        self, *, model: str, system: str, user: str, schema: Mapping[str, Any]
    ) -> str:
        self.calls.append(
            {"model": model, "system": system, "user": user, "schema": schema}
        )
        if self.raises is not None:
            raise self.raises
        return self.response


def _ok(
    outcome: str = "new_client", notes: list[str] | None = None, summary: str = "s"
) -> str:
    return json.dumps(
        {
            "outcome": outcome,
            "compliance_notes": notes if notes is not None else [],
            "summary": summary,
        }
    )


def _run(
    client: CapturingClient,
    profile: Profile,
    *,
    turns: Sequence[TranscriptTurn] = TURNS,
    timeout_s: float = 30.0,
) -> Analysis:
    return asyncio.run(analyse(turns, profile, client=client, timeout_s=timeout_s))


def test_a1a_schema_constrains_outcome_to_the_profile_vocabulary(
    profile: Profile,
) -> None:
    """A1.a -- the schema sent carries enum == (*profile.outcomes, "unclassified").

    Asserted on what was SENT, not on intent: the constraint has to reach the
    provider to do anything.
    """
    client = CapturingClient(_ok())
    _run(client, profile)

    schema = client.calls[0]["schema"]
    assert schema["properties"]["outcome"]["enum"] == [*profile.outcomes, UNCLASSIFIED]


def test_a1b_an_out_of_vocabulary_outcome_is_downgraded(profile: Profile) -> None:
    """A1.b -- an outcome the profile never heard of becomes unclassified, raw kept.

    Rules out trusting the schema alone. `outcome` is what S5 keys the SMS template
    on, so a foreign value there picks an SMS by a string the profile does not have.
    """
    body = _ok(outcome="definitely_not_a_real_outcome")
    result = _run(CapturingClient(body), profile)

    assert result.outcome == UNCLASSIFIED
    assert result.raw == body


def test_a1c_the_model_kwarg_is_the_profiles_analysis_model(profile: Profile) -> None:
    """A1.c -- model == profile.analysis_model, which differs from live_model here.

    One attribute apart, and the wrong one produces a working call against the wrong
    model -- a conversational model doing structured analysis -- with no error.
    """
    client = CapturingClient(_ok())
    _run(client, profile)

    assert client.calls[0]["model"] == profile.analysis_model
    assert client.calls[0]["model"] != profile.live_model


def test_a1d_the_schema_declares_compliance_notes_as_an_array_of_strings(
    profile: Profile,
) -> None:
    """A1.d -- compliance_notes is an ARRAY with STRING items in the schema built here.

    An unconstrained array turns S4-Q10's coercion from a backstop into the
    load-bearing path.
    """
    schema = build_schema(profile)
    notes = schema["properties"]["compliance_notes"]

    assert notes["type"] == "ARRAY"
    assert notes["items"]["type"] == "STRING"


def test_a1e_the_pure_happy_path(profile: Profile) -> None:
    """A1.e -- one well-formed response yields outcome, notes and raw together.

    Every other clause isolates one field on a crafted response; nothing else
    asserts that an ordinary success produces all of them at once.
    """
    body = _ok(
        outcome=profile.outcomes[0], notes=["flagged a rate question"], summary="ok"
    )
    result = _run(CapturingClient(body), profile)

    assert result.outcome == profile.outcomes[0]
    assert result.compliance_notes == ("flagged a rate question",)
    assert result.summary == "ok"
    assert result.raw == body


def test_a2a_the_transcript_renders_as_caller_and_model_lines_in_order(
    profile: Profile,
) -> None:
    """A2.a -- the user prompt equals the exact CALLER:/MODEL: block, in order.

    Equality, not containment: a reordered transcript still contains every line.
    """
    client = CapturingClient(_ok())
    _run(client, profile)

    assert client.calls[0]["user"] == (
        "CALLER: I want to remortgage.\n"
        "MODEL: Happy to help.\n"
        "CALLER: My flat is in Manchester.\n"
        "MODEL: Noted."
    )


def test_a3a_the_system_prompt_carries_the_profile_text_and_a_json_instruction(
    profile: Profile,
) -> None:
    """A3.a -- system == profile.analysis + an explicit JSON instruction.

    The SDK's own source says the mime type alone leaves the behaviour undefined;
    the profile is owner-authored DRAFT prose that never mentions JSON.
    """
    stripped = replace(
        profile, analysis="Judge the call. No mention of the format here."
    )
    client = CapturingClient(_ok())
    _run(client, stripped)

    system = client.calls[0]["system"]
    assert stripped.analysis in system
    assert "JSON" in system
    assert "outcome" in system and "compliance_notes" in system and "summary" in system


def test_a4a_an_empty_transcript_short_circuits(profile: Profile) -> None:
    """A4.a -- empty transcript: unclassified, client never called, summary names it.

    A paid call to analyse nothing is the one version of this failure that costs
    money. A call that dropped before anyone spoke is the ordinary cause.
    """
    client = CapturingClient(_ok())
    result = _run(client, profile, turns=())

    assert result.outcome == UNCLASSIFIED
    assert client.calls == [], "no API call may be made for an empty transcript"
    assert "empty transcript" in result.summary


@pytest.mark.parametrize("mode", ["raises", "sleeps"])
def test_a4b_a_timeout_is_unclassified_and_named(profile: Profile, mode: str) -> None:
    """A4.b -- timeout: unclassified, and summary names the timeout.

    Both shapes: the client raising TimeoutError, and the client simply taking
    longer than timeout_s -- the second is what wait_for actually has to catch.
    """
    if mode == "raises":
        client = CapturingClient(raises=TimeoutError("slow"))
        result = _run(client, profile, timeout_s=30.0)
    else:

        class SlowClient(CapturingClient):
            async def generate_json(self, **kwargs: Any) -> str:
                await asyncio.sleep(5)
                return ""

        client = SlowClient()
        result = _run(client, profile, timeout_s=0.05)

    assert result.outcome == UNCLASSIFIED
    assert "timeout" in result.summary.lower()


def test_a4c_an_arbitrary_client_exception_is_unclassified_and_named(
    profile: Profile,
) -> None:
    """A4.c -- any other exception: unclassified, and summary carries its type name.

    S4-Q7's justification for catching Exception rather than a narrow list is that
    the summary makes a bug in our own code visible rather than swallowed. Without
    this assertion that justification is unbacked.
    """
    result = _run(CapturingClient(raises=RuntimeError("api down")), profile)

    assert result.outcome == UNCLASSIFIED
    assert "RuntimeError" in result.summary


def test_a4d_a_non_json_response_is_unclassified_with_raw_kept(
    profile: Profile,
) -> None:
    """A4.d -- not JSON: unclassified, raw preserved, summary says unparsable."""
    result = _run(CapturingClient("I am not JSON at all"), profile)

    assert result.outcome == UNCLASSIFIED
    assert result.raw == "I am not JSON at all"
    assert "parse" in result.summary.lower()


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"compliance_notes": [], "summary": "s"}),
        json.dumps({"outcome": 5, "compliance_notes": [], "summary": "s"}),
        json.dumps(
            {"outcome": "new_client", "compliance_notes": "a string", "summary": "s"}
        ),
    ],
    ids=["missing_outcome", "outcome_not_a_string", "notes_not_a_list"],
)
def test_a4e_well_formed_json_of_the_wrong_shape(profile: Profile, body: str) -> None:
    """A4.e -- valid JSON, wrong shape: unclassified, raw kept, summary distinct from A4.d's.

    "wrong shape" and "not JSON at all" are different diagnoses a week later, so
    the two summaries must not read the same.
    """
    result = _run(CapturingClient(body), profile)

    assert result.outcome == UNCLASSIFIED
    assert result.raw == body
    assert "shape" in result.summary.lower()
    assert "parse" not in result.summary.lower(), "must be distinguishable from A4.d"


def test_a4f_cancellation_propagates_and_is_not_converted(profile: Profile) -> None:
    """A4.f -- CancelledError is RE-RAISED, not turned into an Analysis.

    This is the only node that distinguishes `except Exception` from
    `except BaseException` -- one word wider passes every other test here plus ruff
    and mypy, while silently costing teardown the ability to cancel this work.
    """
    client = CapturingClient(raises=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        _run(client, profile)


def test_a5a_raw_is_preserved_on_the_failure_path(profile: Profile) -> None:
    """A5.a -- raw equals the exact text the client returned, on an unparsable response.

    S5 writes raw to {call_sid}.analysis.json, and a parse failure is precisely when
    someone needs to see what the model actually said.
    """
    body = "{ this is not valid json"
    result = _run(CapturingClient(body), profile)

    assert result.raw == body


def test_a5b_the_failure_paths_default_compliance_notes_to_empty(
    profile: Profile,
) -> None:
    """A5.b -- the failure path's compliance_notes default is ()."""
    result = _run(CapturingClient(raises=RuntimeError("boom")), profile)

    assert result.compliance_notes == ()


def test_a5c_non_empty_notes_on_a_successful_parse_are_a_tuple(
    profile: Profile,
) -> None:
    """A5.c -- content correct AND a tuple, on the SUCCESS path.

    This is the clause that kills the passthrough, which ships the parsed list
    straight into a frozen dataclass. Asserting tuple-ness on the failure path,
    where the code hardcodes (), passes for the passthrough too.
    """
    body = _ok(notes=["mentioned a rate", "asked for a figure"])
    result = _run(CapturingClient(body), profile)

    assert result.compliance_notes == ("mentioned a rate", "asked for a figure")
    assert isinstance(result.compliance_notes, tuple)


def test_a5d_compliance_notes_as_a_bare_string_is_a_wrong_shape(
    profile: Profile,
) -> None:
    """A5.d -- a bare string for compliance_notes is unclassified, not iterated.

    Iterating a string yields one note per character -- not a degraded result but a
    nonsense one, reaching a compliance view looking like structured data.
    """
    body = json.dumps(
        {"outcome": "new_client", "compliance_notes": "a single note", "summary": "s"}
    )
    result = _run(CapturingClient(body), profile)

    assert result.outcome == UNCLASSIFIED
    assert result.compliance_notes == ()


def test_a6a_a_long_summary_is_truncated(profile: Profile) -> None:
    """A6.a -- a 5000-char summary comes back at most 600 chars.

    Rules out passthrough, whose consequence is an operator brief with a wall of
    text where a summary should be.
    """
    result = _run(CapturingClient(_ok(summary="x" * 5000)), profile)

    assert len(result.summary) <= 600


def test_a7a_the_real_client_asks_for_json(profile: Profile) -> None:
    """A7.a -- response_mime_type is application/json and the schema carries the enum.

    Inspected without a network request. The schema is stored as a plain dict, not
    coerced to types.Schema, so this is subscript access.
    """
    config = GeminiAnalysisClient.build_config(
        system="sys", schema=build_schema(profile)
    )

    assert config.response_mime_type == "application/json"
    assert config.response_schema["properties"]["outcome"]["enum"] == [  # type: ignore[index]
        *profile.outcomes,
        UNCLASSIFIED,
    ]


def test_a7b_the_real_client_passes_the_schema_with_the_array_intact(
    profile: Profile,
) -> None:
    """A7.b -- the forwarded schema keeps compliance_notes as an ARRAY of STRINGs."""
    config = GeminiAnalysisClient.build_config(
        system="sys", schema=build_schema(profile)
    )

    notes = config.response_schema["properties"]["compliance_notes"]  # type: ignore[index]
    assert notes["type"] == "ARRAY"
    assert notes["items"]["type"] == "STRING"


def test_a7c_the_async_facade_is_awaited_not_the_blocking_one(profile: Profile) -> None:
    """A7.c -- client.aio.models.generate_content is awaited; the sync facade is not used.

    The sync facade is a blocking def. Wrapping it in an async def gives a coroutine
    with no internal await, which defeats wait_for's timeout and stalls the event
    loop forwarding audio for every other live call. No fake AnalysisClient can
    catch this, because a fake suspends correctly by construction.
    """
    client = GeminiAnalysisClient(api_key="k")

    async def _go() -> str:
        with patch.object(
            type(client._client.aio.models),
            "generate_content",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = type("R", (), {"text": _ok()})()
            out = await client.generate_json(
                model="m", system="s", user="u", schema=build_schema(profile)
            )
            assert mock.await_count == 1, "the async facade must be awaited"
            return out

    assert asyncio.run(_go()) == _ok()


def test_a7d_the_api_key_is_forwarded_not_taken_from_the_environment() -> None:
    """A7.d -- genai.Client receives the api_key passed in, not the environment's.

    The SDK falls back to os.environ['GEMINI_API_KEY'] when none is passed, and that
    is exactly what this project's deploy injects -- so a dropped key passes CI, the
    smoke AND production. This assertion holds regardless of the environment, which
    is the whole point.
    """
    with patch("decana.analysis.gemini_client.genai.Client") as mock_client:
        GeminiAnalysisClient(api_key="distinct-fixture-value")

    assert mock_client.call_args.kwargs == {"api_key": "distinct-fixture-value"}
