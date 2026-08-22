# Overseer self-improvement audit log

Proposals from the overseer for changes to its own SKILL.md. The overseer
NEVER modifies SKILL.md directly — proposals here await human ratification
(propose → gate → ratify → replay).

This file is the V2 path. In V1, the overseer just appends proposals; the
human reads them and edits SKILL.md manually when ratified.

## Proposal format

```
## <ISO timestamp UTC> — <proposed change>
- Evidence: <ledger entries supporting this — minimum 3 cited>
- Rationale: <why this would improve the overseer>
- Risk: <how this could go wrong>
- Status: PROPOSED | RATIFIED | REJECTED
```

## When to propose

- A pattern fired 5+ times across 3+ slices and is not in the current
  12-check checklist → propose adding it.
- A current check fires often but is reversed by the human in
  escalations.md → propose tuning or removal.
- A class of escalation is consistently waved through → propose
  autonomous handling.

## What NOT to propose

- Removing any check just because it triggers BLOCKs frequently. Frequent
  BLOCKs are the point. Anti-Goodhart.
- Adding checks that mimic existing tooling (linters, type checks).
- Lowering the citation-or-prune threshold.

---

(no proposals yet)
