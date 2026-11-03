"""Cooperative worktree ownership for local tooling. No force takeover or cleanup."""

import contextlib
import fcntl
import hashlib
import os
import json
import time
import os
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


@contextlib.contextmanager
def resource_lock(repo, cancel):
    """Linked worktrees share test ports, build tools and physical verifier devices."""
    _, common = canonical(repo)
    locks = common / "auto-bmad-locks"
    locks.mkdir(mode=0o700, exist_ok=True)
    path = locks / "shared-checks.lock"
    try:
        fh = path.open("r")
    except FileNotFoundError:
        fh = path.open("a")
    # flock needs no write access: sandboxed test workers can share a host-created lock.
    with fh:
        while True:
            if cancel.is_set():
                raise ValueError("run cancelled while waiting for shared verification resources")
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.05)
        yield fh.fileno()


def changed_files(repo, base, head):
    """Commit range only. Uncommitted state is separately checked before a result gate."""
    for rev in (base, head):
        if len(rev) not in (40, 64) or any(c not in "0123456789abcdef" for c in rev):
            raise ValueError("expected a full canonical commit SHA")
    proc = git(str(repo), "diff", "--name-only", "-z", base, head)
    if proc.returncode:
        raise ValueError("cannot inspect commit range")
    return list(filter(None, proc.stdout.split("\0")))


def fingerprint(root):
    """Detect code/spec edits even when a read-only task returns a success message."""
    paths = git(str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if paths.returncode:
        raise ValueError("cannot inspect worktree contents")
    stages = git(str(root), "ls-files", "--stage", "-z")
    if stages.returncode:
        raise ValueError("cannot inspect Git index")
    links = {entry.split("\t", 1)[1] for entry in stages.stdout.split("\0")
             if entry.startswith("160000 ") and "\t" in entry}
    digest = hashlib.sha256(revision(root).encode())
    digest.update(stages.stdout.encode())
    for rel in sorted(set(filter(None, paths.stdout.split("\0")))):
        if rel.startswith(".auto-bmad/"):
            continue
        path = root / rel
        digest.update(os.fsencode(rel) + b"\0")
        if path.is_symlink():
            digest.update(b"link:" + os.fsencode(os.readlink(path)))
        elif rel in links and path.is_dir():
            top = git(str(path), "rev-parse", "--show-toplevel")
            if top.returncode == 0 and Path(top.stdout.strip()).resolve() == path.resolve():
                digest.update(fingerprint(path).encode())
            else:
                # Uninitialized gitlinks may contain user files; include those without following symlinks.
                for directory, dirs, files in os.walk(path, followlinks=False):
                    dirs.sort()
                    for name in sorted(files + [d for d in dirs if (Path(directory) / d).is_symlink()]):
                        item = Path(directory) / name
                        digest.update(os.fsencode(item.relative_to(root)))
                        if item.is_symlink():
                            digest.update(os.fsencode(os.readlink(item)))
                        else:
                            with item.open("rb") as fh:
                                digest.update(hashlib.file_digest(fh, "sha256").digest())
        elif path.is_file():
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"worktree file escapes root: {rel}")
            digest.update(str(path.stat().st_mode).encode())
            with path.open("rb") as fh:
                digest.update(hashlib.file_digest(fh, "sha256").digest())
        elif path.exists():
            raise ValueError(f"unsupported tracked entry: {rel}")
        else:
            digest.update(b"deleted")
    return digest.hexdigest()
