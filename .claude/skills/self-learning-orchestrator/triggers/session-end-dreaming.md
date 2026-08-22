# Trigger: Session-End Dreaming

The session or task is ending. This is the trigger where lesson candidates accumulated during the session get *classified*, *written* to the right memory file, and *committed* — turning ephemeral experience into durable knowledge. Skipping this silently drops everything you learned.

## When this fires

Strong signals:
- User says "wrap up", "done for now", "let's end here", "good for today".
- User types `/clear`, `/bye`, `/wrap-up`.
- Task or slice reaches DONE state.
- Sustained idle period (>2h) followed by an end-conversation cue.

Weak signals (defer to user confirmation):
- A commit appears to close the in-progress task per progress.md.
- All items in claude-progress.md "What's left" are marked done.
- The user's response feels like a sign-off ("thanks, that's great", "perfect, ship it").

When in doubt: ask the user "Are we wrapping up this task? If so I'd like to do session-end-dreaming before you `/clear`." Wait for confirmation.

## Procedure (4 phases)

### Phase 1 — Gather candidates

```
Read claude-progress.md
Read .claude/architecture/tasks/<active-task>/reflections.md 2>/dev/null
Read .claude/lesson-queue.md 2>/dev/null
```

The three input sources, in order:
- **Lesson queue**: one-liners captured in-flow during the session.
- **Reflections**: failure notes per task (if `reflections.md` was kept during the task).
- **Progress notes**: anything in the progress file that smells like a lesson but wasn't queued.

Compile a candidate list. Each candidate is one observation that *might* be a lesson.

### Phase 2 — Classify each candidate

This is the core skill of session-end-dreaming. See `references/lesson-classification.md` for the full decision tree. The short version:

For each candidate, ask in order:

1. **Is this generic / obvious?** ("Pydantic is great", "tests are important"). → **DISCARD**. Don't pollute memory.

2. **Is this project-specific tactical?** ("the dunning service uses raw text() because of legacy schema"). → **PROJECT-SCOPE** memory: append to `.claude/architecture/MEMORY.md`.

3. **Is this a tech/library quirk that would bite in any project using the same stack?** ("argon2-cffi's verify raises VerifyMismatchError, not returns False"). → **TECH-SCOPE** memory: append to `~/.claude/memory/<tech>/MEMORY.md`.

4. **Could it be both?** ("PyJWT version-pinning matters because v2.x changed the API"). → **BOTH**: write to project AND to `~/.claude/memory/python/MEMORY.md` (or the most relevant tech).

