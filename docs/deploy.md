# Deploying decana to Cloud Run

S6's deliverable. Written for a **clean Ubuntu box with nothing installed**, in the
order you run it. You run every command; nothing here is run by the agent.

**Target, confirmed against the ratified contract** (`.claude/architecture/feature/vertical-profile-bridge.md`,
"Edge S3 → S6"), not from memory:

> `Dockerfile` runs `decana` (the script entry) with `PORT` honoured; Cloud Run service:
> `min-instances=1`, `max-instances=1` (one process per number, Twilio stream affinity),
> `--session-affinity`, timeout ≥ 3600 s (WebSocket lifetime), secrets `GEMINI_API_KEY`,
> `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `SMTP_*` from Secret Manager into env;
> `PUBLIC_WSS_URL = wss://<service-url>`; Twilio number voice webhook →
> `https://<service-url>/voice`.

So: **the target is Cloud Run**, and **this Ubuntu box is only where `gcloud` runs from**.
The contract says nothing that contradicts that.

## Why europe-west2 (London) — and why the obvious worry does not apply

Checked 2026-09-12 against current docs, because the region fixes the service URL and
re-pointing Twilio later is the cost of getting it wrong.

**The concern was: if Gemini Live serves from far away, a London Cloud Run region adds a
round-trip per audio chunk and loses more on the Gemini leg than it gains on Twilio's.
That is the right question, and it does not bind here.**

