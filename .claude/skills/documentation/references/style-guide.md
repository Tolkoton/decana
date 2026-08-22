# Style guide and linter setup

> **Scope.** This guide applies when you are actually writing human-facing
> prose — README, tutorials, how-to, explanation pages. Agent-facing files
> (AGENTS.md, ADR Decision/Consequences) follow the same voice rules but are
> terser and more imperative; the linter setup applies to both.

A style guide that no linter enforces is decoration. This file gives a small set
of writing conventions and the minimal automated checks that keep them honest.

## Voice and wording

- **Address the reader directly.** "You configure..." not "The user configures..."
- **Match voice to the Diataxis quadrant.** Tutorials: "we", encouraging.
  How-to: imperative. Reference: neutral and factual. Explanation: discursive.
- **Active voice, present tense.** "The parser reads the file" not "The file is
  read by the parser."
- **One idea per sentence.** Short sentences survive translation and skimming.
- **Define an acronym on first use** in each document, then use it freely.
- **Be concrete.** "Runs in about 30 seconds" beats "runs quickly."
- **Do not document the obvious.** If the code or a screenshot already says it,
  the prose does not need to.

## Terminology consistency

Pick one term per concept and never alternate. Decide up front, for the project:
`directory` vs `folder`, `sign in` vs `log in`, the exact casing of product and
component names. Inconsistent terms make a reader wonder if two things differ.
Keep the chosen terms in the project's Vale vocabulary so the linter enforces
them.

## Markdown conventions

- One `#` H1 per file, as the first line.
- Sentence-case headings ("Running the tests", not "Running The Tests").
- Fenced code blocks always carry a language tag (` ```python `, ` ```bash `).
- Relative links between docs use repo-relative paths so they survive moves.
- Prefer real Markdown tables and lists over ASCII-art alternatives.
- Keep line length reasonable for diff review; do not hard-wrap inside
  sentences if the team's linter config disables the line-length rule — be
  consistent with the repo's `.markdownlint.json`.

## Code samples

- Every sample must run as shown. Untested samples rot fastest.
- Show the command **and** its expected output when the output matters.
- Pin versions in tutorials; a tutorial that breaks on a new release is broken.
- Prefer copy-pasteable blocks: no leading `$` if the reader would copy the `$`.

## Linter setup

Two linters cover most of the value. Add them in `bootstrap` and run them in CI.

### markdownlint — structure

`.markdownlint.json` at the repo root:

```json
{
  "default": true,
  "MD013": false,
  "MD033": false,
  "MD041": true
}
```

`MD013` (line length) is usually disabled for prose repos; `MD033` (inline HTML)
is often needed for docs sites. Adjust to the team's preference, but commit the
config so the rule set is shared.

### Vale — prose and terminology

`.vale.ini` at the repo root:

```ini
StylesPath = .vale/styles
MinAlertLevel = warning

Packages = write-good

[*.md]
BasedOnStyles = Vale, write-good
```

Start with `write-good`; graduate to the Microsoft or Google style package once
the team agrees. Put project-specific terms (product names, the chosen
terminology) in a Vale vocabulary so misuses are flagged automatically.

### Keep the linter credible

If a linter produces a flood of warnings on every change, contributors learn to
ignore it and it stops working. When that happens, relax rules or downgrade
severity from error to warning until the signal is trustworthy again. A linter
people respect is worth more than a strict one people route around.

## CI

A single workflow, triggered on changes to `docs/**`, `*.md`, the dependency
manifest, or source, should run: `vale`, `markdownlint`, a broken-link check,
the docs build (if there is a docs site), and `doc_audit.py` from this skill.
Designated rules block the merge — docs failures get the same severity as a
failing test for those rules.
