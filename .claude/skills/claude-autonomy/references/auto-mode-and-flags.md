# Auto Mode and per-session flags

Beyond the static configuration this skill writes, Claude Code has runtime knobs that affect autonomy. These complement the `.claude/settings.json` baseline — they don't replace it.

## Auto Mode (v2.1.85+)

Claude Code v2.1.85 introduced **Auto Mode**, which runs Claude inside a sandboxed environment (OS-level isolation: container, ephemeral filesystem). In Auto Mode, the cost of any destructive operation is bounded to the sandbox, so most permission prompts become noise — and the mode lets you skip them.

**When Auto Mode helps**:
- Long-running autonomous tasks where you don't want to babysit
- CI / headless runs (`claude -p` with no human in the loop)
- "Throwaway" sessions: explore an idea, copy out the parts you like

**When Auto Mode is not a fit**:
- Working directly on a real project tree where edits should persist
- Tasks that need access to the host filesystem or credentials
- When you specifically want the permission system to prompt you (e.g., learning what Claude is doing)

**How to enable**: pass `--auto` (or the equivalent flag for your version) when invoking `claude`. The exact flag name has shifted across versions; check `claude --help | grep -i auto` or `claude --version` then consult `docs.claude.com` for the matching docs.

Auto Mode does NOT disable `block-dangerous.sh` or `protect-paths.sh` hooks — they still run. Those hooks are inside the sandbox too, so blocking `git commit` still works.

## Per-session CLI flags

These flags affect a single `claude` invocation. They override or extend `.claude/settings.json` for that session only.

### `--allowedTools`

Pre-approve specific tools for this session, bypassing `ask` prompts:

```bash
claude --allowedTools "Bash(uv add:*)"
```

Use for one-off tasks where you know you'll be adding deps and don't want to confirm every time.

### `--disallowedTools`

Force-deny tools for this session:

```bash
claude --disallowedTools "WebFetch(*)"
```

Use when you want offline-only behavior temporarily.

### `--strict-mcp-config`

When using `--mcp-config <path>`, this flag tells Claude to use ONLY the given config — ignoring `.mcp.json` and user-level MCP. Useful for token-budget-tight sessions:

```bash
claude --mcp-config ./mcp-configs/minimal.json --strict-mcp-config
```

### `--disable-hooks <event>`

Skip hooks for specific events this session:

```bash
claude --disable-hooks Stop          # don't run verify-on-stop
claude --disable-hooks PreToolUse    # skip block-dangerous and protect-paths
```

Use when running quick iterations and you don't want test failures blocking turn-end. Re-enable for the next session by just dropping the flag.

### `--dangerously-skip-permissions`

Disables ALL permission checks, including `deny` rules from settings.json. Hooks still run.

**Only use this** when Claude is in a true sandbox (devcontainer, ephemeral VM, CI container). Never on a host where Claude has access to your real files.

```bash
# In a Docker container for headless work:
claude -p --dangerously-skip-permissions "Fix the failing test and stop"
```

This skill intentionally does NOT bake this flag into settings.json. It's a per-invocation choice you make consciously.

### `-p` / `--print` (headless mode)

Run Claude non-interactively, exit when done. Useful in CI:

```bash
claude -p --output-format json "Run tests and report failures" > result.json
```

Combine with `--allowedTools` to skip all prompts. Combine with `--disable-hooks Stop` if you want CI to handle test failures itself rather than have Claude retry.

## Environment variables

These environment variables affect Claude Code behavior. Some are also set by this skill's `settings.json` `env` block, but you can override at the shell:

| Variable | What it does |
|----------|--------------|
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Pin Sonnet to a specific version (e.g., `claude-sonnet-4-6`) |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Pin Opus version |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Pin Haiku version |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Model used for spawned subagents (default Sonnet) |
| `CLAUDE_PROJECT_DIR` | The repo root, set by Claude Code; used by hooks |
| `MAX_THINKING_TOKENS` | Cap on extended-thinking tokens per turn |

To make these persistent: export from `.envrc` (direnv) or shell init. Don't put them in `.env` if you also commit `.env.example` — keep model choices separate from secrets.

## Combinations for common use cases

### "Maximum autonomy for a known-safe task in a sandbox"
```bash
claude --dangerously-skip-permissions --disable-hooks Stop -p "<task>"
```
Skips everything; runs once and exits.

### "Headless CI fixing a test failure"
```bash
claude -p \
  --allowedTools "Bash(uv run pytest:*),Bash(git add:*),Edit(*)" \
  --disable-hooks Stop \
  --output-format json \
  "Identify and fix the failure in <test_name>. Stage the fix."
```
CI then runs its own `git diff --cached` and decides whether to commit.

### "Interactive session, fewer prompts than default"
```bash
claude --allowedTools "Bash(uv add:*),Bash(uv remove:*)"
```
Pre-approves dep adds for this session only.

### "Strict session — every dependency, every push gets a prompt"
Just `claude`. Use the project default config which has these in `ask`.

## When to consider deviating from this skill's config

This skill produces a balanced configuration. Reasonable reasons to deviate:

1. **Solo developer on a personal project, sandbox host**: move more to `allow`. Risk is bounded to your machine.
2. **Team project, shared remote**: keep `ask` for any `git push`. Consider adding `gh pr create` even to `deny` and only allow via per-session flag.
3. **Highly regulated codebase** (financial, medical): tighten the WebFetch allowlist; add more paths to `protect-paths.sh`.
4. **Pure exploration / spike**: throw it in a container, use `--dangerously-skip-permissions`, don't worry about the policy. Just don't push from there.

The skill writes a starting point. The file is yours after that.
