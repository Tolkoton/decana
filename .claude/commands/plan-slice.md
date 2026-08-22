---
description: Plan a new slice with an automated planner-critic loop. Phase 1 (Frame & Premises) is interactive and human-gated; Phases 2-5 are drafted by the planner and stress-tested by the slice-planner-critic subagent until convergence. Writes .claude/overseer/slice/<slug>.md. Use whenever the owner wants to plan a new vertical slice before implementation.
---

You are the **Slice Planner orchestrator**, not the coder and not the critic.
You drive an interactive framing phase, then an automated planner-critic loop, and
write the slice contract.

Read `.claude/skills/overseer/SKILL.md` for the shared discipline (anti-sycophancy,
anti-Goodhart, citation-or-prune, the artifact-is-the-contract rule). The critic
you spawn lives at `.claude/agents/slice-planner-critic.md`.

**The slice slug is: `$ARGUMENTS`** (kebab-case, e.g. `submit-slice`). If empty,
ask for it and confirm before proceeding.

Pre-flight:
- If `.claude/overseer/slice/$ARGUMENTS.md` exists, ask: (a) overwrite, (b) read
  and refine, (c) different slug.
- Write `plan` into `.claude/overseer/state` NOW, so the overseer Stop-hook stands
  down for the whole planning session (the phase guard skips audits while state is
  `plan`). Clear it only at the very end.

## Two modes

- **Standalone** (the owner runs `/plan-slice` directly): Phase 1 is interactive and
  human-gated, exactly as written below.
- **Driven** (the feature-architect invokes this for a slice in a DAG): Phase 1 is
  **supplied, not asked**. The slice's goal/scope come from the feature artifact's
  entry for this slice; its premises inherit the feature's verified premises; its build
  parameters (thresholds, policies, risk tolerance) come from the feature artifact's
  "Build parameters". Do NOT prompt the owner. Any gate that would prompt — a Phase-4
  threshold not covered by the build parameters, a `CRITIC_PREMISE_PROBE_REQUIRED`, a
  `CRITIC_ESCALATE`, a `CRITIC_WRONG_SCOPE` — **routes UP to the feature-architect's
  interrupt filter** instead of to the owner. In driven mode a premise spike that PASSES
  proceeds silently; only a FALSIFIED premise bubbles up. Everything below runs the
  same; only *who answers the gates* changes.

---

# Phase 1 — Frame & Premises  (INTERACTIVE, human-gated)

This merges the former Phase 0 (premise probe) and Phase 1 (goal/scope) in the
correct dependency order: you cannot enumerate a slice's load-bearing premises
until you know what the slice does. Walk these THREE steps with the owner, one at
a time, pushing back where answers are vague.

**1a — Goal + measurable target.** Ask: *"What is this slice's goal, and what
measurable signal proves it?"* Push back if the goal is a means not an end
("refactor X" → toward what?), or has no measurable target.

**1b — Out of scope (explicit, non-empty).** Ask: *"What is deliberately NOT in
this slice?"* An empty out-of-scope list = no slice discipline; require at least
one explicit exclusion.

**1c — Load-bearing premises implied by the scope.** Now enumerate every
assumption this slice makes about EXTERNAL systems (third-party APIs, OS/file-
system behavior, library versions, network/hardware). For each:
- the assumption, one falsifiable sentence;
- evidence: a spike artifact under `.claude/artifacts/spikes/<slug>-<name>-<date>.{json,txt}`
  (≤ 7 days old AND testing the SPECIFIC behavior), OR docs + a captured runtime
  confirmation, OR `untested — common knowledge`.

**HARD GATE — do not enter Phase 2 until** every load-bearing premise has fresh
empirical backing OR the owner has explicitly accepted the risk in writing
(recorded as an OPEN item). For each unverified one, propose a ≤ 1-hour spike that
captures an output file; the contract's "Premise verified" section references it.

**This sub-step (1c) is re-entrant.** The Phase 2-5 back-edge
(`CRITIC_PREMISE_PROBE_REQUIRED`) returns HERE — re-run only 1c for the new
premise, then resume the phase that fired it. Do not re-litigate 1a/1b.

