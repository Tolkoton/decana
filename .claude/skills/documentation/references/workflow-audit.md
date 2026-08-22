# Workflow: Audit

Use this when asked whether the docs are still accurate — periodically, before a
release, or after a stretch of fast development. The output of an audit is a
**remediation plan**, not a pile of silent edits. Surface findings; let a human
decide what to fix and in what order.

## Step 1 — Run the automated check first

```
python scripts/doc_audit.py
```

This is fast and deterministic. It reports entry-file line caps, Diataxis
quadrant coverage, broken relative links, the ADR inventory, and `make` targets
referenced in docs that do not exist. Capture its full output; it anchors the
rest of the audit.

## Step 2 — Verify commands and environment

Automated link-checking does not catch a command that is *valid Markdown* but
*wrong*. Check by hand:

- For every command shown in `docs/` and `AGENTS.md`, confirm it still exists:
  cross-check against `pyproject.toml` (`[project.scripts]`), the `Makefile` or
  `justfile`, and the CI workflow files.
- For every environment variable named in docs, confirm it still appears in
  `.env.example` and is still read by the code.
- For version numbers and pinned dependencies mentioned in prose, confirm they
  match the manifest.

## Step 3 — Check reference docs against the code

Reference docs make precise factual claims, so they drift hardest.

- Diff `docs/reference/` against the current public API. Use language tooling
  (import the module, inspect signatures; or diff the generated reference)
  rather than eyeballing — do not rely on inference for signatures.
- Flag any documented symbol that no longer exists, and any public symbol with
  no reference entry.

## Step 4 — Check ADRs against reality

- List every ADR with status `Accepted`.
- For each, check whether the current code still reflects that decision.
- Where code contradicts an accepted ADR, **flag it for human review** — do not
  auto-supersede. Either the code drifted from the decision (a bug) or the
  decision changed without an ADR (a missing ADR). A human must say which.

## Step 5 — Check Diataxis hygiene (only if narrative docs exist)

Skip this step entirely if the project has no `tutorials/`, `how-to/`, or
`explanation/` folders — that is a valid agent-first configuration, not a gap.
If narrative folders do exist:

- Scan for pages that mix quadrants: a tutorial padded with reference tables, a
  reference page that editorializes, a how-to that teaches concepts.
- Scan for orphan pages not linked from `docs/index.md` or any navigation.
- Note empty or near-empty quadrant folders — they are candidates for removal,
  not for filling with placeholder content.

## Step 6 — Check freshness signals

- `git log` the docs: pages untouched for a long time while their subject code
  changed recently are suspect. List them; do not assume they are wrong.
- Screenshots and diagrams: flag any that may no longer match the UI.
- `TODO` / `FIXME` / `TBD` markers left in docs.

## Step 7 — Produce the remediation plan

Write a single ordered report. Do not edit docs in this workflow.

```
## Documentation audit — <date>

### Errors (block release)
- <file:line> — <what is wrong> — <suggested fix>

### Warnings (fix soon)
- ...

### Drift flagged for human decision
- ADR-00NN appears contradicted by <file> — code drifted, or ADR is stale?

### Stale candidates (verify, may be fine)
- ...
```

Order findings by severity. For each, give the location and a concrete
suggested fix. Once the human approves, hand the actual fixing to
`references/workflow-incremental.md`.

## Done criteria

- `doc_audit.py` output is captured and triaged.
- Commands, env vars, and reference docs have been checked against the code.
- Every accepted ADR has been checked against current reality.
- A single ordered remediation report exists, with no silent edits made.
