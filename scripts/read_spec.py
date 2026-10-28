#!/usr/bin/env python3
"""Finds a story's spec and reads its frontmatter.

Slug segments are compared AS NUMBERS, so `1-1` does not match `1-10`. Also the
fallback when the subagent returned a header that breaks the contract.

Usage:
    read_spec.py --story 1-3 [--repo .]
    read_spec.py --slug issue-12 [--repo .]     # a task outside the epics: spec-<slug>-*.md
    read_spec.py --story 1-3 --result [--repo .]  # plus the run result: no need to read the spec

`--result` adds `auto_run_result` (the last `## Auto Run Result` section), `commit` (the
story's engine commit) and `files` (the number of files in that commit). Not found — null.
The engine commit is the last commit since `baseline_revision` that changed both the spec and
code outside `_bmad-output/`: a later story's commit does not touch this spec. A spec that is
never committed with code — the last commit that changed code.

With `--story` it also reads the story's status in sprint-status.yaml (`sprint_status`). A
`done` spec of a story in `review` there gets the route `review`: the code is committed, and
the engine runs a fresh review pass on the spec path. Then `commit` and `later_commits` (code
commits of other work after it) are in the answer without `--result`: the engine reviews the
diff since the baseline, so later commits get into that review. A `review` story with no spec
gets `ask-human`: there is code but no spec the engine can review against (`plan` takes such
stories out of the queue).

Exit 0 — exactly one spec found, 1 — error, 2 — zero or more than one.
"""

import argparse
import glob
import subprocess
import json
import os
import re
import sys

from common import ARTIFACTS, SPRINT_REL, is_story_spec, parse_story
from plan_run import read_status, story_entry


def frontmatter(path):
    """Flat YAML frontmatter parse: top-level scalars plus list sizes."""
    fields, lists, current = {}, {}, None
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    if not lines or lines[0].strip() != "---":
        return fields, lists
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith((" ", "\t")):
            if current and line.strip().startswith("- "):
                lists[current] = lists.get(current, 0) + 1
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        current = key if not value else None
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            lists[key] = len([x for x in inner.split(",") if x.strip()]) if inner else 0
            current = None
        elif value:
            fields[key] = value.strip("'\"")
    return fields, lists


RESULT_LIMIT = 6000


REV = re.compile(r"^[0-9a-fA-F]{4,64}$")


def section(path, heading):
    """The body of the last `## <heading>` section, up to the next `## `; none — None.

    The engine appends result details on a HALT, so a later section is the newer one.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read().replace("\r\n", "\n")
    found = list(re.finditer(rf"^## {re.escape(heading)}[ \t]*$", text, re.M))
    if not found:
        return None
    m = found[-1]
    end = re.search(r"^## ", text[m.end():], re.M)
    body = text[m.end():m.end() + end.start() if end else len(text)].strip()
    return body[:RESULT_LIMIT] + ("\n…(cut)" if len(body) > RESULT_LIMIT else "")


def sprint_status(repo, epic, num):
    """The story's status in sprint-status.yaml; no file or no key — None."""
    entries, _ = read_status(os.path.join(repo, SPRINT_REL))
    return story_entry(entries or [], epic, num)[1]


def baseline(fields):
    """The spec's baseline revision; older engine versions wrote `baseline_commit`."""
    return (fields.get("baseline_revision") or fields.get("baseline_commit") or "").strip()


def git_out(repo, *args):
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return proc.stdout.strip() or None if proc.returncode == 0 else None


CODE = (".", ":(exclude)_bmad-output")


def story_commit(path, repo, fields):
    """→ (the story's engine commit, code commits after it that do not touch the spec); unknown — (None, None).

    The engine commits the spec together with the code; tracking and spec-only commits touch
    only _bmad-output/, and a later story's commit does not touch this spec.
    """
    base = baseline(fields)
    if not REV.match(base):
        return None, None
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(repo))
    own = (git_out(repo, "log", "--format=%h", f"{base}..HEAD", "--", rel) or "").split()
    commit = None
    for sha in own:
        names = (git_out(repo, "show", "--name-only", "--format=", sha) or "").splitlines()
        if any(n and not n.startswith("_bmad-output/") for n in names):
            commit = sha
            break
    if commit is None:
        # the spec was never committed with code: the last commit that changed code, later ones unknown
        return git_out(repo, "log", "-1", "--format=%h", f"{base}..HEAD", "--", *CODE), None
    later = (git_out(repo, "log", "--format=%h", f"{commit}..HEAD", "--", *CODE) or "").split()
    return commit, len([sha for sha in later if sha not in own])


