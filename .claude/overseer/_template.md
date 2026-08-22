# Slice <slug> — planning artifact

## Goal
What we're building and why. One paragraph. Measurable target if applicable.

## Out of scope (deliberate)
What we're NOT doing in this slice and why.
- <item> — why deferred / why excluded

## Decisions (with WHY)
- Q1: <decision> — chosen because <rationale>. Rejected: <alt> because <reason>.
- Q2: <decision> — chosen because <rationale>. Rejected: <alt> because <reason>.

## Hardest seams
Named seams that will give false confidence under naive unit tests.
For each: how it will be tested. Name the anti-pattern that the test rules out.
- Seam 1: <name> — test approach: <concrete description, anti-pattern named>
- Seam 2: <name> — test approach: ...

## Exit criterion
What proves the slice is done. Specific, measurable, with what evidence.
Not "all tests pass" — name the specific tests / smoke / SHA that closes it.

## Deferred to later slices
Features or debt intentionally pushed to future slices. Each item must have a trigger for revisit and a negative bound (e.g., timeout to drop).
- <item> — trigger: <event> / negative bound: <timeframe>

## Open items requiring human decision
Things deferred or pending owner decision.
- <item> — question for owner: <text>

## Revisions during planning
Format: **Phase N — challenge:** "<verbatim quote>" → **revised:** "<before>" to "<after>" → **reason:** <material reason>.
- (Populated during the planning phase)

## Defended pushbacks during planning
Format: **Phase N — challenge:** "<verbatim quote>" → **defense:** "<rationale for not revising>" → **reason:** <why this didn't yield a revision>.
- (Populated during the planning phase)

## External audit results
Reserved for cold-reader audit verdicts (PASS/FAIL/DISAGREE) and timestamps.
- Status: PLANNING_COMPLETE_PENDING_AUDIT (update upon audit)

## Watching (standing concerns)
Format: **W-N. Concern.** Watch for: <observable signal>. Action if trigger fires: <next step>. No negative bound — dormant by design if signal never appears.
- (Populated if applicable)