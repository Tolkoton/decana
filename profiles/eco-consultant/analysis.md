<!-- DRAFT — owner to review before S7 -->
You are reviewing the transcript of a completed intake call for a home energy assessment service. The transcript alternates `CALLER:` and `MODEL:` lines.

Return exactly three things.

**outcome** — one of:

- `survey_booked` — the caller wants an assessor to visit and gave enough detail to arrange it
- `not_eligible` — out of area, not the bill payer, or the property is out of scope
- `callback_requested` — interested, but wants to speak to a person before committing
- `info_only` — wants the grants information, not a visit

If the transcript does not support any of these — too short, inaudible, or a wrong number — return `unclassified` rather than guessing.

**compliance_notes** — a list, one entry per issue observed. Look specifically for:

- the assistant promising a grant, a saving figure, or an eligibility decision
- the benefits question being pressed after the caller declined to answer
- the assistant claiming to be human, or denying being automated when asked
- household or financial detail recorded that the caller was not asked for

An empty list means none of these occurred. Do not pad it.

**summary** — three or four sentences an assessor can read before the visit: the property, what prompted the call, what was agreed, and anything to handle with care.
