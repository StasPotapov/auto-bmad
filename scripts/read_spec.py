#!/usr/bin/env python3
"""Finds a story's spec and reads its frontmatter.

Slug segments are compared AS NUMBERS, so `1-1` does not match `1-10`. Also the
fallback when the subagent returned a header that breaks the contract.

Usage:
    read_spec.py --story 1-3 [--repo .]
    read_spec.py --slug issue-12 [--repo .]     # a task outside the epics: spec-<slug>-*.md
    read_spec.py --story 1-3 --result [--repo .]  # plus the run result: no need to read the spec

`--result` adds `auto_run_result` (the last `## Auto Run Result` section), `commit` (the last
commit since `baseline_revision` that changed code, not only `_bmad-output/`) and `files`
(the number of files in that commit). Not found — null.

Exit 0 — exactly one spec found, 1 — error, 2 — zero or more than one.
"""

import argparse
import glob
import subprocess
import json
import os
import re
import sys

from common import ARTIFACTS, STORY_NUM, norm_num, parse_story
SPEC_RE = re.compile(rf"^spec-(\d+)-({STORY_NUM})-(.*)\.md$", re.I)


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


def git_out(repo, *args):
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def run_result(path, repo, fields):
    """The run result without reading the spec: the section, the engine commit and its files."""
    base = (fields.get("baseline_revision") or "").strip()
    commit = files = None
    if REV.match(base):
        # the engine commit changes code; tracking and spec-only commits touch only _bmad-output/
        commit = git_out(repo, "log", "-1", "--format=%h", f"{base}..HEAD", "--",
                         ".", ":(exclude)_bmad-output")
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

        def wanted(name):
            sm = SPEC_RE.match(name)
            return bool(sm and int(sm.group(1)) == epic and norm_num(sm.group(2)) == num)
    else:
        slug = args.slug.strip()
        if not re.match(r"^[\w.-]+$", slug):
            message = f"cannot parse the spec slug: {args.slug!r}"
            print(message, file=sys.stderr)
            print(json.dumps({"error": message}, ensure_ascii=False))
            return 1
        label = slug

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
        print(json.dumps({
            "error": f"specs found for {label}: {len(matches)}",
            "found": len(matches),
            "matches": [{"path": os.path.abspath(p),
                         "status": frontmatter(p)[0].get("status")} for p in matches],
        }, ensure_ascii=False, indent=2))
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
    out = {
        "path": os.path.abspath(path),
        "title": fields.get("title"),
        "status": status,
        "route": routes.get(status, "ask-human"),
        "followup_review_recommended": fields.get("followup_review_recommended") == "true",
        "review_loop_iteration": fields.get("review_loop_iteration"),
        "deferred": lists.get("deferred", 0),
        "error": None,
    }
    if args.result:
        out.update(run_result(path, args.repo, fields))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
