"""The real `AnalysisClient`: `google-genai` asked for constrained JSON.

WHY this is the only module importing `google.genai`: everything else in the slice is
driven by the `AnalysisClient` Protocol, so `analyse` is exercisable with fakes and
without a network.

TWO THINGS HERE ARE EASY TO GET WRONG AND SILENT IF YOU DO:

1. **The async facade.** `client.aio.models.generate_content` is an `async def`;
   `client.models.generate_content` is a blocking `def`. Wrapping the blocking one in
   an `async def` produces a coroutine with no internal `await`, which defeats
   `asyncio.wait_for`'s timeout and stalls the event loop forwarding audio for every
   other live call. No fake can catch it (S4-Q9).
2. **The API key.** The SDK falls back to `os.environ['GEMINI_API_KEY']` when none is
   passed, and that is exactly the variable this project's deploy injects — so
   dropping the argument passes CI, the smoke, and production alike (S4-Q12).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from google import genai
from google.genai import types

__all__ = ["GeminiAnalysisClient"]


class GeminiAnalysisClient:
    """Adapts `google-genai` to the `AnalysisClient` Protocol."""

    def __init__(self, *, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    async def generate_json(
        self, *, model: str, system: str, user: str, schema: Mapping[str, Any]
    ) -> str:
        """Ask for JSON constrained by `schema`, and hand back the raw text."""
        config = self.build_config(system=system, schema=schema)
        response = await self._client.aio.models.generate_content(
            model=model, contents=user, config=config
        )
        return response.text or ""

    @staticmethod
    def build_config(
        *, system: str, schema: Mapping[str, Any]
    ) -> types.GenerateContentConfig:
        """The request config, separated so a test can inspect it without a network.

        `response_mime_type` alone is not enough -- the SDK's own source says the
        model "needs to be prompted to output the appropriate response type,
        otherwise the behavior is undefined", which is why `analyse` also appends a
        JSON instruction to the system prompt (S4-Q3).
        """
        return types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=dict(schema),
        )