def run_result(path, repo, fields):
    """The run result without reading the spec: the section, the engine commit and its files."""
    commit, _ = story_commit(path, repo, fields)
    files = None
    if commit:
        names = git_out(repo, "show", "--name-only", "--format=", commit)
        files = len(names.splitlines()) if names else 0
    return {"auto_run_result": section(path, "Auto Run Result"), "commit": commit, "files": files}


def main():
    ap = argparse.ArgumentParser()
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--story", help="story id, for example 1-3 or 1.3")
    target.add_argument("--slug", help="spec slug prefix of a task outside the epics, for example issue-12")
    ap.add_argument("--result", action="store_true",
                    help="also return the Auto Run Result section, the commit and the changed files")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    if args.story is not None:
        parsed = parse_story(args.story)
        if not parsed:
            message = f"cannot parse the story id: {args.story!r}"
            print(message, file=sys.stderr)
            print(json.dumps({"error": message}, ensure_ascii=False))
            return 1
        epic, num = parsed
        label = f"{epic}-{num}"
        sprint = sprint_status(args.repo, epic, num)

        def wanted(name):
            return is_story_spec(name, epic, num)
    else:
        slug = args.slug.strip()
        if not re.match(r"^[\w.-]+$", slug):
            message = f"cannot parse the spec slug: {args.slug!r}"
            print(message, file=sys.stderr)
            print(json.dumps({"error": message}, ensure_ascii=False))
            return 1
        label = slug
        sprint = None

        def wanted(name):
            return name == f"spec-{slug}.md" or (name.startswith(f"spec-{slug}-") and name.endswith(".md"))

    directory = os.path.join(args.repo, ARTIFACTS)
    if not os.path.isdir(directory):
        message = f"missing folder {directory}"
        print(message, file=sys.stderr)
        print(json.dumps({"error": message}, ensure_ascii=False))
        return 1

    matches = []
    for path in sorted(glob.glob(os.path.join(directory, "spec-*.md"))):
        if wanted(os.path.basename(path)):
            matches.append(path)

    if len(matches) != 1:
        print(f"specs found for {label}: {len(matches)}", file=sys.stderr)
        out = {
            "error": f"specs found for {label}: {len(matches)}",
            "found": len(matches),
            "matches": [{"path": os.path.abspath(p),
                         "status": frontmatter(p)[0].get("status")} for p in matches],
            "sprint_status": sprint,
        }
        if not matches and sprint == "review":
            out["route"] = "ask-human"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 2

    path = matches[0]
    fields, lists = frontmatter(path)
    status = fields.get("status")
    # The engine resumes from any point only when given the spec path; on an intent it makes a spec-<id>-2 duplicate.
    routes = {
        "draft": "resume",           # planning was interrupted
        "ready-for-dev": "resume",   # the spec is ready, no code yet
        "in-progress": "resume",     # implementation was interrupted
        "in-review": "resume",       # code exists, review did not finish
        "done": "sync-only",         # work is done, only tracking lags behind
        "blocked": "ask-human",      # the engine would HALT: story already blocked
    }
    route = routes.get(status, "ask-human")
    if route == "sync-only" and sprint == "review":
        route = "review"             # committed code waits for review: a fresh engine review pass
    out = {
        "path": os.path.abspath(path),
        "title": fields.get("title"),
        "status": status,
        "sprint_status": sprint,
        "route": route,
        "baseline": baseline(fields) if REV.match(baseline(fields)) else None,
        "followup_review_recommended": fields.get("followup_review_recommended") == "true",
        "review_loop_iteration": fields.get("review_loop_iteration"),
        "deferred": lists.get("deferred", 0),
        "error": None,
    }
    if route == "review":
        out["commit"], out["later_commits"] = story_commit(path, args.repo, fields)
    if args.result:
        out.update(run_result(path, args.repo, fields))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
