#!/usr/bin/env python3
"""Background servers of a check (API stubs, a dev server): started and stopped by name.

A verifier that starts a server must stop it, and without a human `kill $(cat pid)` and
`pkill -f` are often denied by the permission hook. `auto-bmad stub` is one allowed
command for both: `start` runs the command in its own process group and records it in
`.auto-bmad/stubs/<name>.json` of the main tree; `stop` stops only what it recorded.

Every stub knows its owner: the working tree it was started from (a run worktree is its
own tree) and the run, when there is one (`--run <id>` or $AUTO_BMAD_RUN). `stop --all`
stops the stubs of its own tree; `stop --all --runs-only` (story-finish, the end of a run)
only those of a run, so a server a human started by hand stays alive.

A pid can go to another process after ours exits. So `stop` signals a process only while
its pid, start time and process group are the recorded ones; the command is reported, not
compared (a server may re-exec itself). With the leader gone, it signals the group only
while every live member started after the stub. TERM to the group first, KILL after a
pause; then it waits until the port is free. When it cannot tell, it keeps the record.

Usage:
    stub.py start <name> [--port N] [--wait 30] [--run ID] [--repo .] -- <command> [args…]
    stub.py stop <name> [--repo .]
    stub.py stop --all [--runs-only] [--repo .]
    stub.py list [--repo .]

The command after `--` runs without a shell, in the repository; shell syntax needs
`-- sh -c '…'`. With `--port`, start waits until the port answers and refuses a port
that is already taken.

JSON on stdout. Exit 0 — done, 1 — call error, 2 — refused or not done: the name is busy
with another command, the port is taken, the server did not come up, a stub did not stop,
its record is broken or its state is unknown.
"""

import argparse
import datetime
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import time

from common import git, main_tree
from gitexclude import ensure_excluded
from worktree import RUN_NAME as NAME

STUBS_REL = os.path.join(".auto-bmad", "stubs")
GRACE = 5
PORT_FREE_WAIT = 10
PS_ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}       # lstart in English whatever the locale


class Unknown(Exception):
    """ps did not answer: whether the process lives is not known."""


def stubs_dir(repo):
    return os.path.join(main_tree(repo), STUBS_REL)


def state_path(repo, name):
    return os.path.join(stubs_dir(repo), f"{name}.json")


def tree_of(repo):
    """The working tree the command runs in: a linked worktree is its own tree."""
    top = git(repo, "rev-parse", "--show-toplevel")
    return os.path.realpath(top.stdout.strip() if top.returncode == 0 else repo)


def ps(*args):
    proc = subprocess.run(["ps", *args], capture_output=True, text=True, env=PS_ENV)
    return proc.returncode, proc.stdout


