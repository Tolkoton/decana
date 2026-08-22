---
name: documentation
description: Creates, updates, and audits documentation that serves both human developers and AI coding agents. Use this skill whenever the user wants to document a project, write or update a README, AGENTS.md, or CLAUDE.md, write an Architecture Decision Record (ADR), bootstrap documentation for an existing or undocumented repository, keep docs in sync with a code change, audit documentation for staleness or drift, reorganize docs into a Diataxis structure, or asks broad questions like "what does this codebase do" or "help me onboard onto this project." Trigger it even when the user does not say the word "documentation" — any task that touches README files, doc folders, ADRs, agent-instruction files, or doc structure should use this skill. It enforces a two-tier single-source-of-truth model, Diataxis organization, lean agent entry files, and a docs-as-code workflow.
---

# Documentation

Create and maintain documentation **primarily so AI coding agents working in
the repository can do their job**. Human-readable docs are a secondary,
consistent layer over the same source — they exist where they earn their
keep, not by default. The whole point of this skill is to enforce one
consistent model where the agent gets what it needs first and humans benefit
from the same material: no duplication, no drift, no obligation to write
prose nobody is reading.

## The model

```
Layer 0  AGENTS.md  (+ CLAUDE.md -> @AGENTS.md)   agent entry: <=200 lines, pinned commands + a map
Layer 1  docs/reference/, docs/adr/                facts and "why" - mandatory
Layer 2  docstrings, generated reference           deep detail, read on demand
Layer 3  docs/tutorials/, docs/how-to/, docs/explanation/   narrative human docs - optional
Layer 4  .claude/skills/, .claude/hooks/           agent-only behavior
```

The agent entry file does **not** duplicate `docs/`. It points into it.
Layers 0-2 are the agent's working memory and must always be accurate.
Layer 3 is for human readers and is written on demand, not pre-emptively.

## Core principles

Apply these in every workflow below. They are the reason the rules exist.

- **Agent-first.** Write for the agent first; humans benefit because the same
  source serves both. When the two needs diverge, the agent's need wins.
  Narrative human docs are valuable when a human will actually read them and
  pure overhead when nobody will.
- **Single source of truth.** Each fact lives in exactly one place. AGENTS.md
  links to `docs/`; it never restates it. Duplication guarantees drift.
- **Diataxis.** Every human-facing page is exactly one of: tutorial, how-to,
  reference, explanation. Mixing types is the most common doc failure — see
  `references/diataxis.md`.
- **Co-location.** Docs live in the repo, and a doc change ships in the *same
  pull request* as the code change that caused it. Docs that lag behind code
  are worse than no docs because they actively mislead.
- **Progressive disclosure.** Keep entry files short. An agent reliably follows
  only a limited number of instructions; a 400-line AGENTS.md means it follows
  *none* of them well. Push detail into linked files read on demand.
- **Positive phrasing.** Write "Use X" not "Do NOT use Y." Models process
  negation poorly, and a wall of prohibitions drowns the signal.
- **Append-only decisions.** ADRs are never edited once accepted. To change a
  decision, write a new ADR that supersedes the old one. The history is the
  value.
- **Generated output is a draft.** `/init`, autodoc, and templates bias toward
  comprehensiveness, which is exactly wrong for an entry file. Always prune.
- **Linters are enforcement, prose is guidance.** If a rule *must* hold, put it
  in CI or a hook, not in a markdown sentence.

## Step 1 — Pick the workflow

Read the matching reference file fully before acting. Do not improvise these
workflows from memory.

| Situation | Workflow | Read |
|---|---|---|
| Repo has no docs, or only a thin README; greenfield project | **bootstrap** | `references/workflow-bootstrap.md` |
| Ordinary code change; a feature, flag, command, or API changed | **incremental** | `references/workflow-incremental.md` |
| "Are the docs still accurate?"; periodic or pre-release check | **audit** | `references/workflow-audit.md` |

