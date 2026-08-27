# Slice analysis (S4) — planning artifact

Feature `vertical-profile-bridge`, slice S4. Planned 2026-08-27, unattended.

**RATIFIED 2026-08-27.** Planned unattended: 2 critic rounds on Phase 2, then six
cold-read passes. **Eight defects found and removed, every one the same shape** — a
ratified thing with fewer than all three of (a decision naming the mechanism, a seam
naming the wrong implementation, an id naming the test node). Not one was found by
re-reading; every one came from an enumeration walked row by row.

The eighth is the one to read first if you are about to change this file:
`except BaseException` — one word wider than S4-Q7 ratifies — passes all 24 nodes that
existed before `A4.f`, and silently costs teardown the ability to cancel this work.

## Goal

Deliver `src/decana/analysis/`: turn a finished call's transcript into a structured
`Analysis` that S5 can dispatch. Three modules, fixed by the ratified contract:
`model.py` (the `Analysis` value object), `analyse.py` (`analyse()` + the
`AnalysisClient` Protocol), `gemini_client.py` (`GeminiAnalysisClient`, the real one).

**Measurable target.** Every ratified guarantee has a passing test against a fake
`AnalysisClient`, plus one real-API check against a fixture transcript. The central
property: **`analyse` never raises** — an empty transcript, a timeout, an API error,
an unparsable response and an out-of-vocabulary outcome all yield
`Analysis(outcome="unclassified", …)`.

## Out of scope (deliberately)

- **Dispatch** (SMS, email, files, the idempotency marker) — S5.
- **Mid-call intervention.** Ratified: no guardrail regex, no tool calls. Compliance
  is judged post-call, here, from the transcript alone.
- **Prompt authoring.** `analysis.md` ships as owner-editable DRAFT text (S1 Q11);
  S4 consumes `profile.analysis` verbatim and never edits it.
- **Retry or backoff on the analysis call.** `voice-intake-demo` Q22 part 3 still
  governs: a failure is data. One attempt, one timeout, then `unclassified`.
- **Transcript storage or redaction** — S5 writes files; UK-region residency is a
  feature-level deferral with its own trigger.

## Premise verified

### P1 — `google-genai` supports constrained JSON output
`generate_content` accepts `response_mime_type="application/json"` and a
`response_schema`, and honours an enum constraint on a field.
**VERIFIED 2026-08-27 by reading the installed SDK's source**, per the standing rule
this project earned on S2: three claims about this SDK's runtime were stated
confidently from docs and all three were wrong.

- `GenerateContentConfig.response_mime_type` documents `application/json` as a
  supported value (`google/genai/types.py`).
- `response_schema` takes a `SchemaUnion`; `types.Schema` carries `type`,
  `properties`, `required`, `items` **and `enum`**, and constructing
  `Schema(type="STRING", enum=[...])` round-trips — checked by execution, not read.

**One caveat the source states and the docs page does not, and it changes the
design:** *"The model needs to be prompted to output the appropriate response type,
otherwise the behavior is undefined."* Setting the mime type is NOT sufficient — the
prompt must also ask for JSON. `profile.analysis` is owner-authored DRAFT prose and
cannot be relied on to say so, so **S4 appends the JSON instruction itself** rather
than assuming the profile carries it. See S4-Q3.

### P2 — `TranscriptTurn` is available and stable
S3 ships `TranscriptTurn(role: Literal["caller","model"], text: str)` in
`src/decana/twilio/records.py`, and S4 consumes it. **VERIFIED 2026-08-27**: S3's
46 ratified ids are green, including `S9.b`, which pins transcript role and order.

### P3 — `profile.outcomes` and `profile.analysis` exist and are non-empty
**VERIFIED 2026-08-26** by S1: `outcomes: tuple[str, ...]` and `analysis: str` are
validated at load, and S1's shipped-profile seam asserts both profiles carry them.

### P4 — the analysis model name is per-profile
`profile.analysis_model`, not a constant. **VERIFIED** — S1's `Profile` carries it,
and the ratified `main()` sketch says "model is per-call: analyse() passes
profile.analysis_model".

## HARD GATE disposition

**All four premises verified; the gate passes.** P1 was the one the seam's shape
depends on, and it was checked against the installed SDK's source and by execution
**before Phase 2 was drafted** rather than after — the S2 lesson applied in advance
instead of in retrospect. That ordering earned its keep immediately: the source
carries a caveat the docs page omits (the prompt must also ask for JSON), which is why
S4-Q3 exists at all.

Two further SDK facts were verified the same way once the seam existed, and both
changed it: the sync/async facade split behind S4-Q9, and `response_schema` accepting
and retaining a plain `dict` behind Seam 7(a). Neither was reachable from the
signatures.

## Seam (contract)

Modules, fixed by the ratified feature contract: `src/decana/analysis/model.py`,
`analyse.py`, `gemini_client.py` (+ `__init__.py`).

