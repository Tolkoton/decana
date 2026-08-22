---
name: self-learning-orchestrator
description: Orchestrates the self-learning loop across a Claude Code dev cycle — knows WHEN to read, update, or distill the project's living memory (CLAUDE.md, decisions.md, MEMORY.md files, claude-progress.md, reflections.md) and dispatches to the right sub-skill at each moment. Use this skill at session start (read prior learning), when a substantive decision is being made, when stuck for more than ~20 minutes, before any commit, at session/task end (distill lessons), and on periodic maintenance days. Also use whenever the user mentions "session start", "session end", "wrap up", "done for now", "/clear", "/bye", "stuck", "tried everything", "we picked", "going with", "trade-off", "ready to commit", "review my changes", "wrap up the task", "memory maintenance", "review CLAUDE.md", "this took forever to debug", "remember this for next time", "lesson learned", or whenever you notice a workflow moment (just opened a new session, just fixed a non-obvious bug, just completed a task) where memory should be consulted or updated. Proactively detect these moments even if the user has not explicitly asked.
---

# Self-Learning Orchestrator

Orchestrate the project's living memory across the development lifecycle. This skill is the *trigger dispatcher*: it recognizes WHICH self-learning moment is happening and routes to the right protocol. It does not duplicate the content of the per-artifact skills — it speaks their cue phrases so they activate.

## What this skill manages

A layered memory stack with deliberately different update frequencies:

| Artifact | Scope | Lifetime | Update cadence |
|---|---|---|---|
| `CLAUDE.md` | project | forever | rare, deliberate |
| `decisions.md` | project | append-only forever | per substantive decision (~weekly) |
| `.claude/architecture/MEMORY.md` | project | append-only, periodic prune | per session-end |
| `~/.claude/memory/<tech>/MEMORY.md` | global per-tech | append-only forever, periodic consolidate | per session-end |
| `claude-progress.md` | task | deleted on completion | per commit |
| `<task>/reflections.md` | task | archived on completion | per failed attempt |

Mismatching the cadence is the most common failure mode. CLAUDE.md is not a place to log every bug; MEMORY.md is not a place to record every commit. The triggers below map each moment to the correct artifact.

## The trigger state machine

```
                            ┌────────────────────────────────┐
                            │ Session start (every session)  │
                            │   → triggers/session-start.md  │
                            └────────────────────────────────┘
                                          │
                                          ▼
                            ┌────────────────────────────────┐
       ┌────── new task ───►│ Task start                     │
       │                    │   → cue plan-mode skill        │
       │                    │   → maybe create progress.md   │
       │                    └────────────────────────────────┘
       │                                  │
       │                                  ▼
       │      ┌────────────────────────────────────────────────────────┐
       │      │ Execution loop                                          │
       │      │                                                         │
       │      │  edits ──► hooks (ruff, mypy, pytest)                  │
       │      │      │                                                  │
       │      │      ├─ substantive decision?                          │
       │      │      │    → triggers/decision-checkpoint.md            │
       │      │      │                                                  │
       │      │      ├─ stuck >20 min?                                  │
       │      │      │    → triggers/stuck-protocol.md                 │
       │      │      │                                                  │
       │      │      ├─ bug fix >15 min?                                │
       │      │      │    → /lesson queue (lightweight capture)        │
       │      │      │                                                  │
       │      │      └─ ready to commit?                                │
       │      │           → triggers/pre-commit-checkpoint.md          │
       │      │                                                         │
       │      └────────────────────────────────────────────────────────┘
       │                                  │
       │                                  ▼
       │                    ┌────────────────────────────────┐
       └────── more ────────┤ Task done?                     │
              tasks         │   no → next task               │
                            │   yes → session-end-dreaming    │
                            │     → triggers/session-end.md   │
                            └────────────────────────────────┘

       ────────────────── independent cadence ──────────────────
                            ┌────────────────────────────────┐
                            │ Periodic (weekly/monthly)      │
                            │   → triggers/periodic.md       │
                            └────────────────────────────────┘
```

## How to dispatch (the only rule)

When invoked, identify which moment is happening and read the matching trigger file:

| If the moment is... | Read |
|---|---|
| New session starting / first message after `/clear` | `triggers/session-start.md` |
| About to make a real choice with alternatives | `triggers/decision-checkpoint.md` |
| Tried ≥3 approaches without progress | `triggers/stuck-protocol.md` |
| About to commit / "done with this" | `triggers/pre-commit-checkpoint.md` |
| User said "/clear", "/bye", "wrap up", or task is complete | `triggers/session-end-dreaming.md` |
| User said "/memory-maintenance" or asked for periodic review | `triggers/periodic-maintenance.md` |
| User said `/lesson "..."` | append to `.claude/lesson-queue.md`, see "Lesson capture" below |

Read **only the trigger file that applies**. Do not preload everything — each trigger has independent context needs.

## Lesson capture (lightweight, inline)

When a non-obvious bug is fixed in-flow, do not interrupt with a full ADR. Append a one-liner to the lesson queue:

