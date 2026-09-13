# ADR-0001 — Where UK callers' call data is processed

- **Status: RATIFIED 2026-09-13 (owner) — option A for the test phase.** The owner's
  decision, in their words after the trade-off was laid out plainly: "YES" to *stay on the
  Gemini Developer API (API-key route) while the only callers are the owner and testers;
  re-decide before the number goes to real callers.* The owner's product read: fully
  UK-hosted voice is not available from any Google voice model, so the achievable claim is
  "UK-hosted except the real-time voice model, which can be EU" — and that is a decision to
  take when real caller data is about to exist, not before. **The gate on S7's first call
  is therefore OPEN for owner-placed test calls only.**
- **Hop 3 (the SMTP relay) is CLOSED by a separate owner decision, same day: no email
  channel at all** ("we shouldn't use any"). The operator brief is still written to the
  call's artifact files; it is not emailed. This removes hop 3 from the residency surface
  entirely and means the five `SMTP_*` secrets are never created. Note this contradicts
  S5's ratified guarantee (c), "the operator email is sent unconditionally" — that
  guarantee now describes a channel the product does not use, and S5's contract should be
  amended rather than left describing dead behaviour. Not done in this ADR.
- **Model note:** the Live model was switched to `gemini-3.1-flash-live-preview` on
  2026-09-13 (owner's instruction). The region tables below were read for the 2.5 Live
  model and have NOT been re-checked for 3.1. Re-read them before the re-decision.
- **The falsifier this ADR was blocked on is RESOLVED** (2026-09-12, read in a browser).
  It changed the answer: option B/C buys **EU** jurisdiction, **not UK**. UK in-country
  processing of the call audio is **not available** with this model by any route. If the
  product's claim is "UK-hosted", that is a product decision, not an engineering one.
- Raised: 2026-09-12, during S6 deploy preparation
- Owner's stated read (2026-09-12, not yet a ratification): the product is positioned as
  MCOB-aware, UK-hosted, regulated-context; sending UK prospect transcripts to a global
  endpoint with no residency control contradicts what is being sold, so the likely answer
  is Vertex AI in an EU region. **Recorded as the owner's leaning, deliberately not folded
  in as decided** — this is a one-way door and gets a real decision.
- Does **not** block S6. Deploy, wiring, and smoke tiers 1 and 2 involve no real caller
  data. See "What this gates" below for the exact line.

## Context

### What the current architecture does

Both Gemini clients are constructed `genai.Client(api_key=...)` —
`src/decana/gemini/live.py:356` and `src/decana/analysis/gemini_client.py:34`. No
`vertexai=True`, no project, no location. Grep of `src/` and `scripts/` finds no region
parameter anywhere, because **the Gemini Developer API does not have one.** Its
["available regions" page](https://ai.google.dev/gemini-api/docs/available-regions) lists
**country eligibility** — who may call the API — not selectable serving endpoints.
`generativelanguage.googleapis.com` is a single global endpoint.

So: **nothing in the current architecture constrains where a UK caller's speech or
transcript is processed.** Not a misconfiguration — there is no configuration.

### Why it matters for this product specifically

This is not incidental telemetry. The feature's own design treats the context as
regulated: `profiles/*/disclosure.md` is spoken to every caller precisely because
disclosure is mandatory, and `Analysis.compliance_notes` exists to flag adviser conduct
(rate-quoting, capacity estimates, denying being an AI). A product that ships compliance
machinery while having no answer for where the recordings are processed has a gap between
what it does and what it claims.

### The full surface, enumerated — it is wider than Gemini

The residency question was raised about Gemini. Walking every hop the caller's data
actually takes shows five, not one:

| # | hop | what it carries | region control today |
|---|---|---|---|
| 1 | **Gemini Live** (`live.py`) | the caller's raw audio, and both transcripts | **None.** Global endpoint. |
| 2 | **Gemini analysis** (`gemini_client.py`) | the full transcript, as the analysis prompt | **None.** Same global endpoint. |
| 3 | **SMTP relay** (`senders.py`) | the operator brief, whose body is `render_brief(...)` and therefore contains `analysis.summary` — a summary of what the caller said | **Provider's choice.** Unpinned as of this ADR. |
| 4 | **Twilio** | the call audio itself; the SMS to the caller | Twilio's own regional config. Separate question. |
| 5 | **Cloud Run instance disk** (`DECANA_ARTIFACT_DIR`) | `transcript.txt`, `analysis.json`, `brief.md` | `europe-west2` (London). **Fine.** |

**Hop 3 is the one this ADR adds.** The brief email is not a notification — it is the
substance of the call. Choosing a US-hosted relay would reintroduce the exact problem
hop 1 poses, through a door nobody was looking at. **The SMTP provider decision is
therefore part of this ADR, not separate from it.**

Hop 5 is already right, and for a reason worth keeping: the `europe-west2` pin
(`docs/deploy.md`) puts the artifact files in London.

## Options

### A. Keep the Developer API (status quo)

- **Gives:** simplicity. One API key, no project wiring, no region to manage. Works today;
  every test and both smokes are green against it.
- **Costs:** no residency control on hops 1 and 2 — the two that carry the most sensitive
  payload. Nothing to point at in a DPA or a client conversation.
- **Honest note:** this is not "non-compliant" by inspection. It is *unanswerable*, which
  for a regulated-context product is its own problem.

### B. Migrate to Vertex AI in an EU region (the owner's leaning)

- **Gives:** a region binding, documented data-residency controls, and an answer that
  survives a client asking the question.
- **Costs — a real migration, not a flag:**
  1. **Client construction changes.** `genai.Client(api_key=...)` becomes
     `genai.Client(vertexai=True, project=..., location=...)`. Two call sites
     (`live.py:356`, `gemini_client.py:34`), but the credential model changes with it:
     Vertex authenticates via ADC / a service account, not an API key. So
     `Settings.gemini_api_key` — currently **required**, exit 2 if absent — stops being
     the right shape, and S6's Secret Manager wiring for it changes too.
  2. **Model identifiers differ.** `profiles/*/profile.toml` pins
     `gemini-2.5-flash-native-audio-preview-12-2025`; Vertex's native-audio Live model is
     named differently. Both profiles change — which is *correct* per the feature's own
     property (a vertical is a directory), but it is churn in ratified profile data.
  3. **It interacts with the region pin — VERIFIED, not indicative.** The Live model is not
     served in `europe-west2`, the region this deploy is pinned to (see the resolved
     falsifier below). So Vertex-EU means either a cross-region hop (London Cloud Run →
     Belgium Gemini) or moving the service, and **moving the service changes its URL, which
     means re-pointing the Twilio webhook.** B therefore collapses into C in practice.
  5. **And it does NOT deliver what it was wanted for.** B was proposed to get UK residency.
     It cannot: the EU multi-region explicitly excludes the UK, and the model has no
     `europe-west2` availability. B buys **EU** jurisdiction, not UK.
  4. **The premises get re-opened.** S2's measured 3229 ms to first audio and S3's 3128 ms
     `start` → first frame were measured against the Developer API. A different endpoint
     and a cross-region hop invalidate both as evidence for A3's ≤3000 ms bound, and A3 is
     what the feature is judged on. Article 8: this would re-open S2's and S3's premise
     log entries, not just change a client line.

### C. Vertex AI in an EU region, service moved to match

As B, plus relocating Cloud Run to whichever region actually serves the Live model, so
hops 1, 2 and 5 are all EU and there is no cross-region audio hop.

- **Gives:** the coherent version of B.
- **Costs:** everything in B, plus a new service URL and a Twilio webhook re-point. Cheap
  **now** — nothing is provisioned. Expensive **after** S7, once a number is in circulation.

### D. Keep the Developer API and disclose it

Treat global processing as an accepted risk, stated in the disclosure and in client
contracts rather than engineered away.

- **Gives:** zero engineering cost; honest.
- **Costs:** it puts the answer in the disclosure a caller hears in the first ten seconds
  of a cold call, which is a product and marketing decision well outside this ADR. Named
  for completeness because "engineer it away" is not the only legitimate answer.

## The falsifier — RESOLVED 2026-09-12, read in a browser

The previous version of this section said the Vertex Live region list was assumed. It has
now been read directly. **The result changes the decision, and not in the comfortable
direction.**

### 1. The Live model is NOT served in `europe-west2` (London)

From the model's own page, verbatim (`.../models/gemini/2-5-flash-live-api`, "Supported
regions → Model availability"):

> **United States:** us-central1, us-east1, us-east4, us-east5, us-south1, us-west1, us-west4
> **Europe:** europe-central2, europe-north1, europe-southwest1, europe-west1, europe-west4, europe-west8

Six European regions. **London is not one of them.** So the assumption was correct, and
this is now plain text rather than an inferred checkmark grid.

### 2. The EU multi-region endpoint EXPLICITLY EXCLUDES the UK

This is the finding that matters most, and it was not anticipated at all. From the Data
residency page, verbatim:

> **Note:** The European Union multi-region (eu) endpoint strictly covers data residency
> within EU member states. **Geographies outside the European Union political boundary,
> including the United Kingdom and Switzerland, are excluded from this endpoint.**

So "Vertex with the EU multi-region endpoint" is **not a UK residency answer.** Post-Brexit,
the EU multi-region is the wrong instrument for a UK product.

### 3. The residency table gives this model NO UK commitment

The Data residency page's Google-models table has a dedicated **United Kingdom
(europe-west2)** column. Read visually (the text extraction drops the checkmarks):
`gemini-live-2.5-flash-native-audio` has ticks in the first two columns only and is **blank
across every country column, UK included** — while `gemini-2.5-flash` on the row below is
ticked all the way across, which is what makes the blank meaningful rather than a rendering
artefact.

### 4. Locational endpoints DO satisfy GDPR — this part is better than feared

Also verbatim, and it softens the "endpoints don't guarantee residency" callout on the
endpoints page:

> **Locational endpoints:** These endpoints (like us-central1, europe-west1) ensure that ML
> processing remains entirely within the broader multi-regional or country jurisdiction
> associated with that region.
> **Compliance alignment:** While locational endpoints meet standard enterprise data
> governance and sovereign requirements (such as GDPR and HIPAA), workloads requiring
> specialized government isolation frameworks like DoD IL5 or ITAR should be deployed on
> jurisdictional endpoints.

So a locational endpoint in a *served* EU region does give in-jurisdiction ML processing and
is documented as meeting GDPR.

### 5. One discrepancy between two Google pages — flagged, not resolved

The **Deployments and endpoints** page's Google-model multi-region table shows the Live model
with **no** US or EU multi-region availability (verified visually — blanks, where Gemini 3.5
Flash shows ✓ ✓). The **Data residency** page shows the same model **with** US and EU
multi-region ticks. The two disagree.

Possible reading: one table is endpoint *invocability*, the other is ML-processing
*commitment*. **I am not asserting that** — it is a guess. It does not affect this ADR's
conclusion, because both pages agree the UK column is empty and the model page independently
excludes `europe-west2`. Recorded so nobody later "resolves" it by picking whichever table
suits them.

## What this means for the options — the honest version

| goal | achievable? |
|---|---|
| **UK in-country** processing of the call audio | **NO.** The model is not served in `europe-west2`, and the EU multi-region explicitly excludes the UK. Not available by either route. |
| **EU-jurisdiction** processing of the call audio | **YES** — Vertex on a locational endpoint in a served EU region (`europe-west1`, `europe-west4`, `europe-central2`, `europe-north1`, `europe-southwest1`, `europe-west8`), which the docs say meets GDPR. |
| Status quo | Global endpoint, no regional isolation, no residency guarantee — Google's own words. |

**So option B/C, as originally framed, was wrong about what it buys.** It buys EU, not UK.
If the product's claim is "UK-hosted", **that claim cannot be met for the audio leg with
this model**, and that is a product and marketing question, not an engineering one. If
"EU-hosted, GDPR-aligned" is the real requirement, B/C works — and then the region pin must
move off `europe-west2`, because London does not serve the model.

### Two incidental findings from the same reading

- **`gemini-live-2.5-flash-native-audio` has a retirement date: 2026-12-13.** Roughly fifteen
  months out. Both profiles pin it. Not urgent, but it is a dated dependency and nothing in
  the repo records it.
- **"Maximum conversation length: Default 10 minutes that can be extended."** The Cloud Run
  timeout is set to 3600 s for the WebSocket, but the *model* caps a session at 10 minutes by
  default. Fine for scripted S7 calls; relevant the first time a real caller talks longer.

## What this gates, precisely

**Not gated — proceed now, no real caller data involved:**

- the whole of S6: Dockerfile build, `gcloud run deploy`, secrets, IAM, Twilio webhook wiring
- smoke **tier 1** (fake senders, synthetic fixture, local filesystem)
- smoke **tier 2** (one email to the operator address, synthetic fixture — no real caller)
- the `curl` service-up check in `docs/deploy.md` step 6a

**GATED on owner ratification of this ADR:**

- smoke **tier 3** — sends a real SMS via Twilio
- **the tracer gate (Order row 4): the first real call.** This is the line. A real call
  means a real human's speech reaching hop 1, and from that moment the un-region-controlled
  data exists and cannot be un-created.
- all of **S7**

## Decision

**None yet. Awaiting owner ratification.** The owner's leaning is B/C; the falsifier above
decides which. Until ratified, the Developer API stays and the deploy proceeds — that is
the owner's explicit instruction (2026-09-12), not a default.

## Consequences once ratified

- **If A or D:** no code change. Record the accepted risk here and in the premise log; S7
  proceeds.
- **If B or C:** re-open S2's and S3's latency premises (Article 8), re-measure A3 against
  the new endpoint, change two client call sites plus `Settings`' credential shape, update
  both profiles' `live_model`, and revisit the `europe-west2` pin. **Do it before the
  Twilio number is in circulation**, because after that the URL re-point has an audience.
