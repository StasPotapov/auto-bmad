#!/usr/bin/env python3
"""Preflight checks of an auto-bmad run in one call.

Covers Step 1 and Step P0: tree state, the engine and its scripts, sprint tracking,
uv, agent types; with --parallel also whether the engine is under git (otherwise it
is missing from a new worktree; the reason and the fix are in engine_untracked) and
whether worktrees are left from a previous run. Checks after a story ([[verify]]) with a
`preflight` command run it too: the check's fields go to its stdin as JSON, exit 1 is a
warning, 2 — blocking, the first stdout line is the message (for example, mockmatch with
`design_project` asks whether Claude Design is logged in). With --level only the checks of
that level run their preflight.

Usage:
    preflight.py [--repo .] [--parallel] [--level normal]

Exit 0 — good to go, 2 — something blocks (see blocking in JSON), 1 — call error
(the folder does not exist). "Not a git repository", a missing engine or uv are not
call errors but blocking findings: exit 2 and a line in blocking.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

from ext import expand, load
from roles import ROLES, load_roles
from gitexclude import ensure_excluded
from worktree import cmd_list

# Agent types come with the plugin: agents/ next to scripts/.
AGENTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents")
USER_SETTINGS = os.path.expanduser("~/.claude/settings.json")
PROJECT_SETTINGS = os.path.join(".claude", "settings.json")
LOCAL_SETTINGS = os.path.join(".claude", "settings.local.json")


# How the project runs its tests: (marker file, command), in search priority order.
TEST_HINTS = [
    ("package.json", "npm test"),
    ("Makefile", "make test"),
    ("pyproject.toml", "pytest"),
    ("pytest.ini", "pytest"),
    ("gradlew", "./gradlew test"),
    ("Cargo.toml", "cargo test"),
]

# Where the project could hide .claude/ from tests and linters that walk the tree.
IGNORE_CONFIGS = ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini",
                  "package.json", "jest.config.js", "vitest.config.ts", "Makefile")


def find_test_command(repo):
    """The project's test command, found before the first wave."""
    for marker, command in TEST_HINTS:
        path = os.path.join(repo, marker)
        if not os.path.exists(path):
            continue
        if marker == "package.json":
            try:
                import json as _json
                with open(path, encoding="utf-8") as fh:
                    if "test" not in (_json.load(fh).get("scripts") or {}):
                        continue
            except (OSError, ValueError):
                continue
        if marker == "Makefile":
            try:
                with open(path, encoding="utf-8") as fh:
                    if not any(line.startswith("test:") for line in fh):
                        continue
            except OSError:
                continue
        return command
    return None


