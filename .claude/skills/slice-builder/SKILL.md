---
name: slice-builder
description: Build ONE isolated testable logical piece (a "thin slice") of a larger system using strict per-test TDD (RED→GREEN→REFACTOR), paranoid-SRP (one method = one responsibility; multi-responsibility logic becomes a flow method orchestrating helpers), seam-first design, and dependency injection. Use this skill WHENEVER the user asks to "implement a small piece", "add a thin slice", "build the upload module", "build piece N of the pipeline", "wrap this API in a clean function", or otherwise wants controlled incremental progress on a known integration without architecture overhead. Output is one production module + integration tests derived from the method's distinct behaviors + one manual smoke script + a PROGRESS.md entry. STOPS at scope, seam, behavior-list and smoke checkpoints — not at TDD transitions inside an approved behavior list. DO NOT use for greenfield architecture (→ master-architect), splitting oversized multi-file features (→ feature-architect), unknown-API exploration (→ spike, no skill), or single-file edits (→ user edits directly).
---

# Slice Builder

You are extending a known system one isolated logical piece at a time. The user already knows the rough shape (sometimes from `master-architect`, often just from being the system's owner). External dependencies are already accessible and validated — credentials live in `.env`, vendor docs are in the repo. You are NOT designing a system. You are NOT executing a `tasks.yaml` line item. You are adding ONE clean, testable, isolated module.

## Discipline (apply ALL of these)

1. **Seam-first.** Confirm function signature, types, and return shape with the user BEFORE writing any code. State what the component will **NOT** do — this is the boundary of the slice.

2. **Dependency injection always.** External clients, configs, time sources, and randomness are passed as arguments. NEVER import them inside the module under construction. This makes the module testable in isolation and prevents hidden coupling.

3. **Strict TDD per test.** RED → GREEN → REFACTOR per test. Show pytest output at every transition. Write ONE test at a time. NEVER write the next test before the previous one is green AND the code is refactored. Never write impl before its test.

4. **Paranoid-SRP.** ONE method = ONE responsibility. No exceptions, no asking. If logic requires multiple responsibilities, it becomes a **flow method** that calls single-responsibility helpers in order — the flow method's responsibility is "orchestrate these steps", each helper's responsibility is one step. Helper functions for SRP are NOT premature abstraction (that's about ABCs/protocols/factories, see rule 5).

   Example. NOT this:
   ```python
   def upload_to_folder(file_path, folder_id, client) -> UploadResult:
       if not file_path.exists(): return UploadResult(False, error="missing")
       if file_path.stat().st_size > MAX: return UploadResult(False, error="too big")
       token = client.authenticate()
       resp = client.post(...)
       if resp.status != 200: return UploadResult(False, error=resp.text)
       return UploadResult(True, document_id=resp.json()["id"])
   ```
   THIS:
   ```python
   def upload_to_folder(file_path, folder_id, client) -> UploadResult:
       """Flow: validate → upload → map response."""
       if (err := _validate_file(file_path)) is not None:
           return UploadResult(success=False, error=err)
       raw = _do_upload(file_path, folder_id, client)
       return _map_response(raw)

   def _validate_file(p: Path) -> str | None: ...
   def _do_upload(p: Path, fid: str, c: RemoteClient) -> RawResponse: ...
   def _map_response(r: RawResponse) -> UploadResult: ...
   ```
   Each helper has one reason to change. The flow has one reason to change (orchestration order).

5. **No premature abstraction.** No ABCs, no protocols, no `*_Factory`, no plugin systems, no `*_Manager`, no generic `*_Service` indirection, no retry policies, no circuit breakers, no structured event emission. If the user asked for a function, write a function.

6. **Tests: derived from method behaviors, not from a quota.** Before writing tests, enumerate the distinct externally observable behaviors the method guarantees, then write one test per behavior. Show the behavior list to the user before the first RED for sanity-check. Heuristics by method type:

   - **Pure transformation / formatter** (no I/O, no branches): 1-2 tests — success + one boundary if a meaningful one exists.
   - **Single-responsibility helper with validation**: success + one test per distinct failure mode it can return.
   - **Flow method (orchestrator)**: success orchestration + one test per step that can short-circuit the flow + one test per branch the flow itself chooses.
   - **Thin wrapper over external API**: success + at least one error path that the wrapper maps (typically 2). The external API's own behavior space is not your test surface — sandbox the integration.

   What is NEVER added at slice level: mutmut / cosmic-ray mutation testing, exhaustive hypothesis property tests, wide-lens enumeration (security/performance/concurrency/encoding lenses) — those belong to a full-feature implementation effort. Adding them to a slice is scope creep.

7. **Manual smoke verification at the end.** A `scripts/smoke_test_<slice>.py` that exercises the real path against the real system, prints results, and gives the user explicit human-verifiable instructions. The slice is NOT complete until the user runs this and reports OK.

## When to use this skill

User says or implies:
- "Implement the upload module" / "Build the magic-link generator"
- "Add a thin slice for X"
- "Build piece 1 of the pipeline"
- "Small isolated function for Y"
- "Wrap this vendor SDK in a clean function for our use"
- "Let's start small and test if X works in our system"
- "Incrementally add..."

User context typically includes:
- Rough idea of the larger system (sketch, not full architecture)
- External dependencies already accessible (`.env`, vendor docs in repo)
- No urgent need for full architecture process or `tasks.yaml`

## When NOT to use this skill

| If the user wants... | Use instead |
|---|---|
| "Design the architecture for X from scratch" | `master-architect` |
| "Implement this large multi-file feature end-to-end" | `master-architect` + `feature-architect` |
| "Split t007 / this task is too big" | `feature-architect` |
| "Does API X even work? I have no creds/docs yet" | Spike work — no skill, direct conversation |
| "Fix this typo / rename this variable / one-line change" | No skill — user edits directly |
| Cross-module refactor of an existing feature | No skill — user-led, possibly with `master-architect` BACKTRACK |

If invoked incorrectly, name the correct skill and ask the user to redirect.

## Workflow

### Step 0 — Validate scope

Ask the user (concise, all at once):
- What's the seam? (function signature, input types, return type)
- What's the external dependency? Where are its docs? (path in repo)
- What does this slice **NOT** do? (List 3-5 items the user must agree to defer.)
- Existing conventions in the repo to follow? (test layout, type strictness, Pydantic vs dataclass for what kinds of objects)

**STOP. Wait for answers.**

### Step 1 — Read external docs

Read the vendor docs the user pointed to. Report back:
- Which API/function to call (exact name, expected request/response shape)
- Which credentials are needed (confirm they exist in `.env.example` or `.env`)
- Whether a test/sandbox environment exists, and what its config looks like
- Any constraints on inputs (file size, MIME, character encoding, etc.)

**STOP. Wait for user to provide test environment details** (folder ID, account ID, sandbox URL, etc.) if not already in `.env`.

### Step 2 — Skeleton

Write the module skeleton:
- Function signature with `raise NotImplementedError("slice in progress")`
- Value objects (frozen dataclasses, or Pydantic v2 if user requested cross-boundary type) — name them, give fields, give types
- Type hints, suitable for mypy strict
- Module-level docstring stating WHAT this module does and what it explicitly DOESN'T (echoes Step 0)

Run `pytest --collect-only` (or equivalent) — import must succeed.

**STOP.**

### Step 3 — Enumerate behaviors

Before writing any test, list the distinct externally observable behaviors the slice must guarantee. Use the heuristics from rule 6 to scope the list. For a flow method, list behaviors at the flow level — helpers will get their own tests if they're exposed, but typically helpers are tested THROUGH the flow.

Output format:
```
Behaviors of upload_to_folder:
  B1. Returns success=True + document_id when file uploads to valid folder
  B2. Returns success=False + error when file path doesn't exist
  B3. Returns success=False + error when folder_id is unknown to the remote service
  B4. Returns success=False + error when file size exceeds the service limit
```

**STOP. User confirms the list, removes/adds behaviors, then approves.** Behavior list is the test plan.

### Step 4 — TDD per behavior (one cycle per behavior)

For each behavior Bn in order:
- **RED**: Write ONE test for Bn. Run pytest. Show failing output.
- **GREEN**: Minimal implementation to make Bn pass without breaking earlier behaviors. Run pytest (full slice suite). Show all green.
- **REFACTOR**: Clean. If SRP rule 4 says a flow needs splitting into helpers — do it here. Run pytest. Still green.

The order is strict: never write Bn's implementation before its test, and never start Bn+1 before Bn is green AND refactored. But the whole cycle runs in **one turn**, and you continue to Bn+1 without stopping — the behavior list was the gate, and the owner already passed it at Step 3. Show every transition's pytest output in the transcript regardless; it is read afterwards. See "The gate is the behavior list, not the cadence" under Stop discipline.

**If during a cycle you discover a behavior was missing from the list, STOP and ask the user to amend the list — don't sneak it in.** This is the one boundary chaining never crosses, and the reason the rest of Step 4 can run unattended.

### Step 5 — Smoke script

Write `scripts/smoke_test_<slice>.py`:
- Sets up real inputs (generate file, build payload, load real creds from `.env`)
- Calls the slice function with real DI dependencies
- Prints the result
- Prints an EXPLICIT human-verifiable instruction (e.g., "Open the admin panel at /uploads, look for file `smoke_<slice>_<timestamp>.txt`. Reply DONE or FAIL.")

**STOP. Tell user:** "Run `python scripts/smoke_test_<slice>.py` and verify per the printed instruction. Reply DONE or FAIL."

### Step 6 — PROGRESS update

After user reports smoke DONE, append to `PROGRESS.md` at repo root (create if missing):

```
## Slice N — <name> (DONE YYYY-MM-DD)

- Module: <path> (~NN LOC)
- Tests: N integration tests, all green
- Smoke: passed, <verification result>
- Surprises: <1-2 lines or "none">
- Open for next slice: <questions / tech debt / "none">
```

Hand back to user with a one-line summary. **STOP.** Do NOT commit on the user's behalf — let them review and commit.

## Anti-patterns (refuse politely if user requests these mid-slice)

If the user asks for any of the following DURING the slice, push them out of scope:

- Tests not derived from a stated behavior (vibe-based "while I'm here" tests)
- Mutation testing (mutmut, cosmic-ray)
- Wide test design (test lenses, exhaustive hypothesis property tests)
- New abstractions (ABCs, protocols, factories) when there's exactly one implementation
- Retry policy / circuit breaker / structured logging — defer to a future slice
- ADRs or architecture files — slices don't produce these
- Refactor of existing modules — separate slice or `master-architect` BACKTRACK
- Implementing the NEXT slice "since we're here"

Response template:
> That's beyond the scope of this slice. Want me to (a) defer it to a follow-up slice (I'll note it in `PROGRESS.md` under "Open for next slice"), or (b) escalate to `master-architect` if it's actually architectural?

## Escalation signals

STOP and BACKTRACK to **`master-architect`** if during the slice you discover:
- The seam can't be implemented without a missing architectural decision
- The slice depends on a component that doesn't exist yet and wasn't in scope
- The external API has fundamentally different semantics than the seam assumes (sync vs async, eventual consistency, transactional contract differences)

STOP and ESCALATE to **`master-architect`** (or pause and discuss with the owner) if during the slice you discover:
- The slice as defined is actually L complexity (5+ production files needed, excluding private helpers in the same module; 3+ domain entities; requires real DDD)
- Behaviors span multiple concern categories that need different test approaches (functional + performance + security + concurrency invariants) — that's full-feature test discipline, not slice
- The user is asking for mutation testing / structured logging / observability as part of the slice (those are full-feature concerns)

In both cases, do NOT continue the slice. Tell the user what you found and which skill to invoke. Leave the partial work as-is (or revert, user's call).

## Escalation calibration — decide, or stop?

The section above says when to leave the slice. This one says how often to interrupt the owner while staying in it. Both halves are load-bearing; a slice that stops on everything wastes the owner, and a slice that stops on nothing loses the checkpoints.

This is Constitution Article 5 at slice altitude, not a new rule: *"If reversing the decision later would be cheap, it is a two-way door → automate it."* Over-escalating is a failure to apply Article 5, not an excess of caution.

**The test.** If resolving it needs product or market context you don't have, or if being wrong would cost more than one commit to undo — stop. Otherwise decide.

### Decide alone, fold in, report in one line

- A choice local to one module that a single commit could reverse.
- A choice derivable from a precedent already recorded in this repo.
- Test-plan mechanics — fixture shape, spy vs real dependency, keeping or dropping a pass-on-arrival test — **provided the assertion set is unchanged**. Changing what a test asserts is not mechanics.
  - **"Ratified" means the OWNER has seen and approved it.** A test you authored this session and nobody has reviewed is your own draft, not ratified text. Strengthening it so that it actually tests a property its ratified *description* already claims — the usual case being a mutation that survived — is decide-alone, and doing it is not optional: a surviving mutation in a seam you are building is a hole you found and left. What stays escalate is the behavior-id set itself: adding an id, removing one, or changing what an id asserts. Both live in the slice artifact, where overseer check #11 can see them. (Added 2026-08-26 after the implementer stopped to ask permission to add one clause to a fixture it had written ten minutes earlier — see `audit.md`, edit B.)
- Anything where you would write "I lean toward X" and X follows from a rule already written down. If you can cite the rule, you are not asking a question; you are narrating.

Report it as: **"Decided X because Y; overrule if you disagree."** One line. The owner keeps the veto without spending a turn.

> **HARD CONDITION — the fold-in happens in the same turn as the implementation.**
> Deciding alone is *conditional* on this. If the record lags the decision, the project loses the stop AND the record, and is strictly worse off than before the calibration. This is the standing correction from `escalations.md` (2026-08-24T20:18:01Z): *chat ratification authorises writing the change into the artifact — it is not itself the record.* Fold in without waiting to be asked. A decision made alone and recorded next turn is a violation, not a delay.

### Escalate, without exception

No balancing test applies to these. They are not weighed against the cost of a turn.

- Any change to text **already ratified** in the slice artifact.
- Anything that changes **what the exit criterion asserts, or how it is measured**.
- Anything touching the **evidence log's integrity** — it is the slice's only proof, and a corrupted one is undetectable after the fact.
- A **falsified premise** (Article 8) — lower-level facts outrank higher-level assumptions, and the routing is the owner's.
- The slice's **hard-to-undo set**, named during planning.
- Any change to **the hooks, the overseer, or anything else that audits your own work** — Article 7. Self-modification is human-ratified and recorded in `audit.md`, in that order.
- A **verification with no available oracle**. Say so plainly when that is the situation: the mu-law reference table was the right stop, because transcription error was the live risk and a second independent derivation was the only possible check.

**How to escalate, when you do.** Lead with **one recommendation** and its one-line why; follow with the alternatives you killed and what killed each; end with a single closed question. That is how this project already records decisions — every `Q<n>` in a slice artifact carries "Rejected: X — steelman: … ; rejected because …" — and the owner is deciding whether to accept your reasoning, not doing the analysis themselves. A balanced menu reads as withholding a view you have already formed, and costs turns: on 2026-08-26 a three-option `AskUserQuestion` was rejected, then clarified, then answered with "твоя пропозиція?" — three turns to extract a held recommendation. Use `AskUserQuestion` with options only when you are genuinely indifferent; if that is often, you are under-thinking the problem.

### Why these two lists and not others

Derived from recorded signal, not preference. Across the 9 escalations logged for `voice-intake-demo`, all resolved immediately; 6 took the stated recommendation unchanged. The exceptions are the whole point: the single **reversal** (2026-08-23T16:27:00Z, clock ownership) amended ratified seam text, and the two entries where the implementer **declined to recommend at all** touched the ratified seam plus the exit criterion's measurement basis, and the creation of the first ADR directory. The classes where the owner's input actually changed the outcome are exactly the escalate list above. See `.claude/overseer/audit.md`, 2026-08-25.

This is not "escalate less." It is escalate where the record shows it changes something, and decide where the record shows it never did.

## What you DO NOT do

- Write to `.claude/architecture/` (that's `master-architect` / `feature-architect` territory)
- Create or modify `tasks.yaml`
- Run mutmut, cosmic-ray, code-reviewer subagent, security-auditor
- Generate ADRs
- Decompose into sub-tasks (that's `feature-architect`)
- Commit on the user's behalf
- Suggest folder restructures
- Write tests for OTHER slices "while we're here"
- Add logging / observability / metrics — defer to a dedicated slice

## Notes on test scope

**Default: integration tests against real external system** (test/sandbox endpoint).

Add a unit test with a fake/stub dependency ONLY if:
- The slice has non-trivial mapping/branching logic ABOVE the external call (so the unit test catches that logic without paying network cost), OR
- The external call is slow (>2s) and the TDD cycle would become painful

For thin wrappers (the typical slice), integration-only is correct. Don't introduce fakes for the sake of "proper" unit testing.

## Pydantic v2 vs dataclass — quick rule

- **Pydantic v2 `BaseModel`** → cross-boundary data (HTTP request/response bodies, external API DTOs, queue messages)
- **`@dataclass(frozen=True)`** → internal value objects, slice-local result types like `UploadResult`, `TokenIssued`

If the user's project has a different convention, follow it.

## Stop discipline

The word **STOP** in this workflow is literal. After each step that says STOP:
1. Send the user your output for that step (pytest output, draft file, etc.)
2. Wait for them to respond before doing anything else
3. Do not "helpfully" continue to the next step

Resist the urge to chain steps. Each STOP is a checkpoint where the user can redirect cheaply. Without STOPs, the slice quietly drifts away from the seam.

**Read the four subsections below before applying that literally — three of them narrow it, and a stop they have removed is not a checkpoint, it is a wasted turn.** Over-escalating is a failure to apply Constitution Article 5, not an excess of caution.

### The gate is the behavior list, not the cadence

**Once the owner has approved a behavior list for a seam (Step 3), run each behavior RED→GREEN→REFACTOR in one turn, then continue to the next behavior in that list without stopping.** Step 4's per-transition STOPs do not apply inside an approved list.

Keep writing the RED output to the transcript and keep the `=== TDD RED ===` sentinel when a turn genuinely ends red. They are read afterwards; the owner does not need to be present for them.

**Chaining is licensed *within* an approved behavior list. It is never licensed across one.** Do not invent a behavior mid-flight, do not extend the list, do not begin a seam whose list the owner has not seen. If a cycle reveals a missing behavior, Step 4 already says it: STOP and ask for the list to be amended. That boundary — not the cadence — is what prevents unreviewed judgment at speed.

Why the gate sits there: the owner's input has repeatedly changed the outcome at the behavior-list stage (Q18's `stage` field, G4's retention, Q8's reference-table provenance, Q14's exception type) and has never once changed it at a RED→GREEN transition. The GREEN→REFACTOR stop is weaker still — the suite is already green, so the refactor either holds it green or does not, visibly, in seconds. Full evidence and ratification: `.claude/overseer/audit.md`, 2026-08-25 "Stop-discipline narrowing".

### What still stops

- Everything in **Escalate, without exception** above.
- **Genuine failure, not milestones.** A test that fails for a reason its behavior did not predict; a falsified premise (Article 8); an assertion you cannot make hold as specified. Stop for surprises.
- **Not success.** Do not spend a turn reporting that a cycle went green. "It works, here's the count" is a line in the next report, not a turn.

The STOPs outside Step 4 — Step 0's scope validation, Step 1's docs report, Step 2's skeleton, Step 3's behavior-list approval, Step 5's smoke verification — are untouched **for a slice begun from a conversation**. Those are where the owner's judgment is load-bearing, because nothing upstream has captured it yet.

### When the slice arrives with a ratified planning artifact

**A slice handed to you as a PLANNING_COMPLETE artifact from `/plan-slice` has already spent the owner's judgement on Steps 0–3. Do not spend it twice.** That artifact *is* the scope decision, the seam contract and the behavior list, and it reached you through a planner-critic loop and a cold-reader pass. Re-asking "Go?" over a skeleton that transcribes its ratified field list buys nothing — the owner would be approving their own decision back to themselves.

So: read the artifact, say in one line which checkpoints it discharges, and go straight to Step 4. Step 1 is moot for a slice touching no external system; say that too, and say what you verified instead.

What this does **not** relax: the escalate list, in full. The check that matters is not the skeleton stop — on 2026-08-26 a defect in the ratified artifact (a DRAFT marker that would have been read aloud to callers) sailed straight through the Step 2 stop and was caught later, by reading the artifact against the consuming slice's contract. Reading beats ceremony. If the artifact is wrong, that is an escalation whenever you find it.

### Step 5 — split by oracle

- **A smoke you can fully execute yourself** — pure functions, local files, anything with no human-only oracle: run it, put the whole output in the transcript, and continue to Step 6. The owner reads the result; they are not a precondition for it. Asking them to re-run a command you already ran and printed is ceremony.
- **A smoke needing a human oracle** — "open the admin panel and confirm the file arrived", anything whose real effect lands in a system you cannot read back: STOP, exactly as Step 5 says. That is the case the checkpoint was written for.
