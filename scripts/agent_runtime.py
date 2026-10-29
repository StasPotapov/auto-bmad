"""Bounded argv-only process transport for coding CLI adapters. No workflow or retries here."""

import json
import os
import selectors
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from process_guard import spawn, wait_cleanup
from execution_state import current_lease_fd

MAX_LINE = 1024 * 1024
MAX_OUTPUT = 32 * 1024 * 1024


class ProtocolError(ValueError):
    pass


def atomic_json(path, value):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def environment(names):
    return {key: os.environ[key] for key in names if key in os.environ}


def terminate(proc, grace=0.5):
    """The group was created by launch. Never look up or kill processes by name."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        if sig == signal.SIGTERM:
            until = time.monotonic() + grace
            while time.monotonic() < until:
                proc.poll()
                time.sleep(0.01)
    proc.wait()


def execute(argv, *, cwd, env, stdin, directory, timeout, consume, finish, cancel=None,
            max_output=MAX_OUTPUT, structured=True, manage_signals=True, lease_fd=None, lease_fds=(), cleanup_session=None):
    """A main-thread controller owns SIGTERM until its child group has stopped."""
    terminated = threading.Event()
    main_thread = manage_signals and threading.current_thread() is threading.main_thread()
    previous = signal.getsignal(signal.SIGTERM) if main_thread else None
    if main_thread:
        signal.signal(signal.SIGTERM, lambda *_: terminated.set())
    try:
        return _execute(argv, cwd=cwd, env=env, stdin=stdin, directory=directory, timeout=timeout,
                        consume=consume, finish=finish,
                        cancel=lambda: terminated.is_set() or (cancel is not None and cancel.is_set()),
                        max_output=max_output, structured=structured,
                        lease_fd=current_lease_fd() if lease_fd is None else lease_fd,
                        lease_fds=lease_fds, cleanup_session=cleanup_session)
    finally:
        if main_thread:
            signal.signal(signal.SIGTERM, previous)


def _execute(argv, *, cwd, env, stdin, directory, timeout, consume, finish, cancel,
             max_output, structured, lease_fd, lease_fds, cleanup_session):
    """Consume JSONL while draining stderr. Caller owns permissions and worktree lease.

    consume(event) and finish(exit_code) belong to the selected adapter. A completed
    process is not a successful BMAD story. Attempts are new directories and never reused.
    """
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and "\0" not in x for x in argv):
        raise ValueError("argv must be a nonempty list of literal strings")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(directory, 0o700)
    state = {"execution_status": "starting", "exit_code": None, "error": None}
    atomic_json(directory / "status.json", state)
    proc = None
    life_fd = None
    started = time.monotonic()
    try:
        with tempfile.TemporaryFile() as input_file, \
                open(directory / "stdout.jsonl", "wb") as stdout_log, \
                open(directory / "stderr.log", "wb") as stderr_log:
            input_file.write(stdin.encode("utf-8"))
            input_file.seek(0)
            if cancel():
                state["execution_status"] = "cancelled"
                atomic_json(directory / "status.json", state)
                return state
            proc, life_fd = spawn(argv, cwd=cwd, env=env, stdin=input_file,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, lease_fd=lease_fd,
                                  lease_fds=lease_fds, session=cleanup_session)
            state.update(execution_status="running", pid=proc.pid)
            atomic_json(directory / "status.json", state)
            pending = b""
            total = 0
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ, stdout_log)
                selector.register(proc.stderr, selectors.EVENT_READ, stderr_log)
                while selector.get_map() or proc.poll() is None:
                    if cancel():
                        state["execution_status"] = "cancelled"
                        break
                    if time.monotonic() - started >= timeout:
                        state["execution_status"] = "timed_out"
                        break
                    for key, _ in selector.select(timeout=0.05):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        if total > max_output:
                            raise ProtocolError("output limit exceeded")
                        key.data.write(chunk)
                        if structured and key.fileobj is proc.stdout:
                            pending += chunk
                            while b"\n" in pending:
                                line, pending = pending.split(b"\n", 1)
                                if len(line) > MAX_LINE:
                                    raise ProtocolError("JSONL line limit exceeded")
                                if line.strip():
                                    event = json.loads(line)
                                    if not isinstance(event, dict):
                                        raise ProtocolError("event must be a JSON object")
                                    consume(event)
                            if len(pending) > MAX_LINE:
                                raise ProtocolError("JSONL line limit exceeded")
                if state["execution_status"] in ("cancelled", "timed_out"):
                    terminate(proc)
                else:
                    # A final line without newline is legal; a partial JSON object is not.
                    if structured and pending.strip():
                        event = json.loads(pending)
                        if not isinstance(event, dict):
                            raise ProtocolError("event must be a JSON object")
                        consume(event)
                    remaining = timeout - (time.monotonic() - started)
                    try:
                        proc.wait(timeout=max(0.001, remaining))
                    except subprocess.TimeoutExpired:
                        state["execution_status"] = "timed_out"
                        terminate(proc)
                state["exit_code"] = proc.returncode
                if state["execution_status"] == "running":
                    state.update(finish(proc.returncode))
    except (ValueError, OSError) as e:
        if proc is not None:
            terminate(proc)
        state.update(execution_status="failed", error={"kind": "protocol" if isinstance(e, ValueError)
                     else "process", "message": str(e)}, exit_code=proc.returncode if proc else None)
    except BaseException:
        if proc is not None:
            terminate(proc)
        state.update(execution_status="interrupted")
        atomic_json(directory / "status.json", state)
        raise
    finally:
        if life_fd is not None:
            os.close(life_fd)
        if proc is not None:
            proc.stdout.close()
            proc.stderr.close()
            try:
                wait_cleanup(proc)
            except (OSError, RuntimeError) as e:
                state.update(execution_status="needs_attention", error={"kind": "cleanup_failed", "message": str(e)})
                atomic_json(directory / "status.json", state)
    state["seconds"] = round(time.monotonic() - started, 3)
    atomic_json(directory / "status.json", state)
    return state
