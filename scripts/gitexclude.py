#!/usr/bin/env python3
"""Local git exclusion of service paths, shared by the auto-bmad scripts.

The skill creates its own files inside the working tree (the level profile, parallel
worktrees, the .auto-bmad/ state). Unignored, they make the tree dirty, and the engine
HALTs on a dirty tree. .git/info/exclude is local: it does not reach the repository
and does not touch the project's .gitignore.
"""

import os
import subprocess


def ensure_excluded(repo, line):
    """Appends the line to .git/info/exclude if it is not there yet."""
    proc = subprocess.run(["git", "-C", repo, "rev-parse", "--git-common-dir"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return False
    git_dir = proc.stdout.strip()
    if not os.path.isabs(git_dir):
        git_dir = os.path.join(repo, git_dir)
    exclude = os.path.join(git_dir, "info", "exclude")
    try:
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        existing = ""
        if os.path.exists(exclude):
            with open(exclude, encoding="utf-8") as fh:
                existing = fh.read()
        if line in existing.split():
            return True
        with open(exclude, "a", encoding="utf-8") as fh:
            prefix = "" if not existing or existing.endswith("\n") else "\n"
            fh.write(f"{prefix}{line}\n")
        return True
    except OSError:
        return False
