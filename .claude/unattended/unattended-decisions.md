# Unattended-operation decisions

Every call made while building the 24/7 harness, with its reasoning and its
cost-to-reverse. Pre-ratified by the owner's message of 2026-08-27 ("Decide
everything, log to unattended-decisions.md"). Nothing here was asked about;
that was the instruction.

Format: **D-N. Decision.** Why. Alternative rejected. Cost to reverse.

---

## Platform

**D-1. The supervisor is a POSIX shell loop, not a systemd unit.**
The box this was built on is macOS (Darwin 23.6.0) — `systemd` does not exist
here, so a unit file could not be tested, and an untested supervisor is the one
component that must not be untested. `supervisor.sh` runs anywhere with a shell,
including under systemd, launchd, tmux, or nohup. A ready-to-use unit file ships
alongside it as `claude-unattended.service` for the Linux server, but the logic
under test is the shell loop in both cases.
*Rejected:* systemd-native with `Restart=on-failure`. It would push restart
policy into a file I cannot exercise here, and it cannot read the final-state
file to distinguish "finished" from "died" without a wrapper anyway.
*Cost to reverse:* near zero — the unit already exists, delete the loop.

**D-2. The session command is configurable (`SESSION_CMD`), defaulting to
`claude -p`.**
This is what lets the harness be proven without spending tokens on a
demonstration, and it is also how a different runner is dropped in later.
*Rejected:* hardcoding `claude`. Untestable without cost, and it welds the
supervisor to one CLI.
*Cost to reverse:* near zero — one variable.

## Liveness and termination

**D-3. The final-state file is authoritative; the exit code is corroborating.**
`state.json` carries `status`, and the supervisor restarts only when the status
is non-terminal. A session that exits 0 without writing a terminal status is
treated as *died*, not as *finished*.
*Why this direction:* the dangerous failure is stopping when work remains — a
silent halt on a server nobody watches costs a whole night. Restarting a
finished run costs one cheap no-op session that immediately reports `finished`.
Bias toward the recoverable error.
*Rejected:* trusting exit 0 as "clean". A crashed CLI, an OOM kill, and a
successful finish can all produce 0.
*Cost to reverse:* one condition in `classify_exit`.

**D-4. Liveness = the newer of `PROGRESS.md` mtime and the heartbeat file.**
`PROGRESS.md` is the signal the owner named, but it only moves at unit
boundaries, which can legitimately be tens of minutes apart. A session that is
working normally would look hung. The heartbeat file gives a fast signal without
weakening the slow one; a stall is declared only when *both* are stale.
*Rejected:* PROGRESS.md alone (false stalls on long units); heartbeat alone
(a wedged session can still tick a heartbeat if the tick is in the wrong place).
*Cost to reverse:* one function.

**D-5. A stalled session is killed with SIGTERM, then SIGKILL after a grace
period, and counted as a restart.**
A hang consumes the same wall-clock as a crash loop and must be capped the same
way.
*Cost to reverse:* trivial.

## Caps

**D-6. Restart cap is a rolling one-hour window over a timestamp file, not a
fixed-window counter.**
A fixed window resets on the hour and permits a burst of `2 × MAX` across a
boundary. The rolling window cannot.
*Cost to reverse:* trivial.

**D-7. Hitting the restart cap writes status `halted` and stops. Hitting the
cost cap writes status `parked` and stops.**
Different classes: a crash loop is a defect (someone must look at it), an
exhausted budget is an input (someone must raise it). Both stop; they are
labelled differently so the state file says which.
*Rejected:* treating both as `halted`. The owner asked for park-not-retry on
cost specifically.
*Cost to reverse:* one string.

**D-8. The cost cap is checked before spawning, never mid-session.**
The supervisor cannot see inside a running session, and killing one mid-unit to
save budget would leave a half-finished unit — more expensive to recover than
the overshoot it saves. Consequence, stated plainly: actual spend can exceed the
cap by at most one session's cost. `MAX_SESSION_USD` bounds that overshoot.
*Cost to reverse:* moderate — would need in-session reporting.

