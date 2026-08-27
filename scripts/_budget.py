"""A disk-persisted cap on real paid-API calls.

WHY on disk rather than in memory: the loop this guards runs unattended across
session deaths and restarts. An in-process counter resets on every restart, which
turns "at most N calls" into "at most N calls per crash" -- and a crash-loop
around a failing smoke is exactly the shape that spends money while looking like
progress.

WHY it parks rather than raises: under the unattended rules a blocked item is
logged with its unblocker and the loop moves on. A cap that killed the process
would idle the machine over something that is not an error.

Usage:
    from _budget import Budget
    budget = Budget(Path(".claude/overseer/.api-budget.json"), limit=20)
    if not budget.try_spend("smoke_twilio_server"):
        ...  # park; do not call the API
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["Budget"]


@dataclass
class Budget:
    """Counts real-API calls against a daily limit, persisted across restarts."""

    path: Path
    limit: int = 20

    def _load(self) -> dict[str, Any]:
        """Read today's state. A MISSING file starts fresh; a CORRUPT one fails closed.

        The two cases look similar and must not be treated alike. A missing file is
        the first run, and refusing to spend then would park the loop forever. A
        corrupt file means the count is unknown -- and for a spending guard, unknown
        must mean "no", because failing open removes the cap entirely and the whole
        point of the cap is that nobody is watching. One parked smoke is cheap; an
        uncapped crash-loop against a paid API is not.
        """
        today = datetime.now(UTC).date().isoformat()
        state: dict[str, Any]
        try:
            raw = self.path.read_text()
        except OSError:
            return {"date": today, "spent": 0, "calls": []}

        try:
            state = json.loads(raw)
            if not isinstance(state, dict):
                raise TypeError("budget state is not an object")
        except (json.JSONDecodeError, TypeError, ValueError):
            return {"date": today, "spent": self.limit, "calls": [], "corrupt": True}

        if state.get("date") != today:
            # A new UTC day resets the count. Deliberately date-based rather than
            # a rolling window: a fresh session must be able to reconstruct the
            # budget from the file alone, with no memory of when calls happened.
            return {"date": today, "spent": 0, "calls": []}
        return state

    def remaining(self) -> int:
        state = self._load()
        return max(0, self.limit - int(state.get("spent", 0)))

    def try_spend(self, label: str, cost: int = 1) -> bool:
        """Record `cost` calls if the budget allows. Returns False if capped."""
        state = self._load()
        if state.get("corrupt"):
            # Unknown count. Refuse, and say why -- a silent refusal reads as a
            # normal cap and nobody goes and fixes the file.
            print(f"budget: {self.path} is corrupt; refusing to spend until it is repaired")
            return False
        spent = int(state.get("spent", 0))
        if spent + cost > self.limit:
            return False

        calls: list[dict[str, Any]] = list(state.get("calls", []))
        calls.append(
            {"at": datetime.now(UTC).isoformat(), "label": label, "cost": cost}
        )
        state["spent"] = spent + cost
        state["calls"] = calls[-50:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2))
        return True
