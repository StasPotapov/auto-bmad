#!/usr/bin/env python3
"""The project's dev server for the mockmatch check: on a free port, started once per run.

A port that answers is not proof that it is this project's site: on a shared machine it may
be another service. So a running server is reused only when this script started it (the
state file in .auto-bmad/ names its process group and the process is alive). Otherwise the
script takes the first free port from the port of --url up, starts --serve on it and waits
until the site answers.

The port reaches the server three ways: `{port}` in --serve is replaced; PORT=<port> is set
in the environment; `<pm> run <script>` gets `--port <port>` appended (`-- --port` for npm),
and `python3 -m http.server N` gets N replaced.

Usage (from the project root):
    serve.py start --serve "npm run dev" --url http://localhost:5173 [--wait 90]
    serve.py stop

Always JSON on stdout. start: {"url", "port", "pid", "started", "cleanup", "log"}, exit 0;
the server did not come up — {"error", "log_tail"}, exit 1. stop: {"stopped"}, exit 0.
"""
import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

STATE_DIR = ".auto-bmad"
STATE = os.path.join(STATE_DIR, "mockmatch-serve.json")
LOG = os.path.join(STATE_DIR, "mockmatch-serve.log")
PORT_TRIES = 50


def port_busy(port):
    """Something listens on the port (IPv4 or IPv6), or it cannot be bound."""
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
    except OSError:
        return True
    return False


def free_port(start):
    for port in range(start, start + PORT_TRIES):
        if not port_busy(port):
            return port
    return None


def answers(url):
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except urllib.error.HTTPError:
        return True                   # the server is up, the page is another matter
    except (OSError, ValueError):
        return False


def alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except (OSError, TypeError):
        return False


def with_port(url, port):
    parts = urlsplit(url)
    return urlunsplit(parts._replace(netloc=f"{parts.hostname}:{port}"))


def command_for(serve, port):
    if "{port}" in serve:
        return serve.replace("{port}", str(port))
    m = re.search(r"http\.server(\s+\d+)?\s*$", serve)
    if m:
        return serve[:m.start()] + f"http.server {port}"
    m = re.search(r"\b(npm|pnpm|yarn|bun)\s+(run\s+)?[\w:.-]+\s*$", serve)
    if m:
        return serve + (f" -- --port {port}" if m.group(1) == "npm" else f" --port {port}")
    return serve


def read_state():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def tail(path, n=30):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return "\n".join(fh.read().splitlines()[-n:])
    except OSError:
        return ""


def stop():
    state = read_state()
    stopped = False
    if state and alive(state.get("pid")):
        try:
            os.killpg(state["pid"], signal.SIGTERM)
            stopped = True
        except OSError:
            pass
    try:
        os.remove(STATE)
    except OSError:
        pass
    return {"stopped": stopped}, 0


def start(serve, url, wait):
    me = os.path.abspath(__file__)
    cleanup = f"python3 {me} stop"
    state = read_state()
    if state and alive(state.get("pid")) and answers(state["url"]):
        return {**state, "started": False, "cleanup": cleanup, "log": LOG}, 0
    if not urlsplit(url).port:
        return {"error": f"no port in --url {url}"}, 1
    port = free_port(urlsplit(url).port)
    if port is None:
        return {"error": f"no free port in {urlsplit(url).port}–{urlsplit(url).port + PORT_TRIES - 1}"}, 1
    os.makedirs(STATE_DIR, exist_ok=True)
    target = with_port(url, port)
    command = command_for(serve, port)
    with open(LOG, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(["sh", "-c", command], stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True,
                                env={**os.environ, "PORT": str(port), "BROWSER": "none"})
    state = {"url": target, "port": port, "pid": proc.pid, "command": command}
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    deadline = time.time() + wait
    while time.time() < deadline:
        if answers(target):
            return {**state, "started": True, "cleanup": cleanup, "log": LOG}, 0
        if proc.poll() is not None:
            break
        time.sleep(1)
    stop()
    why = "the server exited" if proc.poll() is not None else f"no answer in {wait} s"
    return {"error": f"{why}: {command}", "url": target, "log_tail": tail(LOG)}, 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--serve", required=True)
    s.add_argument("--url", required=True)
    s.add_argument("--wait", type=int, default=90)
    sub.add_parser("stop")
    a = ap.parse_args()
    out, code = start(a.serve, a.url, a.wait) if a.cmd == "start" else stop()
    print(json.dumps(out, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
