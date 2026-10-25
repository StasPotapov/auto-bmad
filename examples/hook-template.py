#!/usr/bin/env python3
"""auto-bmad hook template: copy, edit `handle`, register in a config layer.

Register (in ~/.config/auto-bmad/config.toml or the project's .auto-bmad.toml):

    [[hook]]
    name = "notify"
    events = ["story-done", "story-blocked", "run-end"]
    command = "python3 ~/my-hooks/notify.py"
    timeout = 60

stdin  — JSON: event, repo, unattended, story, title, epic, level, spec, commit, status,
         questions_file, data.
stdout — JSON: ok, message (shown in the report), link, files (created in the tree,
         auto-bmad commits them), ask (a question for a human; only on run-start and
         only when a human is present).
A hook never stops a run: errors become a line in the report.
"""

import json
import sys


def handle(event):
    kind = event.get("event")
    if kind == "story-done":
        return {"ok": True, "message": f"story {event.get('story')} done: {event.get('commit')}"}
    if kind == "story-blocked":
        return {"ok": True, "message": f"story {event.get('story')} blocked"}
    if kind == "run-end":
        return {"ok": True, "message": f"run finished: {event.get('status')}"}
    return {"ok": True}


if __name__ == "__main__":
    try:
        result = handle(json.load(sys.stdin))
    except Exception as e:  # a hook must answer JSON even when it fails
        result = {"ok": False, "message": f"hook failed: {e}"}
    print(json.dumps(result, ensure_ascii=False))
