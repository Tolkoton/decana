#!/usr/bin/env python3
"""D-16 regression: which nodes the supervisor must refuse to spawn."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runstate import self_reference, next_node  # noqa: E402

MUST_REFUSE = [
    # the real one that started this
    {"id": "S4b", "title": "Prove supervisor + real sessions crossing a slice boundary",
     "why_parked": "the supervisor loop is blocked on a permission"},
    {"id": "X1", "title": "Run the supervisor overnight"},
    {"id": "X2", "title": "Launch the unattended loop against the real DAG"},
    {"id": "X3", "title": "Start the supervisor and confirm it self-feeds"},
    {"id": "X4", "task": "bash .claude/unattended/supervisor.sh --reset"},
    {"id": "X5", "description": "exec ./session-claude.sh for one node"},
    {"id": "X6", "title": "Exercise the supervisor loop end to end"},
    {"id": "X7", "note": "spawns claude subprocesses in a self-restarting loop"},
    {"id": "X8", "title": "Drive the supervisor through a crash"},
    {"id": "X9", "title": "Invoke session-claude for the next node"},
]

MUST_ALLOW = [
    {"id": "A1", "title": "Port block-dangerous.sh to Python so it enforces without jq"},
    {"id": "A2", "title": "Fix restart accounting bug in supervisor.sh"},
    {"id": "A3", "title": "Document the supervisor's decision table in README"},
    {"id": "A4", "title": "Add cost-capture assertions for session-claude.sh"},
    {"id": "A5", "title": "Anchor verdict markers in overseer_stop.py"},
    {"id": "A6", "title": "Fill AGENTS.md placeholder text"},
    {"id": "A7", "title": "Resolve project.env being unwritable under protect-paths"},
    # 'evidence' is excluded from the scanned fields on purpose: a finished node
    # that PROVED something about the supervisor must not become unselectable.
    {"id": "A8", "title": "Verify format-on-edit enforces post-jq",
     "evidence": "ran the supervisor loop and it self-fed across the boundary"},
]

fails = []
for n in MUST_REFUSE:
    hit = self_reference(n)
    print(f"  refuse {n['id']:4} -> {hit!r}")
    if not hit:
        fails.append(f"{n['id']} SHOULD be refused but was allowed")

print()
for n in MUST_ALLOW:
    hit = self_reference(n)
    print(f"  allow  {n['id']:4} -> {hit!r}")
    if hit:
        fails.append(f"{n['id']} SHOULD be allowed but was refused on {hit!r}")

# next_node must never hand back a self-referential node, even when it is the
# only thing left that is otherwise ready.
print()
dag = {"nodes": [
    {"id": "N1", "title": "ordinary work", "deps": [], "status": "done"},
    {"id": "N2", "title": "Run the supervisor loop", "deps": ["N1"], "status": "todo"},
]}
v, nid = next_node(dag)
print(f"  next_node with only a self-ref node ready -> {(v, nid)!r}")
if v == "ready":
    fails.append(f"next_node handed back self-referential node {nid!r}")

print()
if fails:
    print(f"FAIL ({len(fails)}):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print(f"PASS: {len(MUST_REFUSE)} refused, {len(MUST_ALLOW)} allowed, next_node clean")
