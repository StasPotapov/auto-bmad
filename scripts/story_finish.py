#!/usr/bin/env python3
"""Finishing steps of a story (or a wave) in one call.

The skill used to chain them in one Bash command: the open questions, the sprint sync,
the tracking commit, the hook events and the statistics. Without a human, the auto mode
classifier checks such a chain as a whole and at times denies it, and then every part is
lost. Here each step runs on its own: a failed step is reported and the others still run.

The input is a JSON file (the skill writes it with the Write tool, no heredoc):

    {
      "epic": 1, "level": "normal",
      "stories": [
        {"story": "1-3", "title": "CSV import", "spec": "<path>", "commit": "<sha>",
         "status": "done | blocked",
         "questions": "<the Needs attention items as is; empty — none>",
         "verify": {"status": "pass | problem | skipped", "fixes": 0, "checks": {"name": "pass"}}}
      ],
      "wave": 2,
      "run_end": {"status": "done | blocked | window", "done": 3, "left": 0}
    }

All keys are optional except `epic` when `stories` is empty. In this order the script:
  1. fires verify-done for each story with `verify`;
  2. moves the `done` stories to done in sprint-status.yaml (one sync call);
  3. writes each story's section of the open questions file (or removes it: no questions);
  4. commits the tracking and the questions file in one commit;
  5. fires story-done / story-blocked per story, then wave-merged when `wave` is set;
  6. fires run-end when `run_end` is set;
  7. records the session statistics when `--session` is given.
Files a hook returns in `files` are committed right after its event, with its message.

Usage:
    story_finish.py --input <file.json> [--session <id>] [--repo .]

Prints a short JSON: `ok`, `commit` (the tracking commit or null), `steps` (one line per
step with `ok` and a detail), `messages` and `links` from hooks, `warnings`, `failed`.
Exit 0 — every step went through (hook errors do not count: hooks never stop a run),
1 — call error (no input, broken JSON), 2 — some step failed: see `failed`.
"""

import argparse
import json
import os
import subprocess
import sys

from common import SPRINT_REL, commit_paths as commit, parse_story, questions_file
from ext import fire, payload
from gitexclude import ensure_excluded

HERE = os.path.dirname(os.path.abspath(__file__))


def script(name, args, repo):
    """Run a sibling script → (exit code, parsed JSON or {"error": …})."""
    proc = subprocess.run([sys.executable, os.path.join(HERE, name), *args, "--repo", repo],
                          capture_output=True, text=True)
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        out = {"error": (proc.stderr or proc.stdout).strip()[:300] or f"exit code {proc.returncode}"}
    return proc.returncode, out


STATUSES = ("done", "blocked")


class Run:
    def __init__(self, repo):
        self.repo = repo
        self.steps, self.messages, self.links, self.warnings, self.failed = [], [], [], [], []

    def step(self, name, ok, detail=None):
        row = {"step": name, "ok": ok}
        if detail:
            row["detail"] = detail
        self.steps.append(row)
        if not ok:
            self.failed.append(name)

    def event(self, event, story=None, data=None, **fields):
        name = f"{event} {story}" if story else event
        try:
            out = fire(self.repo, payload(event, self.repo, data, story=story, **fields))
        except Exception as e:  # a broken config must not stop the other steps
            self.step(name, False, f"{type(e).__name__}: {e}")
            return
        errors = []
        for r in out["results"]:
            if r.get("message"):
                self.messages.append(r["message"])
            if r.get("link"):
                self.links.append({"story": story, "name": r["name"], "link": r["link"]})
            if r.get("error"):
                errors.append(f"hook {r['name']} failed: {r['error']}")
        self.warnings += out.get("warnings", []) + errors
        if out["files"]:
            message = next((r["message"] for r in out["results"] if r.get("files") and r.get("message")),
                           f"chore: files from auto-bmad hooks ({name})")
            sha, err = commit(self.repo, out["files"], message)
            self.step(f"commit hook files ({name})", err is None, err or sha)
        self.step(name, True, f"{len(out['results'])} hooks" if out["results"] else None)


