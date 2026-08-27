#!/usr/bin/env python3
"""State, cost, and DAG operations for the unattended run.

One module so the supervisor (shell) and the sessions (agent) share exactly one
implementation of what a status means and how the DAG advances. Shell calls it
as a CLI; nothing here needs a third-party package.

STATUSES — the supervisor's whole decision surface:
    working   a session is in flight. If the process is gone and the status is
              still this, the session DIED -> restart.
    unit-done a unit finished and more work exists -> restart (self-feed).
    finished  the DAG is exhausted -> do NOT restart. Legitimate stop 3.
    parked    work remains but every node is blocked -> do NOT restart.
              Legitimate stop 1 or 2, depending on the park class.
    halted    a cap fired -> do NOT restart. Needs a human to look.

TERMINAL = {finished, parked, halted}. Everything else means "keep going".

Exit codes are corroborating evidence only; this file is authoritative (D-3).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

TERMINAL = {"finished", "parked", "halted"}
NON_TERMINAL = {"working", "unit-done"}
VALID = TERMINAL | NON_TERMINAL

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "state.json"
COST_FILE = HERE / "cost.json"
HEARTBEAT = HERE / "heartbeat"


# --------------------------------------------------------------------------
# small io helpers
# --------------------------------------------------------------------------

def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, obj: Any) -> None:
    """Atomic: write a temp file in the same dir, then rename. A supervisor
    reading state while a session writes it must never see half a file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _now() -> int:
    return int(time.time())


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

def get_state() -> dict:
    return _read_json(STATE_FILE, {"status": "unknown", "reason": "no state file"})


def set_state(status: str, reason: str = "", unblocks: str = "", node: str = "") -> dict:
    if status not in VALID:
        raise SystemExit(f"invalid status {status!r}; expected one of {sorted(VALID)}")
    prev = get_state()
    obj = {
        "status": status,
        "reason": reason,
        "unblocks_when": unblocks,
        "node": node or prev.get("node", ""),
        "updated_at": _now(),
        "updated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sessions": prev.get("sessions", 0) + (1 if status == "working" else 0),
    }
    _write_json(STATE_FILE, obj)
    return obj


def is_terminal() -> bool:
    return get_state().get("status") in TERMINAL


# --------------------------------------------------------------------------
# cost (D-9: the file is the source of truth, it survives the supervisor)
# --------------------------------------------------------------------------

def get_cost() -> dict:
    return _read_json(COST_FILE, {"spent_usd": 0.0, "sessions": 0, "updated_at": 0})


def add_cost(amount: float) -> dict:
    c = get_cost()
    obj = {
        "spent_usd": round(float(c.get("spent_usd", 0.0)) + float(amount), 6),
        "sessions": int(c.get("sessions", 0)) + 1,
        "updated_at": _now(),
    }
    _write_json(COST_FILE, obj)
    return obj


# --------------------------------------------------------------------------
# DAG (D-10)
# --------------------------------------------------------------------------

def load_dag(dag_path: Path) -> dict:
    dag = _read_json(dag_path, None)
    if dag is None:
        raise SystemExit(f"no readable DAG at {dag_path}")
    return dag


# --------------------------------------------------------------------------
# Self-reference invariant (D-16)
# --------------------------------------------------------------------------
# A node whose own task is "run the supervisor" must never be spawnable BY the
# supervisor. Spawning it means the supervisor launches a session whose job is
# to launch a supervisor, which launches a session, and the caps that bound a
# single run do not bound the tree of runs beneath it.
#
# This was hit for real: node S4b was titled "Prove supervisor + real sessions
# crossing a slice boundary". It was avoided by hand once. Hand-avoidance is not
# an invariant, so it is enforced here, in the one place both the selection path
# (next_node) and the spawn-time check (guard-node) can share.
#
# Deliberately scoped to EXECUTION, not mention. A node that edits, tests, or
# documents supervisor.sh is ordinary maintenance work and must stay spawnable;
# only a node that RUNS the harness is refused.
SELF_REF_PATTERNS = [
    # an execution verb aimed at the supervisor / the loop
    r"\b(run|runs|running|launch|launches|launching|start|starts|starting"
    r"|spawn|spawns|spawning|execute|executes|executing|invoke|invokes"
    r"|invoking|drive|drives|driving|prove|proves|proving)\b[^.]{0,40}?"
    r"\b(supervisor|unattended loop|session-claude)\b",
    # a literal invocation of either script
    r"(?:\bbash\b|\bsh\b|\bexec\b|\./)\s*\S*supervisor\.sh",
    r"(?:\bbash\b|\bsh\b|\bexec\b|\./)\s*\S*session-claude\.sh",
    # the loop named as the thing being exercised
    r"\bsupervisor\s+loop\b",
    r"\bself-restarting\s+loop\b",
]
SELF_REF_RE = [re.compile(p, re.IGNORECASE) for p in SELF_REF_PATTERNS]