def exists(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def proc_info(pid):
    """→ {"start", "pgid", "command", "zombie"} of a process; gone — None; ps failed — Unknown."""
    if not exists(pid):
        return None
    code, out = ps("-o", "pgid=", "-o", "stat=", "-o", "lstart=", "-o", "command=", "-p", str(pid))
    m = re.match(r"^\s*(\d+)\s+(\S+)\s+(\w{3}\s+\w{3}\s+\d+\s+[\d:]+\s+\d{4})\s+(.*)$", out.strip())
    if not m:
        if not exists(pid):
            return None
        raise Unknown(f"ps gave no line for pid {pid} (exit {code})")
    if m.group(2).startswith("Z"):
        return None
    return {"pgid": int(m.group(1)), "start": " ".join(m.group(3).split()), "command": m.group(4)}


def started_at(lstart):
    try:
        return datetime.datetime.strptime(lstart, "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None


def group_members(pgid):
    """[(pid, start)] of the live processes in a process group; zombies do not count."""
    code, out = ps("-A", "-o", "pid=", "-o", "pgid=", "-o", "stat=", "-o", "lstart=")
    if code:
        raise Unknown(f"ps -A failed (exit {code})")
    members = []
    for line in out.splitlines():
        m = re.match(r"^\s*(\d+)\s+(\d+)\s+(\S+)\s+(.+?)\s*$", line)
        if m and int(m.group(2)) == pgid and not m.group(3).startswith("Z"):
            members.append((int(m.group(1)), started_at(" ".join(m.group(4).split()))))
    return members


def ours(state):
    """Is the recorded group still ours → (True / False / None when unknown, why)."""
    try:
        info = proc_info(state["pid"])
        if info:
            if info["start"] == state["start"] and info["pgid"] == state["pgid"]:
                return True, "alive"
            return False, (f"pid {state['pid']} is another process now "
                           f"(started {info['start']}: {info['command'][:80]}) — left alone")
        members = group_members(state["pgid"])
    except Unknown as e:
        return None, f"state unknown: {e} — the record is kept"
    if not members:
        return False, "already stopped"
    begin = started_at(state["start"])
    if begin and all(start and start >= begin for _, start in members):
        return True, f"the leader is gone, its group is alive ({len(members)} process(es))"
    return False, f"group {state['pgid']} has processes older than the stub — left alone"


def port_busy(port):
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            pass
    return False


def read(path):
    """The record → (state or None when there is no file, error or None)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as e:
        return None, f"the record {path} is unreadable: {e}"
    missing = [k for k in ("pid", "pgid", "start") if not isinstance(data, dict) or k not in data]
    if missing:
        return None, f"the record {path} is not a stub record (no {', '.join(missing)}) — check it and remove it by hand"
    return data, None


def tail(path, n=20):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return "\n".join(fh.read().splitlines()[-n:])
    except OSError:
        return ""


def signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def stop_group(pgid):
    """TERM, then KILL after GRACE → (stopped, killed)."""
    signal_group(pgid, signal.SIGTERM)
    deadline = time.time() + GRACE
    while time.time() < deadline and group_members(pgid):
        time.sleep(0.2)
    killed = False
    if group_members(pgid):
        signal_group(pgid, signal.SIGKILL)
        killed = True
        time.sleep(0.2)
    return not group_members(pgid), killed


def stop_one(repo, name):
    path = state_path(repo, name)
    state, error = read(path)
    if error:
        return {"name": name, "stopped": False, "error": error}, False
    if not state:
        return {"name": name, "stopped": False, "note": "no such stub"}, True
    mine, why = ours(state)
    out = {"name": name, "pid": state.get("pid"), "port": state.get("port"),
           "command": state.get("command"), "stopped": False, "note": why}
    if mine is None:
        return out, False
    if mine:
        try:
            out["stopped"], out["killed"] = stop_group(state["pgid"])
        except Unknown as e:
            out["note"] = f"state unknown after the signal: {e} — the record is kept"
            return out, False
        out["note"] = "stopped" if out["stopped"] else "still alive after KILL — the record is kept"
        if state.get("port"):
            deadline = time.time() + PORT_FREE_WAIT
            while time.time() < deadline and port_busy(state["port"]):
                time.sleep(0.2)
            out["port_free"] = not port_busy(state["port"])
    if not mine or out["stopped"]:
        try:
            os.remove(path)
        except OSError:
            pass
    return out, (not mine) or (out["stopped"] and out.get("port_free", True))


def recorded(repo):
    folder = stubs_dir(repo)
    return sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json")) if os.path.isdir(folder) else []


def stop(repo, name=None, every=False, runs_only=False):
    """Stops one stub by name, or every stub of this tree (`runs_only` — only those of a run)."""
    if not every:
        if not NAME.match(name or ""):
            return {"error": f"bad stub name {name!r}"}, 1
        res, ok = stop_one(repo, name)
        return {"stubs": [res], "ok": ok}, 0 if ok else 2
    tree = tree_of(repo)
    results, ok, kept = [], True, []
    for n in recorded(repo):
        state, error = read(state_path(repo, n))
        if state and (state.get("tree") != tree or (runs_only and not state.get("run"))):
            kept.append(n)
            continue
        res, good = stop_one(repo, n)
        results.append(res)
        ok = ok and good
    out = {"stubs": results, "ok": ok}
    if kept:
        out["kept"] = kept          # another tree's stubs, or started by hand outside a run
    return out, 0 if ok else 2


def start(repo, name, command, port=None, wait=30, run=None):
    if not NAME.match(name or ""):
        return {"error": f"bad stub name {name!r}: letters, digits, dots, dashes, underscores"}, 1
    if not command:
        return {"error": "no command: stub start <name> [--port N] -- <command> [args…]"}, 1
    path = state_path(repo, name)
    joined = shlex.join(command)
    tree = tree_of(repo)
    run = run or os.environ.get("AUTO_BMAD_RUN") or None
    state, error = read(path)
    if error:
        return {"error": error}, 2
    if state:
        mine, why = ours(state)
        if mine is None:
            return {"error": f"stub {name}: {why}"}, 2
        if mine and state.get("command") == joined and state.get("tree") == tree:
            return {**state, "started": False, "note": "already running"}, 0
        if mine:
            return {"error": f"stub {name} runs another command ({state.get('command')}) from {state.get('tree')} — "
                             f"stop it first: auto-bmad stub stop {name}"}, 2
        os.remove(path)
    if port and port_busy(port):
        return {"error": f"port {port} is already taken by another process — "
                         "pick another port or stop that process"}, 2
    ensure_excluded(main_tree(repo), ".auto-bmad/")
    os.makedirs(stubs_dir(repo), exist_ok=True)
    log = os.path.join(stubs_dir(repo), f"{name}.log")
    try:
        with open(log, "w", encoding="utf-8") as fh:
            proc = subprocess.Popen(command, cwd=repo, stdout=fh, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        return {"error": f"cannot start {joined}: {e}"}, 2
    try:
        first = proc_info(proc.pid)
    except Unknown:
        first = None
    deadline = time.time() + (wait if port else 0.5)
    while time.time() < deadline and proc.poll() is None:
        if port and port_busy(port):
            break
        time.sleep(0.2)
    try:
        info = proc_info(proc.pid) if proc.poll() is None else None
        if not info and first:
            # The leader exited (a command that daemonizes): the group may be the server.
            begin = started_at(first["start"])
            members = [m for m in group_members(proc.pid) if m[1] and begin and m[1] >= begin]
            if members:
                info = {**first, "command": first["command"], "leader_gone": True}
    except Unknown:
        info = None
    if not info or (port and not port_busy(port)):
        why = ("the command exited" if not info else f"port {port} did not answer in {wait} s")
        result = {"error": f"{why}: {joined}", "log": log, "log_tail": tail(log)}
        if signal_group(proc.pid, signal.SIGKILL):
            result["killed_group"] = proc.pid      # nothing of it is left without a record
        return result, 2
    state = {"name": name, "pid": proc.pid, "pgid": info["pgid"], "command": joined,
             "ps_command": info["command"], "start": info["start"], "port": port,
             "tree": tree, "run": run, "log": log,
             "started_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    if info.get("leader_gone"):
        state["leader_gone"] = True
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    return {**state, "started": True, "stop": f"auto-bmad stub stop {name}"}, 0


def listing(repo):
    out = []
    for n in recorded(repo):
        state, error = read(state_path(repo, n))
        if error:
            out.append({"name": n, "error": error})
            continue
        mine, why = ours(state)
        out.append({k: state.get(k) for k in ("name", "pid", "port", "command", "tree", "run", "started_at")}
                   | {"alive": mine, "note": why})
    return {"stubs": out}, 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command = []
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=("start", "stop", "list"))
    ap.add_argument("name", nargs="?")
    ap.add_argument("--port", type=int)
    ap.add_argument("--wait", type=int, default=30, help="seconds to wait for the port (start)")
    ap.add_argument("--run", help="the run that owns the stub (default $AUTO_BMAD_RUN)")
    ap.add_argument("--all", action="store_true", help="stop every stub of this tree")
    ap.add_argument("--runs-only", action="store_true", help="with --all: only the stubs of a run")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    if a.action == "start":
        result, code = start(repo, a.name, command, a.port, a.wait, a.run)
    elif a.action == "stop":
        if not a.name and not a.all:
            result, code = {"error": "stop needs a name or --all"}, 1
        else:
            result, code = stop(repo, a.name, a.all, a.runs_only)
    else:
        result, code = listing(repo)
    if result.get("error"):
        print(result["error"], file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