### Types — `model.py`

```python
@dataclass(frozen=True)
class Analysis:
    outcome: str                       # in profile.outcomes, or "unclassified"
    compliance_notes: tuple[str, ...]  # empty = nothing flagged
    summary: str                       # <= 600 chars, for the operator brief
    raw: str                           # the model's raw JSON text; S5 writes it out
```

### The seam — `analyse.py`

```python
class AnalysisClient(Protocol):
    async def generate_json(
        self, *, model: str, system: str, user: str, schema: Mapping[str, Any]
    ) -> str: ...

UNCLASSIFIED = "unclassified"

async def analyse(
    transcript: Sequence[TranscriptTurn],
    profile: Profile,
    *,
    client: AnalysisClient,
    timeout_s: float = 30.0,
) -> Analysis
```

### The real client — `gemini_client.py`

```python
class GeminiAnalysisClient:
    def __init__(self, *, api_key: str) -> None: ...
    async def generate_json(self, *, model, system, user, schema) -> str
```

### Errors

**`analyse` never raises.** Every failure path returns
`Analysis(outcome="unclassified", compliance_notes=(), summary="<reason>", raw=<what
came back, or "">)`. This is ratified and is the whole point of the seam: it runs
inside S5's `post_call`, which itself runs inside S3's `_teardown`, where an escaping
exception would cost the call its record.

### Dependencies (injected, never imported)

`client`, `profile`, `timeout_s`. `gemini_client.py` is the only module that imports
`google.genai`, and it takes `api_key` as an argument — it never reads an env var.

### Does NOT do

Dispatch, retry, mid-call intervention, prompt authoring, transcript storage.

---

## Decisions (with WHY)

**S4-Q1: the outcome vocabulary is constrained by schema AND re-checked after parsing.**

Chosen: the JSON schema passed to the client sets
`enum = (*profile.outcomes, "unclassified")` on `outcome`; after parsing, `analyse`
checks membership again and downgrades anything else to `"unclassified"`.

WHY both: the schema is the model provider's promise, and this project's record on
believing such promises is poor — three `google-genai` runtime claims falsified on S2
alone. The schema constrains the *usual* path cheaply; the post-parse check is what
holds when it does not, and it costs one `in` test. `outcome` is what S5 keys the SMS
template on, so an out-of-vocabulary value there means either a KeyError in dispatch
or an SMS chosen by a string the profile has never heard of.

Rejected: **trust the schema alone.** Steelman: it is the provider's documented
mechanism and duplicating it is defensive clutter. Rejected on this project's own
evidence — and the check is one line against a failure that reaches a real caller.
Rejected: **check only, no schema.** Steelman: one mechanism, no duplication.
Rejected: without the enum the model has no signal about the vocabulary at all, so
`unclassified` would become the common case rather than the failure case.

**S4-Q2: the transcript renders as `CALLER:` / `MODEL:` lines, in order.**

Chosen: `"\n".join(f"{'CALLER' if t.role == 'caller' else 'MODEL'}: {t.text}")`.

