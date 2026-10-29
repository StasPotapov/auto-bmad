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
    worktree.py start epic-7 [--repo .]         # the run worktree (worktree mode): create or resume

In the main flow of a parallel run the worktree is created not by this script but by
subagent isolation (`isolation: "worktree"`): an agent cannot enter someone else's
worktree — only one whose working directory is already inside it. The directory still
lands in the repository's `.claude/worktrees/`, and the harness names it. `add` stays
for resuming work interrupted in an existing worktree.

`start` serves the worktree mode of a whole run (`--worktree`, `[run] worktree`): the
branch `bmad/<target>` in `.claude/worktrees/bmad-<target>` of the main tree. The
orchestrator enters it with EnterWorktree, and the whole run goes there; `auto-bmad land`
merges the branch later. A live worktree of the same target is resumed, not created again.

Exit 0 — success, 1 — error (text in stderr and in JSON).
"""

import argparse
import json
import os
import shutil
import re
import sys
import uuid
from pathlib import Path

from common import git, main_tree
from gitexclude import ensure_excluded, remove_excluded

PROFILE_REL = os.path.join("_bmad", "custom", "bmad-build-auto.user.toml")
SEED_EXT = (".toml", ".yaml", ".yml")
SEED_MAX = 256 * 1024
WORKTREES_REL = os.path.join(".claude", "worktrees")
RUN_PREFIX = "bmad/"
RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,48}$")
# Local files outside _bmad/ that a run needs and git does not carry: permissions of the
# unattended run, a project config kept out of git, local instructions.
RUN_LOCAL = (os.path.join(".claude", "settings.local.json"), ".auto-bmad.toml", ".auto-bmad.local.toml",
             "CLAUDE.local.md")
BASE_KEY = "branch.{branch}.autoBmadBase"
BASE_COMMIT_KEY = "branch.{branch}.autoBmadBaseCommit"


def paths(repo, story_id):
    return (os.path.join(repo, WORKTREES_REL, f"auto-bmad-{story_id}"),
            f"auto-bmad/{story_id}")


def is_ours(item, repo):
    """Is this our worktree: a path under .claude/worktrees/ or a branch auto-bmad/*.

    Both `add` and subagent isolation put the directory there, but isolation picks its
    own name and the agent sets the story branch only inside. Before its `checkout -B`
    (or after a break halfway) only the path identifies it.
    """
    if item.get("branch", "").startswith(RUN_PREFIX):
        return False                    # a run worktree (`start`): `auto-bmad land` owns it
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
        if copy_seed(source, target, rel):
            copied.append(rel)
    return sorted(copied)


def copy_seed(source, target, rel):
    """Local settings must not overwrite a committed file or follow a destination symlink."""
    src, dst = os.path.join(source, rel), os.path.join(target, rel)
    source_root, target_root = os.path.realpath(source), os.path.realpath(target)
    if os.path.commonpath([source_root, os.path.realpath(src)]) != source_root:
        raise ValueError(f"seed source escapes the source tree: {rel}")
    if (os.path.islink(dst) or
            os.path.commonpath([target_root, os.path.realpath(dst)]) != target_root):
        raise ValueError(f"seed destination is a symlink or escapes the target tree: {rel}")
    parent = os.path.dirname(os.path.abspath(dst))
    while parent != os.path.abspath(target):
        if os.path.islink(parent):
            raise ValueError(f"seed destination has a symlink parent: {rel}")
        next_parent = os.path.dirname(parent)
        if next_parent == parent:
            raise ValueError(f"seed destination escapes the target tree: {rel}")
        parent = next_parent
    if os.path.realpath(src) == os.path.realpath(dst) or tracked(target, rel):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return True


def cmd_add(repo, story_id):
    path, branch = paths(repo, story_id)
    if os.path.exists(path):
        return {"error": f"worktree {path} already exists — remove it or use another id"}, 1
    excluded = ensure_excluded(repo, ".claude/worktrees/")
    proc = git(repo, "worktree", "add", "-b", branch, path, "HEAD")
    if proc.returncode != 0:
        return {"error": proc.stderr.strip() or "git worktree add failed"}, 1

    try:
        seeded = seed(repo, path)
    except (OSError, ValueError) as e:
        return {"error": f"seed failed; worktree is kept: {e}", "path": path, "branch": branch}, 1
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


def run_paths(main, name):
    return os.path.join(main, WORKTREES_REL, f"bmad-{name}"), f"{RUN_PREFIX}{name}"


def tracked(repo, rel):
    return git(repo, "ls-files", "--error-unmatch", "--", rel).returncode == 0


def ignored(repo, rel):
    return git(repo, "check-ignore", "-q", "--", rel).returncode == 0


def seed_run(source, target):
    """seed() plus the local files of RUN_LOCAL → (copied, left in the main tree).

    Only a git-ignored local file is copied: the same rules hide it in the worktree, so it
    does not make the tree dirty (the engine HALTs on a dirty tree). One that is not ignored
    stays in the main tree, and the config readers take the config layers from there
    (ext.layers). Nothing is written into the shared .git/info/exclude: the main tree would
    start hiding these files too.
    """
    copied, left = seed(source, target), []
    for rel in RUN_LOCAL:
        src, dst = os.path.join(source, rel), os.path.join(target, rel)
        if not os.path.isfile(src) or tracked(source, rel):
            continue
        if not ignored(source, rel):
            left.append(rel)
            continue
        if copy_seed(source, target, rel):
            copied.append(rel)
    return sorted(copied), left


def cmd_start(repo, name):
    """Creates the run worktree of a target, or resumes the live one.

    → path, branch, `created` / `resumed`. The worktree branches from HEAD of the main
    tree; uncommitted files of the main tree are not in it — `main_dirty` names them.
    """
    if not RUN_NAME.match(name or ""):
        return {"error": f"bad run target {name!r}: letters, digits, dots, dashes "
                         "and underscores, as in epic-7 or 7-3"}, 1
    main = main_tree(repo)
    path, branch = run_paths(main, name)
    excluded = ensure_excluded(main, ".claude/worktrees/")
    live = next((i for i in worktree_items(main) if i.get("branch") == branch), None)
    if live and os.path.realpath(live["path"]) == os.path.realpath(main):
        return {"error": f"{branch} is checked out in the main tree — switch the main tree "
                         "to its base branch first"}, 1
    if live and os.path.isdir(live["path"]):
        path, state = live["path"], "resumed"
    else:
        git(main, "worktree", "prune")
        if os.path.exists(path):
            return {"error": f"{path} exists but is not the worktree of {branch} — "
                             "move it away or remove it"}, 1
        has_branch = git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
        args = ([path, branch] if has_branch else ["-b", branch, path, "HEAD"])
        proc = git(main, "worktree", "add", *args)
        if proc.returncode != 0:
            return {"error": proc.stderr.strip() or "git worktree add failed"}, 1
        state = "resumed" if has_branch else "created"
        if not has_branch:
            base = git(main, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
            if base:
                git(main, "config", BASE_KEY.format(branch=branch), base)
            git(main, "config", BASE_COMMIT_KEY.format(branch=branch),
                git(main, "rev-parse", "HEAD").stdout.strip())
    try:
        seeded, left = seed_run(main, path)
    except (OSError, ValueError) as e:
        return {"error": f"seed failed; worktree is kept: {e}", "path": path, "branch": branch}, 1
    # Earlier versions excluded the copied local files in the shared exclude: take that back.
    cleaned = remove_excluded(main, ["/" + rel.replace(os.sep, "/") for rel in RUN_LOCAL])
    dirty, _ = uncommitted(main)
    result = {
        "path": os.path.abspath(path),
        "branch": branch,
        "created": state == "created",
        "resumed": state == "resumed",
        "base_branch": git(main, "config", "--get", BASE_KEY.format(branch=branch)).stdout.strip() or None,
        "head": git(path, "rev-parse", "--short", "HEAD").stdout.strip(),
        "seeded": seeded,
        "left_in_main": left,
        "profile_copied": PROFILE_REL in seeded,
        "main_tree": main,
        "main_dirty": dirty or [],
        "land": f"auto-bmad land {branch}",
        "git_excluded": excluded,
    }
    if cleaned:
        result["exclude_cleaned"] = cleaned
    if dirty:
        result["warning_dirty"] = ("the main tree has uncommitted files — they are not in the "
                                   "run worktree: the run goes from the last commit")
    return result, 0


def create_cli(repo, label):
    """Create a unique CLI run from this exact HEAD; failures preserve its worktree."""
    source = Path(repo).resolve(strict=True)
    main = Path(main_tree(str(source))).resolve(strict=True)
    if not RUN_NAME.fullmatch(label):
        raise ValueError("invalid CLI run target")
    parent = main / ".auto-bmad/worktrees"
    if not parent.resolve().is_relative_to(main):
        raise ValueError("CLI worktree directory escapes the project")
    if not ensure_excluded(str(main), ".auto-bmad/"):
        raise ValueError("cannot exclude runtime worktrees")
    parent.mkdir(parents=True, exist_ok=True)
    name = label[:16] + "-" + uuid.uuid4().hex
    target = parent / name
    branch = "codex/auto-bmad/" + name
    base = git(str(source), "rev-parse", "--verify", "HEAD^{commit}")
    if base.returncode:
        raise ValueError("source has no HEAD commit")
    proc = git(str(source), "worktree", "add", "-b", branch, str(target), base.stdout.strip())
    if proc.returncode:
        raise ValueError(proc.stderr.strip() or "cannot create the CLI worktree")
    out = {"path": str(target), "branch": branch, "base_commit": base.stdout.strip(), "created": True}
    try:
        copied = seed(str(source), str(target))
        for rel in (".auto-bmad.toml", ".auto-bmad.local.toml"):
            if (source / rel).is_file() and not tracked(str(source), rel) and ignored(str(source), rel):
                if copy_seed(str(source), str(target), rel):
                    copied.append(rel)
        out["seeded"] = sorted(set(copied))
        base_branch = git(str(source), "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
        for key, value in ((BASE_KEY, base_branch), (BASE_COMMIT_KEY, base.stdout.strip())):
            if value:
                saved = git(str(source), "config", key.format(branch=branch), value)
                if saved.returncode:
                    raise ValueError("cannot record the CLI run base")
    except (OSError, ValueError) as e:
        out["error"] = f"setup failed; worktree is preserved: {e}"
    return out


def worktree_items(repo):
    """Every worktree of the repository from `git worktree list`: path and branch."""
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
    return items


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


def uncommitted(path, skip_untracked=()):
    """Uncommitted files of a worktree → (paths, error). Renames give the new path.

    Untracked files named in skip_untracked do not count (the local files of RUN_LOCAL).
    """
    proc = git(path, "status", "--porcelain", "-z", *(["--untracked-files=all"] if skip_untracked else []))
    if proc.returncode:
        return None, (proc.stderr or proc.stdout).strip()[:300] or f"git status: exit {proc.returncode}"
    out, parts = [], proc.stdout.split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if not entry:
            continue
        if not (entry.startswith("?? ") and entry[3:].rstrip("/") in skip_untracked):
            out.append(entry[3:])
        if entry[0] in "RC":
            i += 1                      # -z puts the old path of a rename in the next field
    return out, None


def details(item):
    """Add the worktree's last commits and uncommitted files; a missing directory says so."""
    if not os.path.isdir(item["path"]):
        item.update(missing=True, dirty=None, log=None)
        return
    item["dirty"], error = uncommitted(item["path"])
    if error:
        item["error"] = error
    log = git(item["path"], "log", "--oneline", "-3")
    item["log"] = log.stdout.strip().splitlines() if log.returncode == 0 else None


def cmd_list(repo, with_details=False):
    items = worktree_items(repo)
    # The first entry is always the main tree; skip it, or prune would try to remove it
    # when the orchestrator stands on an auto-bmad/* branch.
    ours = [i for i in items[1:] if is_ours(i, repo)]
    if with_details:
        for item in ours:
            details(item)
    return {"worktrees": ours}, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("add", "remove", "list", "prune", "seed", "start"))
    ap.add_argument("story_id", nargs="?", help="for example 1-3; for start — the run target, epic-7")
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
        try:
            seeded = seed(os.path.abspath(args.source), repo)
        except (OSError, ValueError) as e:
            print(json.dumps({"error": f"seed failed: {e}", "path": repo}, ensure_ascii=False))
            return 1
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

    if args.action == "start":
        result, code = cmd_start(repo, args.story_id)
        if code and result.get("error"):
            print(result["error"], file=sys.stderr)
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
        result, code = cmd_list(repo, with_details=True)

    if code and result.get("error"):
        print(result["error"], file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