If the request spans more than one (e.g. "document this repo and set up the
process"), run `bootstrap` first, then hand off to `incremental` for the
ongoing discipline.

## Step 2 — Decide where a document belongs

Before writing a single line, place it. Writing first and placing later is how
tutorials end up full of reference tables.

```
Is it a record of an architecturally significant choice + its tradeoffs?
    -> docs/adr/NNNN-title.md            (see references/adr-template.md)

Is it a build / test / lint command or a repo rule an agent must know,
and is it NOT inferable from the code itself?
    -> AGENTS.md                         (only if it earns its <=200 lines)

Otherwise it is human-facing — pick ONE Diataxis quadrant:
    Teaches a newcomer, step by step, on rails        -> docs/tutorials/
    Helps a competent user accomplish a specific task -> docs/how-to/
    States facts: API surface, options, schemas, CLI  -> docs/reference/
    Explains why / how it works / background           -> docs/explanation/
```

When unsure between two quadrants, ask: *is the reader trying to learn, or
trying to get something done?* That single question resolves most cases. Full
guidance and worked examples are in `references/diataxis.md`.

## Hard rules

These are non-negotiable. They are short on purpose — emphasis only works when
it is rare.

1. **AGENTS.md stays at or under 200 lines.** If you add a section, remove or
   relocate another. When it genuinely cannot shrink, split path-scoped rules
   into nested `AGENTS.md` files inside subdirectories.
2. **Never duplicate content between AGENTS.md and `docs/`.** AGENTS.md links
   to docs; it does not restate them.
3. **Every code change that adds, removes, or renames a flag, command, env
   var, or public symbol must update the *mandatory* docs in the same change:**
   AGENTS.md (if the change is something the agent must know), `docs/reference/`
   (if the public surface changed), and any relevant ADR (if a decision
   changed). Narrative human docs (`docs/tutorials/`, `docs/how-to/`,
   `docs/explanation/`) are updated only when a human reader actually needs
   them — they are not required by default. The change is not done until the
   mandatory docs are done.
4. **ADRs are append-only.** To revise a decision, create a new ADR with status
   `Accepted` and a line `Supersedes ADR-NNNN`; set the old ADR's status to
   `Superseded by ADR-MMMM`. Never rewrite an accepted ADR's decision.
5. **Run the linters before reporting success.** At minimum
   `python scripts/doc_audit.py` from this skill, plus `vale` and
   `markdownlint` if the repo has them configured. Report their output verbatim
   rather than summarizing it away.

## Anti-patterns — refuse or push back

If the user asks for one of these, explain the cost and offer the correct
alternative instead of complying silently.

- Auto-generating AGENTS.md / CLAUDE.md and committing it unpruned.
- Pasting every possible command into the entry file "to be safe."
- Maintaining separate, overlapping agent docs and human docs that restate each
  other — they will diverge within weeks.
- Marking many rules `IMPORTANT` / `MUST` / all-caps. Emphasis on everything is
  emphasis on nothing.
- `@`-importing whole large files into CLAUDE.md (it all loads at launch).
  Reference the specific section instead.
- Editing an already-accepted ADR in place.
- Hand-writing API reference that could be generated from docstrings or an
  OpenAPI spec — generated reference cannot lie about signatures.
- One README that is description + tutorial + reference + decisions. Split it.
- Treating "we'll document it later" as a plan. Later does not arrive.

## Reference files

Read these on demand; do not load them all up front.

- `references/workflow-bootstrap.md` — document a new or undocumented repo.
- `references/workflow-incremental.md` — update docs alongside a code change.
- `references/workflow-audit.md` — check existing docs for drift.
- `references/diataxis.md` — the four quadrants, with examples and failure modes.
- `references/agents-md-template.md` — canonical AGENTS.md / CLAUDE.md skeleton.
- `references/adr-template.md` — ADR format (MADR-style) and the status lifecycle.
- `references/style-guide.md` — voice, terminology, Markdown, and linter setup.

## Tooling

`scripts/doc_audit.py` is a stdlib-only Python 3.11+ script. It checks entry-file
line caps, Diataxis quadrant coverage, broken relative links, the ADR inventory,
and `make` targets referenced in docs that do not exist. The `audit` workflow
runs it; the other workflows run it as their final check. It needs no
dependencies and can run from anywhere inside the repo.