WHY: ratified in the feature contract ("S4 serializes the turn list into the analysis
prompt as `CALLER: …\nMODEL: …` lines"). Uppercase role labels rather than the raw
`Literal` values because the prompt is read by a model, and the ratified text shows
them uppercase.

**S4-Q3: `analyse` appends the JSON instruction; it does not rely on the profile.**

Chosen: the system prompt is `profile.analysis` followed by a fixed instruction
naming the required JSON shape and the outcome vocabulary.

WHY: **the SDK's own source says the mime type is not sufficient** — *"The model needs
to be prompted to output the appropriate response type, otherwise the behavior is
undefined."* `profile.analysis` is owner-authored DRAFT prose (S1 Q11) that says
nothing about JSON, and requiring every future profile to remember to ask for JSON
makes a vertical's prompt file responsible for a wire-format detail. Appending here
keeps the profile about the vertical and the format about the code.

Rejected: **require the profile to ask for JSON.** Steelman: fully owner-controlled
output shape. Rejected: it makes a compliance-prose file load-bearing for parsing, and
S1's prompts are explicitly DRAFT.

**S4-Q4: the timeout wraps the client call, and a timeout is `unclassified`.**

Chosen: `asyncio.wait_for(client.generate_json(...), timeout=timeout_s)`; on
`TimeoutError`, return `unclassified` with the reason in `summary`.

WHY: `analyse` runs inside teardown, which runs while a call is ending; an unbounded
wait there holds the socket and the record open indefinitely. One attempt, no retry —
`voice-intake-demo` Q22 part 3: a failure is a measurement, not something to engineer
around before the first measurement.

**S4-Q5: an empty transcript short-circuits before the API call.**

Chosen: an empty or whitespace-only transcript returns `unclassified` immediately,
with no client call.

WHY: ratified as a failure path, and calling a paid API to analyse nothing is the one
version of it that costs money. A call that dropped before anyone spoke is the
ordinary cause.

**S4-Q6: `raw` carries whatever came back, including on failure.**

Chosen: `raw` is the model's response text when there was one, and `""` when the
failure happened before or instead of a response.

WHY: S5 writes `raw` to `{call_sid}.analysis.json`, and a parse failure is exactly
when someone needs to see what the model actually said. Discarding it on the failure
path would throw away the only evidence at the moment it matters.

**S4-Q7: one try/except wraps the call AND the parse, and it catches `Exception`.**

Chosen: a single guarded region around `await asyncio.wait_for(client.generate_json(...))`
*and* the JSON parse and field extraction, catching `Exception`. Every escape returns
`Analysis(outcome=UNCLASSIFIED, compliance_notes=(), summary=<reason>, raw=<text or "">)`.

WHY this needed its own decision: the Errors section *claimed* "never raises" and the
seams tested it, but no decision supplied the mechanism — and `asyncio.wait_for` (S4-Q4)
intercepts only `TimeoutError`. Everything else the awaited coroutine raises passes
through it unchanged. Verified in the installed SDK: `google/genai/errors.py` defines
`APIError`/`ClientError`/`ServerError`, raised on any non-2xx. So as first drafted,
`analyse` still raised on **exactly the two failure modes the ratified contract names
most explicitly** — "API error" and "unparsable response".

WHY `Exception` and not a named tuple of types: `AnalysisClient` is a Protocol that
declares no exception contract, so an implementation — or a test double — may raise
anything. A narrow catch would be a list of the vendor errors known today, which is
the shape that fails when the vendor adds one. `analyse` runs inside S5's `post_call`,
inside S3's `_teardown`; an escape there costs the call its record, which is a worse
outcome than over-catching. `BaseException` is deliberately NOT caught:
`CancelledError` must propagate so teardown can cancel this work.

**Verified by execution, not assumed** (2026-08-27): `issubclass(asyncio.CancelledError,
Exception)` is **False** — it derives from `BaseException` — so a bare `except
Exception` lets it through, which is the behaviour this decision depends on. Also
confirmed in the same run: `wait_for` on a sleeping coroutine raises `TimeoutError`;
an arbitrary `RuntimeError` from the awaited call reaches the same handler; and
`json.loads('{"outcome": 5}')` **succeeds**, producing a dict whose `outcome` is an
int — so a wrong-typed but well-formed field is not a parse failure and is caught
instead by S4-Q1's membership check, which `5 in profile.outcomes` fails.

WHY the parse is inside the same region rather than a second one: the parse failures —
`json.JSONDecodeError`, a missing key, `compliance_notes` arriving as a string — are
the same class of "the model did not do what the schema asked" as an API error, and
they map to the same result. Two regions would be two places to forget.

Rejected: **catch only the SDK's error types.** Steelman: it is precise, and a bare
`except Exception` can hide a bug in our own code. Rejected: the Protocol permits any
exception, the vendor list changes, and the failure mode of missing one is losing a
call's entire record. The `summary` carries the exception type, so a bug in our own
code is visible rather than swallowed.

**S4-Q8: `summary` is truncated to 600 characters by `analyse`, and asked for in the prompt.**

Chosen: the JSON instruction asks for a summary of at most 600 characters, and
`analyse` truncates to 600 regardless.

WHY both: the ratified type carries `summary: str  # ≤ 600 chars, for the brief`, which
is a constraint on what S4 *produces*, not a hope about what the model returns — and
nothing in the draft enforced it. Asking in the prompt gets a summary that ends where
the model meant it to; truncating is the backstop when it does not. Belt and braces for
the same reason as S4-Q1: the model's cooperation is not a mechanism.

Recorded as W-1: truncation can end mid-sentence. Accepted — the brief points at the
transcript rather than replacing it.


**S4-Q9: the real client calls `client.aio.models.generate_content`, never `client.models`.**

Chosen: `GeminiAnalysisClient.generate_json` awaits
`self._client.aio.models.generate_content(...)`. The synchronous facade is forbidden.

WHY, verified by execution rather than read: `inspect.iscoroutinefunction` reports
**False** for `client.models.generate_content` and **True** for
`client.aio.models.generate_content`. The sync one is a blocking `def` with a network
call under it.

The consequence is not stylistic. `async def generate_json(...): return
self._client.models.generate_content(...).text` is a coroutine function with **no
internal `await`**, so:

1. **S4-Q4's timeout stops working for the one client that matters.**
   `asyncio.wait_for` can only cancel at an `await` point. A coroutine that blocks the
   thread runs for the real network duration, not `timeout_s`.
2. **It stalls every other call on the loop.** `analyse` runs inside S5's `post_call`,
   inside S3's `_teardown`, on the same event loop that is forwarding audio for every
   concurrent call. A blocking HTTP request there is dead air on other people's calls
   — the same class of cross-call harm S3's fifth coverage axis exists to track.

**Why no fake can catch this**, which is why it needs a decision and its own seam
clause: a fake `AnalysisClient` is written `async def generate_json(...): await
asyncio.sleep(...)`, which suspends correctly. Every timeout seam passes against it
whether or not the real client ever awaits anything. And `client.models` is the facade
that appears first in `dir()` and in most of the SDK's own examples — it is what an
implementer reaches for.

Rejected: **wrap the sync call in `asyncio.to_thread`.** Steelman: it keeps the loop
free and works with the facade an implementer will find first. Rejected: it adds a
thread per analysis to work around using the wrong entry point, when the SDK ships an
async one; and `to_thread` is not cancellable either, so the timeout would still not
preempt the request — it would only stop *waiting* for it.



**S4-Q10: `compliance_notes` is built by coercing a list's items; a non-list is a wrong shape.**

Chosen, in two parts:
- if `compliance_notes` is absent, or present as a `list`/`tuple`:
  `tuple(str(x) for x in data.get("compliance_notes", ()))`;
- if it is present and is **not** a list or tuple — a bare string is the case S4-Q7
  already names — that is a wrong-shape response and the whole result is
  `unclassified`.

WHY the split: iterating a bare string yields one note per **character**, which is not
a degraded result but a nonsense one, and it would reach a compliance view looking like
structured data. A list whose items are not strings is different in kind: the notes are
prose meant for a human to read, so coercing an item with `str()` preserves the
evidence, which is the same instinct as S4-Q6 keeping `raw` on the failure path and
S3's teardown handing off a partial transcript.

WHY this needed its own decision at all — it is the **second** instance of the same
defect in this one artifact, after S4-Q7. `compliance_notes` had a ratified type
member and a seam whose title claimed to cover it, but no decision naming the
mechanism and no id exercising a successful parse. The seam's only assertion,
"`compliance_notes` is a tuple", sat on the *failure* path where S4-Q7 hardcodes `()` —
so it asserted that an empty tuple is a tuple, and a passthrough
`Analysis(compliance_notes=data["compliance_notes"])` shipping a mutable list inside a
frozen dataclass would have passed every seam in the artifact.
`.claude/overseer/MEMORY.md` states the rule this violates — a decision, a seam, and
an id, or the guarantee is not covered — and it recurred here past the point where a
round-anchored review had credited it as handled.

Rejected: **coerce a bare string into a one-item tuple.** Steelman: it salvages a
result rather than discarding it, and a single note is a plausible thing for a model to
return unwrapped. Rejected: the schema asks for an array, so a string means the model
ignored the schema — which is precisely the signal that the rest of its output is not
trustworthy either. S4-Q1 makes the same call for `outcome`.



**S4-Q11: `analyse` passes `profile.analysis_model`, and the schema it builds declares
`compliance_notes` as an array of strings.**

Chosen: `client.generate_json(model=profile.analysis_model, …)` — never
`profile.live_model`, never a constant. The schema `analyse` constructs sets
`compliance_notes` to `{"type": "ARRAY", "items": {"type": "STRING"}}`.

WHY this needed a decision at all: `analysis_model` and `live_model` are two `str`
fields on the same `Profile`, one attribute apart, and **nothing was testing which one
reached the client.** `Profile` is loaded from TOML where both are present and both are
plausible model ids, so the wrong one produces a working call against the wrong model —
a conversational model doing structured analysis — with no error anywhere. The feature
contract states the requirement in a code comment ("model is per-call: `analyse()`
passes `profile.analysis_model`), and this artifact's own convention is that
feature-level ratification does not exempt a mechanism from having a decision, a seam
and an id: S4-Q2 is also ratified upstream and still got all three. `model` had none of
the three.

WHY the schema's `items` clause is here rather than left to Seam 7: Seam 7 tests what
`GeminiAnalysisClient` *forwards*, which is a schema handed to it. The dict `analyse`
*builds* is a different artifact, and an ARRAY with no `items` is a schema the model
can satisfy with an array of anything — which is precisely the input S4-Q10 then has to
coerce. Constraining it at the source is cheaper than coercing at the sink, and both
are kept because the model's cooperation is not a mechanism (S4-Q1's reasoning).

