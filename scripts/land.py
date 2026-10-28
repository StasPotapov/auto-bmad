#!/usr/bin/env python3
"""Merges the branch of a worktree run (`bmad/<target>`) into the main tree's branch.

The run in worktree mode does not merge itself: it ends with the branch name and this
command. Order, each step stops the next one:

  1. the main tree has uncommitted files — refusal: the merge would mix them in;
  2. a dry merge with `git merge-tree` — nothing in the main tree changes yet;
  3. a conflict only in sprint-status.yaml — resolved here: every key takes the more
     advanced status of the two sides, last_updated — the later one; a conflict in any
     other file — the files are listed and the command stops, it resolves no code;
  4. the merge commit is built without touching the main tree and checked out in the
     run worktree (or a temporary one), where the project tests run (`project-tests`
     of the config — the command from .auto-bmad.toml or the one preflight finds);
  5. the tests pass — the main tree moves to the merge commit (fast-forward), then the
     run worktree and the branch are removed.

Usage:
    land.py bmad/epic-7 [--repo .] [--no-tests] [--onto-current] [--cleanup]

The run branched from another branch than the main tree is on now — refusal;
`--onto-current` merges into the current one on purpose. A branch with no commits of its
own (its tip is the recorded base) is refused too; `--cleanup` removes it anyway.

Exit 0 — merged (or the branch was already merged), 1 — call error, 2 — refused by
rule: a dirty tree, another base branch, no work, a conflict in code, tests failed.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from common import SPRINT_REL, git, main_tree
from sync_sprint import ENTRY, parse_stamp
from worktree import (BASE_COMMIT_KEY, BASE_KEY, RUN_LOCAL, WORKTREES_REL, seed_run, uncommitted,
                      worktree_items)

SPRINT = SPRINT_REL.replace(os.sep, "/")
# How far a sprint-status value has moved: story, epic and retrospective statuses of BMad.
RANK = {"optional": 0, "backlog": 0, "drafted": 1, "contexted": 1, "ready-for-dev": 1,
        "in-progress": 2, "review": 3, "done": 4}


def parse_sprint(text):
    """→ (lines, {key: (index, value)} of development_status, its header index, last_updated index)."""
    lines = text.split("\n")
    entries, header, stamp, inside = {}, None, None, False
    for i, line in enumerate(lines):
        if not line.startswith((" ", "\t")) and ":" in line and not line.lstrip().startswith("#"):
            head = line.split(":", 1)[0].strip()
            inside = head == "development_status"
            if inside:
                header = i
            elif head == "last_updated":
                stamp = i
            continue
        m = ENTRY.match(line) if inside else None
        if m:
            entries[m.group(2).strip()] = (i, m.group(4).split("#", 1)[0].strip().strip("'\""))
    return lines, entries, header, stamp


def comment_tail(value):
    """The trailing `  # comment` of an entry value, with the spaces before it; none — ""."""
    if "#" not in value:
        return ""
    return value[len(value.split("#", 1)[0].rstrip()):]


def merge_sprint(ours, theirs):
    """Both sides of sprint-status.yaml → (merged text, changes, warnings).

    The layout is ours (the base branch); a key takes the status that moved further and
    keeps its comment, keys only in theirs go in after their neighbour from theirs,
    last_updated is the later date — a date that does not parse keeps ours, with a warning.
    """
    lines, own, header, stamp = parse_sprint(ours)
    t_lines, other, _, t_stamp = parse_sprint(theirs)
    if header is None:
        return None, [], []
    changes, inserts, warnings = [], {}, []
    anchor = header
    for key, (ti, value) in other.items():
        if key in own:
            i, mine = own[key]
            anchor = i
            if RANK.get(value, -1) > RANK.get(mine, -1):
                m = ENTRY.match(lines[i])
                lines[i] = f"{m.group(1)}{key}:{m.group(3) or ' '}{value}{comment_tail(m.group(4))}"
                changes.append({"key": key, "from": mine, "to": value})
            continue
        inserts.setdefault(anchor, []).append(t_lines[ti])
        changes.append({"key": key, "from": None, "to": value})
    if stamp is not None and t_stamp is not None:
        mine, their = (parse_stamp(x.partition(":")[2]) for x in (lines[stamp], t_lines[t_stamp]))
        if mine is None or their is None:
            warnings.append(f"last_updated is not a date on one side ({lines[stamp].strip()!r} / "
                            f"{t_lines[t_stamp].strip()!r}): kept the base branch value")
        elif their > mine:
            lines[stamp] = t_lines[t_stamp]
    for at in sorted(inserts, reverse=True):
        lines[at + 1:at + 1] = inserts[at]
    return "\n".join(lines), changes, warnings


def show(repo, rev, path):
    proc = git(repo, "show", f"{rev}:{path}")
    return proc.stdout if proc.returncode == 0 else None


def tree_with(repo, tree, path, text):
    """The tree with one file replaced, built in a temporary index: the main tree is not touched."""
    fd, index = tempfile.mkstemp(prefix="auto-bmad-land-")
    os.close(fd)
    os.unlink(index)
    env = {**os.environ, "GIT_INDEX_FILE": index}

    def run(*args, stdin=None):
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                              env=env, input=stdin)
    try:
        mode = git(repo, "ls-tree", tree, "--", path).stdout.split(" ", 1)[0] or "100644"
        blob = run("hash-object", "-w", "--stdin", stdin=text).stdout.strip()
        if run("read-tree", tree).returncode or run(
                "update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}").returncode:
            return None
        out = run("write-tree")
        return out.stdout.strip() if out.returncode == 0 else None
    finally:
        if os.path.exists(index):
            os.unlink(index)


def test_command(where):
    """The project-tests check of the merged code's config → (command, timeout); turned off — (None, None)."""
    from ext import load
    from verify import resolve_command
    cfg, _, _ = load(where)
    v = next((x for x in cfg.get("verify", []) if x.get("name") == "project-tests"), None)
    if not v:
        return None, None
    return resolve_command(v, where), v.get("timeout", 1800)