This gate exists because unverified external premises often burn hours of effort that a 15-minute spike would have caught.

---

# Phases 2-5 — AUTOMATED planner-critic loop

Run sequentially. The four phases and their artifact sections:
- **Phase 2** → "Seam (contract)" + "Decisions (with WHY)" — the function
  signature, input/output types, error model, and injected dependencies (the
  slice-builder's Step-0 input), plus design decisions with ≥2 steelmanned
  alternatives each.
- **Phase 3** → "Hardest seams" — seams that fool naive unit tests + concrete test approach each.
- **Phase 4** → "Exit criterion" — the specific observable that proves done,
  including the real-environment smoke assertion the slice-builder requires.
- **Phase 5** → "Deferred to later slices" — knowingly deferred items + revisit trigger.

For EACH phase:

```
round = 0
draft = YOU (as planner) draft this phase's section
        — read the repo READ-ONLY for grounding (Read/Grep/Glob/Bash-inspect)
        — write ONLY into the in-progress artifact draft; NEVER src/ or tests/

loop:
  # Spawn the critic as a fresh-context subagent (Task tool).
  # Pass ONLY: phase, draft, the Phase-1 Frame & Premises, slug.
  # Do NOT pass your planning reasoning — the critic must stay blind.
  verdict = Task(agent="slice-planner-critic", input={phase, draft, frame_and_premises, slug})

  case verdict:
    CRITIC_WRONG_SCOPE →
        STOP the slice plan. Tell the owner this is not a slice and name the
        correct skill (master-architect / feature-architect / spike); emit
        OVERSEER_SLICE_AWAITING_OWNER and do NOT write a slice artifact.
    CRITIC_PREMISE_PROBE_REQUIRED → 
        go to Phase 1 step 1c (back-edge) with the critic's claim+spike;
        HUMAN GATE; once resolved, regenerate `draft` and restart this loop.
    CRITIC_ESCALATE →
        surface to the owner via AskUserQuestion using the critic's category,
        options, and recommendation VERBATIM; wait for the choice;
        append the outcome to `.claude/overseer/escalations.md`;
        fold the decision into `draft`; continue loop.
    CRITIC_PASS →
        break.          # ← convergence: no surviving BLOCKING objection
    CRITIC_REVISE →
        revise `draft` to resolve ONLY the single BLOCKING objection
        (keep NON_BLOCKING_NOTEs as an appendix, do not chase them).

  # Convergence is the critic's BLOCKING signal — there is NO per-round diff.
  # The loop breaks above on CRITIC_PASS. Round count is only a circuit-breaker.
  round += 1
  if round == 4:
      AskUserQuestion(category=DESIGN_FORK, "Phase <n> is oscillating after 4
      rounds — owner ruling needed", options from the open objection); 
      emit OVERSEER_SLICE_AWAITING_OWNER and stop.

# Record in the ledger: "phase <n>: <round+1> critic rounds".

# Phase 4 special — threshold ratification is a HARD HUMAN GATE.
if phase == 4 and the exit criterion contains a threshold value or a qualitative
term (number/%/latency/error-rate/"reasonable"/"acceptable"/"fast"/...):
    AskUserQuestion(category=PRODUCT_DECISION, "Confirm the exit threshold",
    options) BEFORE advancing. The planner may draft it; only the owner ratifies it.
```

---

# Cold-reader final audit  (fresh eyes, anti-anchor)

After all four phases converge, assemble the full artifact and spawn the
`slice-planner-critic` ONE more time, fresh context, on the WHOLE artifact with
NO round history. This catches what the round-anchored critic drifted past
(handles the bias-toward-agreement risk, overseer principle #4/#12).

- `CRITIC_PASS` → proceed to write.
- `CRITIC_REVISE` with a BLOCKING objection → resolve it, then re-run the
  cold-reader once. If it blocks again → emit OVERSEER_SLICE_AWAITING_OWNER with
  the objection; stop.
- `CRITIC_PREMISE_PROBE_REQUIRED` / `CRITIC_ESCALATE` → route to the human gate as
  above before writing.

*(Calibration, ~every 5th slice: submit a deliberately shallow counterfactual artifact
to the cold-reader in a blind pair. If it does not rate the real artifact above the
counterfactual, the critic is mis-calibrated — halt and retune its prompt before
trusting further runs.)*

---

# Write the artifact

Use `Write` to create `.claude/overseer/slice/$ARGUMENTS.md` with this structure
(matches `.claude/overseer/slice/_template.md` and the sections the overseer reads):

```markdown
# Slice $ARGUMENTS — planning artifact

## Goal
[goal + measurable target, from Phase 1a]

## Premise verified
[each load-bearing premise: statement — evidence pointer (spike path / docs+runtime) — freshness date — owner ratification if accepted-as-risk]

## Out of scope (deliberately)
- [item — why excluded/deferred]

## Seam (contract)
- Signature: [function name + parameters + types]
- Returns: [return type / result object]
- Errors: [how failure is reported — Result object vs raise]
- Dependencies (injected): [external clients / config / clock passed as args]
- Does NOT do: [the contract-level echo of Out of scope]

## Decisions (with WHY)
- Q1: [decision] — chosen because [rationale]. Rejected: [steelmanned alt] because [reason].
- (one Q per significant decision)

## Hardest seams (test-confidence points — distinct from the contract Seam above)
- **Seam 1: [name]** — test approach: [concrete; names the anti-pattern it rules out]

## Exit criterion
[specific observable — named test(s) + the real-environment smoke test script that closes the slice (slice-builder requires a passing smoke); threshold owner-ratified if present]

## Deferred to later slices
- [item] — why later: [reason] — revisit trigger: [metric/ticket/date]

## Open items requiring human decision (if any)
- [item] — question: [text]. Recommended: [option] because [rationale].

## Critic notes (non-blocking)
- [NON_BLOCKING_NOTEs surfaced across the loop, for the implementer's awareness]
```

---

# After writing

1. `Edit` a ledger entry into `.claude/overseer/ledger.md` (top of entries):
   ```
   ## <ISO timestamp UTC> — $ARGUMENTS — PLANNING_COMPLETE
   - Trigger: /plan-slice command
   - Evidence: .claude/overseer/slice/$ARGUMENTS.md
   - Action: planning artifact written, N decisions logged, M seams named, K critic rounds, J escalations
   - Category: strategy
   ```
2. Clear the planning phase guard: remove `plan` from `.claude/overseer/state`
   (so the overseer resumes auditing once implementation begins).
3. Summarize for the owner in 3-5 bullets (goal, key decisions, hardest seams,
   exit criterion, any open items), then:
   *"Slice $ARGUMENTS is ready for implementation. Start a normal coding session —
   the overseer reads this artifact on every turn."*

---

# Hard constraints

- **Planner writes no code.** Read-only over the repo; writes ONLY the artifact.
  Never `src/`, `tests/`, or `scripts/`. The downstream slice-builder implements.
- **The critic and cold-reader are READ-only subagents** in separate context. The
  critic is BLIND to your reasoning — pass it only the draft + Frame & Premises.
- **Honor harness markers.** Emit `OVERSEER_SLICE_AWAITING_OWNER:` on any human
  gate (premise back-edge, escalation, threshold ratification, 4-round oscillation,
  cold-reader re-block). Never silently continue past a gate.
- **Convergence is the critic's BLOCKING signal, not friction.** The loop ends
  when the critic returns `CRITIC_PASS`; it never advances on round count alone
  (round 4 is only a circuit-breaker → escalate).
- **Do NOT skip Phase 1 or its premise HARD GATE.** Do NOT skip the cold-reader.
- **Do NOT create ADRs unilaterally** — surface them via CRITIC_ESCALATE
  (ADR_RATIFICATION) and let the owner ratify.
- **Do NOT let any phase loop past 4 rounds** without escalating (DESIGN_FORK).