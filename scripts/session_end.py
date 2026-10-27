#!/usr/bin/env python3
"""SessionEnd hook of the plugin: records the session statistics as a safety net.

The skill calls `stats record` itself, but a denied or skipped call loses the session.
Claude Code runs this hook, not the model, so permissions do not apply to it. A plugin
SessionEnd hook gets 1.5 s, so the record runs in a detached process and the hook exits
at once. Recording a session again replaces its rows, so a double record is safe.

Only sessions that ran a bmad-story-runner subagent in a git repository are recorded;
others exit silently.
Input: the hook JSON on stdin (session_id, transcript_path, cwd). Always exits 0.
"""

import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def ran_story_runner(transcript):
    sub_dir = os.path.join(transcript[:-len(".jsonl")], "subagents")
    for meta in glob.glob(os.path.join(sub_dir, "*.meta.json")):
        try:
            with open(meta, encoding="utf-8") as fh:
                if "bmad-story-runner" in (json.load(fh).get("agentType") or ""):
                    return True
        except (OSError, ValueError):
            continue
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    sid, transcript, cwd = data.get("session_id"), data.get("transcript_path") or "", data.get("cwd")
    if not (sid and cwd and transcript.endswith(".jsonl") and ran_story_runner(transcript)):
        return 0
    # the shared .git of a worktree lives in the main tree: record there, not in the worktree
    try:
        top = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             capture_output=True, text=True, timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if top.returncode:
        return 0                      # not a git repository: no project to record into
    repo = os.path.dirname(top.stdout.strip())
    launch([sys.executable, os.path.join(HERE, "stats.py"), "record", "--session", sid, "--repo", repo])
    return 0


def launch(command):
    """Start a command that outlives the hook and the session."""
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


if __name__ == "__main__":
    sys.exit(main())