Rejected: **take the model name as an `analyse()` parameter.** Steelman: it makes the
choice explicit at the call site and removes a `Profile` lookup from the seam.
Rejected: the ratified signature is `analyse(transcript, profile, *, client,
timeout_s)`, and adding a parameter to it is contract drift for no gain — the profile
already carries the answer, and a caller free to pass any model is a caller free to
pass the wrong one.



**S4-Q12: `GeminiAnalysisClient` forwards `api_key` into `genai.Client(api_key=...)`,
and a seam proves it at construction time.**

Chosen: `self._client = genai.Client(api_key=api_key)`, with a seam that patches the
`google.genai.Client` **class** and asserts the forwarded kwarg equals a distinct
fixture value — construction only, no network.

WHY this one is worse than the four defects before it, and needs its own decision: the
SDK **falls back to the environment**. `google/genai/_api_client.py:128-140` defines
`get_env_api_key()`, which reads `GOOGLE_API_KEY` then `GEMINI_API_KEY` when no key is
passed. Verified by execution: `genai.Client()` with no argument constructs
successfully whenever either variable is set.

And `GEMINI_API_KEY` is precisely the secret this project's own deploy contract injects
into the Cloud Run process environment (feature contract, Edge S3 → S6), and precisely
what a developer exports locally to iterate against this SDK. So an implementation
that drops `api_key` on the floor — `genai.Client()` — **passes the unit suite, passes
the real-API smoke, and passes production.** There is no environment in this project's
deploy shape where it reveals itself.

