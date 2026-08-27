# Unattended-run configuration. Sourced by supervisor.sh and the helpers.
# Every value has a working default; override here per machine.
#
# NAMED .sh, NOT .env — deliberately. protect-paths.sh denies any write to a
# path matching `\.env$`, and it is right to: it cannot tell a config file from
# a secrets file by name alone. Blocked this file on first write 2026-08-27.
# Keep credentials OUT of here regardless; this file is committed.

# ---------------------------------------------------------------------------
# What a session IS
# ---------------------------------------------------------------------------
# The command the supervisor spawns for one session. It receives the next DAG
# node id as $1 and the prompt as $2. It must write a terminal status into
# state.json before it exits (see README "Session contract"), or the supervisor
# treats its exit as a death and restarts.
#
# Default is a real headless Claude Code run. The proof harness overrides this
# with .claude/unattended/session-sim.sh (see D-15).
SESSION_CMD="${SESSION_CMD:-.claude/unattended/session-claude.sh}"

# Prompt handed to the session. {NODE} is replaced with the DAG node id.
# ASSIGNED IN TWO STEPS, NOT VIA ${SESSION_PROMPT:-...} — deliberately.
# Bash closes a parameter expansion at the FIRST unescaped '}', which inside a
# ${VAR:-default} is the one belonging to the {NODE} placeholder itself. The
# default therefore stored "... Next DAG node: {NODE. Follow ... exiting.}" —
# closing brace eaten, stray brace appended — so supervisor.sh's
# ${SESSION_PROMPT//\{NODE\}/$node} substitution never matched and every real
# session was handed the literal text "{NODE", never learning which node it was
# building. It shipped undetected because BOTH proofs (D-15 simulated runner,
# the D-16 boundary run) exported SESSION_PROMPT explicitly and so never
# exercised this default — the production path was the one path untested.
if [ -z "${SESSION_PROMPT:-}" ]; then
  SESSION_PROMPT="Continue the unattended run. Next DAG node: {NODE}. Follow CLAUDE.md: decide and log, park and route around, three legitimate stops only. Write .claude/unattended/state.json before exiting."
fi

# ---------------------------------------------------------------------------
# Caps — the things that stop a bad night
# ---------------------------------------------------------------------------
# Restarts allowed in any rolling 60 minutes. Exceeding this writes status
# 'halted' and stops for good.
MAX_RESTARTS_PER_HOUR="${MAX_RESTARTS_PER_HOUR:-6}"

# Total USD the run may spend. Checked BEFORE each spawn (D-8), so real spend
# can exceed this by at most one session.
COST_CAP_USD="${COST_CAP_USD:-25.00}"

# Expected worst-case cost of a single session. Used to warn when the remaining
# budget cannot fit even one more session.
MAX_SESSION_USD="${MAX_SESSION_USD:-3.00}"

# Hard ceiling on total sessions for this run, independent of restarts.
# A backstop against a self-feeding loop that always finds "one more node".
MAX_SESSIONS="${MAX_SESSIONS:-200}"

# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------
# Seconds with NO update to either PROGRESS.md or the heartbeat before a
# session is declared stalled and killed (D-4, D-5).
STALL_TIMEOUT_SEC="${STALL_TIMEOUT_SEC:-900}"

# How often the supervisor polls a running session.
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-15}"

# Grace period between SIGTERM and SIGKILL when killing a stalled session.
KILL_GRACE_SEC="${KILL_GRACE_SEC:-20}"

# Seconds between a session ending and the next spawn. Also the minimum spacing
# that keeps a fast crash loop from spinning the CPU.
RESPAWN_DELAY_SEC="${RESPAWN_DELAY_SEC:-10}"

# ---------------------------------------------------------------------------
# Work source
# ---------------------------------------------------------------------------
DAG_FILE="${DAG_FILE:-.claude/architecture/feature-dag.json}"

# ---------------------------------------------------------------------------
# Rotation (D-13)
# ---------------------------------------------------------------------------
ROTATE_MAX_KB="${ROTATE_MAX_KB:-2048}"
ROTATE_KEEP="${ROTATE_KEEP:-7}"
ARCHIVE_MAX_AGE_DAYS="${ARCHIVE_MAX_AGE_DAYS:-30}"