def claude_dir_ignored(repo):
    """Whether .claude/ is excluded in the configs that tests and linters use to walk the tree."""
    for name in IGNORE_CONFIGS:
        path = os.path.join(repo, name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                if ".claude" in fh.read():
                    return True
        except OSError:
            continue
    return False


def _base_ref_in(path):
    """worktree.baseRef from one settings file; None — not set or the file is unreadable."""
    try:
        import json as _json
        with open(path, encoding="utf-8") as fh:
            data = _json.load(fh)
    except (OSError, ValueError):
        return None
    value = data.get("worktree.baseRef")
    if value is None and isinstance(data.get("worktree"), dict):
        value = data["worktree"].get("baseRef")
    return value


def worktree_base_ref(repo):
    """The worktree.baseRef setting: fresh (default) or head.

    Claude Code merges settings by layer, the nearer one wins, so all layers are read:
    user settings alone would miss a project-level override in either direction.
    """
    value = None
    for path in (USER_SETTINGS, os.path.join(repo, PROJECT_SETTINGS),
                 os.path.join(repo, LOCAL_SETTINGS)):
        found = _base_ref_in(path)
        if found:
            value = found
    return value or "fresh"


def git(repo, *args):
    proc = subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def ignore_rule(repo, rel):
    """The ignore rule that hides rel from git, or None.

    Lets the human see which .gitignore line is the cause, not just "not under git".
    """
    code, out, _ = git(repo, "check-ignore", "-v", "--no-index", rel)
    if code != 0 or not out:
        return None
    # <source>:<line>:<pattern>\t<path>
    source, line, pattern = out.split("\t", 1)[0].split(":", 2)
    if pattern.startswith("!"):
        return None
    return {"file": source, "line": int(line), "pattern": pattern}


def engine_fix(rel, rule):
    """What to do to get rel into git — one sentence for the human."""
    # Commit the whole folder: the engine needs the sibling skills and the _bmad/ config.
    top = ".claude/skills" if rel.startswith(".claude/skills/") else rel.split("/", 1)[0]
    if rule is None:
        return f"not committed — commit {top}"
    return (f"hidden by the rule \"{rule['pattern']}\" ({rule['file']}, line {rule['line']}) — "
            f"remove the rule and commit {top}")


def verify_preflights(repo, level=None):
    """[(check name, exit code, message)] of the checks' own preflight commands."""
    try:
        cfg, _, _ = load(repo)
    except Exception as e:                       # a broken config is the checks' problem, not this one's
        return [("config", 1, f"cannot read the config: {e}")]
    found = []
    for v in cfg.get("verify", []):
        if not v.get("preflight") or (level and level not in v.get("levels", ["normal", "deep"])):
            continue
        fields = {k: val for k, val in v.items() if k != "preflight"}
        try:
            proc = subprocess.run(["sh", "-c", expand(v["preflight"])], cwd=repo, capture_output=True,
                                  text=True, timeout=120, input=json.dumps(fields))
            code, text = proc.returncode, (proc.stdout.strip() or proc.stderr.strip())
        except (OSError, subprocess.TimeoutExpired) as e:
            code, text = 1, f"preflight did not run — {e}"
        if code:
            found.append((v.get("name", "?"), code, text.splitlines()[0] if text else f"exit {code}"))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--parallel", action="store_true")
    ap.add_argument("--level", help="the run level: only checks of this level run their preflight")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)

    if not os.path.isdir(repo):
        message = f"folder {repo} does not exist — nothing to check"
        print(message, file=sys.stderr)
        print(json.dumps({"repo": repo, "error": message}, ensure_ascii=False))
        return 1

    out = {"repo": repo, "blocking": [], "warnings": [], "parallel_ready": None}

    code, _, _ = git(repo, "rev-parse", "--git-dir")
    if code != 0:
        out["blocking"].append("not a git repository — the engine cannot commit")
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 2

    _, branch, _ = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _, porcelain, _ = git(repo, "status", "--porcelain")
    dirty = [line for line in porcelain.split("\n") if line.strip()]
    out["branch"] = branch
    out["dirty_files"] = dirty
    if dirty:
        out["blocking"].append(
            f"the tree is dirty ({len(dirty)} files) — the engine will HALT on its VCS sanity check")

    required = {
        ".claude/skills/bmad-build-auto/SKILL.md": "the bmad-build-auto engine skill",
        "_bmad/scripts/render_skill.py": "the engine renderer",
        "_bmad-output/implementation-artifacts/sprint-status.yaml": "sprint tracking",
    }
    for rel, what in required.items():
        if not os.path.exists(os.path.join(repo, rel)):
            out["blocking"].append(f"missing {rel} — {what}")

    if not os.path.isdir(os.path.join(repo, "_bmad", "custom")):
        out["blocking"].append("missing _bmad/custom/ — nowhere to put the level profile")

    if not shutil.which("uv"):
        out["blocking"].append("uv is not in PATH — the engine renders through uv run")

    if not os.path.exists(os.path.join(AGENTS, "bmad-story-runner.md")):
        out["blocking"].append(
            "missing agent type auto-bmad:bmad-story-runner (the plugin's agents/) — no way to isolate a story")
    missing_types = [f"bmad-{role}" for role in ROLES if role != "story-runner"
                     and not os.path.exists(os.path.join(AGENTS, f"bmad-{role}.md"))]
    if missing_types:
        out["warnings"].append(
            "missing agent types " + ", ".join(missing_types) +
            " — the engine will start subagents without a type and note it in the result")

    _, role_errors, role_warnings = load_roles(repo)
    out["blocking"] += role_errors
    out["warnings"] += role_warnings

    if args.level != "fast":
        for name, code, message in verify_preflights(repo, args.level):
            (out["blocking"] if code == 2 else out["warnings"]).append(f"check {name}: {message}")

    out["test_command"] = find_test_command(repo)
    if args.parallel and out["test_command"] and not claude_dir_ignored(repo):
        out["warnings"].append(
            "the project tests do not exclude .claude/ anywhere — guard tests that walk the "
            "repository files will see a second copy of the code in a worktree and fail not "
            "because of the merge. Run worktree.py prune before the tests and take the result "
            "before the wave as a baseline")

    if args.parallel:
        problems = []
        for rel in (".claude/skills/bmad-build-auto/SKILL.md", "_bmad/scripts/render_skill.py"):
            code, _, _ = git(repo, "ls-files", "--error-unmatch", rel)
            if code != 0:
                problems.append(rel)
        out["engine_untracked"] = [
            {"path": rel, "ignored_by": rule, "fix": engine_fix(rel, rule)}
            for rel, rule in ((rel, ignore_rule(repo, rel)) for rel in problems)]
        if problems:
            fixes = "; ".join(f"{item['path']} {item['fix']}"
                              for item in out["engine_untracked"])
            out["warnings"].append(
                f"the engine is not under git and will be missing from a new worktree — parallel "
                f"is not possible, run sequentially. Fix: {fixes}")
        # Subagent isolation creates the worktree inside the working tree; without this
        # exclude line the tree gets dirty on the first wave.
        out["git_excluded"] = ensure_excluded(repo, ".claude/worktrees/")
        if not out["git_excluded"]:
            out["warnings"].append(
                "could not add .claude/worktrees/ to .git/info/exclude — once the first "
                "worktree appears, the tree gets dirty and the next run's preflight stops on it")

        # With `fresh` isolation branches from origin/<default>, which may not exist at all.
        _, origin, _ = git(repo, "remote")
        base_ref = worktree_base_ref(repo)
        out["has_origin"] = "origin" in origin.split()
        out["worktree_base_ref"] = base_ref
        if base_ref != "head" and not out["has_origin"]:
            out["warnings"].append(
                "the repository has no origin and worktree.baseRef = fresh (branching from "
                "origin/<default>): if a subagent with isolation does not get a worktree, "
                "set worktree.baseRef = head with /config and retry")

        # Same detection as worktree.py: a path under .claude/worktrees/ or an auto-bmad/* branch.
        listed, _ = cmd_list(repo)
        stale = [item["path"] for item in listed["worktrees"]]
        out["stale_worktrees"] = stale
        if stale:
            out["warnings"].append(
                f"worktrees from a previous run are left ({len(stale)}) — ask the human "
                "whether to remove them; do not delete someone else's work yourself")
        out["parallel_ready"] = not problems

    out["ok"] = not out["blocking"]
    if out["blocking"]:
        print("; ".join(out["blocking"]), file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