def finish(spec, repo, session=None):
    run = Run(repo)
    stories = spec.get("stories") or []
    level = spec.get("level")
    epic = spec.get("epic")
    if not isinstance(stories, list) or not all(isinstance(s, dict) for s in stories):
        raise ValueError("`stories` must be a list of objects")
    if spec.get("run_end") is not None and not isinstance(spec["run_end"], dict):
        raise ValueError("`run_end` must be an object")
    for s in stories:
        parsed = parse_story(str(s.get("story", "")))
        if not parsed:
            raise ValueError(f"cannot parse the story id: {s.get('story')!r}")
        s["story"] = f"{parsed[0]}-{parsed[1]}"
        s["epic"] = parsed[0]
        epic = epic if epic is not None else parsed[0]
        s["status"] = str(s.get("status") or "done").strip().lower()
        if s["status"] not in STATUSES:
            raise ValueError(f"story {s['story']}: status must be done or blocked, not {s['status']!r}")
        if s.get("verify") is not None and not isinstance(s["verify"], dict):
            raise ValueError(f"story {s['story']}: `verify` must be an object")
    if epic is None and (stories or spec.get("run_end")):
        raise ValueError("no epic: give `epic` or at least one story")
    done = [s for s in stories if s["status"] == "done"]
    blocked = [s for s in stories if s["status"] != "done"]

    for s in stories:
        v = s.get("verify")
        if v:
            run.event("verify-done", s["story"], status=v.get("status"),
                      data={"fixes": v.get("fixes", 0), "checks": v.get("checks", {})})

    to_commit = []
    if done:
        args = [a for s in done for a in ("--story", s["story"])]
        code, out = script("sync_sprint.py", args, repo)
        missing = out.get("not_found") or []
        if code == 0:
            to_commit.append(SPRINT_REL)
        if missing:
            run.step("sync", False, "not in sprint-status.yaml: " + ", ".join(missing))
        elif code == 0:
            run.step("sync", True, ", ".join(f"{c['key']} → {c['to']}" for c in
                                             out.get("stories_changed", []) + out.get("epics_changed", [])))
        else:
            # code 2 with every story found: they already are done (a resumed story) — not a failure
            run.step("sync", code == 2, out.get("error"))

    for s in stories:
        text = str(s.get("questions") or "").strip()
        if s["status"] != "done" and not text:
            run.step(f"questions {s['story']}", False, "a blocked story without the blocker text")
            continue
        args = ["--story", s["story"]]
        if text:
            path = os.path.join(repo, ".auto-bmad", "finish", f"questions-{s['story']}.md")
            try:
                ensure_excluded(repo, ".auto-bmad/")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text + "\n")
            except OSError as e:
                run.step(f"questions {s['story']}", False, f"cannot write the items file: {e}")
                continue
            args += ["--title", s.get("title") or "", "--spec", s.get("spec") or "",
                     "--commit", s.get("commit") or "", "--status", "done" if s["status"] == "done" else "blocked",
                     "--items-file", path]
        else:
            args.append("--none")
        code, out = script("open_questions.py", args, repo)
        run.warnings += out.get("warnings") or []
        if code == 0:
            to_commit.append(questions_file(s["epic"]))
            run.step(f"questions {s['story']}", True, out.get("action"))
        elif code == 2:
            # nothing to remove, or a human wrote the file: the run goes on, the text is in the report
            if "no auto-bmad marker" in (out.get("error") or ""):
                run.warnings.append(out["error"])
            run.step(f"questions {s['story']}", True, out.get("error"))
        else:
            run.step(f"questions {s['story']}", False, out.get("error"))

    tracking = None
    if to_commit:
        ids = ", ".join(s["story"] for s in done)
        if not done:
            message = (f"docs: open questions for epic {blocked[0]['epic']} — story "
                       f"{', '.join(s['story'] for s in blocked)} blocked")
        elif len(done) == 1:
            message = f"chore: story {ids} → done in sprint tracking"
        else:
            message = f"chore: stories {ids} → done in sprint tracking"
        tracking, err = commit(repo, to_commit, message)
        run.step("commit", err is None, err or tracking or "nothing changed")

    for s in stories:
        event = "story-done" if s["status"] == "done" else "story-blocked"
        run.event(event, s["story"], status=s["status"], title=s.get("title"), epic=s["epic"],
                  level=level, spec=s.get("spec"), commit=s.get("commit"),
                  questions_file=questions_file(s["epic"]))
    if spec.get("wave") is not None:
        run.event("wave-merged", epic=epic, level=level,
                  data={"wave": spec["wave"], "stories": [s["story"] for s in done]})
    end = spec.get("run_end")
    if end:
        run.event("run-end", epic=epic, level=level, status=end.get("status"),
                  data={"done": end.get("done"), "left": end.get("left")})

    if session:
        code, out = script("stats.py", ["record", "--session", session], repo)
        # statistics are auxiliary: code 2 (no story-runner runs yet) is not a failure
        run.step("stats", code in (0, 2), out.get("error") or out.get("note")
                 or f"{out.get('recorded')} records")

    return {"ok": not run.failed, "commit": tracking, "steps": run.steps,
            "messages": run.messages, "links": run.links, "warnings": run.warnings,
            "failed": run.failed}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--input", required=True, help="JSON file with the stories and events")
    ap.add_argument("--session", help="the run session: record its statistics")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    try:
        if not os.path.isdir(repo):
            raise ValueError(f"no such directory {repo}")
        with open(a.input, encoding="utf-8") as fh:
            spec = json.load(fh)
        if not isinstance(spec, dict):
            raise ValueError("the input is not a JSON object")
        out = finish(spec, repo, a.session)
    except (OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1
    for line in out["warnings"]:
        print(line, file=sys.stderr)
    for row in out["steps"]:
        if not row["ok"]:
            print(f"{row['step']}: {row.get('detail')}", file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
