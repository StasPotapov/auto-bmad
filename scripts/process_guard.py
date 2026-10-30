"""Own a child's process group until it exits or the supervising pipe closes."""

import os
import fcntl
import json
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


def spawn(argv, *, lease_fd=None, lease_fds=(), session=None, cleanup_on_exit=True, **kwargs):
    read_fd, write_fd = os.pipe()
    done_read, done_write = os.pipe()
    inherited = (read_fd, done_write, *lease_fds) + (() if lease_fd is None else (lease_fd,))
    try:
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(read_fd), str(done_write),
                                 str(session) if session else "", "always" if cleanup_on_exit else "interrupted", "--", *argv],
                                pass_fds=inherited, start_new_session=True, **kwargs)
        proc.cleanup_fd = done_read
    except BaseException:
        os.close(write_fd)
        os.close(done_read)
        raise
    finally:
        os.close(read_fd)
        os.close(done_write)
    return proc, write_fd


def wait_cleanup(proc):
    fd = getattr(proc, "cleanup_fd", None)
    if fd is not None:
        try:
            if not select.select([fd], [], [], 3)[0] or os.read(fd, 1):
                raise RuntimeError("managed process group cleanup did not finish")
        finally:
            os.close(fd)
            proc.cleanup_fd = None


def session_cleanup(session):
    """A separate sentinel retains inherited leases while detached session tests stop."""
    if not session:
        return
    import stub
    ready_read = ready_write = None
    try:
        ready_read, ready_write = os.pipe()
        child = os.fork()
    except OSError:
        child = None
        for fd in (ready_read, ready_write):
            if fd is not None:
                os.close(fd)
    if child:
        os.close(ready_write)
        ready = os.read(ready_read, 1)
        os.close(ready_read)
        if ready:
            return
        child = None
    if child == 0:
        os.close(ready_read)
        try:
            os.setsid()
            os.write(ready_write, b"1")
        except OSError:
            os._exit(125)
        os.close(ready_write)
        for fd in (0, 1, 2):
            try:
                os.close(fd)
            except OSError:
                pass
    path = Path(session)
    while True:
        try:
            (path.parent / "tests-closed").touch(exist_ok=True)
            data = json.loads(path.read_text())
            import cli_verifier
            if cli_verifier.cleanup_session(path):
                raise ValueError("verifier services could not be stopped")
            for name in stub.recorded(data["repo"]):
                record, error = stub.read(stub.state_path(data["repo"], name))
                if record and not error and record.get("tree") == data["repo"] and record.get("run") == path.parent.name:
                    _, code = stub.stop(data["repo"], name)
                    if code:
                        raise ValueError("a session stub could not be stopped")
            directory = Path(data["repo"]) / ".auto-bmad/tests"
            live = False
            if directory.exists():
                for item in directory.glob("*.pid"):
                    try:
                        record = json.loads(item.read_text())
                    except FileNotFoundError:
                        continue
                    if record.get("session") == str(path) and 0 <= time.monotonic() - record.get("pulse", 0) <= 2:
                        live = True
                lock_path = directory / "lock"
                if lock_path.exists():
                    with lock_path.open("r") as lock:
                        try:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            live = True
                        else:
                            fcntl.flock(lock, fcntl.LOCK_UN)
            if not live:
                if child == 0:
                    os._exit(0)
                return
        except (OSError, ValueError, KeyError, TypeError, stub.Unknown):
            # Unknown cleanup keeps ownership; it must not authorize another writer.
            pass
        time.sleep(0.05)


def main():
    parent_fd = int(sys.argv[1])
    session = sys.argv[3]
    cleanup_on_exit = sys.argv[4] == "always"
    argv = sys.argv[6:]
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if select.select([parent_fd], [], [], 0)[0] and not os.read(parent_fd, 1):
        return 125
    try:
        child = subprocess.Popen(argv)
    except OSError as e:
        print(f"process guard: {e}", file=sys.stderr)
        return 127
    while child.poll() is None:
        if stopping or (select.select([parent_fd], [], [], 0.05)[0] and not os.read(parent_fd, 1)):
            session_cleanup(session)
            os.killpg(os.getpgrp(), signal.SIGTERM)
            time.sleep(0.4)
            os.killpg(os.getpgrp(), signal.SIGKILL)
        # select() is the wait: the pipe closes even if the supervisor died by SIGKILL.
    # Keep group identity, cleanup acknowledgement and inherited leases alive until every
    # remaining same-group descendant has been stopped, while preserving the child's exit code.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if cleanup_on_exit:
        session_cleanup(session)
    try:
        reaper = os.fork()
    except OSError:
        reaper = 0
    if reaper == 0:
        os.killpg(os.getpgrp(), signal.SIGTERM)
        time.sleep(0.15)
        os.killpg(os.getpgrp(), signal.SIGKILL)
    return child.returncode if child.returncode >= 0 else 128 - child.returncode


if __name__ == "__main__":
    sys.exit(main())