5. **Is this a decision worth re-litigating?** → not a lesson; should have been an ADR. Add to decisions.md now (with apology that it's late).

6. **Is this a rule that should apply automatically forever?** → add to CLAUDE.md as a one-liner.

If unsure, default to **PROJECT-SCOPE**. Tech-scope MEMORY.md is global and lasts forever; project-scope MEMORY.md is more easily pruned.

### Phase 3 — Write entries

For each non-discarded candidate, append to the chosen file. Use this format:

```markdown
### YYYY-MM-DD — <one-line title>

**Context**: <one sentence — what we were doing>
**Observation**: <what we learned>
**Action / rule**: <what to do next time>
**Source**: <commit-sha or task-id>
```

Example (tech-scope):

```markdown
### 2026-05-20 — argon2-cffi: verify() raises on mismatch, never returns False

**Context**: Implementing password auth.
**Observation**: `ph.verify(hash, password)` raises `VerifyMismatchError` on bad password rather than returning False. We initially wrote `if not ph.verify(...): ...` which never reached the else branch.
**Action / rule**: Wrap in try/except VerifyMismatchError, or use the lower-level `ph.verify_argon2id_hash()` which returns bool.
**Source**: <project> @<sha> (auth_test fix)
```

Example (project-scope):

```markdown
### 2026-05-20 — vendor API: amount field can be string OR Decimal

**Context**: Project consumes vendor invoice exports.
**Observation**: The 'amount' field is sometimes a string ("123.45") and sometimes a number, depending on the vendor's serializer. Pydantic's default coercion handles the string case but logs a warning in strict mode.
**Action / rule**: Accept both via `Union[str, Decimal]` with a custom validator that normalizes to Decimal. See decisions.md "money handling".
**Source**: <project> @<sha> (import fix)
```

### Phase 4 — Commit and clean up

After all entries are written:

1. Show the user the diff for the memory files. **Always confirm before committing.**

   ```bash
   git diff -- '.claude/architecture/MEMORY.md' '~/.claude/memory/' CLAUDE.md decisions.md
   ```

2. On confirmation, commit:

   ```bash
   git add .claude/architecture/MEMORY.md CLAUDE.md decisions.md
   git commit -m "chore(memory): distill lessons from <task or session description>"
   ```

   Note: `~/.claude/memory/` is NOT in the project repo. If you have a separate git repo for `~/.claude/` (recommended for backup), commit there separately.

3. Archive the lesson queue:

   ```bash
   # Move to dated archive so future maintenance can re-read if needed.
   mkdir -p .claude/lesson-archive
   mv .claude/lesson-queue.md ".claude/lesson-archive/lesson-queue-$(date +%F).md"
   ```

4. If the task is complete, archive or delete `claude-progress.md`:

   ```bash
   # If using gitignored progress files:
   rm claude-progress.md
   # If you committed it:
   git mv claude-progress.md "docs/done/$(date +%F)-<task-name>.md"
   ```

5. Report back to the user:

   ```
   Session-end dreaming complete.
   - <N> candidates considered
   - <N> discarded as generic / obvious
   - <N> added to project memory
   - <N> added to tech memory (<list>)
   - <N> added to CLAUDE.md as rules
   - <N> deferred as ADRs (added to decisions.md)
   - <N> queued items unresolved (carry forward)
   ```

## What if there's nothing to distill?

Some sessions produce no lessons — that's fine. The check is not "find something to write" but "filter what's there." If the candidate list is empty, the report is:

```
Session-end dreaming complete. No lessons to capture this session — clean task.
```

Skip the writes, archive the (empty) queue, move on. Do not invent lessons.

## What if there are many candidates?

If you have > 10 candidates from one session, something is off. Either:
- The session was unusually long (split tasks more aggressively next time).
- You were over-capturing in-flow (the lesson-queue threshold should be higher: only queue genuinely non-obvious observations).
- Most candidates are restatements of the same lesson (consolidate before writing).

Process them anyway, but flag in the report: "10+ candidates this session — consider tightening lesson-queue threshold."

## What this trigger does NOT do

- Does not write to skills. Promotion from memory to skill is rare and happens via `triggers/periodic-maintenance.md`, not here.
- Does not delete existing memory entries. Pruning is periodic-maintenance work.
- Does not run code. The lesson is about what just happened; if you need to verify a claim before writing it, do that *before* invoking this trigger.
- Does not write entries the user hasn't confirmed. Memory writes are deliberate, not silent.

## Failure modes

- **Skipping when tired.** End-of-session is when this trigger fires; you're least motivated then. The cost of skipping is high *and invisible* (lost lessons don't show up in any metric). Schedule discipline: lesson queue non-empty → cannot `/clear` without processing.
- **Writing without classifying.** Dumping all candidates into one MEMORY.md creates an unsearchable junk drawer. The classification step is the value.
- **Tech-scope when it should be project-scope.** Pollutes the global memory. When unsure, prefer project-scope (it's easier to promote later than to demote).
- **Project-scope when it should be tech-scope.** Loses the lesson when the project ends. When unsure across projects, *also* write a tech-scope copy.
- **Writing "we learned X" without an action.** "Lesson: Pydantic v2 changed the API" → so what? Add "Action: when upgrading from v1, run pydantic-v2-bump migration tool." Without the action, the lesson can't fire next time.

## Frequency

Typically once per meaningful task end, OR once per session if multiple small tasks. Not once per commit (that's pre-commit-checkpoint's job), not once per chat turn (way too often).
