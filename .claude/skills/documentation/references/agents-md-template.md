# Agent entry file: AGENTS.md + CLAUDE.md

The agent entry file is a **behavioral contract**, not documentation. It tells a
coding agent the things it cannot infer from the code and would otherwise get
wrong. It is read at the start of every session, so every line competes for the
agent's limited instruction-following budget.

## Two files, one source of truth

- **AGENTS.md** — the cross-tool open standard, at the repo root. This is the
  real content.
- **CLAUDE.md** — Claude Code's project-memory file. Make it a single import so
  it never diverges:

  ```markdown
  @AGENTS.md
  ```

  Add Claude-specific lines below the import only when genuinely needed (e.g.
  "When editing `src/billing/`, use plan mode first"). If there are none, the
  one-line import is the whole file.

- Tool-specific files (`.cursorrules`, `.github/copilot-instructions.md`) should
  **symlink** to `AGENTS.md` rather than hold their own copy.

- In a monorepo, place nested `AGENTS.md` files in subdirectories; a nested file
  overrides the root for work in that subtree.

## The 200-line cap

Keep AGENTS.md at or under 200 lines. This is not stylistic. An agent follows a
bounded number of instructions reliably, and quality degrades *uniformly* as the
count grows — extra instructions do not get appended at lower priority, they
dilute *all* of them. The session harness already spends much of that budget.
A bloated entry file means the agent half-follows everything.

When it cannot shrink: split path-scoped rules into nested `AGENTS.md` files,
and move any explanatory detail into `docs/` with a link.

## What goes in — and what stays out

| Include | Exclude |
|---|---|
| Exact build / test / lint commands the agent cannot guess | Anything readable from the code itself |
| Code-style rules that differ from language defaults | Standard language conventions |
| How to run the tests; the preferred test invocations | Detailed API docs — link to `docs/reference/` |
| Repo etiquette: branch naming, commit format, PR rules | Information that changes frequently |
| Project-specific architectural constraints | Long tutorials or explanations |
| Dev-environment quirks; required env vars | File-by-file descriptions of the tree |
| Non-obvious gotchas and footguns | Self-evident advice ("write clean code") |

## Writing rules

- **Positive, not prohibitive.** "Use `uv run pytest`" beats "Do NOT use bare
  pytest." Reserve the few real prohibitions for genuine footguns.
- **Emphasis is rationed.** All-caps / `IMPORTANT` / `MUST` on at most one or
  two truly critical lines. Mark everything and you mark nothing.
- **Put the most-violated rules at the top and the bottom.** Models weight the
  start and end of a file most heavily.
- **No `@`-imports of large files.** They load in full at launch. Link to the
  specific section instead.
- **It is a map, not a manual.** Point into `docs/`; do not restate it.

## Canonical skeleton

```markdown
# <Project Name>

<One or two sentences: what this project is and does.>

## Commands
- Install:  <exact command>
- Test:     <exact command>           # e.g. uv run pytest -q
- Lint:     <exact command>
- Format:   <exact command>
- Run:      <exact command>

## Project layout
- `src/<pkg>/`  — <one line>
- `tests/`      — <one line>
- `docs/`       — human + agent docs; see docs/index.md
- `docs/adr/`   — architecture decisions

## Conventions
- <code-style rule that differs from the language default>
- <commit / branch / PR convention>
- <preferred test invocation, fixtures location, etc.>

## Environment
- Required env vars: <LIST> — see `.env.example`
- <any dev-environment quirk an agent would trip over>

## Gotchas
- <non-obvious behavior or footgun, stated positively>

## Where to look
- API reference: docs/reference/
- How-to guides: docs/how-to/
- Why things are the way they are: docs/explanation/ and docs/adr/
```

Trim every section to what is true and non-inferable for this specific repo.
Empty sections should be deleted, not left as headers.

References: https://agents.md/ and Claude Code memory documentation.