# Fields that describe what a node is FOR. 'evidence' is excluded on purpose:
# it records what a finished node proved, and a node that legitimately proved
# something about the supervisor would otherwise be permanently unselectable.
_TASK_FIELDS = ("id", "title", "task", "description", "note", "why_parked")


def self_reference(node: dict) -> str | None:
    """Return the offending phrase if this node's task is to run the harness
    that would spawn it, else None."""
    haystack = " ".join(str(node.get(f, "")) for f in _TASK_FIELDS)
    for rx in SELF_REF_RE:
        m = rx.search(haystack)
        if m:
            return m.group(0).strip()
    return None


def next_node(dag: dict) -> tuple[str, str]:
    """Return (verdict, node_id).

    verdict is one of:
      ready     node_id is the next node to build
      finished  every node is done
      parked    nodes remain but all are blocked or parked
    """
    nodes = dag.get("nodes", [])
    by_id = {n["id"]: n for n in nodes}
    done = {n["id"] for n in nodes if n.get("status") == "done"}

    if len(done) == len(nodes) and nodes:
        return "finished", ""

    for n in nodes:                      # first-ready, in file order (D-10)
        if n.get("status") in ("done", "parked"):
            continue
        if self_reference(n):
            continue                     # D-16: never selectable, never spawnable
        deps = n.get("deps", [])
        if any(d not in by_id for d in deps):
            continue                     # dangling dep -> treat as blocked
        if all(d in done for d in deps):
            return "ready", n["id"]

    return "parked", ""


def set_node_status(dag_path: Path, node_id: str, status: str) -> dict:
    dag = load_dag(dag_path)
    hit = False
    for n in dag.get("nodes", []):
        if n["id"] == node_id:
            n["status"] = status
            hit = True
    if not hit:
        raise SystemExit(f"no node {node_id!r} in {dag_path}")
    _write_json(dag_path, dag)
    return dag


# --------------------------------------------------------------------------
# CLI — the shell surface
# --------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]

    if cmd == "get-status":
        print(get_state().get("status", "unknown"))
    elif cmd == "get-state":
        print(json.dumps(get_state(), indent=2))
    elif cmd == "is-terminal":
        return 0 if is_terminal() else 1
    elif cmd == "set":
        # set <status> [reason] [unblocks] [node]
        set_state(*(argv[2:6] + [""] * (4 - len(argv[2:6]))))
        print(get_state().get("status"))
    elif cmd == "heartbeat":
        HEARTBEAT.write_text(str(_now()), encoding="utf-8")
    elif cmd == "get-cost":
        print(get_cost().get("spent_usd", 0.0))
    elif cmd == "add-cost":
        print(add_cost(float(argv[2]))["spent_usd"])
    elif cmd == "next-node":
        verdict, node = next_node(load_dag(Path(argv[2])))
        print(f"{verdict} {node}".strip())
    elif cmd == "set-node":
        set_node_status(Path(argv[2]), argv[3], argv[4])
        print(f"{argv[3]}={argv[4]}")
    elif cmd == "guard-node":
        # guard-node <dag> <node_id> -> exit 0 safe, exit 3 self-referential.
        # Spawn-time half of D-16. next_node already refuses to select such a
        # node; this catches one that reached a spawn by any other route (a
        # hand-set node, a resumed state file, a future caller).
        dag = load_dag(Path(argv[2]))
        node = next((n for n in dag.get("nodes", []) if n["id"] == argv[3]), None)
        if node is None:
            print(f"no node {argv[3]!r} in {argv[2]}", file=sys.stderr)
            return 2
        hit = self_reference(node)
        if hit:
            print(hit)
            return 3
        print("safe")
    else:
        print(f"unknown command {cmd!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
