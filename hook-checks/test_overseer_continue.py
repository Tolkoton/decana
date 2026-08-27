#!/usr/bin/env python3
"""Does the Stop hook actually keep the orchestrator going?"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

HOOK = "/Users/lao/Documents/GitHub/claude-cli-config/.claude/hooks/overseer_stop.py"

def run(mode, status, msg="ordinary turn, no sentinel", env=None, count=None):
    root = Path(tempfile.mkdtemp())
    (root/".claude/overseer").mkdir(parents=True)
    (root/".claude/unattended").mkdir(parents=True)
    if mode: (root/".claude/overseer/mode").write_text(mode)
    if status: (root/".claude/unattended/state.json").write_text(json.dumps({"status":status,"node":"S3"}))
    if count is not None: (root/".claude/overseer/.continue_count").write_text(str(count))
    e = dict(os.environ); e["CLAUDE_PROJECT_DIR"]=str(root); e.pop("CLAUDE_UNATTENDED_SESSION",None)
    if env: e.update(env)
    r = subprocess.run([sys.executable,HOOK],input=json.dumps({"last_assistant_message":msg}),
                       capture_output=True,text=True,env=e)
    return r.stdout.strip()

CASES = [
    ("unattended + session working -> MUST BLOCK",      dict(mode="unattended",status="working"),      True),
    ("unattended + unit-done       -> MUST BLOCK",      dict(mode="unattended",status="unit-done"),    True),
    ("unattended + finished        -> must pass",       dict(mode="unattended",status="finished"),     False),
    ("unattended + parked          -> must pass",       dict(mode="unattended",status="parked"),       False),
    ("ATTENDED  + session working  -> must pass",       dict(mode="attended",status="working"),        False),
    ("no mode file + working       -> must pass",       dict(mode=None,status="working"),              False),
    ("spawned session (env set)    -> must pass",       dict(mode="unattended",status="working",
                                                            env={"CLAUDE_UNATTENDED_SESSION":"1"}),    False),
    ("continue budget exhausted    -> must pass",       dict(mode="unattended",status="working",
                                                            count=25),                                 False),
]
fails=[]
for name,kw,should_block in CASES:
    out = run(**kw)
    blocked = '"decision": "block"' in out or '"decision":"block"' in out
    ok = blocked == should_block
    print(f"  {'ok ' if ok else 'FAIL'} {name:44} -> {'BLOCK' if blocked else 'pass'}")
    if not ok: fails.append(name)

if fails:
    print(f"\nFAIL ({len(fails)})"); sys.exit(1)
print(f"\nPASS: {len(CASES)}/{len(CASES)}")
