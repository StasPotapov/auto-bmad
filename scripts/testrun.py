#!/usr/bin/env python3
"""Project test runs under the folder's lock, with the result kept for unchanged code.

Every role of a run (the engine session, the implementer, the post-story check, land) runs
the project tests through this command instead of the command itself:
  * linked Git worktrees share a resource lock: test databases, ports and devices must
    not overlap. Each folder also keeps its own test lock. Unrelated repositories do
    not wait for each other;
  * the result is kept by the key "content of the tree + command": the tree is the working
    copy with untracked files, without _bmad-output/ and .auto-bmad/ (spec and state edits
    do not change the code). The same key again — the kept result comes back at once,
    a green one and a red one: the same code fails the same way. A timeout is not kept.
    --rerun takes only a result of the last RECENT seconds (a failure from outside the code —
    Docker was not running); `rerun="red"` takes a red result of the last RECENT_RED seconds
    only (verify baseline: a red kept from another day must not hide a story's breakage);
  * the run goes in its own detached process and outlives the Bash call: after --wait
    seconds the call answers `running`, and the same call again joins that run — also when
    the run itself changed the tree. Nobody needs run_in_background, pgrep or sleep loops.

State: <folder>/.auto-bmad/tests/ — lock, <key>.json (result), <key>.log (full output),
<key>.pid (the run in progress: pid, start, command), <key>.answer.json (the answer to the
call that started a run), history.jsonl (one line per finished call: seconds, reused).

Usage:
    testrun.py [--command CMD | --name project-tests] [--wait 540] [--timeout S] [--rerun] [--repo .]

Without --command the command is the kind=command check --name of the config. Prints JSON:
verdict pass | problem | running, code, seconds, reused, tail (the end of a failed output),
log. Exit: 0 — finished (the verdict says how), 3 — still running, call again; 1 — error.
"""

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import threading
from contextlib import nullcontext
from types import SimpleNamespace
from process_guard import spawn as guarded_spawn, wait_cleanup

from gitexclude import ensure_excluded

STATE = os.path.join(".auto-bmad", "tests")
NOT_CODE = ("_bmad-output", ".auto-bmad")
TAIL = 60
DEFAULT_WAIT = 540     # below the 600 s limit of a Bash call
DEFAULT_TIMEOUT = 1800
RECENT = 120           # --rerun still takes a result this fresh: the answer to its own run
RECENT_RED = 900       # rerun="red" (verify baseline): a red result of this run is kept
KEEP = 40              # results kept per folder


def git(repo, *args, env=None):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=env)


