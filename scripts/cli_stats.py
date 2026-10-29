"""Anonymous accounting from host-owned CLI sessions, independent of model reports."""

import collections
import datetime
import hashlib
import json
import re
from pathlib import Path

from agent_adapters import CodexResult
from execution_state import canonical, ControllerWatch

BASE = ("in", "out_est", "cache_read", "cache_write", "input_exact", "out_exact")


def read(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def revision(paths):
    return max((p.stat().st_mtime_ns for p in paths if p.exists()), default=0)


def metrics(folder, state, adapter):
    if isinstance(state.get("metrics"), dict):
        return state["metrics"]
    parser = CodexResult() if adapter == "codex" else None
    if parser:
        try:
            with (folder / "stdout.jsonl").open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            parser.consume(event)
                    except (ValueError, TypeError, AttributeError):
                        parser.failure = "incomplete accounting stream"
        except OSError:
            pass
        result = parser.snapshot()
        if not result["turns"]:
            if isinstance(state.get("usage"), dict):
                result["turns"] = [state["usage"]]
            result["unfinished_turn"] = result["unfinished_turn"] or state.get("execution_status") != "completed"
        return result
    usage = state.get("usage")
    return {"turns": [usage] if isinstance(usage, dict) else [], "tools": {},
            "unfinished_turn": state.get("execution_status") != "completed"}


def count(value):
    return value if type(value) is int and value >= 0 else None


def counters(data):
    turns = data.get("turns") or []
    values = {k: [] for k in ("input_tokens", "cached_input_tokens", "output_tokens")}
    for turn in turns:
        turn = turn if isinstance(turn, dict) else {}
        for key in values:
            values[key].append(count(turn.get(key)))
    # A partial turn is unknown, not a free call. Report measured subtotals separately
    # from completeness; cache is a subset of Codex input, never an additional input bill.
    usage = {k: sum(v for v in ns if v is not None) if any(v is not None for v in ns) else None
             for k, ns in values.items()}
    pairs = list(zip(values["input_tokens"], values["cached_input_tokens"]))
    valid_cache = bool(turns) and all(i is not None and c is not None and c <= i for i, c in pairs)
    cached = [c for i, c in pairs if c is not None and (i is None or c <= i)]
    fresh = [i - c for i, c in pairs if i is not None and c is not None and c <= i]
    usage["cached_input_tokens"] = sum(cached) if cached else None
    usage["uncached_input_tokens"] = sum(fresh) if fresh else None
    complete = bool(turns) and all(all(n is not None for n in ns) for ns in values.values()) and valid_cache
    status = "complete" if complete and not data.get("unfinished_turn") else (
        "partial" if any(v is not None for v in usage.values()) else "unavailable")
    acc = dict.fromkeys(BASE, 0)
    acc.update({"in": usage["uncached_input_tokens"] or 0, "cache_read": usage["cached_input_tokens"] or 0,
                "input_exact": usage["input_tokens"] or 0, "out_exact": usage["output_tokens"] or 0,
                "calls": 1, "usage_complete": int(status == "complete"),
                "usage_partial": int(status == "partial"), "usage_unavailable": int(status == "unavailable")})
    return usage, acc, status


def call(folder, identity, defaults, result=None):
    state = read(folder / "status.json")
    if not state and not folder.exists():
        return None
    meta = {**defaults, **state.get("call", {})}
    adapter = meta.get("adapter", "codex")
    snapshot = metrics(folder, state, adapter)
    usage, acc, availability = counters(snapshot)
    final = result or state
    if state.get("execution_status") not in ("completed", "failed") and availability == "complete":
        availability = "partial"
        acc.update(usage_complete=0, usage_partial=1)
    ended = state.get("ended")
    started = state.get("started")
    if (not ended and state.get("execution_status") not in ("starting", "running", None)
            and (folder / "status.json").exists()):
        end = datetime.datetime.fromtimestamp((folder / "status.json").stat().st_mtime, datetime.timezone.utc)
        ended = end.isoformat()
        if isinstance(state.get("seconds"), (int, float)):
            started = (end - datetime.timedelta(seconds=state["seconds"])).isoformat()
    return {"id": identity, "role": meta.get("role", "?"), "adapter": adapter,
            "model_requested": meta.get("model_requested", meta.get("model", "?")), "model_observed": None,
            "profile_id": meta.get("profile_id"), "layer_id": meta.get("layer_id"),
            "started": started, "ended": ended, "seconds": state.get("seconds"),
            "execution_status": final.get("execution_status", state.get("execution_status", "interrupted")),
            "usage": usage, "usage_status": availability, "tokens": acc,
            "tools": {k: v for k, v in snapshot.get("tools", {}).items()
                      if type(v) is int and v >= 0},
            "_revision": revision([folder / "status.json", folder / "stdout.jsonl"])}


def collect_session(path):
    from stats import add_tokens, total, review, minutes
    directory = path.parent
    session = read(path)
    if session.get("kind") == "queue" or not session.get("story"):
        return []
    manifest = read(directory / "manifest.json")
    profiles = manifest.get("roles", {})
    calls = []
    for folder in sorted(directory.glob("controller-*")):
        if folder.is_dir() and re.fullmatch(r"controller-\d+", folder.name):
            item = call(folder, directory.name + "/" + folder.name,
                        {"role": "story-runner", **profiles.get("story-runner", {})},
                        read(directory / (folder.name + ".result.json")))
            if item:
                calls.append(item)
    for attempt in sorted((directory / "attempts").glob("*")):
        request, result = read(attempt / "request.json"), read(attempt / "result.json")
        role = request.get("role", result.get("role", "?"))
        item = call(attempt / "process", directory.name + "/" + attempt.name,
                    {"role": role, **profiles.get(role, {}), "layer_id": request.get("layer_id")}, result)
        if item:
            calls.append(item)
    if not calls:
        return []
    by_model, by_role_model, agents, tools = {}, {}, collections.Counter(), collections.Counter()
    for item in calls:
        model, role = item["model_requested"], item["role"]
        add_tokens(by_model, {model: item["tokens"]})
        add_tokens(by_role_model.setdefault(role, {}), {model: item["tokens"]})
        agents[role] += 1
        tools.update(item["tools"])
    result = read(directory / "result.json")
    status = result.get("execution_status", session.get("status", "interrupted"))
    if status in ("running", "stopping"):
        try:
            active = ControllerWatch(session["repo"], path).alive()
        except (OSError, ValueError):
            active = False
        if not active:
            status = "interrupted"
    started = min((c["started"] for c in calls if c["started"]), default=None)
    ended = max((c["ended"] for c in calls if c["ended"]), default=None)
    rev = max(revision([path, directory / "result.json"]), *(c.pop("_revision") for c in calls))
    story = session["story"]
    return [{"id": f"cli:{directory.name}:{story}", "session": "cli:" + directory.name,
             "source": "cli", "kind": "story", "story": story, "epic": int(story.split("-", 1)[0]),
             "level": manifest.get("level"), "queue_id": session.get("queue_id"),
             "status": "done" if result.get("story_completed") else status,
             "execution_status": status, "started": started, "ended": ended, "minutes": minutes(started, ended),
             "commit": result.get("head_commit"), "agents": dict(agents), "tools": dict(tools), "calls": calls,
             "tokens": {"total": total(by_model), "by_model": by_model,
                        "by_role": {role: total(models) for role, models in by_role_model.items()},
                        "by_role_model": by_role_model},
             "measurement": {"output": "reported", "input": "reported", "model": "requested",
                             "cache_write": "unavailable"},
             "review": review(result.get("spec"), session.get("repo")), "revision": rev}]


def collect_attempt(attempt):
    from stats import total, minutes
    result, request = read(attempt / "result.json"), read(attempt / "request.json")
    item = call(attempt / "process", "agent/" + attempt.name, {**request, **result}, result)
    if not item:
        return []
    task = request.get("task_id", "?")
    if not isinstance(task, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", task):
        task = "task-" + hashlib.sha256(str(task).encode()).hexdigest()[:16]
    story = bool(re.fullmatch(r"\d+-\d+[a-z]?", task))
    model, role = item["model_requested"], item["role"]
    measured = {model: item["tokens"]}
    return [{"id": "cli-agent:" + attempt.name, "session": "cli-agent:" + attempt.name,
             "source": "cli", "kind": "task", "scope": "role", "story_completed": False, "story": task,
             "epic": int(task.split("-", 1)[0]) if story else None, "level": None,
             "status": item["execution_status"],
             "execution_status": item["execution_status"], "started": item["started"], "ended": item["ended"],
             "minutes": minutes(item["started"], item["ended"]), "agents": {role: 1}, "tools": item["tools"],
             "revision": item.pop("_revision"), "calls": [item],
             "tokens": {"total": total(measured), "by_model": measured, "by_role": {role: total(measured)},
                        "by_role_model": {role: measured}},
             "measurement": {"output": "reported", "input": "reported", "model": "requested", "cache_write": "unavailable"}}]


def attempts(repo):
    from common import git
    trees = git(str(repo), "worktree", "list", "--porcelain", "-z")
    roots = [Path(s[len("worktree "):]) for s in trees.stdout.split("\0") if s.startswith("worktree ")]
    return [path for root in roots for path in (root / ".auto-bmad/agents").glob("*") if path.is_dir()]


def sessions(repo):
    _, common = canonical(repo)
    return sorted((common / "auto-bmad-sessions").glob("*/session.json"))


def find(repo, identity):
    _, common = canonical(repo)
    parent = common / "auto-bmad-sessions"
    candidate = Path(identity)
    if not candidate.is_absolute():
        candidate = parent / identity.removeprefix("cli:") / "session.json"
    if candidate.name != "session.json" or not candidate.resolve().is_relative_to(parent.resolve()):
        return None
    return candidate if candidate.is_file() else None


def record(repo, identity=None):
    from stats import save
    paths = [find(repo, identity)] if identity else sessions(repo)
    if identity and paths[0] and read(paths[0]).get("kind") == "queue":
        queue = read(paths[0])
        children = {str(v.get("session")) for v in queue.get("stories", [])}
        paths = [p for p in sessions(repo) if str(p) in children or read(p).get("queue_id") == paths[0].parent.name]
    rows = [row for path in paths if path for row in collect_session(path)]
    if not identity:
        rows += [row for attempt in attempts(repo) for row in collect_attempt(attempt)]
    if not rows:
        return {"recorded": 0, "model_started": False}
    path = save(repo, rows)
    return {"recorded": len(rows), "file": path, "model_started": False}


def publish(repo, session):
    """Accounting is best effort and never changes the story's quality gates."""
    try:
        return record(str(repo), str(session) if session is not None else None)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        return {"recorded": 0, "error": str(e), "model_started": False}


def publish_attempt(repo, attempt):
    from stats import save
    try:
        rows = collect_attempt(attempt)
        return {"recorded": len(rows), "file": save(str(repo), rows), "model_started": False} if rows else {"recorded": 0}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        return {"recorded": 0, "error": str(e)}