**D-9. Cost is recorded by the session, in `cost.json`, and the file is the
source of truth across restarts.**
A counter in supervisor memory dies with the supervisor, which is the exact
event this whole harness exists to survive.
*Cost to reverse:* n/a.

## Work selection

**D-10. Self-feeding reads a DAG file and picks the first node whose
dependencies are all `done` and which is not `parked`.**
Deterministic and inspectable. First-ready rather than any heuristic ordering,
so a rerun makes the same choice.
*Rejected:* letting the agent choose freely each session. Non-reproducible, and
it makes "did it advance?" unanswerable from the outside.
*Cost to reverse:* one function.

**D-11. Terminal states are distinguished: `finished` (no nodes left),
`parked` (nodes left, all blocked), `halted` (a cap fired).**
These are the owner's three legitimate interrupts, made machine-readable so the
supervisor can act on them without interpretation.
*Cost to reverse:* n/a.

**D-12. Parked items are re-checked before each spawn, not on a timer.**
Every spawn is already a natural checkpoint, and a timer adds a second scheduler
to reason about. An item whose `unblocks_when` condition is now satisfiable
returns to the queue automatically.
*Cost to reverse:* trivial.

## Housekeeping

**D-13. Rotation is size-triggered, checked before each spawn, keeping N
generations gzipped in `archive/`.**
Time-based rotation does nothing on a quiet day and too little on a loud one.
*Cost to reverse:* trivial.

**D-14. `logs/`, `archive/`, and the runtime state files are gitignored.**
They are machine-local and would otherwise put a commit in every session's path
— and committing is blocked by design, so they would simply accumulate as noise
in `git status` forever.
*Cost to reverse:* trivial.

## Scope limit found during the build

**D-15. The end-to-end proof runs against a simulated session runner, not live
`claude` sessions.**
The bar is a supervisor property: kill a session, have it restart, have it pull
the next DAG node, cross a slice boundary with no human turn. A scripted runner
exercises exactly that code path deterministically, for free, in seconds. Real
sessions would test the same supervisor logic while adding nondeterminism and
token spend to a test that is run many times during development.
*Stated honestly:* this proves the harness, not the agent's work quality inside
a session. The `SESSION_CMD` default is the real `claude -p` invocation; the
simulator is only what the proof harness substitutes.
*Cost to reverse:* set `SESSION_CMD` and run.

## Decisions taken after the first real run (2026-08-27)

**D-16. A node whose task is to RUN the supervisor is never spawnable by the
supervisor.**
Enforced in two places sharing one definition (`runstate.self_reference`):
`next_node` will not select such a node, and `supervisor.sh` re-checks at spawn
time via `runstate.py guard-node` for a node that arrived by any other route.
Refusing parks that node and selects another; it does not end the run and does
not consume the restart budget.
*Why:* node S4b was titled "Prove supervisor + real sessions crossing a slice
boundary". Spawning it means a session whose job is to launch a supervisor,
which spawns a session — and the caps that bound one run do not bound the tree
of runs beneath it. It was avoided by hand once. Hand-avoidance is not an
invariant.
*Scoped to execution, not mention:* a node that edits, tests, or documents
`supervisor.sh` stays spawnable. The bias is deliberately conservative — a
phrase like "run the test suite for supervisor.sh" WILL be refused. Refusing
costs one parked node a human can look at; allowing costs an unbounded process
tree.
*Regression:* 10 refused / 8 allowed + `next_node` clean.
*Cost to reverse:* trivial — delete the patterns.

**D-17. A simulated session runner is refused in a real run unless
`ALLOW_SIM_SESSIONS=1`.**
D-15 introduced `session-sim.sh` as a proof fixture. A fixture left wired into a
real run reports clean node completions for work nobody did, which is
indistinguishable from progress in every log and status the harness produces.
*Cost to reverse:* set the env var.