def tree_hash(repo):
    """The tree of the working copy with untracked files, without NOT_CODE; not git — None.

    A copy of the index is staged, so the real index is untouched and unchanged files are
    not hashed again.
    """
    path = git(repo, "rev-parse", "--path-format=absolute", "--git-path", "index").stdout.strip()
    if not path:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        index = os.path.join(tmp, "index")
        if os.path.exists(path):
            # Git needs the original index timestamp to rehash files changed in its
            # timestamp resolution; a newly timestamped copy can hide same-size edits.
            shutil.copy2(path, index)
        env = {**os.environ, "GIT_INDEX_FILE": index}
        if git(repo, "add", "-A", env=env).returncode:
            return None
        git(repo, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", *NOT_CODE, env=env)
        out = git(repo, "write-tree", env=env)
        return out.stdout.strip() if out.returncode == 0 else None


def key_of(repo, command, component=None, scope_config=None):
    if component:
        import project_tests
        tree = project_tests.fingerprint(repo, project_tests.settings({"project_tests": scope_config}), component)
    else:
        tree = tree_hash(repo) or f"no-git-{time.time_ns()}"
    return hashlib.sha1(f"{tree}\0{command}".encode()).hexdigest()[:16]


def state(repo, name=""):
    return os.path.join(repo, STATE, name)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_json(path, data):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def history(repo, row):
    try:
        with open(state(repo, "history.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": now(), **row}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def kept(repo, key, rerun=False):
    """The kept result of the key that may be reused; rerun — only a fresh one (all or "red")."""
    res = read_json(state(repo, f"{key}.json"))
    if not res or res.get("verdict") not in ("pass", "problem"):
        return None
    limit = RECENT if rerun is True else RECENT_RED if rerun == "red" and res["verdict"] == "problem" else None
    if limit is not None:
        try:
            age = time.time() - os.path.getmtime(state(repo, f"{key}.json"))
        except OSError:
            return None
        if age > limit:
            return None
    return res


def live(record):
    """Is the run of this .pid record still the same process (pid and start time)."""
    if record.get("session"):
        try:
            return 0 <= time.monotonic() - record["pulse"] <= 2
        except (KeyError, TypeError):
            return False
    from stub import Unknown, proc_info
    try:
        info = proc_info(record["pid"])
    except Unknown:
        return True
    except (KeyError, TypeError):
        return False
    return bool(info) and info["start"] == record.get("start")


def live_runs(repo):
    """{key: .pid record} of the runs in progress in this folder; stale records are removed."""
    out = {}
    for name in os.listdir(state(repo)):
        if not name.endswith(".pid"):
            continue
        record = read_json(state(repo, name))
        if record and live(record):
            out[name[:-len(".pid")]] = record
        elif record:
            unlink(state(repo, name))
    return out


def prune(repo):
    results = sorted((os.path.getmtime(p), p) for p in
                     (state(repo, n) for n in os.listdir(state(repo)) if n.endswith(".json")))
    for _, path in results[:-KEEP]:
        for p in (path, path[:-len(".json")] + ".log"):
            unlink(p)


def work(repo, key, command, timeout, rerun, session=None, component=None, scope_config=None, owner_fds=()):
    """The detached run: waits for the folder's lock, runs the command, writes the result.

    The key is computed again under the lock — the code may have changed while it waited.
    Cache only a tree unchanged throughout the run. The caller's answer uses its original
    key even when a suite writes untracked files; that new tree still needs verification.
    """
    if session and os.getpgrp() != os.getpid():
        raise ValueError("a session test worker must own its process group")
    from stub import proc_info
    me = {} if session else proc_info(os.getpid()) or {}
    pid_path = state(repo, f"{key}.pid")
    record = {"pid": os.getpid(), "start": me.get("start"), "command": command, "session": session,
              "pulse": time.monotonic()}
    write_json(pid_path, record)
    watch_done = threading.Event()
    watch_thread = None
    if session:
        from execution_state import ControllerWatch
        watch = ControllerWatch(repo, session)

        def supervise():
            while not watch_done.wait(0.1):
                if not watch.tests_alive():
                    os.killpg(os.getpgrp(), signal.SIGTERM)
                    return
                record["pulse"] = time.monotonic()
                write_json(pid_path, record)
        watch_thread = threading.Thread(target=supervise, daemon=True)
        watch_thread.start()
    answer = state(repo, f"{key}.answer.json")
    from execution_state import resource_lock
    project = git(repo, "rev-parse", "--show-toplevel")
    shared = resource_lock(project.stdout.strip(), SimpleNamespace(
        is_set=lambda: bool(session and not watch.tests_alive()))) if project.returncode == 0 else nullcontext(None)
    try:
        with shared as resource_fd, open(state(repo, "lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if session and not watch.tests_alive():
                return 125
            before = key_of(repo, command, component, scope_config)
            res = kept(repo, before, rerun)
            if res:
                write_json(answer, {**res, "reused": True})
                return 0
            log_path = state(repo, f"{before}.log")
            t0 = time.monotonic()
            with open(log_path, "w", encoding="utf-8") as log:
                if session and not watch.tests_alive():
                    return 125
                proc, life_fd = guarded_spawn(["sh", "-c", command], cwd=repo, stdout=log,
                                              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                              lease_fd=lock.fileno(),
                                              lease_fds=tuple(owner_fds) + (() if resource_fd is None else (resource_fd,)))
                try:
                    code, note = proc.wait(timeout=timeout), None
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                    code, note = None, f"the command did not finish in {timeout} s"
                finally:
                    os.close(life_fd)
                    wait_cleanup(proc)
            seconds = round(time.monotonic() - t0)
            with open(log_path, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
            res = {"verdict": "pass" if code == 0 else "problem", "code": code,
                   "seconds": seconds, "command": command, "finished": now(), "log": log_path,
                   "tail": "" if code == 0 else "\n".join(([note] if note else []) + lines[-TAIL:])}
            res["tree_changed"] = before != key_of(repo, command, component, scope_config)
            if code is not None and not res["tree_changed"]:
                write_json(state(repo, f"{before}.json"), res)
            write_json(answer, {**res, "reused": False})
            prune(repo)
    finally:
        watch_done.set()
        if watch_thread:
            watch_thread.join()
        record = read_json(pid_path)
        if record and record.get("pid") == os.getpid():
            unlink(pid_path)
    return 0


def spawn(repo, key, command, timeout, rerun, session=None, component=None, scope_config=None, owner_fds=()):
    args = [sys.executable, os.path.abspath(__file__), "--worker", "--key", key,
            "--command", command, "--timeout", str(timeout), "--repo", repo]
    if rerun:
        args += ["--rerun-mode", "red" if rerun == "red" else "all"]
    if session:
        args += ["--session", session]
    if component:
        args += ["--component", component, "--component-config", json.dumps(scope_config)]
    for fd in owner_fds:
        args += ["--owner-fd", str(fd)]
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True, pass_fds=tuple(owner_fds))
    # Written here too, so a call right after this one joins the run, not starts another.
    if session:
        write_json(state(repo, f"{key}.pid"), {"pid": proc.pid, "start": None, "command": command,
                                             "session": session, "pulse": time.monotonic()})
        return proc
    from stub import Unknown, proc_info
    try:
        info = proc_info(proc.pid)
    except Unknown:
        info = None
    if info:
        write_json(state(repo, f"{key}.pid"), {"pid": proc.pid, "start": info["start"], "command": command, "session": session})
    return proc


def finish(repo, res, key):
    history(repo, {"key": key, "command": res.get("command"), "verdict": res.get("verdict"),
                   "seconds": 0 if res.get("reused") else res.get("seconds"),
                   "reused": bool(res.get("reused"))})
    return {**res, "key": key}, 0


def run(repo, command, timeout=DEFAULT_TIMEOUT, wait=DEFAULT_WAIT, rerun=False, session=None, component=None, scope_config=None, owner_fds=()):
    """The result of the command for the current code → (result dict, exit code).

    rerun — False, True (only a result of the last RECENT seconds) or "red" (so for red only).
    """
    ensure_excluded(repo, ".auto-bmad/")
    if session:
        from execution_state import ControllerWatch
        watch = ControllerWatch(repo, session)
        if not watch.tests_alive():
            return {"error": "controller session is no longer active"}, 1
        # The verifier already owns the shared resource lock. Registered checks use
        # the host bridge; a sandbox worker would wait on its own parent's lock.
        if (read_json(str(watch.session)) or {}).get("writer") == "verifier":
            return {"error": "verifiers must use a registered --name check (project-tests or dev/<name>); "
                             "unregistered commands cannot run inside the verifier resource lock"}, 1
        if not os.path.realpath(state(repo)).startswith(os.path.realpath(repo) + os.sep):
            return {"error": "test state escapes the worktree"}, 1
    os.makedirs(state(repo), exist_ok=True)
    key = key_of(repo, command, component, scope_config)
    runs = live_runs(repo)
    if key not in runs:
        res = kept(repo, key, rerun)
        if res:
            return finish(repo, {**res, "reused": True}, key)
    # A run of the same command in progress is joined, whatever key it was started with.
    joined = key if key in runs else next((k for k, r in runs.items() if r.get("command") == command), None)
    proc = None
    if joined is None:
        joined = key
        unlink(state(repo, f"{key}.answer.json"))
        proc = spawn(repo, key, command, timeout, rerun, session, component, scope_config, owner_fds)
    answer = state(repo, f"{joined}.answer.json")
    deadline = time.monotonic() + wait
    while True:
        res = read_json(answer)
        if res:
            return finish(repo, res, joined)
        if proc:
            done = proc.poll() is not None
        else:
            record = read_json(state(repo, f"{joined}.pid"))
            done = not (record and live(record))
        if done:
            res = read_json(answer)
            if res:
                return finish(repo, res, joined)
            return {"error": "the test run stopped without a result",
                    "log": state(repo, f"{joined}.log"), "key": joined}, 1
        if time.monotonic() >= deadline:
            again = "the same command again" + (" without --rerun" if rerun is True else "")
            return {"verdict": "running", "command": command, "key": joined,
                    "log": state(repo, f"{joined}.log"),
                    "note": f"the tests still run in the background: call {again} to wait for "
                            "them; do not start them another way"}, 3
        time.sleep(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--command", help="the command to run (default: the --name check)")
    ap.add_argument("--name", default="project-tests", help="a kind=command check of the config")
    ap.add_argument("--target", action="append", help="repository-relative test file/node for a registered dev/ check (repeatable)")
    ap.add_argument("--wait", type=int, default=DEFAULT_WAIT, help="seconds to wait before `running`")
    ap.add_argument("--timeout", type=int, help="seconds the command may run (default: the check's)")
    ap.add_argument("--rerun", action="store_true",
                    help=f"run again unless a result is under {RECENT} s old")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--session", help="controller-issued session; stop the test if that controller dies")
    ap.add_argument("--base", help="exact pre-story commit for project-defined component checks outside a CLI session")
    ap.add_argument("--component", help=argparse.SUPPRESS)
    ap.add_argument("--component-config", help=argparse.SUPPRESS)
    ap.add_argument("--owner-fd", type=int, action="append", default=[], help=argparse.SUPPRESS)
    ap.add_argument("--tree", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--key", help=argparse.SUPPRESS)
    ap.add_argument("--rerun-mode", choices=("all", "red"), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    if a.target and (a.command or not a.name.startswith("dev/")):
        print(json.dumps({"error": "--target requires --name dev/<check>, without --command"}))
        return 1
    if a.tree:
        print(json.dumps({"tree": tree_hash(repo)}))
        return 0
    if a.worker:
        mode = {"all": True, "red": "red"}.get(a.rerun_mode, False)
        return work(repo, a.key, a.command, a.timeout or DEFAULT_TIMEOUT, mode, a.session,
                    a.component, json.loads(a.component_config) if a.component_config else None, a.owner_fd)
    if not os.path.isdir(repo):
        out, code = {"error": f"no such directory {repo}"}, 1
    else:
        if a.session:
            from execution_state import ControllerWatch
            watch = ControllerWatch(repo, a.session)
            data = read_json(str(watch.session))
            configured, timeout = data.get("test_command"), data.get("test_timeout")
            if data.get("host_tests", {}).get("version") == 1:
                from test_bridge import check_name, request
                name = check_name(data, a.command, a.name)
                if not name and data["host_tests"].get("scopes"):
                    print(json.dumps({"error": "unregistered scoped test command; use project-tests or a registered --name", "checks": list(data["host_tests"]["checks"])}))
                    return 1
                if not name and not a.command:
                    print(json.dumps({"error": "the requested check is not registered in this controller session"}))
                    return 1
                if name:
                    try:
                        out = request(repo, a.session, name, rerun=a.rerun, targets=a.target)
                    except (OSError, ValueError, KeyError, TypeError) as e:
                        out = {"error": str(e)}
                    print(json.dumps(out, ensure_ascii=False, indent=2))
                    return 1 if out.get("error") else 0
        else:
            from verify import command_check
            configured, timeout = command_check(repo, a.name)
            from ext import load
            import project_tests
            cfg = load(repo, strict=True)[0]
            if a.name.startswith("dev/"):
                try:
                    item = project_tests.settings(cfg).get("development", {})[a.name[4:]]
                    command = project_tests.development_command(repo, item, a.target)
                except (OSError, KeyError, ValueError, TypeError) as e:
                    print(json.dumps({"error": str(e)}))
                    return 1
                out, code = run(repo, command, a.timeout or item.get("timeout", DEFAULT_TIMEOUT),
                                max(a.wait, 0), a.rerun)
                print(json.dumps({**out, "development": True, "targets": a.target}, ensure_ascii=False, indent=2))
                return code
            if project_tests.enabled(cfg) and a.name == "project-tests" and (not a.command or a.command == configured):
                if not a.base:
                    print(json.dumps({"error": "scoped project-tests require --base <pre-story commit> (or the controller --session)"}))
                    return 1
                import native_tests
                result, code = native_tests.run(repo, a.base, cfg, max(a.wait, 0), a.rerun, a.timeout)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return code
        command = a.command or configured
        if not command:
            out, code = {"error": f"no test command: the {a.name} check is off, is not a "
                                  "kind=command check, or the project has no test command"}, 1
        else:
            mode = {"all": True, "red": "red"}.get(a.rerun_mode, a.rerun)
            out, code = run(repo, command, a.timeout or timeout or DEFAULT_TIMEOUT,
                            max(a.wait, 0), mode, a.session)
    if out.get("error"):
        print(out["error"], file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
