#!/usr/bin/env python3
"""A stand-in for `claude -p`: plays the next step of the plan in $FAKE_CLAUDE_PLAN (a JSON list in a file).

Steps: "ok" (writes the result file the prompt names), "bad" (writes an invalid result), "limit" (rejected window),
"crash" (exit 1, no result), "low" (ok, but reports 80% used). Each call logs its argv to $FAKE_CLAUDE_PLAN.calls.
"""

import json
import os
import sys
import time
from pathlib import Path

plan_f = Path(os.environ["FAKE_CLAUDE_PLAN"])
plan = json.loads(plan_f.read_text())
args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
with open(str(plan_f) + ".calls", "a") as fh:
    fh.write(json.dumps({"args": args, "cwd": os.getcwd(), "env_secret": "MTGR_BOT_TOKEN" in os.environ}) + "\n")
probe = prompt == "Reply with OK."
step = "ok" if probe else (plan.pop(0) if plan else "ok")
if not probe:
    plan_f.write_text(json.dumps(plan))
sid = args[args.index("--session-id") + 1] if "--session-id" in args else args[args.index("--resume") + 1]
reset = time.time() + 3600
util = {"low": 0.8}.get(step, 0.1)
status = "rejected" if step == "limit" else "allowed"
print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}))
print(
    json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": status,
                "unifiedWindows": {
                    "five_hour": {"utilization": util, "resetsAt": reset, "status": status},
                    "seven_day": {"utilization": 0.2, "resetsAt": reset + 86400, "status": "allowed"},
                },
            },
        }
    )
)
if step == "limit":
    print(
        json.dumps(
            {"type": "result", "subtype": "error", "is_error": True, "result": "usage limit reached", "session_id": sid}
        )
    )
    sys.exit(1)
if step == "crash":
    print("boom", file=sys.stderr)
    sys.exit(1)
if not probe:
    ep = Path.cwd()
    (ep / "factory").mkdir(exist_ok=True)
    if "script_result.json" in prompt:
        (ep / "script").mkdir(exist_ok=True)
        (ep / "script" / "script.md").write_text("# script")
        res = {
            "title": "Postgres reads pages",
            "hook": "Postgres never reads a row",
            "takeaway": "8 KB pages",
            "duration_s": 80,
            "scenes": [{"title": f"s{i}", "narration": "n"} for i in range(4)],
            "caption": "c",
            "hashtags": ["postgres"],
            "script_path": "script/script.md",
        }
        name = "script_result.json"
    else:
        (ep / "v.mp4").write_bytes(b"\0" * 1000)
        (ep / "v_cover.png").write_bytes(b"\x89PNG")
        res = {
            "title": "Pages",
            "video": "v.mp4",
            "cover": "v_cover.png",
            "caption": "A caption that is long enough.",
            "hashtags": ["postgres", "backend"],
            "duration_s": 80,
            "changed": ["caption"],
        }
        name = "post_result.json"
    if step == "bad":
        res = {"title": "x"}
    (ep / "factory" / name).write_text(json.dumps(res))
print(
    json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "done",
            "session_id": sid,
            "total_cost_usd": 1.5,
            "usage": {},
        }
    )
)
