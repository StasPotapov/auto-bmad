"""Offline BMAD role stand-in. No model dependencies."""
import json
from pathlib import Path
import sys
import subprocess

sys.stdin.read()
if sys.argv[1] == "write":
    Path("app.py").write_text("answer = 42\n")
if sys.argv[1] == "write-submodule":
    Path("library/app.py").write_text("answer = 99\n")
if sys.argv[1] == "switch-branch":
    subprocess.run(["git", "checkout", "-qb", "unexpected"], check=True)
answer = {"status": "done", "report": "role result"}
if sys.argv[1] == "invalid":
    answer["unexpected"] = True
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(answer)}}))
print(json.dumps({"type": "turn.completed", "usage": {"output_tokens": 5}}))
