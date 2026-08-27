# Agents guide — decana

## Project in one sentence

A voice intake line: a caller phones a number, Twilio bridges the audio to Gemini
Live, the AI holds a short intake conversation, and after the call the transcript is
analysed and dispatched to the operator — with everything vertical-specific read from
a profile directory rather than written in code.

## Start here

**Read `PROGRESS.md`'s `## NOW` block first.** It is written for a fresh instance with
no memory of the previous session and names the current slice, what is green, what is
parked and why, and the next unblocked item. If you cannot resume from it alone, it is
wrong — fix it rather than guessing.

## Active agents

| Agent | Layer | Entry point |
|---|---|---|
| `slice-builder` | Build | `/plan-slice` then work |
| `overseer` | Audit | auto-triggered by Stop hook |
| `self-learning-orchestrator` | Memory | `/lesson`, `/wrap-up`, `/stuck` |
| `master-architect` | Design | `/master-architect` |
| `feature-architect` | Design | `/feature-architect` |

## Pipeline

Slice flow: `master-architect` → `/plan-slice` → `slice-builder` → `overseer` (auto).

**The work loop, when running unattended:** finish the current slice → take the next
unbuilt node in the feature DAG → `/plan-slice` it → build it → repeat. DAG exhausted
→ park and wait. The DAG is in
`.claude/architecture/feature/vertical-profile-bridge.md`; the queue with its
HUMAN-REQUIRED nodes is in `PROGRESS.md`.

## Domain context

One Cloud Run process serves one vertical, selected by `DECANA_PROFILE`. A profile
directory carries the disclosure spoken to the caller, the conversation prompt, the
post-call analysis prompt, the outcome vocabulary and the SMS templates — so a new
vertical is a new directory under `profiles/`, not a code change. That property is an
acceptance criterion, not an aspiration: it is proven by swapping profiles and showing
`git diff --stat` touches `profiles/` only.

**The constraint everything bends around is latency.** `<Connect><Stream>` is a
terminal TwiML verb and verbs run in order, so the media WebSocket does not exist while
the disclosure is playing. Gemini needs ~3–4 s to connect and greet. The session is
therefore opened in the `POST /voice` webhook — the only code that runs during the
disclosure — and adopted by the socket when it arrives.

## Key paths

| Path | What it is |
|---|---|
| `src/decana/profile/` | S1 — profile loading and validation |
| `src/decana/bridge/` | the shipped audio bridge: μ-law codec, streaming resampler, timing recorder, `BridgeSession` |
| `src/decana/gemini/` | S2 — the Gemini Live client |
| `src/decana/twilio/` | S3 — TwiML webhook, media socket, `CallRecord` |
| `src/decana/settings.py`, `__main__.py` | the composition root; the only place the environment is read |
| `profiles/<name>/` | one vertical: `profile.toml` + three prompt `.md` files |
| `tests/` | one file per slice; every test's docstring opens with its ratified behavior id |
| `scripts/` | smokes, the mutation harness, the budget cap, the supervisor |
| `.claude/overseer/slice/` | the ratified planning artifact per slice — the behavior list, and the contract |
| `.claude/overseer/MEMORY.md` | cross-slice failure patterns. Read before planning; they are the priors |

## Conventions that are load-bearing

- **`uv run mypy --strict src scripts tests`** — that exact command. `pyproject.toml`
  scopes mypy to `src`/`scripts`, so a bare run silently skips the suite and reports
  clean. Two real errors were lost that way once.
- **No test exists that does not trace to a ratified behavior id**, and no id lacks a
  test. Both directions; check it with the diff in `PROGRESS.md`.
- **`scripts/mutate_check.py` is the only sanctioned mutation harness.** It asserts the
  mutation applied, restores in a `finally` and on signals, and verifies the restore.
  An ad-hoc runner once died mid-mutation and left the tree corrupted.
- **Commits are the human's.** Stage and report; `git commit` is hook-blocked.
