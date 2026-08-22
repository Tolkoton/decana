# Diataxis: the four quadrants

> **Agent-first note.** In this skill's model, `docs/reference/` and
> `docs/adr/` (the append-only "why") carry most of the weight because they
> capture facts and decisions an agent cannot reconstruct from code. Tutorials,
> how-to guides, and the broader explanation quadrant are valuable but
> **optional** — write them when a human reader actually exists. The framework
> below tells you *where* any given piece of content belongs; it does not
> oblige you to fill every quadrant.

Every human-facing documentation page belongs to exactly **one** of four types.
The framework's core insight: documentation fails most often not from missing
content but from *mixing types* on one page. A tutorial derailed by reference
detail teaches badly; reference prose that editorializes informs badly.

Place a page before writing it. The decisive question:

> Is the reader trying to **learn**, or trying to **do**?
> Does the page serve their **practical** need, or their need to **understand**?

```
                practical                       theoretical
            +-----------------------+-----------------------+
  learning  |      TUTORIALS        |     EXPLANATION       |
            |  learning-oriented    |  understanding-orient.|
            +-----------------------+-----------------------+
  doing     |     HOW-TO GUIDES     |      REFERENCE        |
            |   task-oriented       |  information-oriented |
            +-----------------------+-----------------------+
```

## Tutorials — learning-oriented

A lesson. Takes a beginner by the hand through a series of steps to a meaningful
result. The reader learns by doing; the author is responsible for what happens.

- **Audience:** newcomer with no prior context.
- **Voice:** "we", encouraging, concrete.
- **Rules:** every step must work, every time, in order. No choices, no
  digressions, no alternatives. Pin versions. Minimize explanation — a sentence
  of "why" is fine, a paragraph is a derailment.
- **Lives in:** `docs/tutorials/`.
- **Test:** could a nervous newcomer follow this start to finish and succeed?

## How-to guides — task-oriented

A recipe. Directs a competent user through the steps to solve a specific
real-world problem. Assumes skill; the reader already knows the basics.

- **Audience:** a user who knows what they want and needs the steps.
- **Voice:** imperative — "Configure X", "Run Y".
- **Rules:** focus on the goal. It is fine to offer alternatives and to assume
  knowledge. Do not teach fundamentals; link to a tutorial for that. Title
  starts with "How to...".
- **Lives in:** `docs/how-to/`.
- **Test:** does this solve one concrete problem for someone who already knows
  the tool exists?

## Reference — information-oriented

A description. States facts about the machinery: APIs, options, CLI flags,
config keys, schemas. Dry, neutral, complete, accurate.

- **Audience:** a working user who needs to look up an exact fact.
- **Voice:** neutral, factual, consistent structure. No opinions, no
  instruction, no narrative.
- **Rules:** mirror the structure of the code. Be exhaustive within scope.
  **Generate it** from docstrings or an OpenAPI spec wherever possible —
  generated reference cannot lie about a signature.
- **Lives in:** `docs/reference/`.
- **Test:** can a user trust every fact here without running the code?

## Explanation — understanding-oriented

A discussion. Clarifies and illuminates: why the system is built this way, what
the alternatives were, how the pieces relate, the history and constraints.

- **Audience:** someone studying the project, not in the middle of a task.
- **Voice:** discursive, reflective, free to weigh tradeoffs and admit
  uncertainty.
- **Rules:** make connections, give context, discuss the "why". Do not give
  step-by-step instructions and do not document the API surface.
- **Lives in:** `docs/explanation/`.
- **Note:** ADRs are a specialized, append-only kind of explanation — they live
  in `docs/adr/`, not `docs/explanation/`.

## Common failure modes

| Symptom | What went wrong | Fix |
|---|---|---|
| Tutorial bloated with every option and edge case | reference content inside a tutorial | move the table to `docs/reference/`, link to it |
| Reference page that argues for an approach | explanation content inside reference | move the rationale to explanation or an ADR |
| How-to that spends half its length teaching basics | tutorial content inside a how-to | link to the tutorial; assume competence |
| Explanation with numbered "do this" steps | how-to content inside explanation | extract the procedure to `docs/how-to/` |
| One giant README doing all four jobs | no separation at all | split into the four quadrants; README becomes a map |

## Practical adoption

Do not reorganize an entire doc set into four quadrants in one sweep — that
reliably stalls. Improve one page at a time: when you touch a page, place it
correctly and split out anything that belongs elsewhere. The structure emerges.

Reference: https://diataxis.fr/