**D-18. Helper tooling must clear the same permission layer as the real work.**
The first supervisor watcher was written inline with `comm -13 <(...) <(...)`
and the harness permission classifier prompted on the process substitution.
Attended that is one keypress; unattended it is a denial, leaving the supervisor
running with nothing watching it and nobody to unblock the watcher. Fixed as
`.claude/unattended/watch.sh` using only grep/wc/tail/sleep.
*The wider finding:* this was NOT catchable by `park-ask-gated.py`. That hook
only matches the 21 patterns mirrored from `settings.json`'s ask list, so it
converts ask-list prompts into structured parks and nothing else. The classifier
is a separate, wider gate with no park conversion. Verified: the old `<(...)`
command passes the hook clean while `git push origin main` is denied by it.
*Cost to reverse:* trivial.

**D-19. The supervisor refuses to spawn a session whose prompt still contains
the unsubstituted `{NODE}` placeholder, and halts.**
*The bug it was written for:* `config.sh` assigned the default prompt as
`SESSION_PROMPT="${SESSION_PROMPT:-... Next DAG node: {NODE}. ...}"`. Bash closes
a parameter expansion at the first unescaped `}` — which is the placeholder's own
brace. The stored default became `... Next DAG node: {NODE. ... exiting.}`, so
`${SESSION_PROMPT//\{NODE\}/$node}` never matched, and every real session was
handed the literal text `{NODE` and never learned which node it was building —
while every log line still read `node=S3`. Fixed by assigning in two steps.
*Why it survived two proofs:* D-15's simulated runner and the D-16 boundary run
both exported `SESSION_PROMPT` explicitly, so neither exercised the default. The
one path used by every production run was the one path never tested. This is the
general shape of fixture-hidden defects: the fixture replaces exactly the
component whose default is wrong.
*Halt, not park:* a malformed prompt affects every node, so nothing unblocked can
move — legitimate stop 3, needing a human.
*Verified both ways:* broken prompt -> `MALFORMED PROMPT ... rc=125, state='halted'`;
real default -> substitutes to `Next DAG node: S3` and does not trip.
*Also fixed here:* the guard's `runstate set` echoed its status into
`run_session`'s stdout, which IS the return value, corrupting `rc=halted`. The
same stdout-capture trap the file header already documents. Now `>/dev/null`.
*Cost to reverse:* trivial.

**D-20. The Stop hook blocks the ORCHESTRATING session from ending its turn
while the unattended run is live.**
*The bug:* the only continuation branch was `OVERSEER_PASS -> CONTINUE`
(`overseer_stop.py:443`). `OVERSEER_PASS` only exists after an audit; the audit
fires only on the sentinel PLUS an edit under `SOURCE_DIRS`, which is `"src"`;
and this repo deliberately has no `src/` (see AGENTS.md). So in the one
repository that describes itself as running unattended, the audit branch could
never fire, the CONTINUE branch was therefore unreachable, and every ordinary
turn fell through to `_passthrough()` and simply stopped. The autonomous loop
was structurally dead here while reading as fully configured.
*The fix:* `_stop_or_continue()` replaces the three "nothing to audit" exits. It
blocks when the mode file says unattended AND either a supervisor session is in
flight or a DAG node is ready and unblocked.
*Exempt — supervisor-spawned sessions*, via `CLAUDE_UNATTENDED_SESSION=1`
exported in `session-claude.sh`. They MUST be free to end: finishing a node means
writing `unit-done` and exiting so the supervisor spawns the next one, and a
death must leave `working` behind for the restart logic to detect. Blocking their
Stop would break both mechanisms.
*Bounded* by `MAX_UNATTENDED_CONTINUES = 25` so a wedged loop cannot spin.
*Verified 8/8*, including the two cases where it must BLOCK.
*Prose fixed alongside:* `CLAUDE.md` step 4 read "STOP and wait for the human to
review the diff", which licensed ending the turn right after staging. The
three-stops paragraph now names the non-reasons explicitly — waiting on a
background task, having something to report, asking to ratify a two-way door
already decided, or reaching a natural-feeling pause.
*Cost to reverse:* trivial.

