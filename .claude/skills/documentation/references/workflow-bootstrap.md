# Workflow: Bootstrap

Use this when a repository has no documentation, or only a thin README, and you
need to stand up the full dual-audience structure from scratch.

The bias of this workflow is **minimal and correct over comprehensive and
stale**. A small set of accurate, well-placed docs beats a large auto-generated
set that nobody trusts.

## Phase 1 — Discovery (read-only)

Do not write anything yet. Inspect the repo and build a mental model.

- Detect the language and version from `pyproject.toml`, `package.json`,
  `go.mod`, etc.
- Detect the package manager and lockfile (`uv.lock`, `poetry.lock`,
  `package-lock.json`, `pnpm-lock.yaml`).
- Detect the test framework and how tests are invoked.
- Detect the build / lint / format commands. Look in `pyproject.toml`,
  `Makefile`, `justfile`, CI workflow files, and existing scripts.
- Identify entry points, top-level packages, and the rough module map.
- Note required environment variables and external services.
- Look for an existing `.env.example`, CI config, and any partial docs.

## Phase 2 — Confirm the stack

Surface what Phase 1 found and **ask the human to confirm** before generating
anything. Do not silently commit a structure built on a wrong guess. Present it
compactly:

```
Detected: Python 3.12, uv, pytest, ruff. Entry point: src/<pkg>/__main__.py.
External: <service> API. Env vars: <LIST>. No docs/ folder, README is 12 lines.
Proposed: AGENTS.md + CLAUDE.md + docs/ (4 Diataxis folders) + docs/adr/.
Confirm or correct?
```

## Phase 3 — Generate the skeleton

Once confirmed, create the **mandatory** structure first. Use the templates in
this skill. Each file should be lean — bias toward minimal-and-correct, not
comprehensive-and-stale.

```
README.md             # short: what / why / quickstart / links into AGENTS.md and docs/
AGENTS.md             # from references/agents-md-template.md, <=200 lines
CLAUDE.md             # one line: @AGENTS.md  (+ Claude-only overrides if any)
docs/
  index.md            # one-paragraph map of what is in docs/ (one line is fine)
  reference/          # API / CLI / config — generate from docstrings where possible
  adr/
    0001-record-architecture-decisions.md
```

Create the **optional** files and folders only when they have a clear near-term
reader. Do not pre-create empty narrative folders just because Diataxis has
four quadrants — empty folders are noise.

```
CONTRIBUTING.md          # only if external contributors are expected
CHANGELOG.md             # only if you cut releases
docs/tutorials/          # only when onboarding a human newcomer is a real goal
docs/how-to/             # only when you have human users solving recurring tasks
docs/explanation/        # only when architectural narrative exceeds what fits in ADRs
```

Keep each generated file lean. AGENTS.md should contain only commands and rules
an agent cannot infer from the code — see `references/agents-md-template.md` for
the include/exclude split.

## Phase 4 — Seed ADRs retroactively

A new repo still has a decision history; capture the load-bearing ones so future
readers (human and agent) understand the *why*.

1. Write `0001-record-architecture-decisions.md` — the meta-ADR in which the
   project adopts ADRs. (The template in `references/adr-template.md` includes
   this one ready to use.)
2. For each architecturally significant choice you can detect — framework,
   persistence layer, auth approach, package manager, API integration strategy
   — draft an ADR with status `Accepted` and a note `(retroactive)`.
3. Keep retroactive ADRs short. Context, Decision, Consequences. Do not invent
   alternatives that were never actually considered; say "rationale
   reconstructed retroactively" where the original reasoning is unknown.
4. **A human reviews each retroactive ADR before commit.** You are reconstructing
   history, not inventing it.

## Phase 5 — Wire the safety net

- Add `.vale.ini` and `.markdownlint.json` (see `references/style-guide.md`).
- Add or extend a CI job that runs `vale`, `markdownlint`, a broken-link check,
  and the docs build on any change touching `docs/**`, `*.md`, the dependency
  manifest, or source.
- If the project uses a docs site, prefer MkDocs + Material + mkdocstrings for
  Python projects (Markdown-native, low setup). Sphinx is the choice only for
  large libraries needing reST and intersphinx.

## Phase 6 — Verify and hand off

1. Run `python scripts/doc_audit.py` from this skill. Fix every error.
2. Run `vale` and `markdownlint` if configured. Fix violations; never disable a
   rule inline without a comment explaining why.
3. Report what was created, where, and what the human still needs to fill in
   (tutorials and explanation pages usually need human input — leave clear
   `TODO` stubs with a one-line scope note rather than fabricating content).
4. Point the user at `references/workflow-incremental.md` for keeping it alive.

## Done criteria

- AGENTS.md exists, is at or under 200 lines, and contains no content inferable
  from code.
- CLAUDE.md exists and imports AGENTS.md rather than duplicating it.
- `docs/` has an `index.md`, a `reference/` folder (even if generated reference
  is the only content), and `adr/`.
- `docs/adr/0001` exists; load-bearing decisions have draft ADRs awaiting human
  review.
- Narrative folders (`tutorials/`, `how-to/`, `explanation/`) exist only if
  there is a near-term human reader for them. Empty placeholders are not
  created.
- `doc_audit.py` exits clean.