**This project uses the Gemini *Developer* API, not Vertex AI.** Both clients are built as
`genai.Client(api_key=...)` (`gemini/live.py:356`, `analysis/gemini_client.py:34`) — no
`vertexai=True`, no project, no location. Grepped `src/` and `scripts/`: there is no region
parameter anywhere, because the Developer API does not have one. Its
["available regions" page](https://ai.google.dev/gemini-api/docs/available-regions) is
**country eligibility**, not a list of serving endpoints you pick from — it exists to say
who may call the API, not where it answers from.

So `generativelanguage.googleapis.com` is a single global endpoint reached over Google's
edge network. **Cloud Run region does not select a Gemini serving location**, and there is
no "Cloud-Run-to-Gemini hop" to shorten by choosing Belgium over London: traffic from
either enters the same backbone at whichever POP is nearest, and London and Belgium are
both major POPs a few hundred km apart.

That leaves the two legs as:

| leg | when it costs | region effect |
|---|---|---|
| Twilio → Cloud Run | **once**, at call setup (the `POST /voice` webhook) | London is marginally closer for UK calls. Small, and non-recurring. |
| Cloud Run → Gemini | **per chunk, for the whole call** — the latency-critical loop | **No region effect.** Global endpoint, not region-bound. |

The leg inside the loop is region-independent, so the tiebreak falls to the one-time leg,
and that favours London. **Pinned `europe-west2`.**

### The one thing that would change this answer

If the project ever moves to **Vertex AI** — the plausible reason being data residency, see
below — then region *does* bind, and the Live API's regional availability starts to matter.
Indications are that the native-audio Live model is served in `europe-west1` (Belgium),
`europe-west4` and `europe-north1`, and that `europe-west2` is **not** among the tested
Live regions.

**Confidence, stated plainly: I could not verify that from a primary doc.** The Vertex
locations and Live API reference pages return navigation shells to a fetcher, so the
region list above comes from a search summary and a developer-forum thread, not from a
quoted table. Treat it as **assumed, not verified.** What would falsify it: opening the
Vertex AI locations page or the Live API model reference in a browser and reading the
supported-locations table.

**So:** the pin is correct on today's architecture, which is verified. If a Vertex
migration is actually on the roadmap, check that region table properly *before* the first
deploy — because at that point `europe-west1` probably wins, and switching after the fact
means a new service URL and re-pointing Twilio.

### Flagged, separately, because it is not a latency question

**This is now recorded as [ADR-0001](adr/0001-caller-data-residency.md) and it GATES the
first real call.** S6 is not gated: deploy, wiring, and smoke tiers 1 and 2 carry no real
caller data. **Smoke tier 3 and the tracer gate (step 6d and 6e) do not run until the
owner ratifies that ADR.** The ADR also found that this decision reaches the SMTP provider
choice, not just Gemini — the brief email's body contains `analysis.summary`, so hop 3
carries caller data too.

The Developer API's global endpoint means **call transcripts have no region control at
all.** This service records what UK prospects say on the phone and sends it to a global
endpoint; nothing in the current architecture constrains where that is processed. The whole
`disclosure.md` / `compliance_notes` machinery exists because this is a regulated context,
which makes the mismatch worth a deliberate decision rather than a default.

This does not block S6 and it is not mine to settle — it is a product and compliance call,
and it is the kind that gets harder to reverse once real client calls have been recorded.
Vertex AI with an EU region is the lever if the answer is "that is not acceptable". Raised
here so it is on the record before the first real call, not after.

## Cost and reversibility legend

Every step is marked. Read the mark before running the step.

| mark | meaning |
|---|---|
| 🟢 | free, local, reversible |
| 💰 | **spends money or creates a billable resource** |
| ⚠️ | **hard to undo** — reversing it costs more than re-running a command |

**`min-instances=1` is the standing cost.** It keeps one container alive 24/7 so Twilio's
stream has a warm process — that is a deliberate latency decision, not a default, and it
bills continuously until you set it to 0 or delete the service.

## Placeholders you fill

Marked `<LIKE_THIS>` throughout. Set them once as shell variables in step 2.

| placeholder | what it is | when I need it from you |
|---|---|---|
| ~~`<GCP_PROJECT_ID>`~~ | **PINNED: `decana-voice-prod`** (project number `95407434241`), a dedicated project linked to the `Pocket_lawyer` billing account `010D67-7CE4F1-3B7AD3` — the open one carrying credits. Credits sit on the billing account, not the project, so a separate project spends them just the same while keeping decana's IAM and secrets apart from the other product. | settled 2026-09-13 (owner) |
| ~~`<GCP_REGION>`~~ | **PINNED: `europe-west2` (London)** | settled 2026-09-12 — see "Why europe-west2" below |
| ~~`<SERVICE_NAME>`~~ | **PINNED: `decana-voice`** | settled 2026-09-12 (owner) |
| `<SMTP_HOST>` | the real SMTP relay hostname | **step 3 — tell me and I will pin it** |
| `<SMTP_PORT>` | `465` (implicit TLS) or `587` (STARTTLS) — see step 6c | step 3 |
| `<SMTP_USER>`, `<SMTP_FROM>` | relay login and envelope sender | step 3 |
| ~~`<TWILIO_NUMBER>`~~ | **PINNED (interim): `+18392749051`** — a US number already in the owner's Twilio account, used until UK number compliance is done (owner, 2026-09-13). Calls from the UK reach it as international; SMS to the caller goes from the profile's alphanumeric `sms_sender_id`, not from this number, so swapping to a UK number later touches only the Twilio console, not the deploy. | step 5 |

Secret **values** are never written in this doc, and never passed on a command line where
they would land in shell history. Every secret is piped from a prompt at run time.

---

## 1. Prerequisites 🟢

Verified against the current official install page (`https://docs.cloud.google.com/sdk/docs/install`,
checked 2026-09-12 — note the canonical host moved from `cloud.google.com` to
`docs.cloud.google.com`). `apt-key` is deprecated; the current method is a keyring plus
`signed-by`.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates gnupg curl

curl https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg

echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list

sudo apt-get update && sudo apt-get install -y google-cloud-cli
```

Verify:

```bash
gcloud version
```

**Nothing else is needed on this box.** No Docker: step 4 builds with Cloud Build from
source, so the image is never built locally. (If you would rather build locally, that is a
different route and this doc does not cover it.)

---

## 2. One-time GCP setup

### 2a. Authenticate, and create the project if there isn't one 🟢 / 💰

```bash
gcloud auth login
```

If you already have a project to bill this to, skip to 2b. To create one — **💰 a project
is free, but it is the billing container everything else attaches to**:

```bash
gcloud projects create <GCP_PROJECT_ID> --name="decana"
gcloud billing accounts list                      # find your billing account id
gcloud billing projects link <GCP_PROJECT_ID> --billing-account=<BILLING_ACCOUNT_ID>
```

Linking billing is what makes the later 💰 steps able to charge. Nothing bills until
step 2c enables APIs and step 4 creates the service.

This opens a browser. If this box has no browser, use `gcloud auth login --no-launch-browser`
and paste the code.

### 2b. Set the project and region 🟢

```bash
export PROJECT_ID=decana-voice-prod # PINNED — see "Placeholders you fill"
export REGION=europe-west2          # PINNED — see "Why europe-west2"
export SERVICE=decana-voice        # PINNED

gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
```

Confirm what you are pointed at before anything billable:

```bash
gcloud config list
```

### 2c. Enable the APIs 💰

Enabling an API is free, but it is the gate on services that bill. Four are needed —
`run` and `secretmanager` for the service itself, `cloudbuild` and `artifactregistry`
because a source deploy builds the image with Cloud Build and stores it in Artifact
Registry.

```bash
gcloud services enable \
  run.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com
```

**What this will cost later:** the first source deploy auto-creates an Artifact Registry
repository named `cloud-run-source-deploy` in `$REGION` and stores every built image
there. Storage bills per GB-month and images accumulate on each deploy — prune them
occasionally, or it grows quietly.

---

## 3. Secrets 💰 — read cross-project from the owner's vault (revised 2026-09-13)

**The owner keeps every credential in ONE Secret Manager vault, in project
`pocket-lawyer-431614` (project number `1017046526541`).** decana does not copy them:
the Cloud Run service in `decana-voice-prod` mounts them straight from that project by
full resource path. One vault, one rotation. The accepted cost: deleting the vault project
takes decana down with it.

Secret names there are lowercase-hyphen; the env var names decana reads are unchanged.
The mapping, and what exists as of 2026-09-13:

| env var (`settings.py`) | secret in `pocket-lawyer-431614` | state |
|---|---|---|
| `GEMINI_API_KEY` | `gemini-api-key` | exists, 39 bytes, no trailing newline |
| `TWILIO_ACCOUNT_SID` | `twilio-account-sid` | created 2026-09-13, 34 bytes |
| `TWILIO_AUTH_TOKEN` | `twilio-auth-token` | exists |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASSWORD` `SMTP_FROM` | **never** | owner decision 2026-09-13: no email channel at all. Tier 2 of `smoke_dispatch.py` is therefore permanently N/A, and the "mount SMTP later" command in step 4 is moot. |

`twilio-api-key-sid` / `twilio-api-key-secret` also exist in the vault but are NOT used:
decana authenticates with Account SID + Auth Token.

**Adding a secret to the vault** without the value touching shell history — `read -rs`
prompts silently, `printf '%s'` adds no trailing newline:

```bash
read -rsp 'NAME: ' V && echo && printf '%s' "$V" \
  | gcloud secrets create <name> --data-file=- --project=pocket-lawyer-431614 ; unset V
```

To rotate, `gcloud secrets versions add <name>` with the same pipe. Check length, never
value: `gcloud secrets versions access latest --secret=<name> --project=pocket-lawyer-431614 | wc -c`.

### 3a. Let decana's service identity read them ⚠️

The service runs as `decana-voice-prod`'s default compute service account,
`95407434241-compute@developer.gserviceaccount.com`. It needs `secretAccessor` **on each
secret, in the vault project**. Done 2026-09-13 for the three that exist; repeat for every
`SMTP_*` secret when it is added, or the deploy fails at mount time:

```bash
for S in gemini-api-key twilio-auth-token twilio-account-sid; do
  gcloud secrets add-iam-policy-binding "$S" \
    --project=pocket-lawyer-431614 \
    --member="serviceAccount:95407434241-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
```

Verify with `gcloud secrets get-iam-policy <name> --project=pocket-lawyer-431614`: the
member must be listed. A missing binding does not fail at grant time — it fails as a
deploy error, or as a service that starts and then exits 2 on the missing variable.

---

## 4. Deploy 💰⚠️

**💰** This creates the running service and starts the `min-instances=1` standing charge.
**⚠️** The service URL is derived from the service name and region; changing either later
gives you a *new URL*, which means re-pointing the Twilio webhook and re-setting
`PUBLIC_WSS_URL`. Pick `$SERVICE` and `$REGION` once.

`PUBLIC_WSS_URL` is a chicken-and-egg: it must be the service's own URL, which does not
exist until the first deploy. So deploy once without it, read the URL, then set it. The
first deploy will not serve a working call — that is expected.

### 4a. First deploy — creates the service and the URL

```bash
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --min-instances 1 \
  --max-instances 1 \
  --session-affinity \
  --timeout 3600 \
  --set-env-vars DECANA_PROFILE=mortgage-broker,DECANA_PROFILES_ROOT=/app/profiles,DECANA_ARTIFACT_DIR=/app/artifacts/calls \
  --set-secrets GEMINI_API_KEY=projects/1017046526541/secrets/gemini-api-key:latest,TWILIO_ACCOUNT_SID=projects/1017046526541/secrets/twilio-account-sid:latest,TWILIO_AUTH_TOKEN=projects/1017046526541/secrets/twilio-auth-token:latest
```

Run it from the repo root — `--source .` uploads the build context, and `.dockerignore`
trims it. The first run asks to create the Artifact Registry repository
`cloud-run-source-deploy`; answer `Y`.

**Secrets are full resource paths** (`projects/<vault project NUMBER>/secrets/<name>:latest`)
because they live in the owner's vault project, not this one — see step 3. **SMTP is not
mounted on the first deploy**: the five `SMTP_*` secrets do not exist yet. `Settings`
treats them as optional per group, so the service starts and every dispatch except the
operator email runs. When they exist, mount them without touching code:

```bash
gcloud run services update "$SERVICE" --region "$REGION" \
  --update-secrets SMTP_HOST=projects/1017046526541/secrets/smtp-host:latest,SMTP_PORT=projects/1017046526541/secrets/smtp-port:latest,SMTP_USER=projects/1017046526541/secrets/smtp-user:latest,SMTP_PASSWORD=projects/1017046526541/secrets/smtp-password:latest,SMTP_FROM=projects/1017046526541/secrets/smtp-from:latest
```

**If the build step fails with a permissions error** (new projects route Cloud Build
through the default compute service account, which sometimes lacks build rights), grant
it and retry:

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:95407434241-compute@developer.gserviceaccount.com" \
  --role="roles/cloudbuild.builds.builder"
```

**Why each non-obvious flag, since the contract fixes them:**

| flag | why |
|---|---|
| `--min-instances 1` | keeps a warm process so Twilio's stream is not waiting on a cold start. **This is the standing cost.** |
| `--max-instances 1` | one process per number — Twilio stream affinity. More than one instance would split a call's webhook and its media socket across processes, and the in-memory session registry would miss. |
| `--session-affinity` | same reason, at the routing layer. |
| `--timeout 3600` | **a WebSocket stream IS an HTTP request to Cloud Run and is subject to the request timeout.** Default is 300 s (5 min); 3600 s (60 min) is the documented maximum. A call is cut at the timeout regardless of what the app does. |
| `--allow-unauthenticated` | Twilio's webhook is an unauthenticated POST from the public internet. |
| `DECANA_PROFILES_ROOT=/app/profiles` | **the port trap's sibling.** `Settings.profiles_root` defaults to `<repo root>/profiles` resolved from `decana.__file__`, which assumes an editable install. The image is not editable. The `Dockerfile` already sets this; it is repeated here so the service config is self-describing. |
| `DECANA_ARTIFACT_DIR=/app/artifacts/calls` | the default is *relative* to the working directory. Absolute and writable by the non-root user. |
| **no `PORT`** | Cloud Run injects it and `Settings.port` reads it (default 8080). **Do not set it** — a fixed value here would fight the platform. |

### 4b. Set `PUBLIC_WSS_URL` 🟢 — DONE 2026-09-13

**What actually happened on the first deploy, so nobody re-derives it:** the build
succeeded, revision `00001` crash-looped on `missing required environment variable:
PUBLIC_WSS_URL` (exit 2, as designed), and **`status.url` stayed EMPTY** — Cloud Run does
not publish the URL until some revision is Ready. So the runbook's "read the URL, then set
it" loop cannot close on its own.

It does not need to. Cloud Run URLs are deterministic:
`https://<service>-<project number>.<region>.run.app`. For this service that is

```
https://decana-voice-95407434241.europe-west2.run.app
```

and it was set directly, which also ended the crash loop:

```bash
gcloud run services update "$SERVICE" \
  --region "$REGION" \
  --update-env-vars PUBLIC_WSS_URL=wss://decana-voice-95407434241.europe-west2.run.app
```

Once revision `00002` was Ready, `status.url` published the *legacy* form
`https://decana-voice-ualhbcwuta-nw.a.run.app`. **Both hostnames reach the same service**
(verified: both return FastAPI's JSON 404 on `/`). `PUBLIC_WSS_URL` stays on the
deterministic one because it carries no hash and survives anything short of renaming the
service or moving region. Use either for the Twilio webhook; the runbook uses the
deterministic one throughout.

**No trailing slash.** S3 builds the stream URL by appending `/media`, so a trailing slash
produces `//media` and the socket never connects.

**6a was run against this deploy (2026-09-13 09:02 UTC): 200, TwiML with `<Say>`,
`<Connect>`, `<Stream url="wss://decana-voice-95407434241.europe-west2.run.app/media">`,
and the google-genai client logged a model response two seconds later** — so the
cross-project `gemini-api-key` mount works end to end.

---

## 5. Post-deploy wiring ⚠️

**⚠️ Provisioning a Twilio number is the hard-to-undo act in this whole document** — the
MVP doc flags it, and if the number becomes the one you give to brokers it is a one-way
door. Do not provision a number you are not prepared to keep.

Point the number's **Voice** webhook at:

```
https://<SERVICE_URL>/voice        # HTTP POST
```

Either in the Twilio console (Phone Numbers → your number → Voice Configuration → *A call
comes in* → Webhook, HTTP POST), or:

```bash
# requires the Twilio CLI, which this box does not have; console is fine
twilio phone-numbers:update <TWILIO_NUMBER> --voice-url "https://${SERVICE_URL#https://}/voice"
```

**Restore point for `+18392749051` (read from the Twilio console 2026-09-13, before the
change).** The number was serving another product, `anna-booking-bridge`, and the owner
asked that it be restorable. To hand it back, set the Voice Configuration fields to:

| field | previous value |
|---|---|
| Configure with | Webhook, TwiML Bin, Function, Studio Flow, Proxy Service |
| A call comes in | Webhook · `https://anna-booking-bridge-1017046526541.europe-west3.run.app/incoming` · HTTP POST |
| Primary handler fails | Webhook · *(empty)* · HTTP POST |
| Call status changes | `https://anna-booking-bridge-1017046526541.europe-west3.run.app/twilio/status` · HTTP POST |
| Caller Name Lookup | Disabled |

Number SID `PN804a0c758c5cd064cc4cf906123a76ba`. For decana, **A call comes in** points at
`/voice` and **Call status changes is cleared** — decana does not consume status callbacks,
and leaving it would post every decana call's lifecycle to the other product.

Two URLs, one service, and they are not interchangeable:

- Twilio's webhook uses **`https://…/voice`** — the TwiML endpoint.
- `PUBLIC_WSS_URL` is **`wss://…`** with no path — S3 appends `/media` itself.

---

## 6. Verification, in the order that each step proves something new

### 6a. The service is up 🟢

```bash
curl -i "$SERVICE_URL/voice" -X POST \
  -d 'CallSid=VERIFY_ONLY&From=%2B440000000000'
```

Expect **200** and a TwiML body containing `<Say>`, `<Connect>` and `<Stream>`. A **422**
means `CallSid` or `From` was missing — that is S3's required-field behaviour working, not
a fault. A **500** is a real fault: check the logs.

```bash
gcloud run services logs read "$SERVICE" --region "$REGION" --limit 50
```

**This POST opens a real Gemini Live session** (S3-Q1 opens it in the webhook so the
connect cost hides behind the disclosure), so it spends a little API quota and leaves a
session to time out. Use it once, not in a loop.

### 6b. Smoke tier 1 — no credentials, proves the dispatch chain 🟢

Run **locally**, not against the deployed service: tier 1 exercises the filesystem
contract, which is the same code in both places.

```bash
uv run python scripts/smoke_dispatch.py
DECANA_PROFILE=eco-consultant uv run python scripts/smoke_dispatch.py
```

Expect `TIER 1: PASSED` (13/13) for both profiles. Both passing with only an env var
changed is A4's property — a new vertical is a directory, not a code change.

### 6c. Smoke tier 2 — the first thing only the real relay can settle 💰

This is where **`SMTP_PORT`'s "465 means implicit TLS" assumption is confirmed or
falsified.** It is an assumption, explicitly recorded as unmeasured in the slice artifact:
the code chooses `SMTP_SSL` for 465 and `SMTP` + `starttls()` for anything else, with **no
plaintext fallback** — a relay that offers neither fails loudly rather than sending call
transcripts in the clear.

```bash
export SMTP_HOST=<SMTP_HOST> SMTP_PORT=<SMTP_PORT> \
       SMTP_USER=<SMTP_USER> SMTP_PASSWORD='PASTE_AT_RUN_TIME' SMTP_FROM=<SMTP_FROM>

uv run python scripts/smoke_dispatch.py
```

Expect `TIER 2: PASSED — one email sent to …`. Costs one email.

- **If it fails with a TLS or timeout error on 465** → the assumption is falsified for this
  relay. Try `587`. **Tell me either way** — a falsified premise is recorded against the
  slice, not just fixed in passing.
- **If it fails with an auth error** → credentials, not transport. The transport reached
  the server, so the port choice was right.

### 6d. Smoke tier 3 — Twilio 💰⚠️ **GATED on ADR-0001**

**STOP — [ADR-0001](adr/0001-caller-data-residency.md) must be ratified before this step.**
Everything above this line involves no real caller data; this step and the next do.

**⚠️** Needs a provisioned number (step 5). **💰** Sends one real SMS and spends the
`_budget` cap, which it takes *before* opening a socket so a crash-loop cannot exceed it.

```bash
export TWILIO_ACCOUNT_SID=<...> TWILIO_AUTH_TOKEN='PASTE_AT_RUN_TIME' \
       DECANA_SMOKE_SMS_TO=<your mobile, E.164>

uv run python scripts/smoke_dispatch.py
```

Expect `TIER 3: PASSED — sid='SM…'`.

**This is load-bearing, not ceremonial.** It is the only check that premise **P2** holds
against a real Twilio response. P2 was *falsified* at plan time: the ratified contract types
`SmsSender.send -> str`, but `MessageInstance.sid` is `Optional[str]` (SDK source
`message/__init__.py:119`). The adapter narrows and raises on a sid-less response. Every
test of that path uses a constructed response; tier 3 is the only place a real one appears.

### 6e. The tracer gate — one real call ⚠️ **GATED on ADR-0001**

**STOP — [ADR-0001](adr/0001-caller-data-residency.md) gates this.** A real call is the
moment un-region-controlled caller data starts existing, and it cannot be un-created.

The ratified PASS condition (Order row 4), unchanged:

> Owner dials once. PASS = hears whatever `disclosure.md` currently contains via `<Say>`
> (placeholder text is fine), then the model opens the conversation; `{call_sid}.jsonl`
> exists with `call_answered` and ≥ 1 `chunk_forwarded_to_twilio`; `on_call_end` log line
> shows a non-empty transcript.

```bash
gcloud run services logs read "$SERVICE" --region "$REGION" --limit 200
```

**A3 latency is NOT judged here** — that is S7 with the turnlog.

### What stays unproven until S7

- **A3**, the latency the feature is judged on, measured on a real PSTN call with the
  disclosure playing. The local proxy measured 3128 ms with ~10 s of margin behind the
  disclosure, but the disclosure's own duration is a words-per-minute *estimate*, not a
  measurement.
- **P2's wire half** beyond tier 3: whether `customParameters` values arrive as strings,
  whether `sequenceNumber` is contiguous, whether `mark` is echoed. None is checkable
  without a real call and there is no SDK source to read.
- **A4's `git diff --stat`** evidence, which needs the eco redeploy in 7b.

### 6f. Call artifacts go to a Cloud Storage bucket, not instance disk (added 2026-09-13) 💰

**Why:** the first real call (Twilio sid `CA1bc6ed503fad7a34b735d1c7ce30d7c8`, 77 s,
2026-09-13 09:45 UTC) ran end to end, and then **nothing could be read back**: the
transcript, analysis and brief were written to `/app/artifacts/calls` on the instance's
local disk, which has no `exec`, and the INFO-level lifecycle lines were dropped because
no log handler was configured. That call's artifacts are gone. Two fixes:

1. `__main__.py` now calls `logging.basicConfig(level=INFO)` — wiring, no logic.
2. `DECANA_ARTIFACT_DIR` is a **Cloud Storage FUSE volume** backed by a bucket in
   `europe-west2`. Files survive redeploys (which also retires the "copy artifacts off
   before 7b" warning below), stay in London, and are readable with `gcloud storage`.

```bash
gcloud storage buckets create gs://decana-voice-prod-artifacts \
  --location=europe-west2 --uniform-bucket-level-access

gcloud storage buckets add-iam-policy-binding gs://decana-voice-prod-artifacts \
  --member="serviceAccount:95407434241-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

gcloud run deploy decana-voice --source . --region europe-west2 \
  --execution-environment gen2 \
  --add-volume name=artifacts,type=cloud-storage,bucket=decana-voice-prod-artifacts \
  --add-volume-mount volume=artifacts,mount-path=/app/artifacts/calls
```

**INCIDENT on the first mounted revision (`00004`, 2026-09-13 10:00 UTC), and the fix.**
The mount as written above broke calls: S3 appends one line to `{call_sid}.jsonl` per
audio chunk, many times a second, and on a FUSE mount every append rewrites the object.
Cloud Storage allows roughly one write per second per object, so it answered with a 429
storm, the blocked writes stalled the server, and the next webhook returned 502 (Twilio
alert 11200). **Per-chunk appends must never touch the bucket.**

The fix is a split: `Settings.timing_dir` (`DECANA_TIMING_DIR`, default = `artifact_dir`)
is where the timing log goes and stays on local disk; `DECANA_ARTIFACT_DIR` is dispatch's
three files per call and is the bucket. The `Dockerfile` sets both. Deploy with the
volume still mounted at `/app/artifacts/calls` and the timing dir beside it:

```bash
gcloud run deploy decana-voice --source . --region europe-west2 \
  --update-env-vars DECANA_TIMING_DIR=/app/artifacts/timing
```

(The volume and mount from the first command persist on the service template; only the
image and the one env var change.) The app's `mkdir(parents=True, exist_ok=True)` sees
the mount as an existing directory. **Still unverified on FUSE:** `dispatch.py` creates
its idempotency marker with `open("x")` (exclusive create). If a call's dispatch logs a
marker error, that is the premise to check.

Read a call back:

```bash
gcloud storage ls gs://decana-voice-prod-artifacts/
gcloud storage cat gs://decana-voice-prod-artifacts/<call_sid>.brief.md
# audio of both legs (added 2026-09-13; 8 kHz mono WAV, plays anywhere):
gcloud storage cp "gs://decana-voice-prod-artifacts/<call_sid>.*.wav" .
```

**The accent is a profile setting**, `[gemini] accent` in `profile.toml`, appended to the
call script as the last paragraph of the system instruction (added 2026-09-13). It had
been a sentence inside `conversation.md`; an edit dropped it between the 10:26 and 10:47
builds and the line turned American. There is no `[gemini] language` key and no
`language_code` is sent: Google documents that native audio models do not support one,
3.1 ignored it, and 2.5 native audio closes the socket with 1007 "Unsupported language
code" — which hung up a real call right after the disclosure (2026-09-13 13:15 UTC).

**Caller audio is NOT lifted** (`decana.bridge.gain`, `PHONE_INBOUND_GAIN_DB = 0.0`,
2026-09-13). The first recorded real call measured the caller at -39 dBFS against the
model's -10 dBFS, so a lift was tried twice: +12 dB with a hard clip (revision 00017,
"slightly worse", 7.6 % of frames clipped) and +9 dB through a tanh limiter (revision 00018,
"much worse, barely working": the model sat silent for 19 s while caller audio flowed).
The mechanism is not established — the between-word level is digital silence on every
recorded call, so it was not amplified noise — but the gain was the only variable against
the owner's best call, so it is backed out. The module stays as a no-op; any future lift
should be an A/B pair of calls with recordings compared. The recording keeps the RAW leg.

**Every call is recorded** as `<call_sid>.caller.wav` (what the caller sent) and
`<call_sid>.model.wav` (what the caller heard, after the codec). Owner request on
2026-09-13 after a softphone call with two voices that no artifact could show. Written
ONCE per leg at teardown by `decana.bridge.recording.CallRecorder`, so the FUSE mount is
a safe target; the two legs are separate files because the model leg is sent faster
than real time and a stereo file would misalign them. A failed write is logged, never
raised, so it cannot change a call's ending reason.

**FREE test calls: `scripts/softphone.html`** (added 2026-09-13 after the owner asked for
"some free testing vehicle"). A one-file browser softphone that speaks the Twilio Media
Streams protocol from the laptop microphone: POST `/voice`, optional disclosure stand-in,
then `connected`/`start`/20 ms μ-law `media` frames over `wss://…/media`, playing back
what the model sends. The server cannot tell it from Twilio, so the timing log and bucket
artifacts are produced identically. Serve it from localhost so the microphone is allowed:

```bash
cd scripts && python3 -m http.server 8765 --bind 127.0.0.1
# then open http://127.0.0.1:8765/softphone.html in Chrome, allow the microphone once
```

Point it at Cloud Run (default) or at a local `decana` on `http://localhost:8080`. No
Twilio charge, no phone. What it does NOT exercise: the PSTN leg (Twilio's own codec
path, carrier audio, `<Say>`), so the real-dial check below stays as the final gate.

**Cheap test calls without dialling internationally:** have Twilio call *you*. The
owner's mobile is a verified caller ID, so it can be both `From` and `To`; Twilio then
reports the mobile as the caller and the closing SMS reaches it.

```bash
export TWILIO_ACCOUNT_SID="$(gcloud secrets versions access latest --secret=twilio-account-sid --project=pocket-lawyer-431614)"
export TWILIO_AUTH_TOKEN="$(gcloud secrets versions access latest --secret=twilio-auth-token --project=pocket-lawyer-431614)"
curl -s -X POST "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/Calls.json" \
  -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
  --data-urlencode "To=<owner mobile, E.164>" \
  --data-urlencode "From=<owner mobile, E.164>" \
  --data-urlencode "Url=https://decana-voice-95407434241.europe-west2.run.app/voice" \
  --data-urlencode "Method=POST"
```

### Before 7b's redeploy — no longer applies once 6f is in place

**S7 step 7b redeploys this same service twice** (to `eco-consultant`, then back). Cloud
Run's local disk does not survive a redeploy, and `DECANA_ARTIFACT_DIR` is on it. So
**complete 7a's read-out, or copy the artifacts off the instance, BEFORE the first
redeploy** — otherwise 7b destroys the evidence 7a produced. This is written into the
feature contract's row 7b and its "Edge S7 — what it reads" section too; it is repeated
here because this is the document you will have open.

---

## Teardown 🟢

Stops the standing charge. Reversible — redeploy re-creates everything except the URL,
which may differ.

```bash
gcloud run services delete "$SERVICE" --region "$REGION"
```

To keep the service but stop paying for the warm instance:

```bash
gcloud run services update "$SERVICE" --region "$REGION" --min-instances 0
```

That reintroduces cold-start latency on the first call, which is exactly what
`min-instances=1` exists to avoid — so it is a debugging measure, not a config.
