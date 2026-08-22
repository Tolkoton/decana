# Workflow: Incremental Update

Use this during ordinary development: a feature landed, a flag changed, an API
gained an argument, a command was renamed. The goal is to keep docs in lockstep
with code so they never become a liability.

The rule that governs this workflow: **a code change is not finished until its
documentation is finished, in the same change.**

## Step 1 — Classify the change

Determine what kind of change happened, because that decides what to update.
The rows are split: **mandatory** updates run on every applicable change;
**optional** updates run only when the human audience exists.

**Mandatory** (these protect the agent's working memory):

| The change... | Update |
|---|---|
| Adds/removes/renames a public function, class, CLI flag, or config key | `docs/reference/` (generated wherever possible) |
| Alters or establishes an architecturally significant decision | a new `docs/adr/NNNN-*.md` |
| Adds/removes/renames a build, test, or lint command, or a repo rule the agent must know | `AGENTS.md` |

**Optional** (only if the relevant human reader exists):

| The change... | Update |
|---|---|
| Changes observable behavior or a workflow a human user follows | `docs/how-to/` and/or `docs/explanation/` |
| Adds a feature a newcomer should be walked through | `docs/tutorials/` |
| Is user-visible *and* the project publishes a changelog | `CHANGELOG.md` under `Unreleased` |

A single change often hits several rows. A new CLI flag, for example, always
touches reference (mandatory) and may touch how-to (optional, only if there
are humans using the CLI directly).

## Step 2 — Update reference docs

For reference content, prefer **generated** over hand-written. If the project
uses mkdocstrings, Sphinx autodoc, or an OpenAPI spec, update the docstring or
the spec — the rendered reference follows automatically and cannot drift from
the signature. Only hand-write reference for things no tool can extract.

## Step 3 — Update narrative docs (only if relevant)

Narrative docs (how-to, tutorial, explanation) are optional in agent-first mode.
**Update or write them only when the human reader they target actually exists.**
If you do write them, keep each page in its single Diataxis quadrant: a
reference table inside a tutorial belongs in `docs/reference/` with a link from
the tutorial. See `references/diataxis.md`.

## Step 4 — Update the agent entry file (only if needed)

Touch `AGENTS.md` **only** when the change adds or alters something an agent
cannot infer from the code: a new command, a changed test invocation, a new repo
rule. Then:

- Update `AGENTS.md` only — never copy the same text into `docs/`.
- Check the file is still at or under 200 lines. If the addition pushes it over,
  remove something stale or move detail into a `docs/` reference and link to it.
- Phrase additions positively ("Run `uv run pytest -q` for the fast suite") not
  as prohibitions.

Most code changes do **not** need an AGENTS.md edit. If in doubt, leave it.

## Step 5 — Record the decision, if there was one

If the change embodies an architecturally significant decision — a new
dependency with lock-in, a shift in how a layer works, a new external
integration — write an ADR using `references/adr-template.md`. If it changes a
*previous* decision, do not edit the old ADR: write a new one that supersedes it.

## Step 6 — Changelog

If the project keeps a `CHANGELOG.md`, add a line under `## [Unreleased]` in the
appropriate group (`Added`, `Changed`, `Fixed`, `Removed`, `Deprecated`,
`Security`). Write it for a human reader of the release notes, not as a commit
message.

## Step 7 — Verify

1. Run `python scripts/doc_audit.py` from this skill.
2. Run `vale` and `markdownlint` if configured.
3. Fix every error. If you must disable a linter rule on a line, add a comment
   stating why — an unexplained disable is a future bug.
4. Report concisely: which files changed, which quadrant each belongs to, and
   why. Surface linter output verbatim.

## Done criteria

- Every reference row triggered in Step 1 has a matching doc update in this
  same change.
- AGENTS.md, if touched, is still at or under 200 lines and free of
  code-inferable content.
- Any decision is recorded as an ADR (new, or superseding).
- `doc_audit.py` exits clean.
