"""Real-environment check for the analysis slice: one live call, budgeted.

Ratified as "one real-API check against a fixture transcript (cheap, auto-run)".
Everything else in this slice runs against a fake `AnalysisClient`; this is the only
place the real `GeminiAnalysisClient` meets the real API, and the only place the
premise that the schema actually constrains the model gets tested rather than assumed.

NO HUMAN ORACLE: every assertion is machine-checkable, so this runs to completion and
its output goes in the transcript.

PARKS rather than fails when `GEMINI_API_KEY` is absent or the daily budget is spent,
and it spends the budget BEFORE opening any socket, so a crash-loop cannot exceed the
cap.

Usage:  uv run python scripts/smoke_analysis.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _budget import Budget

from decana.analysis.analyse import UNCLASSIFIED, analyse
from decana.analysis.gemini_client import GeminiAnalysisClient
from decana.profile.load import load_profile
from decana.twilio.records import TranscriptTurn

REPO_ROOT = Path(__file__).resolve().parent.parent

FIXTURE = (
    TranscriptTurn(role="model", text="Hello, thanks for calling. How can I help?"),
    TranscriptTurn(role="caller", text="I want to remortgage my flat in Manchester."),
    TranscriptTurn(role="model", text="Are you looking to borrow more, or keep the same balance?"),
    TranscriptTurn(role="caller", text="Same balance. What rate could I get?"),
    TranscriptTurn(role="model", text="I can't quote rates -- an adviser will follow up."),
)


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("PARKED: GEMINI_API_KEY is not in the environment. Nothing was called.")
        return 3

    budget = Budget(Path(".claude/overseer/.api-budget.json"))
    if not budget.try_spend("smoke_analysis"):
        print(f"PARKED: real-API budget exhausted (limit {budget.limit}/day). Nothing was called.")
        return 3
    print(f"budget: {budget.remaining()} real-API calls left today")

    profile = load_profile("mortgage-broker", root=REPO_ROOT / "profiles")
    client = GeminiAnalysisClient(api_key=os.environ["GEMINI_API_KEY"])
    result = asyncio.run(analyse(FIXTURE, profile, client=client, timeout_s=60.0))

    print(f"  outcome          : {result.outcome!r}")
    print(f"  compliance_notes : {result.compliance_notes}")
    print(f"  summary          : {result.summary[:120]!r}")
    print(f"  raw length       : {len(result.raw)} chars")

    allowed = (*profile.outcomes, UNCLASSIFIED)
    failures: list[str] = []
    if result.outcome not in allowed:
        failures.append(f"outcome {result.outcome!r} is outside {allowed}")
    if result.outcome == UNCLASSIFIED:
        # Not automatically a failure -- unclassified is a legitimate answer -- but on
        # a clean fixture transcript it means the schema or the prompt did not land,
        # which is exactly what this check exists to detect.
        failures.append(f"the model returned unclassified on a clean fixture: {result.summary}")
    if not result.raw:
        failures.append("raw is empty; nothing came back to write to the analysis file")
    else:
        try:
            json.loads(result.raw)
        except json.JSONDecodeError as exc:
            failures.append(f"raw is not valid JSON: {exc}")
    if not isinstance(result.compliance_notes, tuple):
        failures.append("compliance_notes is not a tuple")
    if len(result.summary) > 600:
        failures.append(f"summary is {len(result.summary)} chars, over the 600 bound")

    print()
    if failures:
        for line in failures:
            print(f"  FAIL: {line}")
        return 1
    print("  PASS: the real model returned a schema-conformant analysis.")
    return 0


if __name__ == "__main__":
    print("=== smoke: analysis (real Gemini) ===")
    raise SystemExit(main())
