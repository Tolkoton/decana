# Permission philosophy — what goes where, and why

This skill organizes permissions by the cost of the operation, not by its name.

## The three buckets

### deny — never let Claude do this, period

The cost is irreversible damage in the worst case. Includes:

- **Filesystem destruction**: `rm -rf /`, `rm -rf ~`, wildcard expansion that could nuke the user's data. The risk isn't Claude maliciously typing these; it's prompt injection through web/MCP content steering Claude into running them.
- **Git history destruction**: `git push --force`, `git reset --hard origin`, `git filter-branch`, `git clean -fdx`. Recovery may be impossible if others have pulled.
- **Secret exposure**: reading `.env`, `~/.ssh/*`, AWS/GCP credentials. Claude doesn't need these to write code that uses them.
- **Publishing**: `twine upload`, `uv publish`, `poetry publish`, `npm publish`. Yanking is annoying; accidentally publishing a private package once is a real incident.
- **Migration tampering**: editing files in `migrations/`, `alembic/versions/`. These are append-only history; modifying a committed migration breaks every other developer's DB.
- **CI tampering**: editing `.github/workflows/`. Subtle changes here propagate to production deploys.
- **`git commit`**: not destructive per se, but commits are the human checkpoint in this workflow. Defense-in-depth makes the hook block it AND the settings.json have it in `ask` (where Claude would still get the message that this is a checkpoint).

### ask — Claude must request confirmation

The cost is "I shared this with the world" or "I changed long-term state". Includes:

- **`git push`, `gh pr create/merge`, `gh release`**: pushing affects the remote; PRs and releases are intent statements. Worth one explicit "yes" each.
- **Dependency adds/removes**: `uv add`, `poetry add`, `pip install`. Adding a dependency is a long-term commitment (licenses, security, transitive bloat). Defer to the human.
- **Schema migrations**: `alembic upgrade/downgrade/revision`, `python manage.py migrate/makemigrations`. Even on dev DB, the schema delta is something the human should consciously approve.
- **`docker push`, `docker run`, `docker compose up`**: starting containers can hog ports, create state on disk, or push images. Not catastrophic but worth confirming.

### allow — no prompt; just go

Everything else routine. The cost is at most some wasted time, recoverable by undo/git.

- **All reads**: source files, config, lockfiles. Reading is free.
- **All edits** to non-protected paths: `acceptEdits` mode handles this without per-file prompts.
- **Read-only git**: `status`, `diff`, `log`, `show`, `blame`, `reflog`.
- **Modify-local git**: `add`, `restore`, `checkout -b`, `switch`, `stash`, `tag`, `branch`. These only affect the local repo and are easy to undo.
- **All test/lint/format tools**: pytest, ruff, mypy, black, isort, coverage, bandit.
- **Toolchain wrappers**: `uv run`, `poetry run`, `python -m`.
- **File utilities**: `ls`, `cat`, `grep`, `rg`, `find`, `head`, `tail`, `jq`, `tree`. Pure reads or local-only operations.
- **Most subprocess reads**: `docker ps/logs/inspect`, `kubectl get/describe/logs`. Inspection is fine; mutation needs `ask`.
- **Documentation fetches**: Python docs, framework docs (FastAPI, Django, Pydantic, SQLAlchemy), GitHub, Stack Overflow.
- **Web search**: pure information retrieval; safe.

## Why not `--dangerously-skip-permissions` for everything?

`--dangerously-skip-permissions` is a runtime flag that disables ALL permission checks, including `deny` rules. It's intended for sandboxed environments (devcontainer, ephemeral VM) where there's nothing to destroy.

This skill deliberately does NOT bake that flag into the configuration. If you're running in a sandbox, you can pass `--dangerously-skip-permissions` at the CLI yourself (e.g., for headless `claude -p` in CI inside a container). But the default config keeps the safety net so that even if Claude makes a mistake, the blast radius is bounded.

## How the bug-aware design works

Claude Code's deny rules have known holes (see issues `anthropics/claude-code#6699`, `#12918`, `#27040`). For example, `Edit(./.env)` blocks the built-in Edit tool, but `Bash(echo SECRET >> .env)` may slip through if the Bash command doesn't trigger the right matcher.

That's why this configuration uses three lines of defense:

1. **settings.json deny/ask/allow**: the documented mechanism. Blocks the obvious shapes.
2. **`block-dangerous.sh` PreToolUse hook**: catches Bash patterns that slip past settings.json, including all the wildcard-expansion shapes.
3. **`protect-paths.sh` PreToolUse hook**: catches Edit/Write/MultiEdit on protected paths even if the settings.json glob didn't match.

You can defeat all three by editing the hook scripts. They're yours. But out of the box, three layers means a single bug doesn't expose you.

## Common edits and their tradeoffs

### Moving `Bash(uv add *)` from ask to allow

**Pro**: no prompt when Claude needs to add a dependency mid-task.
**Con**: Claude can quietly grow your `pyproject.toml`. You'll discover unwanted deps at lockfile-review time. Some teams prefer this; some don't.

### Adding `Bash(git push *)` to allow

**Don't**. The `ask` prompt is the human's chance to think "is this really ready?". Pushing without a beat is how WIP commits end up on `main`.

### Moving `WebFetch(domain:*)` to allow universally

**Tradeoff**: Claude can fetch any URL without prompt. The risk is prompt injection from malicious sites. The benefit is no "may I fetch this docs page?" friction.

If you trust your usage patterns and aren't doing security-sensitive work, this is reasonable. Add `"WebFetch(*)"` to allow. The trade is reduced friction for a slightly broader attack surface.

### Adding a `MCP__github__*` tool

If you set up an MCP server later, its tools appear as `mcp__<server>__<tool>`. To pre-approve specific MCP tools without prompts, add patterns like `"mcp__github__list_issues"` to allow.

Be specific. `mcp__*` allows every MCP tool from every connected server, which can include destructive operations.

## Calibration test

After running this skill and starting a fresh Claude Code session, ask Claude to do these tasks in order. Each should run WITHOUT prompts:

1. "List the Python files in src/"
2. "Run the tests"
3. "Check what's in CLAUDE.md"
4. "Format all Python files"
5. "Show me the last 5 commits"
6. "Edit src/foo.py and add a docstring to the main function"
7. "Look up the latest Pydantic v2 docs for validators"
8. "Stage src/foo.py for me"

If any of these prompts unexpectedly, the configuration is too tight — add the relevant pattern to allow.

Then ask Claude to do this (should prompt):

1. "Add `requests` to the dependencies"
2. "Push to origin"
3. "Open a PR"

If any of these DON'T prompt, the configuration is too loose — move the relevant pattern to ask or deny.