Contrast the others: S4-Q9's blocking facade eventually shows up as latency under
load; S4-Q11's wrong model produces observably poor analysis. This one is silent
forever. The artifact already *claimed* the property in prose — "it takes `api_key` as
an argument — it never reads an env var" — with no decision, no seam and no id behind
it, which is the fifth instance of that shape in this one document.

**Verified the fix is testable before ratifying it:** patching `google.genai.Client`
and constructing with `api_key="distinct-fixture-value"` yields
`call_args.kwargs == {"api_key": "distinct-fixture-value"}`. The assertion holds
regardless of what is in the environment, which is the whole point — an env-sensitive
check would inherit the bug it is meant to catch.

Rejected: **assert it by unsetting both env vars and expecting a failure.** Steelman:
it tests the real path end to end rather than a constructor call. Rejected: it makes
the test depend on the absence of ambient state, which is the least reliable thing to
depend on in CI, and it would still pass for an implementation that reads the env var
itself instead of taking the argument.


## Hardest seams (test-confidence points)

## Decision → seam coverage map

Three axes, because on S3 each new axis produced a finding: decisions, ratified
guarantees, and members of ratified types. Walk the table, not the seam list.

| item | seam |
|---|---|
| S4-Q1 schema enum + post-parse re-check | 1 (a)(b) |
| S4-Q2 `CALLER:`/`MODEL:` rendering, in order | 2 |
| S4-Q3 the JSON instruction is appended by S4 | 3 |
| S4-Q4 timeout wraps the call; timeout → unclassified | 4 (b) |
| S4-Q5 empty transcript short-circuits, no API call | 4 (a) |
| S4-Q6 `raw` carries the response even on failure | 5 |
| S4-Q9 the real client uses the async facade | 7 (b) |
| S4-Q10 `compliance_notes` coercion; non-list is a wrong shape | 5 (a)(b) |
| S4-Q11 `model` is `profile.analysis_model`; schema constrains the array's items | 1 (c)(d) |
| S4-Q12 `api_key` is forwarded into `genai.Client` | 7 (c) |
| Guarantee: transcript rendered in order | 2 |
| Guarantee: schema constrains outcome to `outcomes + unclassified` | 1 (a) |
| Guarantee: empty/timeout/API-error/unparsable → unclassified | 4 (a)-(e) |
| Guarantee: **invalid-outcome** → unclassified | **1 (b)** — NOT seam 4; its five cases are empty/timeout/generic-exception/non-JSON/wrong-shape, none of which is well-formed JSON whose outcome is merely out of vocabulary |
| Guarantee: **`analyse` never raises** | 4, all cases |
| `Analysis.outcome` | 1 |
| `Analysis.compliance_notes` | 5 (a)(b) — success path, not just the failure default |
| `Analysis.summary` (≤600 chars) | 6 |
| `Analysis.raw` | 5 |
| `GeminiAnalysisClient.generate_json` | 7 (a)(b) |
| `GeminiAnalysisClient.api_key` | 7 (c) — the SDK's env fallback makes every other check blind to it |

---

**Seam 1: the outcome vocabulary holds even when the model ignores the schema.**

Wrong implementation a naive test passes: trusting the schema and assigning
`data["outcome"]` straight through. A fake client that returns a valid outcome —
which is what a happy-path fake returns — makes the passthrough and the checked
version identical.

Test approach:
- **(a)** the schema handed to the client has `enum == (*profile.outcomes,
  "unclassified")` — captured from the fake and asserted, so the constraint is
  proven to be *sent*, not just intended.
- **(b)** a fake returning `{"outcome": "definitely_not_a_real_outcome", ...}` yields
  `unclassified`, and the raw text is preserved.
