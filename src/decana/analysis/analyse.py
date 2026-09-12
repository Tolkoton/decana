"""Turn a finished call's transcript into a structured `Analysis`.

WHAT: renders the transcript, asks an injected `AnalysisClient` for JSON constrained
by a schema built from the profile, and parses the answer into an `Analysis`.

THE CENTRAL PROPERTY: **`analyse` never raises.** An empty transcript, a timeout, an
API error, an unparsable response and an out-of-vocabulary outcome all yield
`Analysis(outcome="unclassified", ...)` with the reason in `summary`. This runs inside
S5's `post_call`, inside S3's `_teardown`, where an escaping exception costs the call
its record.

The one exception to that, and it is deliberate: `asyncio.CancelledError` propagates.
It is a `BaseException`, so `except Exception` lets it through, and teardown needs to
be able to cancel this work. See S4-Q7.

WHAT THIS DOES NOT DO: dispatch, retry, prompt authoring, transcript storage. It never
imports `google.genai` -- only `gemini_client.py` does.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from decana.analysis.model import Analysis
from decana.profile.model import Profile
from decana.twilio.records import TranscriptTurn

__all__ = ["UNCLASSIFIED", "AnalysisClient", "analyse"]

UNCLASSIFIED = "unclassified"
MAX_SUMMARY_CHARS = 600

_JSON_INSTRUCTION = (
    "Reply with a single JSON object and nothing else. It must have exactly these "
    'keys: "outcome" (one of the allowed values), "compliance_notes" (an array of '
    'strings, empty if nothing is flagged), and "summary" (at most '
    f"{MAX_SUMMARY_CHARS} characters)."
)


class AnalysisClient(Protocol):
    """The one thing `analyse` needs from a model provider."""

    async def generate_json(
        self, *, model: str, system: str, user: str, schema: Mapping[str, Any]
    ) -> str: ...


def render_transcript(transcript: Sequence[TranscriptTurn]) -> str:
    """`CALLER: ...` / `MODEL: ...` lines, in order (S4-Q2)."""
    return "\n".join(
        f"{'CALLER' if turn.role == 'caller' else 'MODEL'}: {turn.text}"
        for turn in transcript
    )


def build_schema(profile: Profile) -> dict[str, Any]:
    """The JSON schema sent with the request.

    `outcome` is constrained to the profile's vocabulary plus `unclassified`, and
    `compliance_notes` is an ARRAY whose items are STRINGs -- an unconstrained array
    would turn S4-Q10's coercion from a backstop into the load-bearing path (S4-Q11).
    """
    return {
        "type": "OBJECT",
        "properties": {
            "outcome": {"type": "STRING", "enum": [*profile.outcomes, UNCLASSIFIED]},
            "compliance_notes": {"type": "ARRAY", "items": {"type": "STRING"}},
            "summary": {"type": "STRING"},
        },
        "required": ["outcome", "compliance_notes", "summary"],
    }


def _unclassified(reason: str, raw: str = "") -> Analysis:
    """Every failure path lands here, with the reason named (S4-Q4, S4-Q7)."""
    return Analysis(
        outcome=UNCLASSIFIED,
        compliance_notes=(),
        summary=reason[:MAX_SUMMARY_CHARS],
        raw=raw,
    )


def _notes_from(payload: Any) -> tuple[str, ...]:
    """Coerce a list's items; a non-list is a wrong shape (S4-Q10).

    Raises `TypeError` for a non-list so the caller maps it to `unclassified` --
    iterating a bare string would otherwise yield one note per character.
    """
    notes = payload.get("compliance_notes", ())
    if not isinstance(notes, list | tuple):
        raise TypeError("compliance_notes is not an array")
    return tuple(str(item) for item in notes)


def _to_analysis(text: str, profile: Profile) -> Analysis:
    """Parse one response into an `Analysis`. Raises on any wrong shape."""
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise TypeError("response is not a JSON object")

    outcome = payload["outcome"]
    if not isinstance(outcome, str):
        # A NON-STRING outcome is a wrong SHAPE, not a wrong value: the schema asked
        # for a STRING, so a number means the model ignored the type, and that is the
        # same diagnosis as `compliance_notes` arriving as a string. Distinguishing
        # the two matters a week later, when the record is all there is.
        raise TypeError("outcome is not a string")

    if outcome not in (*profile.outcomes, UNCLASSIFIED):
        # A well-formed string that is simply not in the vocabulary. Re-checked after
        # parsing even though the schema constrains it: the schema is the provider's
        # promise, and this project has falsified several (S4-Q1).
        return Analysis(
            outcome=UNCLASSIFIED,
            compliance_notes=_notes_from(payload),
            summary=str(payload.get("summary", ""))[:MAX_SUMMARY_CHARS],
            raw=text,
        )

    return Analysis(
        outcome=outcome,
        compliance_notes=_notes_from(payload),
        summary=str(payload["summary"])[:MAX_SUMMARY_CHARS],
        raw=text,
    )


async def analyse(
    transcript: Sequence[TranscriptTurn],
    profile: Profile,
    *,
    client: AnalysisClient,
    timeout_s: float = 30.0,
) -> Analysis:
    """Flow: short-circuit an empty transcript -> ask the model -> parse the answer."""
    rendered = render_transcript(transcript)
    if not rendered.strip():
        # No paid call to analyse nothing. A call that dropped before anyone spoke
        # is the ordinary cause (S4-Q5).
        return _unclassified("empty transcript: nothing to analyse")

    text = ""
    try:
        text = await asyncio.wait_for(
            client.generate_json(
                model=profile.analysis_model,
                system=f"{profile.analysis}\n\n{_JSON_INSTRUCTION}",
                user=rendered,
                schema=build_schema(profile),
            ),
            timeout=timeout_s,
        )
        return _to_analysis(text, profile)
    except TimeoutError:
        return _unclassified(
            f"timeout after {timeout_s}s waiting for the analysis model"
        )
    except json.JSONDecodeError as exc:
        return _unclassified(f"could not parse the response as JSON: {exc}", raw=text)
    except (KeyError, TypeError, ValueError) as exc:
        return _unclassified(
            f"response JSON had the wrong shape: {type(exc).__name__}: {exc}", raw=text
        )
    except Exception as exc:  # noqa: BLE001 - see S4-Q7; CancelledError still propagates
        return _unclassified(f"analysis failed: {type(exc).__name__}: {exc}", raw=text)