**D-21. `block-dangerous.sh` matches at command position, and its false
positives are accepted rather than fixed.**
Four evasions were closed: a compound command walking past the caret anchor, a
git global option hiding the subcommand, a quoted or braced home variable, and a
tab-indented privilege escalation. The fix is a shared prefix meaning "start of
string, or just after a separator", plus an option group that tolerates a flag
carrying its own argument -- the two-token form was the single case that still
slipped through the first attempt, caught only because the regression suite
covered it.
*Verified:* 10 blocked / 9 allowed in `hook-checks/test_deny_gaps.py`, where the
9 exist to prove the widening did not start catching ordinary commands; the
pre-existing suite went from four documented GAPs to 62 PASS / 0 FAIL.
*Not fixed, deliberately:* the hook matches inside quoted literals and heredoc
bodies, so describing a dangerous command is blocked as if running it. This bit
twice during the work itself. Telling a real invocation from a quoted mention
needs shell parsing, and the obvious shortcut opens a genuine hole because a
heredoc fed to a shell executes its body. For a deny control a false positive is
a nuisance and a false negative is a breach.
*Cost to reverse:* trivial.

**D-22. A decision is closed by being logged, and `escalations.md` gained a
format that can represent an autonomous one.**
*The bug:* verdict routing says a two-way door is logged to `escalations.md` and
continued. But that file's only entry format had fields `Question`, `Options
offered`, `Recommendation`, `Human chose`, `Latency to decision` -- every one
presuming a human answered. There was no shape for "two-way door, decided
autonomously, no human needed". The rule pointed at a file that could not hold
the thing the rule described, so the log stayed at "(no entries yet)" while
decisions were being made.
*The consequence, observed:* the S3 reopening was decided, acted on, and
vindicated -- and then re-surfaced to the owner in three consecutive turns,
because nothing recorded it as settled. An unlogged decision is an open
decision, and an open decision becomes a stop wearing a question mark.
*The fix:* a second AUTONOMOUS entry format (decision / door / cost to reverse /
why not escalated / evidence / falsified by / Status), the S3 decision logged
retroactively as CLOSED, and the doctrine made explicit in CLAUDE.md: logging is
what closes a decision, CLOSED means closed, and a deviation from an owner
instruction is classified by reversibility like anything else -- "the owner said
X" does not make a cheap reversible call one-way.
*Enforced, not just written:* `hook-checks/test_decision_logged.py` fails when a
DAG node carrying `prior_evidence` -- the trace of an autonomous reopening -- has
no CLOSED entry naming it. Verified in both directions: passes on the real repo,
exits 1 against an empty log.
*Cost to reverse:* trivial.

**D-23. Sessions may repair the harness; they may not touch what limits them.**
Owner-ratified 2026-08-27. Edit/Write/MultiEdit granted under `.claude/hooks/`,
`.claude/unattended/` and `.claude/architecture/` in `settings.local.json`
(machine-local -- `settings.json` ships with the template). `constitution.md`,
`settings.json` and `settings.local.json` are denied in the permission list AND
independently by `protect-paths.sh`, because a permission list can be re-widened
by editing the file that defines it, and an agent that may edit its own
permissions has none.
*Paired with D-24, deliberately:* the grant is only safe if a session's patch is
screened before it lands.
*Verified:* `test_guardrail_paths.py`, 5 refused / 5 allowed.

**D-24. A patch proposed by a session is screened before it is applied.**
`hook-checks/lint_patch.py` flags the transformations that are almost always a
weakening, split into CRITICAL (fails, exit 1) and REVIEW (informational).
*The evidence it was built from:* the S3 patch contained
`PROJECT_ROOT=$(git rev-parse --show-toplevel >/dev/null 2>&1)`. In a command
substitution stdout IS the value, so the "fix" silently emptied the variable and
the hook fell back to the wrong directory. Every test in the session's own suite
still passed, because no test covered project-root detection. A human reading the
diff caught it; unattended it would have landed.
*Tuned for use, not for coverage:* the first version flagged 20 hunks on that
patch, 19 of them legitimate. A gate that fires on twenty when one matters trains
people to ignore it. Now: 1 CRITICAL, 19 informational.
*Verified both ways:* exit 1 on the real patch, exit 0 on a clean one.
*Honest limit:* it is a screen, not a proof. It catches a known shape of
weakening, not wrongness in general.

**D-25. Commits are legal on `unattended/<date>` and nowhere else.**
Owner-ratified 2026-08-27. The checkpoint is kept where it does work -- nothing
reaches `main` without a human reading the diff -- and removed where it only
made work pile up: over a night, every session was building on an unreviewed
index inherited from the session before it, so one bad change was silently
inherited by everything after, with no point to roll back to.
*Fails closed:* an undeterminable branch is refused, not allowed.
*Uses the S7 command-position pattern on both sides,* so `cd x && git commit` and
`git -C dir commit` are caught where they must be caught and permitted where
they are permitted.
*Stages `-u`, never `-A`:* an unattended run emits logs and scratch patches, and
sweeping those in makes the review surface unreadable.
*Verified:* `hook-checks/test_commit_policy.py`, 11/11 against real throwaway
repos with real branches checked out -- the hook reads the branch with
`git branch --show-current`, so faking it would only test the test.
*One step remains and it is not the AI's:* `settings.json` denies
`Bash(git commit*)`, deny beats allow, and D-23 made that file unwritable by the
AI. The last enabling edit belongs to the owner by construction.

**D-26. CORRECTION to D-25: hooks guard tool calls, not scripts.**
D-25 claimed `block-dangerous.sh` enforces the commit rule "independently". For
a command the agent types, true -- 11/11. For a command inside a script, false.
PreToolUse hooks and `permissions.deny` evaluate the Bash tool call that is
issued; a script's internal commands are never re-evaluated.
*Verified 2026-08-27, deliberately with a non-mutating probe:*
`git commit --dry-run` is refused by the harness at top level, and executed
untouched from a two-line script.
*Scope of the problem, which is wider than commits:* every hook in this repo is
bypassable this way -- `block-dangerous.sh`, `protect-paths.sh`, the deny list.
Any script an agent writes is a hole through all of them. This does not make the
hooks useless: they still catch the direct, ordinary, accidental case, which is
the common one. It makes "a hook enforces this" a claim that must be qualified.
*Fixed where it matters now:* `commit_checkpoint.sh` re-checks the branch itself
immediately before committing and refuses anything outside `unattended/*`,
rather than trusting the earlier switch or the hook. On that path those lines
are the only control there is.
*Recorded in AGENTS.md* so it reaches every session, not just this one.

**D-27. `settings.local.json` was committed since the repository's first commit,
contradicting its own header.**
The file states "Machine-local overrides. Gitignored — never committed, never
inherited by a project copied from this template", and the S4b park note gives
that as the reason the supervisor permission went there rather than into
`settings.json`. Both were wrong: `git log --diff-filter=A` puts it in `c9d348e`,
the initial commit, and no `.gitignore` rule ever matched it.
*What it actually shipped:* every clone of this template inherited permission to
auto-launch the supervisor loop, and after D-23 would have inherited write access
under `.claude/hooks`, `.claude/unattended` and `.claude/architecture` too --
precisely the "bad default" the earlier decision was written to prevent. The
reasoning was sound; the mechanism was never checked.
*Fixed:* added to `.gitignore` and `git rm --cached`. The file stays on disk, so
this machine keeps its grants; downstream projects now start with none.
*The general lesson, and it is the same one three times today:* a comment
asserting a mechanism is not the mechanism. `{NODE}` was never substituted, the
continue branch was unreachable, escalations.md could not record an autonomous
decision, and this file was never ignored -- each read as correct and none of
them was ever exercised.