- **(c)** the captured `model` kwarg equals `profile.analysis_model` — and, to make the
  test sharp rather than incidental, the fixture profile's `analysis_model` and
  `live_model` are **different strings**. Rules out `profile.live_model` and a
  hardcoded id, neither of which any other node can see: both produce a working call
  against the wrong model, with no error anywhere.
- **(e)** the pure happy path, asserted on ONE well-formed response: an in-vocabulary
  outcome, non-empty `compliance_notes`, and a populated `raw`, together. Every other
  clause here isolates one field on a crafted response; nothing was checking that a
  single ordinary success produces all of them at once.
- **(d)** the schema `analyse` built declares `compliance_notes` as an ARRAY with
  `items` of type STRING. Rules out an unconstrained array, which the model can satisfy
  with anything and which turns S4-Q10's coercion from a backstop into the load-bearing
  path. Rules out passthrough, whose
  consequence lands in S5 as an SMS template keyed by a string the profile has never
  heard of.

**Seam 2: the transcript reaches the model in order, with the ratified labels.**

Wrong implementation a naive test passes: rendering `role` verbatim
(`caller:`/`model:`), or iterating a set, or reversing. A single-turn transcript is
identical under all of them.

Test approach: a 4-turn transcript alternating roles; capture the `user` string the
fake received and assert it equals the exact expected block, `CALLER: …\nMODEL: …`
in order. Equality, not `in`: a reordered transcript still *contains* every line.

**Seam 3: the JSON instruction is present even when the profile never mentions JSON.**

Wrong implementation a naive test passes: relying on `profile.analysis` to ask for
JSON. Every shipped profile's `analysis.md` is DRAFT prose that does not, and the
SDK's own source says the mime type alone leaves the behaviour undefined.

Test approach: with a profile whose `analysis` text contains no mention of JSON,
capture the `system` string and assert it contains both the profile's text **and** an
explicit JSON instruction naming the required keys. Rules out the
profile-carries-the-format implementation, whose failure is unparsable output on a
vertical nobody re-read.

**Seam 4: every failure path yields `unclassified`, and none of them raises.**

Wrong implementation a naive test passes: any implementation at all, under a fake
that always succeeds. This is the seam the whole slice exists for — `analyse` runs
inside S5's `post_call`, inside S3's `_teardown`, where an escaping exception costs
the call its record.

Test approach — parametrised, one case per failure mode, each asserting **both** that
the result is `unclassified` **and** that nothing propagated:
- **(a)** empty transcript → `unclassified`, the client was **never called** (a paid
  call to analyse nothing), **and `summary` names the empty transcript**;
- **(b)** the client raises `TimeoutError` (and separately: sleeps past `timeout_s`)
  → `unclassified`, **and `summary` names the timeout**;
- **(c)** the client raises an arbitrary `RuntimeError` → `unclassified`, **and
  `summary` contains the exception's type name**;
- **(d)** the client returns text that is not JSON → `unclassified`, `raw` preserved,
  **and `summary` says the response could not be parsed**;
- **(e)** the client returns valid JSON of the wrong shape (missing keys, `outcome`
  not a string, `compliance_notes` not a list) → `unclassified`, `raw` preserved,
  **and `summary` distinguishes this from (d)**.

- **(f)** the client raises `asyncio.CancelledError` → `analyse` **re-raises it**,
  and does NOT return an `Analysis`. Assert with `pytest.raises(asyncio.CancelledError)`.

  This is the only clause that distinguishes the ratified `except Exception` from
  `except BaseException` — one word wider, and it passes every other node here plus
  `ruff` and `mypy`. S4-Q7 names `CancelledError` propagation as the reason to prefer
  the narrower catch, and that half of the decision was verified only as a *Python
  fact* (`issubclass(CancelledError, Exception)` is `False`), never as a property of
  this implementation. The failure is silent forever in the same way S4-Q12's dropped
  key is: a swallowed cancellation costs teardown the ability to stop this work at all,
  and nothing in any environment reveals it.

**Why the `summary` assertions are not decoration.** The ratified contract says every
failure yields `summary="<reason>"`, and **S4-Q7's entire justification for catching
`Exception` rather than a narrow type list rests on it**: "the `summary` carries the
exception type, so a bug in our own code is visible rather than swallowed." Nothing was
testing that. A single hardcoded `summary="failed"` on every branch passes every other
assertion in this seam — `outcome` is still `unclassified`, nothing still propagates —
while falsifying the guarantee and turning S4-Q7's broad catch into an actual swallow.
The **five** reasons must also be **distinguishable from each other**, or the field
identifies that something failed without identifying what, which is the same as not
having it when the call is a week old and the only artifact is the record.

**Five, not four — and the miss is worth recording.** The round that added these
assertions applied them to (b), (c), (d) and (e) and left (a) alone, even though the
Errors section ratifies a reason on *every* failure path and (a) is one of this seam's
own five enumerated modes. A `summary=""` on the empty-transcript short-circuit would
have passed all 24 nodes. **That is a different failure from the six before it:** those
were coverage that never existed, this was a repair that did not cover its own scope.
When a fix applies to a family, apply it to the whole family and then count the
family — the sibling that gets skipped is the one nobody looks at again.