def run_tests(where):
    from verify import run_command
    command, timeout = test_command(where)
    if not command:
        return {"verdict": "skipped", "reason": "no test command: the project-tests check is off "
                                                "or the project has no test command"}
    res = run_command(command, where, timeout)
    res["command"] = command
    return res


def fail(result, message, code):
    result["error"] = message
    return result, code


def land(repo, branch, with_tests=True, onto_current=False, force_cleanup=False):
    main = main_tree(repo)
    result = {"branch": branch, "main_tree": main, "merged": False}
    base = git(main, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if not base:
        return fail(result, "the main tree is not on a branch (detached HEAD): check out the "
                            "branch to merge into", 1)
    result["base"] = base
    if branch == base:
        return fail(result, f"{branch} is the main tree's own branch — name the run branch", 1)
    tip = git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").stdout.strip()
    if not tip:
        return fail(result, f"no branch {branch}", 1)
    recorded = git(main, "config", "--get", BASE_KEY.format(branch=branch)).stdout.strip()
    if recorded and recorded != base:
        if not onto_current:
            result["recorded_base"] = recorded
            return fail(result, f"the run branched from {recorded}, and the main tree is on {base} — "
                                f"check out {recorded}, or pass --onto-current to merge into {base}", 2)
        result["warning_base"] = f"the run branched from {recorded}: merging into {base} (--onto-current)"

    dirty, error = uncommitted(main, RUN_LOCAL)
    if error or dirty:
        result["dirty"] = dirty
        return fail(result, "the main tree has uncommitted changes — commit or stash them first, "
                            "the merge would mix them in" if dirty else f"git status failed: {error}", 2)
    wt = next((i["path"] for i in worktree_items(main)
               if i.get("branch") == branch and os.path.isdir(i["path"])), None)
    result["worktree"] = wt
    if wt:
        wt_dirty, error = uncommitted(wt, RUN_LOCAL)
        if error or wt_dirty:
            result["worktree_dirty"] = wt_dirty
            return fail(result, f"the run worktree {wt} has uncommitted changes — the run is not "
                                "finished: commit them in the run or remove them"
                        if wt_dirty else f"git status in {wt} failed: {error}", 2)

    head = git(main, "rev-parse", "HEAD").stdout.strip()
    if git(main, "merge-base", "--is-ancestor", tip, head).returncode == 0:
        start = git(main, "config", "--get", BASE_COMMIT_KEY.format(branch=branch)).stdout.strip()
        if not force_cleanup and start == tip:
            return fail(result, f"{branch} has no work: no commits of its own after it branched — "
                                "nothing to merge; --cleanup removes the branch and its worktree", 2)
        result["note"] = f"{branch} is already merged into {base}: only the cleanup"
        cleanup(main, wt, branch, result)
        return result, 0

    proc = git(main, "merge-tree", "--write-tree", "--name-only", "--no-messages", head, tip)
    if proc.returncode not in (0, 1):
        return fail(result, f"git merge-tree failed (git 2.38+ is needed): {proc.stderr.strip()[:300]}", 1)
    out = proc.stdout.splitlines()
    tree, conflicts = (out[0].strip() if out else ""), sorted({x for x in out[1:] if x.strip()})
    result["conflicts"] = conflicts
    code_conflicts = [c for c in conflicts if c != SPRINT]
    if code_conflicts:
        return fail(result, "merge conflict in code — auto-bmad land does not resolve code: "
                            f"merge {branch} by hand ({len(code_conflicts)} file(s))", 2)
    if conflicts:
        ours, theirs = show(main, head, SPRINT), show(main, tip, SPRINT)
        merged, changes, warnings = (merge_sprint(ours, theirs) if ours is not None and theirs is not None
                                     else (None, [], []))
        tree = tree_with(main, tree, SPRINT, merged) if merged is not None else None
        if not tree:
            return fail(result, f"could not merge {SPRINT} by statuses — merge {branch} by hand", 2)
        result["sprint_merged"] = changes
        if warnings:
            result["warnings"] = warnings

    commit = git(main, "commit-tree", tree, "-p", head, "-p", tip,
                 "-m", f"merge: {branch} — auto-bmad run")
    if commit.returncode:
        return fail(result, f"git commit-tree failed: {commit.stderr.strip()[:300]}", 1)
    sha = commit.stdout.strip()
    result["merge_commit"] = sha

    if with_tests:
        tests = test_in(main, wt, branch, sha)
        result["tests"] = tests
        if tests.get("error"):
            return fail(result, tests.pop("error"), 1)
        if tests.get("verdict") == "problem":
            return fail(result, f"the project tests fail on the merge of {branch} into {base} — "
                                "nothing is merged; the output tail is in tests.tail", 2)

    ff = git(main, "merge", "--ff-only", "-q", sha)
    if ff.returncode:
        return fail(result, f"could not move {base} to the merge commit, git says: "
                            f"{(ff.stderr or ff.stdout).strip()[:500]}", 1)
    result["merged"] = True
    cleanup(main, wt, branch, result)
    return result, 0


def test_in(main, wt, branch, sha):
    """Runs the project tests on the merge commit: in the run worktree, else in a temporary one."""
    if wt:
        if git(wt, "checkout", "-q", "--detach", sha).returncode:
            return {"error": f"could not check out the merge commit in {wt}"}
        try:
            res = run_tests(wt)
        finally:
            back = git(wt, "checkout", "-q", "-f", branch)    # -f: edits the tests made on the merge commit
        if back.returncode:
            res["error"] = (f"the run worktree {wt} could not go back to {branch} after the tests: "
                            f"{back.stderr.strip()[:300]} — nothing is merged; check it out there by hand")
        return res
    tmp = os.path.join(main, WORKTREES_REL, "auto-bmad-land")
    if os.path.exists(tmp):
        git(main, "worktree", "remove", "--force", tmp)
        shutil.rmtree(tmp, ignore_errors=True)
    git(main, "worktree", "prune")
    if git(main, "worktree", "add", "-q", "--detach", tmp, sha).returncode:
        return {"error": "could not create a temporary worktree for the tests"}
    try:
        seed_run(main, tmp)
        return run_tests(tmp)
    finally:
        git(main, "worktree", "remove", "--force", tmp)


def cleanup(main, wt, branch, result):
    """Removes the run worktree and the branch after the merge."""
    if wt:
        proc = git(main, "worktree", "remove", "--force", wt)
        result["removed_worktree"] = wt if proc.returncode == 0 else None
        if proc.returncode:
            result["warning_cleanup"] = f"worktree {wt} is left: {proc.stderr.strip()[:200]}"
    git(main, "worktree", "prune")
    proc = git(main, "branch", "-d", branch)
    result["removed_branch"] = branch if proc.returncode == 0 else None
    if proc.returncode:
        result["warning_branch"] = f"branch {branch} is left: {proc.stderr.strip()[:200]}"
    else:
        git(main, "config", "--unset", BASE_KEY.format(branch=branch))
        git(main, "config", "--unset", BASE_COMMIT_KEY.format(branch=branch))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("branch", help="the run branch, for example bmad/epic-7")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--no-tests", action="store_true", help="merge without the project tests")
    ap.add_argument("--onto-current", action="store_true",
                    help="merge into the main tree's branch even if the run branched from another one")
    ap.add_argument("--cleanup", action="store_true",
                    help="a branch with nothing to merge: remove it and its worktree anyway")
    args = ap.parse_args()
    branch = re.sub(r"^refs/heads/", "", args.branch.strip())
    result, code = land(os.path.abspath(args.repo), branch, not args.no_tests,
                        args.onto_current, args.cleanup)
    if result.get("error"):
        print(result["error"], file=sys.stderr)
        for path in result.get("conflicts") or []:
            if path != SPRINT:
                print(f"  conflict: {path}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
