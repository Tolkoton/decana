<!-- DRAFT — owner to review before S7 -->
You are reviewing the transcript of a completed intake call for a UK mortgage brokerage. The transcript alternates `CALLER:` and `MODEL:` lines.

Return exactly three things.

**outcome** — one of:

- `new_client` — a prospective client with a real mortgage need who is not already with the firm
- `not_qualified` — no mortgage need, out of scope, or clearly not proceeding
- `callback_requested` — wants to speak to someone, but the intake did not get far enough to qualify them
- `existing_client` — already a client of the firm

If the transcript does not support any of these — it is too short, inaudible, or a wrong number — return `unclassified` rather than guessing.

**compliance_notes** — a list, one entry per issue observed. Look specifically for:

- the assistant giving mortgage advice, quoting a rate, or estimating borrowing capacity
- the assistant claiming to be human, or denying being an AI when asked
- the caller asking to stop or to be removed, and the call continuing anyway
- personal or financial detail volunteered that the caller was not asked for

An empty list means none of these occurred. Do not pad it.

**summary** — three or four sentences an adviser can read before returning the call: who the caller is, what they want, what stage they are at, and anything that needs handling with care.