**Seam 5: `raw` and `compliance_notes` survive the failure paths.**

Wrong implementation a naive test passes: returning `Analysis(outcome=UNCLASSIFIED)`
with defaults and dropping the response text. Every assertion about `outcome` still
holds.

Test approach — the success path first, because that is where the mechanism lives:
- **(a)** a fake returning **non-empty** `compliance_notes` on a well-formed response:
  assert the content matches AND `isinstance(result.compliance_notes, tuple)`. This is
  the clause that kills the passthrough, which ships the parsed `list` straight into a
  frozen dataclass. An earlier draft asserted tuple-ness only on the failure path,
  where S4-Q7 hardcodes `()` — asserting that an empty tuple is a tuple, which the
  passthrough also satisfies.
- **(b)** `compliance_notes` returned as a bare string → `unclassified` (S4-Q10);
  iterating it would otherwise yield one note per character.
- **(c)** on the unparsable-response case, assert `raw` equals the exact text the
  client returned. S5 writes `raw` to `{call_sid}.analysis.json`, and a parse failure is
precisely when someone needs to see what the model said — discarding it throws away
the only evidence at the moment it matters. Also assert `compliance_notes` is a
**tuple**, not a list: `Analysis` is frozen, and a mutable field makes it frozen in
name only.

**Seam 6: the summary is bounded.**

Wrong implementation a naive test passes: passing the model's summary through
unbounded. A well-behaved fake returns something short.

Test approach: a fake returning a 5000-character summary yields
`len(result.summary) <= 600`. Rules out passthrough, whose consequence is an operator
brief with a wall of text where a summary should be.

**Seam 7: the real client asks for JSON and passes the schema (premise P1).**

Wrong implementation a naive test passes: building the request without
`response_mime_type` or without `response_schema`. Nothing in Seams 1-6 touches the
real client — they all use fakes.

Test approach:
- **(a)** construct `GeminiAnalysisClient` and inspect the `GenerateContentConfig` it
  builds **without making a network request** — assert
  `response_mime_type == "application/json"`, that the schema carries the outcome enum,
  **and that it declares `compliance_notes` as an array of strings** (S4-Q10's
  mechanism only holds if the schema asked for an array in the first place).
  **Executed against the installed SDK:** a plain `dict` is accepted for
  `response_schema` and is stored **as a dict**, not coerced to `types.Schema`, so the
  assertion is subscript access
  (`cfg.response_schema["properties"]["outcome"]["enum"]`), not attribute access. That
  also matches the ratified Protocol, which types `schema` as `Mapping[str, Any]` —
  `analyse` builds a plain dict and the client passes it through unchanged. Note the
  consequence: a malformed schema is not rejected at config-construction time, so this
  clause is the only place its shape is checked before a live call. The
  live call belongs to the smoke, which spends budget; this asserts the request shape
  for free. Rules out the wrapper that looks right and asks for prose.
- **(c)** patch the `google.genai.Client` **class**, construct
  `GeminiAnalysisClient(api_key="distinct-fixture-value")`, and assert the class was
  called with that exact `api_key` kwarg. No network, no environment dependence.
  Rules out `genai.Client()` with the key dropped — which the SDK's own env fallback
  (`_api_client.py:128-140`) makes invisible to CI, to the smoke, and to production
  alike, since `GEMINI_API_KEY` is the variable this project's deploy already sets.
