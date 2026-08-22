# Agents guide — Decana

> Copy this file into your project root, then fill in the sections below.
> Remove this instruction line when done.

## Project in one sentence

<What this project does.>

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

## Domain context

<One paragraph on what this project does and its key constraints.>

## Key paths

| Path | What it is |
|---|---|
| `<source-dir>/` | Main source code |
| `tests/` | Test suite |