```bash
# Append to .claude/lesson-queue.md (create if missing)
# Format: - YYYY-MM-DD | <task or commit ref> | <one-line lesson>
echo "- $(date +%F) | $(git log -1 --format=%h) | <lesson>" >> .claude/lesson-queue.md
```

The queue is processed at session-end-dreaming. The point of the queue is *defer the classification* (tech vs project vs noise) until you have several candidates and can see patterns.

Trigger this from:
- The user typing `/lesson "<text>"`
- Recognizing in your own work "this took longer than it should have, future-me would benefit from knowing why"

## Delegation map (cue phrases that activate other skills)

This skill stays thin by speaking phrases the per-artifact skills already match:

| Concern | Cue phrase (Claude speaks aloud in reasoning) | Skill that activates |
|---|---|---|
| Plan the task | "let me use plan-mode decomposition for this" | `plan-mode-and-task-decomposition` |
| Resume a task | "let me check claude-progress.md for resume context" | `progress-file-for-long-tasks` |
| Record a decision | "this is an ADR-worthy decision; let me apply the ADR-lite format" | `decisions-log-adr-lite` |
| Self-review before commit | "let me run the pre-commit self-review checklist" | `pre-commit-self-review-checklist` |
| Debug a stuck failure | "let me apply execution-feedback-debugging discipline here" | `execution-feedback-debugging` |
| End-of-task lesson distillation | "let me do session-dreaming for this task" | `session-dreaming` (from master-architect bundle) OR fall back to `triggers/session-end-dreaming.md` |
| Navigate before editing unfamiliar code | "let me apply codebase-navigation-strategy first" | `codebase-navigation-strategy` |

If a delegated skill is not installed, the trigger file in `triggers/` contains the fallback inline protocol — orchestrator never silently fails.

## Hard rules

1. **Always read CLAUDE.md and the relevant MEMORY.md files at session start.** Skipping this is the single largest learning leak — every subsequent decision is uninformed by prior lessons.
2. **Never write to CLAUDE.md, decisions.md, or MEMORY.md silently.** Show the user what you propose to add and where; get explicit confirmation. Memory pollution is irreversible without git archaeology.
3. **One artifact per piece of knowledge.** A specific fact lives in exactly one of: CLAUDE.md (rule), decisions.md (rationale), MEMORY.md (experience), reflections.md (per-task), code comment (per-line). Duplication causes drift. See `references/artifact-scope-decision-tree.md`.
4. **Defer non-blocking captures to the queue.** Bug fix in flow? Append to `.claude/lesson-queue.md`, do not stop to write a full ADR. Process the queue at session-end.
5. **Session-end is non-optional.** Skipping session-end-dreaming silently drops all lesson candidates accumulated during the session. If a session is ending and the queue is non-empty, process it before `/clear`.
6. **Periodic maintenance is non-optional.** Without prune, MEMORY.md and CLAUDE.md rot to the point of being ignored. Schedule weekly or monthly, treat as real work.
7. **Promotion path is one-way and rare.** A pattern in MEMORY.md may *eventually* be promoted to a Skill, but only after appearing in 3+ projects. Inverse demotion (skill → memory) never happens.

## What this skill does NOT do

- It does NOT replace `master-architect` for architectural design. Master-architect handles Phase 1–4 architectural work and writes its own `.claude/architecture/` artifacts. Self-learning-orchestrator coordinates the *cross-cutting* memory lifecycle around it.
- It does NOT replace `slice-builder` for implementation. Self-learning-orchestrator handles the memory lifecycle around implementation — ad-hoc bug fixes, refactors, exploration sessions — not the slice itself.
- It does NOT write code. It coordinates the memory layer that informs all code work.

## When to skip this skill entirely

- Throwaway scripts in `/tmp/`.
- Single-line typo fixes that need no context.
- User explicitly says "just do it, no protocol".
- Interactive REPL sessions with no commit at the end.

For everything else — every real coding session — run at minimum the session-start trigger.

## References

- `references/artifact-scope-decision-tree.md` — which artifact a given fact belongs in
- `references/lesson-classification.md` — tech vs project vs both vs discard (used in session-end-dreaming)
- `references/memory-pollution-prevention.md` — limits, anti-patterns, when to prune
- `references/promotion-paths.md` — memory → skill, lesson → ADR, draft → rule
- `checklists/session-end.md` — quick checklist before `/clear` or `/bye`

## Compatibility notes

Designed to compose with the broader project setup:
- `claude-autonomy` provides PostToolUse / Stop hooks (quality gates) — those are execution feedback, not learning artifacts; this skill is orthogonal.
- `master-architect` and `feature-architect` own architectural artifacts and may keep their own task-scoped `reflections.md`. This orchestrator handles the *between-task* and *across-task* memory; it defers when they're active.
- The 12 research-backed skills (decisions-log-adr-lite, progress-file-for-long-tasks, pre-commit-self-review-checklist, plan-mode-and-task-decomposition, execution-feedback-debugging, etc.) are the delegates this orchestrator triggers via cue phrases.