- **(b)** replace `client.aio.models.generate_content` with an `AsyncMock` and assert
  it was **awaited**. The sync-facade implementation never touches `.aio` at all, so
  this is the only clause that fails against it — and no fake `AnalysisClient` can,
  because a fake suspends correctly by construction (S4-Q9).

  **Verified implementable before ratification, not assumed.** Executed against the
  installed SDK: `patch.object(type(c.aio.models), "generate_content",
  new_callable=AsyncMock)` gives `await_count == 1` on the async path, and driving
  `c.models.generate_content` instead leaves `await_count == 0`. So the clause
  discriminates, and the implementer does not have to discover the patch target. (The
  sync call also raises `ClientError` with no network, which is incidental
  confirmation that the SDK's errors are `APIError` subclasses as S4-Q7 assumes.)


## Exit criterion

### 1. Unit suite — a property over the ratified id set, both directions

> Every id below has a passing test node, and `tests/test_analysis.py` contains no
> node that does not trace to an id in this list.

Checkable mechanically, and it must be — on S3 this exact diff found three assertions
that vanished when Phase 3's prose was compressed into ids, and a fourth that had no
node at all.

| id | behavior | nodes |
|---|---|---|
| `A1.a` | the schema sent carries `enum == (*profile.outcomes, "unclassified")` | 1 |
| `A1.b` | an out-of-vocabulary outcome is downgraded to `unclassified` | 1 |
| `A1.c` | the `model` kwarg equals `profile.analysis_model`, which differs from `live_model` in the fixture | 1 |
| `A1.d` | the built schema declares `compliance_notes` as ARRAY with STRING items | 1 |
| `A1.e` | the pure happy path (Seam 1(e)): in-vocabulary outcome, non-empty notes and `raw`, all asserted on one well-formed response | 1 |
| `A2.a` | the rendered transcript equals the exact `CALLER:`/`MODEL:` block, in order | 1 |
| `A3.a` | the system prompt carries the profile text AND an explicit JSON instruction | 1 |
| `A4.a` | empty transcript → `unclassified`, client never called, `summary` names the empty transcript | 1 |
| `A4.b` | timeout → `unclassified`, and `summary` names the timeout | 2 |
| `A4.c` | an arbitrary client exception → `unclassified`, and `summary` carries its type name | 1 |
| `A4.d` | non-JSON response → `unclassified`, `raw` preserved, `summary` says unparsable | 1 |
| `A4.e` | valid JSON of the wrong shape → `unclassified`, parametrised, `summary` distinct from A4.d's | 3 |
| `A4.f` | `CancelledError` is **re-raised**, not converted to an `Analysis` | 1 |
| `A5.a` | `raw` equals the text the client returned, on the failure path | 1 |
| `A5.b` | the failure path's `compliance_notes` default is `()` | 1 |
| `A5.c` | non-empty `compliance_notes` on a successful parse: content correct AND a tuple | 1 |
| `A5.d` | `compliance_notes` as a bare string → `unclassified` | 1 |
| `A6.a` | a 5000-char summary is truncated to ≤600 | 1 |
| `A7.a` | the real client's config sets `response_mime_type="application/json"` | 1 |
| `A7.b` | the real client passes the schema, enum intact | 1 |
| `A7.c` | `client.aio.models.generate_content` is awaited — the sync facade is not used | 1 |
| `A7.d` | `genai.Client` receives the `api_key` that was passed in, not the environment's | 1 |

**25 nodes.** Count it with the same regex sum the S3 criterion uses; every hand-count
of a node total on this project has been wrong, twice in `profile-loader`'s Phase 4 and
three times in `twilio-server`'s.

### 2. Real-environment check — one call, budgeted

`scripts/smoke_analysis.py`: the real `GeminiAnalysisClient` against a fixture
transcript, asserting the outcome is in `profile.outcomes + ("unclassified",)` and the
JSON parsed. Ratified as "one real-API check against a fixture transcript (cheap,
auto-run)".

It **spends one unit of the disk-persisted budget** (`scripts/_budget.py`) before
opening any socket, and **parks** rather than failing when `GEMINI_API_KEY` is absent
or the cap is reached. No human oracle, so it runs to completion and its output goes
in the transcript.

### 3. Checks

`ruff check`, and `mypy --strict` over `src`, `scripts` **and `tests`** — that exact
command. `pyproject.toml` scopes mypy to `src`/`scripts`, so a bare run silently skips
the suite and reports clean; S2 lost two real errors that way and S3 repeated it.

---

## Deferred to later slices

1. **Retry or backoff on the analysis call** — why later: `voice-intake-demo` Q22
   part 3 is ratified and still governs; a failure is a measurement. — **trigger:** an
   S7 call whose analysis failed for a reason the timing log does not explain.
2. **Per-outcome or per-profile model parameters** (temperature, thinking budget) —
   why later: `profile.analysis_model` is the only knob any vertical has asked for. —
   **trigger:** a real vertical whose analysis is wrong in a way a parameter fixes.
3. **Transcript redaction before analysis** — why later: only scripted test callers
   until the first prospect, and the transcript never leaves the process except to
   Gemini, which already saw the call. — **trigger:** the first real client's
   transcript, the same trigger as the feature's UK-residency deferral.
4. **Analysis quality evaluation** (a scored eval set) — why later: ratified grading is
   manual transcript review, not an eval harness. — **trigger:** a second vertical, or
   an S7 read-out where the outcome was wrong and nobody could say why.

## Watching

- **W-1. The summary is truncated, not summarised.** A 5000-char response is cut at
  600, which can end mid-sentence. Accepted: the operator brief is a pointer to the
  transcript, not a substitute. **Watch for:** an operator saying the brief reads as
  cut off. **Action:** ask the model for ≤600 in the prompt as well, and truncate only
  as the backstop.
- **W-2. The post-parse outcome check duplicates the schema constraint.** If a future
  SDK enforces the enum server-side, the check becomes dead code that still costs a
  line. Accepted deliberately: this project has falsified three `google-genai` runtime
  claims. **Watch for:** the check never firing across a full vertical's calls.
