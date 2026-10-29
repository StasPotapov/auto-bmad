"""Cooperative worktree ownership for the CLI runtime. No force takeover or cleanup."""

import contextlib
import fcntl
import hashlib
import os
import json
import time
from contextvars import ContextVar
from pathlib import Path

from common import git

_CURRENT_FD = ContextVar("auto_bmad_lease_fd", default=None)


def current_lease_fd():
    return _CURRENT_FD.get()


class ControllerWatch:
    def __init__(self, repo, session):
        self.root, common = canonical(repo)
        self.session = Path(session).resolve(strict=True)
        if not self.session.is_relative_to(common / "auto-bmad-sessions"):
            raise ValueError("test session was not issued by a controller")
        self.lock = common / "auto-bmad-locks" / (hashlib.sha256(os.fsencode(self.root)).hexdigest() + ".lock")

    def alive(self):
        try:
            data = json.loads(self.session.read_text())
            if (data.get("repo") != str(self.root) or data.get("status") != "running"
                    or (self.session.parent / "cancel").exists()):
                return False
            pulse = json.loads((self.session.parent / "pulse.json").read_text())
            if not 0 <= time.monotonic() - pulse["at"] <= 2:
                return False
            with self.lock.open("r") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                fcntl.flock(lock, fcntl.LOCK_UN)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return False

    def tests_alive(self):
        return not (self.session.parent / "tests-closed").exists() and self.alive()


def canonical(repo):
    root = Path(repo).resolve(strict=True)
    proc = git(str(root), "rev-parse", "--show-toplevel")
    if proc.returncode or Path(proc.stdout.strip()).resolve() != root:
        raise ValueError("execution cwd must be the root of a Git worktree")
    common = git(str(root), "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common.returncode:
        raise ValueError("cannot find shared Git metadata")
    return root, Path(common.stdout.strip()).resolve(strict=True)


@contextlib.contextmanager
def lease(repo):
    """One controller per worktree; the final inherited guard releases ownership."""
    root, common = canonical(repo)
    locks = common / "auto-bmad-locks"
    locks.mkdir(mode=0o700, exist_ok=True)
    name = hashlib.sha256(os.fsencode(root)).hexdigest()
    with open(locks / (name + ".lock"), "a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise ValueError(f"worktree already has an active execution: {root}") from e
        try:
            token = _CURRENT_FD.set(fh.fileno())
            yield root
        finally:
            _CURRENT_FD.reset(token)
            # The last inherited descriptor releases the flock after child cleanup.


def revision(repo):
    proc = git(str(repo), "rev-parse", "--verify", "HEAD^{commit}")
    if proc.returncode:
        raise ValueError("worktree has no HEAD commit")
    return proc.stdout.strip()


def changed_files(repo, base, head):
    """Commit range only. Uncommitted state is separately checked before a result gate."""
    for rev in (base, head):
        if len(rev) not in (40, 64) or any(c not in "0123456789abcdef" for c in rev):
            raise ValueError("expected a full canonical commit SHA")
    proc = git(str(repo), "diff", "--name-only", "-z", base, head)
    if proc.returncode:
        raise ValueError("cannot inspect commit range")
    return list(filter(None, proc.stdout.split("\0")))
