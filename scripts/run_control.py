"""Live, clean queue boundaries stored outside the writable story worktrees."""

from contextlib import contextmanager
import datetime
import fcntl
import json
from pathlib import Path

from agent_runtime import atomic_json
from common import parse_story
from execution_state import canonical, ControllerWatch


@contextmanager
def lock(directory):
    with (Path(directory) / "control.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def read(directory, planned):
    path = Path(directory) / "stop-after.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or data.get("stop_after") not in planned):
        raise ValueError("invalid live stop-after request")
    return data["stop_after"]


def request(session_path, story):
    path = Path(session_path).resolve(strict=True)
    session = json.loads(path.read_text())
    _, common = canonical(session["repo"])
    if path.name != "session.json" or path.parent.parent != common / "auto-bmad-sessions":
        raise ValueError("invalid queue session path")
    parsed = parse_story(story)
    if not parsed:
        raise ValueError("stop-after requires a story ID from this queue")
    story = f"{parsed[0]}-{parsed[1]}"
    with lock(path.parent):
        session = json.loads(path.read_text())
        if session.get("kind") != "queue" or session.get("control_version") != 1:
            raise ValueError("this run does not support live stop-after; it must be started with the updated runtime")
        if session.get("status") != "running" or not ControllerWatch(session["repo"], path).alive():
            raise ValueError("the queue is no longer running")
        if not session.get("control_open", True):
            raise ValueError("the queue is already finalizing; the stop target can no longer be changed")
        planned = session["planned_stories"]
        if story not in planned:
            raise ValueError("the requested story does not belong to this run's planned queue")
        boundary = planned.index(story)
        started = set(session.get("started_stories", []))
        beyond = [s for s in planned[boundary + 1:] if s in started]
        atomic_json(path.parent / "stop-after.json", {
            "schema_version": 1, "stop_after": story,
            "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        return {"accepted": True, "stop_after": story, "already_started_after": beyond,
                "effect": "finish-already-started" if beyond else "stop-after-target"}
