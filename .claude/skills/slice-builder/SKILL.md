---
name: slice-builder
description: Build ONE isolated testable logical piece (a "thin slice") of a larger system using strict per-test TDD (RED→GREEN→REFACTOR), paranoid-SRP (one method = one responsibility; multi-responsibility logic becomes a flow method orchestrating helpers), seam-first design, and dependency injection. Use this skill WHENEVER the user asks to "implement a small piece", "add a thin slice", "build the upload module", "build piece N of the pipeline", "wrap this API in a clean function", or otherwise wants controlled incremental progress on a known integration without architecture overhead. Output is one production module + integration tests derived from the method's distinct behaviors + one manual smoke script + a PROGRESS.md entry. STOPS at every TDD transition. DO NOT use for greenfield architecture (→ master-architect), splitting oversized multi-file features (→ feature-architect), unknown-API exploration (→ spike, no skill), or single-file edits (→ user edits directly).
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
- **RED**: Write ONE test for Bn. Run pytest. Show failing output. **STOP.**
- **GREEN**: Minimal implementation to make Bn pass without breaking earlier behaviors. Run pytest (full slice suite). Show all green. **STOP.**
- **REFACTOR**: Clean. If SRP rule 4 says a flow needs splitting into helpers — do it here. Run pytest. Still green. **STOP.**

Do NOT advance to Bn+1 until Bn is green AND refactored AND the user has seen the output. Resist chaining.

If during a cycle you discover a behavior was missing from the list, STOP and ask the user to amend the list — don't sneak it in.

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
