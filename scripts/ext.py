#!/usr/bin/env python3
"""auto-bmad extensions: a three-layer config, events and hooks.

The config is merged from three layers, each later one wins:
  1. defaults.toml in the plugin root — defaults;
  2. personal: $AUTO_BMAD_CONFIG or ~/.config/auto-bmad/config.toml;
  3. project: <repo>/.auto-bmad.toml (kept in the project's git).
Tables merge by key. The table arrays [[hook]] and [[verify]] merge by the `name` field,
the way BMad merges review_layers by id: an entry with the same name adds and overrides
fields. `enabled = false` turns an extension off. A broken layer is skipped with a warning:
extensions never stop a run.

A hook is a command on an event. The core runs it through sh from the project root and
sends JSON to stdin: {"event", "repo", "unattended", "story", "title", "epic", "level",
"spec", "commit", "status", "questions_file", "data"}. The hook answers JSON on stdout:
  ok       — true / false;
  message  — one line for the human (optional);
  link     — a link for the report (optional);
  files    — files the hook created in the tree: the skill commits them;
  ask      — a question to the human: {"question", "options": [{"id", "label", "description"}]}.
The skill passes the human's answer with the `answer` command: the hook gets the event
"answer" with data.answer = id of the chosen option.

Events: run-start, story-start, story-done, story-blocked, wave-merged, verify-done,
run-end, answer. Every event (no texts, only ids, statuses and time) is appended
to <repo>/.auto-bmad/events.jsonl and to $AUTO_BMAD_EVENTS_FILE when it is set.

Usage:
    ext.py config [--repo .]
    ext.py fire <event> [--story 5-3] [--title T] [--epic N] [--level L] [--spec P]
                [--commit SHA] [--status done|blocked] [--questions-file P]
                [--data JSON] [--repo .]
    ext.py answer --hook <name> --option <id> [--repo .]

Always prints JSON on stdout. `fire` and `answer` exit 0 whatever the hooks do:
a hook error is a line in results[].error, and the run does not stop on it.
Exit 1 — a call error (no such directory, unknown hook in answer).
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import tomllib

from gitexclude import ensure_excluded

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS = os.path.join(PLUGIN_ROOT, "defaults.toml")
USER_CONFIG = os.path.expanduser("~/.config/auto-bmad/config.toml")
PROJECT_CONFIG = ".auto-bmad.toml"
STATE_DIR = ".auto-bmad"
EVENTS = ("run-start", "story-start", "story-done", "story-blocked", "wave-merged",
          "verify-done", "run-end", "answer")
NAMED = ("hook", "verify")          # table arrays merged by name
DEFAULT_TIMEOUT = 120
# Payload fields that go to the events journal: ids and statuses only.
LOGGED = ("story", "epic", "level", "status", "commit")


def unattended():
    """No human present: an external runner set a time window deadline, or the explicit flag."""
    return bool(os.environ.get("AUTO_BMAD_DEADLINE") or os.environ.get("AUTO_BMAD_UNATTENDED"))


def layers(repo):
    """[(layer name, path)] in merge order."""
    return [("defaults", DEFAULTS),
            ("user", os.environ.get("AUTO_BMAD_CONFIG") or USER_CONFIG),
            ("project", os.path.join(repo, PROJECT_CONFIG))]


def merge_named(base, extra):
    out = [dict(x) for x in base]
    index = {x.get("name"): i for i, x in enumerate(out) if x.get("name")}
    for item in extra:
        name = item.get("name")
        if name in index:
            out[index[name]] = merge(out[index[name]], item)
        else:
            if name:
                index[name] = len(out)
            out.append(dict(item))
    return out


def merge(base, extra):
    out = dict(base)
    for key, value in extra.items():
        if key in NAMED and isinstance(value, list):
            out[key] = merge_named(out.get(key, []), value)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def load(repo):
    """→ (config, sources, warnings)."""
    cfg, sources, warnings = {}, [], []
    for name, path in layers(repo):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "rb") as fh:
                cfg = merge(cfg, tomllib.load(fh))
            sources.append({"layer": name, "path": path})
        except (OSError, tomllib.TOMLDecodeError) as e:
            warnings.append(f"{path}: unreadable, layer skipped — {e}")
    for key in NAMED:
        cfg[key] = [x for x in cfg.get(key, []) if x.get("enabled", True) is not False]
    return cfg, sources, warnings


def expand(text):
    return text.replace("@plugin", PLUGIN_ROOT) if isinstance(text, str) else text


def log_event(repo, payload, results):
    row = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "event": payload["event"]}
    row.update({k: payload[k] for k in LOGGED if payload.get(k) not in (None, "")})
    if results:
        row["hooks"] = {r["name"]: r["code"] for r in results}
    line = json.dumps(row, ensure_ascii=False) + "\n"
    targets = []
    state = os.path.join(repo, STATE_DIR)
    if os.path.isdir(os.path.join(repo, ".git")) or os.path.isfile(os.path.join(repo, ".git")):
        ensure_excluded(repo, STATE_DIR + "/")
        targets.append(os.path.join(state, "events.jsonl"))
    if os.environ.get("AUTO_BMAD_EVENTS_FILE"):
        targets.append(os.environ["AUTO_BMAD_EVENTS_FILE"])
    for path in targets:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass


def run_hook(hook, payload, repo):
    name = hook.get("name", "?")
    res = {"name": name, "code": None, "ok": False}
    command = expand(hook.get("command"))
    if not command:
        res["error"] = "the hook has no command"
        return res
    try:
        proc = subprocess.run(["sh", "-c", command], cwd=repo, input=json.dumps(payload),
                              capture_output=True, text=True,
                              timeout=hook.get("timeout", DEFAULT_TIMEOUT))
    except subprocess.TimeoutExpired:
        res["error"] = f"the hook did not answer in {hook.get('timeout', DEFAULT_TIMEOUT)} s"
        return res
    except OSError as e:
        res["error"] = f"the hook did not start: {e}"
        return res
    res["code"] = proc.returncode
    try:
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        if not isinstance(out, dict):
            raise ValueError("the answer is not an object")
    except ValueError:
        res["error"] = "the hook answer is not JSON: " + (proc.stdout.strip()[:200] or proc.stderr.strip()[:200])
        return res
    for key in ("message", "link", "files", "ask"):
        if out.get(key):
            res[key] = out[key]
    res["ok"] = bool(out.get("ok", proc.returncode == 0))
    if not res["ok"] and not res.get("message"):
        res["error"] = out.get("error") or proc.stderr.strip()[:200] or f"exit code {proc.returncode}"
    return res


def payload_from(args, event):
    data = {}
    if getattr(args, "data", None):
        try:
            data = json.loads(args.data)
        except ValueError:
            data = {"raw": args.data}
    return {"event": event, "repo": os.path.abspath(args.repo), "unattended": unattended(),
            "story": getattr(args, "story", None), "title": getattr(args, "title", None),
            "epic": getattr(args, "epic", None), "level": getattr(args, "level", None),
            "spec": getattr(args, "spec", None), "commit": getattr(args, "commit", None),
            "status": getattr(args, "status", None),
            "questions_file": getattr(args, "questions_file", None), "data": data}


def fire(repo, payload, only=None):
    cfg, _, warnings = load(repo)
    results = []
    for hook in cfg.get("hook", []):
        if only and hook.get("name") != only:
            continue
        if payload["event"] not in hook.get("events", []) and not only:
            continue
        results.append(run_hook(hook, payload, repo))
    log_event(repo, payload, results)
    asks = [{"hook": r["name"], **r["ask"]} for r in results if r.get("ask")]
    if payload["unattended"]:
        asks = []                     # nobody to ask: the question would hang until morning
    return {"event": payload["event"], "results": results, "asks": asks,
            "files": sorted({f for r in results for f in r.get("files", [])}),
            "warnings": warnings}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"error": message}, ensure_ascii=False))
        print(message, file=sys.stderr)
        sys.exit(1)


def main(argv=None):
    ap = _Parser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    c = sub.add_parser("config")
    c.add_argument("--repo", default=".")
    f = sub.add_parser("fire")
    f.add_argument("event", choices=[e for e in EVENTS if e != "answer"])
    for opt in ("story", "title", "epic", "level", "spec", "commit", "status",
                "questions-file", "data"):
        f.add_argument(f"--{opt}")
    f.add_argument("--repo", default=".")
    a = sub.add_parser("answer")
    a.add_argument("--hook", required=True)
    a.add_argument("--option", required=True)
    a.add_argument("--repo", default=".")
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        ap.error(f"no such directory {repo}")

    if args.cmd == "config":
        cfg, sources, warnings = load(repo)
        out = {"config": cfg, "sources": sources, "warnings": warnings}
    elif args.cmd == "fire":
        out = fire(repo, payload_from(args, args.event))
    else:
        cfg, _, _ = load(repo)
        if not any(h.get("name") == args.hook for h in cfg.get("hook", [])):
            ap.error(f"no hook {args.hook}")
        payload = payload_from(args, "answer")
        payload["data"] = {"answer": args.option}
        out = fire(repo, payload, only=args.hook)
    for w in out.get("warnings", []):
        print(w, file=sys.stderr)
    for r in out.get("results", []):
        if r.get("error"):
            print(f"hook {r['name']}: {r['error']}", file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
