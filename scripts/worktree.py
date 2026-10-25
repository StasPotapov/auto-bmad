#!/usr/bin/env python3
"""Prepares and removes isolated worktrees for a parallel story run.

Replaces the manual commands of Step P2 and the cleanup in PARALLEL.md. Branches strictly
from HEAD of the current branch (the built-in Agent isolation would branch from
origin/<default> and lose the code of the epic's previous stories) and copies the level
profile into the new worktree: bmad-build-auto.user.toml is in .gitignore, and without
a copy the engine silently runs on the project settings.

Usage:
    worktree.py add 1-3 [--repo .]              # to resume an interrupted story
    worktree.py remove 1-3 [--repo .] [--force]
    worktree.py remove --path <path> [--repo .] # a worktree created by subagent isolation
    worktree.py remove --path <path> --keep-branch  # free the branch for a resume
    worktree.py list [--repo .]
    worktree.py prune [--repo .]                # remove all whose branches are merged into HEAD
    worktree.py seed --from <main tree> [--repo .]  # local BMad settings into a worktree

In the main flow of a parallel run the worktree is created not by this script but by
subagent isolation (`isolation: "worktree"`): an agent cannot enter someone else's
worktree — only one whose working directory is already inside it. The directory still
lands in the repository's `.claude/worktrees/`, and the harness names it. `add` stays
for resuming work interrupted in an existing worktree.

Exit 0 — success, 1 — error (text in stderr and in JSON).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

from gitexclude import ensure_excluded

PROFILE_REL = os.path.join("_bmad", "custom", "bmad-build-auto.user.toml")
SEED_EXT = (".toml", ".yaml", ".yml")
SEED_MAX = 256 * 1024
WORKTREES_REL = os.path.join(".claude", "worktrees")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def paths(repo, story_id):
    return (os.path.join(repo, WORKTREES_REL, f"auto-bmad-{story_id}"),
            f"auto-bmad/{story_id}")


def is_ours(item, repo):
    """Is this our worktree: a path under .claude/worktrees/ or a branch auto-bmad/*.

    Both `add` and subagent isolation put the directory there, but isolation picks its
    own name and the agent sets the story branch only inside. Before its `checkout -B`
    (or after a break halfway) only the path identifies it.
    """
    path = os.path.realpath(item.get("path", ""))
    root = os.path.realpath(os.path.join(repo, WORKTREES_REL))
    return (path == root or path.startswith(root + os.sep)
            or item.get("branch", "").startswith("auto-bmad/"))


def seed(source, target):
    """Copies local BMad settings that are not in git into a worktree.

    `_bmad/config.user.toml`, the level profile and other `*.user.*` files are in
    .gitignore, so a fresh worktree does not get them. Without config.user.toml the engine
    fails at render (`missing config value 'user_skill_level'`); without the profile it
    silently runs on the project settings. Takes git-ignored configs under `_bmad/`.
    """
    out = git(source, "ls-files", "--others", "--ignored", "--exclude-standard", "--", "_bmad").stdout
    copied = []
    for rel in out.splitlines():
        src = os.path.join(source, rel)
        if (not rel.endswith(SEED_EXT) or "__pycache__" in rel or not os.path.isfile(src)
                or os.path.getsize(src) > SEED_MAX):
            continue
        dst = os.path.join(target, rel)
        if os.path.realpath(src) == os.path.realpath(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    return sorted(copied)


def cmd_add(repo, story_id):
    path, branch = paths(repo, story_id)
    if os.path.exists(path):
        return {"error": f"worktree {path} already exists — remove it or use another id"}, 1
    excluded = ensure_excluded(repo, ".claude/worktrees/")
    proc = git(repo, "worktree", "add", "-b", branch, path, "HEAD")
    if proc.returncode != 0:
        return {"error": proc.stderr.strip() or "git worktree add failed"}, 1

    seeded = seed(repo, path)
    copied = PROFILE_REL in seeded
    result = {
        "seeded": seeded,
        "path": os.path.abspath(path),
        "branch": branch,
        "profile_copied": copied,
        "git_excluded": excluded,
        "base": git(repo, "rev-parse", "--short", "HEAD").stdout.strip(),
    }
    if not excluded:
        result["warning_exclude"] = ("could not add .claude/worktrees/ to "
                                     ".git/info/exclude — the main tree will look "
                                     "dirty, and the next story's preflight will stop on it")
    if not copied:
        result["warning"] = (f"no profile {PROFILE_REL} in the main tree — "
                             "the engine in the worktree will run on the project settings, "
                             "the run level will not apply")
    return result, 0


def cmd_remove(repo, story_id, force, explicit_path=None, explicit_branch=None,
               keep_branch=False):
    if explicit_path:
        # git resolves a relative path from repo, os.path from the process cwd.
        path = (explicit_path if os.path.isabs(explicit_path)
                else os.path.join(repo, explicit_path))
        branch = explicit_branch or branch_of(repo, path) or ""
    else:
        path, branch = paths(repo, story_id)
    proc = git(repo, "worktree", "remove", *(["--force"] if force else []), path)
    if proc.returncode != 0:
        return {"error": proc.stderr.strip(), "hint": "uncommitted work? check it yourself "
                                                      "before calling with --force"}, 1
    if keep_branch:
        # Resume: remove the directory to free the branch; the work stays in the branch.
        return {"removed_worktree": os.path.abspath(path), "removed_branch": None,
                "kept_branch": branch or None,
                "branch_note": "branch kept on purpose (--keep-branch): "
                               "the resume agent will pick it up"}, 0
    if not branch:
        return {"removed_worktree": os.path.abspath(path), "removed_branch": None,
                "branch_note": "could not find the branch — delete it yourself if not needed"}, 0
    branch_proc = git(repo, "branch", "-D" if force else "-d", branch)
    ok = branch_proc.returncode == 0
    result = {
        "removed_worktree": os.path.abspath(path),
        "removed_branch": branch if ok else None,
        "branch_note": None if ok else branch_proc.stderr.strip(),
    }
    if not ok:
        # The branch is unmerged; a new add with the same id would fail on "branch already exists".
        result["error"] = (f"worktree removed, but branch {branch} is left: "
                           f"{branch_proc.stderr.strip()}")
    return result, 0 if ok else 2


def branch_of(repo, path):
    """The branch the worktree at this path is on."""
    out = git(repo, "worktree", "list", "--porcelain").stdout
    current = None
    for line in out.split("\n"):
        if line.startswith("worktree "):
            current = line.split(" ", 1)[1]
        elif (line.startswith("branch ") and current
              and os.path.realpath(current) == os.path.realpath(path)):
            return line.split(" ", 1)[1].replace("refs/heads/", "")
    return None


def merged_branches(repo):
    """auto-bmad/* branches fully merged into the current HEAD."""
    out = git(repo, "branch", "--merged", "HEAD").stdout
    # git marks the current branch with * and a branch checked out in a worktree with +.
    names = (line.strip().lstrip("*+").strip() for line in out.split("\n"))
    return {name for name in names if name.startswith("auto-bmad/")}


def cmd_prune(repo):
    """Removes worktrees of merged stories.

    Needed before the project tests: the worktree directory is inside the working tree,
    and tests that walk the repository files see a second copy of the code there and fail
    because of the copy, not the merge. A git exclude does not help: the tests walk the
    file system, not the index.
    """
    items, _ = cmd_list(repo)
    merged = merged_branches(repo)
    removed, unmerged, failed = [], [], []
    for item in items["worktrees"]:
        branch = item.get("branch", "")
        if not (branch and branch in merged):
            unmerged.append({**item, "reason": "the branch is not merged into HEAD — it holds unmerged work"})
            continue
        result, code = cmd_remove(repo, None, False, item["path"], branch)
        # code 2: the directory is gone, only the branch is left — not a cleanup failure.
        (failed if code == 1 else removed).append({**item, "result": result})
    kept = unmerged + failed
    notes = []
    if unmerged:
        notes.append("copies of the code are left inside the working tree: tests that walk "
                     "the repository files may pick them up instead of the main code")
    if failed:
        notes.append("cleanup failed — this is not unmerged work but an error: "
                     "look at failed before judging the tests")
    return {"removed": removed, "kept": kept, "unmerged": unmerged, "failed": failed,
            "clean": not kept,
            "note": " / ".join(notes) or None}, 1 if failed else 0


def cmd_list(repo):
    out = git(repo, "worktree", "list", "--porcelain").stdout
    items, current = [], {}
    for line in out.split("\n"):
        if line.startswith("worktree "):
            current = {"path": line.split(" ", 1)[1]}
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].replace("refs/heads/", "")
        elif not line.strip() and current:
            items.append(current)
            current = {}
    if current:
        items.append(current)
    # The first entry is always the main tree; skip it, or prune would try to remove it
    # when the orchestrator stands on an auto-bmad/* branch.
    ours = [i for i in items[1:] if is_ours(i, repo)]
    return {"worktrees": ours}, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("add", "remove", "list", "prune", "seed"))
    ap.add_argument("story_id", nargs="?", help="for example 1-3")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--path", help="worktree path (for remove, when isolation created it)")
    ap.add_argument("--branch", help="worktree branch, if the path is non-standard")
    ap.add_argument("--from", dest="source", help="main tree (for seed)")
    ap.add_argument("--keep-branch", action="store_true",
                    help="remove the directory, keep the branch (resume an interrupted story)")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)

    if args.action == "remove" and args.path:
        result, code = cmd_remove(repo, None, args.force, args.path, args.branch,
                                  args.keep_branch)
        if code and result.get("error"):
            print(result["error"], file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code

    if args.action == "seed":
        if not args.source:
            print(json.dumps({"error": "seed needs --from <main tree>"}, ensure_ascii=False))
            return 1
        seeded = seed(os.path.abspath(args.source), repo)
        result = {"seeded": seeded, "profile_copied": PROFILE_REL in seeded}
        if not result["profile_copied"]:
            result["warning"] = (f"no profile {PROFILE_REL} in the main tree — "
                                 "the engine will run on the project settings")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.action == "prune":
        result, code = cmd_prune(repo)
        if code:
            print("cleanup failed on "
                  f"{len(result['failed'])} worktree(s) — see failed in JSON", file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code

    if args.action in ("add", "remove") and not args.story_id:
        message = f"action {args.action} needs a story id"
        print(message, file=sys.stderr)
        print(json.dumps({"error": message}, ensure_ascii=False))
        return 1

    if args.action == "add":
        result, code = cmd_add(repo, args.story_id)
    elif args.action == "remove":
        result, code = cmd_remove(repo, args.story_id, args.force,
                                  keep_branch=args.keep_branch)
    else:
        result, code = cmd_list(repo)

    if code and result.get("error"):
        print(result["error"], file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
