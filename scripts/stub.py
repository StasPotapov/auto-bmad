#!/usr/bin/env python3
"""Background servers of a check (API stubs, a dev server): started and stopped by name.

A verifier that starts a server must stop it, and without a human `kill $(cat pid)` and
`pkill -f` are often denied by the permission hook. `auto-bmad stub` is one allowed
command for both: `start` runs the command in its own process group and records it in
`.auto-bmad/stubs/<name>.json` of the main tree; `stop` stops only what it recorded.

A pid can go to another process after ours exits. So `stop` signals only a process with
the recorded start time and command; with the leader gone it signals the group only while
every member of it started after our start. TERM to the group first, KILL after a pause;
then it waits until the port is free.

Usage:
    stub.py start <name> [--port N] [--wait 30] [--repo .] -- <command> [args…]
    stub.py stop <name> [--repo .]
    stub.py stop --all [--repo .]
    stub.py list [--repo .]

The command after `--` runs without a shell, in the repository; shell syntax needs
`-- sh -c '…'`. With `--port`, start waits until the port answers and refuses a port
that is already taken.

JSON on stdout. Exit 0 — done, 1 — call error, 2 — refused or not done: the name is busy
with another command, the port is taken, the server did not come up, a port stayed busy.
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

from common import main_tree
from gitexclude import ensure_excluded

STUBS_REL = os.path.join(".auto-bmad", "stubs")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,48}$")
GRACE = 5
PORT_FREE_WAIT = 10


def stubs_dir(repo):
    return os.path.join(main_tree(repo), STUBS_REL)


def state_path(repo, name):
    return os.path.join(stubs_dir(repo), f"{name}.json")


def ps(*args):
    proc = subprocess.run(["ps", *args], capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def proc_info(pid):
    """→ {"start", "pgid", "command"} of a live process, or None."""
    out = ps("-o", "pgid=", "-o", "lstart=", "-o", "command=", "-p", str(pid)).strip()
    m = re.match(r"^\s*(\d+)\s+(\w{3}\s+\w{3}\s+\d+\s+[\d:]+\s+\d{4})\s+(.*)$", out)
    if not m:
        return None
    return {"pgid": int(m.group(1)), "start": " ".join(m.group(2).split()), "command": m.group(3)}


def started_at(lstart):
    try:
        return datetime.datetime.strptime(lstart, "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None


def group_members(pgid):
    """[(pid, start)] of the live processes in a process group; zombies do not count."""
    out = ps("-A", "-o", "pid=", "-o", "pgid=", "-o", "stat=", "-o", "lstart=")
    members = []
    for line in out.splitlines():
        m = re.match(r"^\s*(\d+)\s+(\d+)\s+(\S+)\s+(.+?)\s*$", line)
        if m and int(m.group(2)) == pgid and not m.group(3).startswith("Z"):
            members.append((int(m.group(1)), started_at(" ".join(m.group(4).split()))))
    return members


def ours(state):
    """Is the recorded group still ours → (yes, why)."""
    info = proc_info(state["pid"])
    if info:
        if info["start"] == state["start"] and info["command"] == state["ps_command"]:
            return True, "alive"
        return False, (f"pid {state['pid']} is another process now "
                       f"(started {info['start']}: {info['command'][:80]}) — left alone")
    members = group_members(state["pgid"])
    if not members:
        return False, "already stopped"
    begin = started_at(state["start"])
    if begin and all(start and start >= begin for _, start in members):
        return True, "the leader is gone, its group is alive"
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
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


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


def stop_one(repo, name):
    path = state_path(repo, name)
    state = read(path)
    if not state:
        return {"name": name, "stopped": False, "note": "no such stub"}, True
    mine, why = ours(state)
    out = {"name": name, "pid": state.get("pid"), "port": state.get("port"), "stopped": False, "note": why}
    if mine:
        signal_group(state["pgid"], signal.SIGTERM)
        deadline = time.time() + GRACE
        while time.time() < deadline and group_members(state["pgid"]):
            time.sleep(0.2)
        if group_members(state["pgid"]):
            signal_group(state["pgid"], signal.SIGKILL)
            out["killed"] = True
            time.sleep(0.2)
        out["stopped"] = not group_members(state["pgid"])
        out["note"] = "stopped" if out["stopped"] else "still alive after KILL"
    ok = mine is False or out["stopped"]
    if state.get("port"):
        deadline = time.time() + PORT_FREE_WAIT
        while time.time() < deadline and port_busy(state["port"]):
            time.sleep(0.2)
        out["port_free"] = not port_busy(state["port"])
        ok = ok and (out["port_free"] or not mine)
    if mine is False or out["stopped"]:
        try:
            os.remove(path)
        except OSError:
            pass
    return out, ok


def stop(repo, name=None, every=False):
    names = sorted(f[:-5] for f in os.listdir(stubs_dir(repo)) if f.endswith(".json")) \
        if every and os.path.isdir(stubs_dir(repo)) else [name]
    results, ok = [], True
    for n in names:
        res, good = stop_one(repo, n)
        results.append(res)
        ok = ok and good
    return {"stubs": results, "ok": ok}, 0 if ok else 2


def start(repo, name, command, port=None, wait=30):
    if not NAME.match(name or ""):
        return {"error": f"bad stub name {name!r}: letters, digits, dots, dashes, underscores"}, 1
    if not command:
        return {"error": "no command: stub start <name> [--port N] -- <command> [args…]"}, 1
    path = state_path(repo, name)
    joined = shlex.join(command)
    state = read(path)
    if state:
        mine, why = ours(state)
        if mine and state.get("command") == joined:
            return {**state, "started": False, "note": "already running"}, 0
        if mine:
            return {"error": f"stub {name} runs another command ({state.get('command')}) — "
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
    deadline = time.time() + (wait if port else 0.5)
    while time.time() < deadline and proc.poll() is None:
        if port and port_busy(port):
            break
        time.sleep(0.2)
    info = proc_info(proc.pid) if proc.poll() is None else None
    if not info or (port and not port_busy(port)):
        if proc.poll() is None:
            signal_group(proc.pid, signal.SIGKILL)
        why = "the command exited" if proc.poll() is not None else f"port {port} did not answer in {wait} s"
        return {"error": f"{why}: {joined}", "log": log, "log_tail": tail(log)}, 2
    state = {"name": name, "pid": proc.pid, "pgid": info["pgid"], "command": joined,
             "ps_command": info["command"], "start": info["start"], "port": port,
             "cwd": os.path.abspath(repo), "log": log,
             "started_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    return {**state, "started": True, "stop": f"auto-bmad stub stop {name}"}, 0


def listing(repo):
    out = []
    if os.path.isdir(stubs_dir(repo)):
        for f in sorted(os.listdir(stubs_dir(repo))):
            state = read(os.path.join(stubs_dir(repo), f)) if f.endswith(".json") else None
            if state:
                mine, why = ours(state)
                out.append({k: state.get(k) for k in ("name", "pid", "port", "command", "started_at")}
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
    ap.add_argument("--all", action="store_true", help="stop every recorded stub")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    if a.action == "start":
        result, code = start(repo, a.name, command, a.port, a.wait)
    elif a.action == "stop":
        if not a.name and not a.all:
            result, code = {"error": "stop needs a name or --all"}, 1
        else:
            result, code = stop(repo, a.name, a.all)
    else:
        result, code = listing(repo)
    if result.get("error"):
        print(result["error"], file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
