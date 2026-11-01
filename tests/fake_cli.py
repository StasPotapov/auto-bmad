"""Offline child process used by the CLI transport tests; never imports a model SDK."""
import json
import os
import signal
import subprocess
import sys
import time


def event(value):
    print(json.dumps(value), flush=True)


mode = sys.argv[1]
if mode == "hang":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print("starting", file=sys.stderr, flush=True)
    time.sleep(30)
elif mode == "closed-pipes":
    os.close(1)
    os.close(2)
    time.sleep(30)
elif mode == "malformed":
    print('{"type":', flush=True)
elif mode == "flood":
    sys.stderr.write("x" * 100000)
elif mode == "empty":
    pass
elif mode == "error":
    event({"type": "error", "message": "permission denied"})
elif mode == "exit-failure":
    sys.exit(7)
elif mode == "detached-pipe":
    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True)
    with open("detached.pid", "w") as file:
        file.write(str(child.pid))
    event({"type": "item.completed", "item": {"type": "agent_message", "text": '{"status":"done"}'}})
    event({"type": "turn.completed"})
elif mode in ("late-final", "invalid-terminal"):
    event({"type": "turn.started"})
    time.sleep(1.95 if mode == "late-final" else 0)
    event({"type": "item.completed", "item": {"type": "agent_message", "text": '{"status":"done"}'}})
    sys.stdout.write(json.dumps({"type": "turn.completed"}))
    sys.stdout.flush()
    if mode == "invalid-terminal":
        time.sleep(0.05)
        print("garbage", flush=True)
elif mode in ("progress", "chatter", "duplicate", "duplicate-new-id", "silent"):
    until = time.monotonic() + 0.9
    number = 0
    while time.monotonic() < until:
        if mode == "silent":
            time.sleep(0.04)
            continue
        number += 1
        item = ({"type": "agent_message", "text": "still waiting"} if mode == "chatter" else
                {"type": "command_execution", "id": str(number if mode in ("progress", "duplicate-new-id") else 1),
                 "status": "completed", "command": "work", "aggregated_output": str(number) if mode == "progress" else ""})
        event({"type": "item.completed", "item": item})
        time.sleep(0.04)
    event({"type": "item.completed", "item": {"type": "agent_message", "text": '{"status":"done"}'}})
    event({"type": "turn.completed"})
else:
    text = sys.stdin.read()
    sys.stderr.write("x" * 70000)  # larger than a pipe buffer
    event({"type": "thread.started", "thread_id": "fake-thread"})
    event({"type": "future.optional.event"})
    event({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({
        "status": "done", "stdin": text, "arguments": sys.argv[2:],
        "secret_seen": "AUTO_BMAD_FAKE_SECRET" in os.environ})}})
    last = json.dumps({"type": "turn.completed", "usage": {"output_tokens": 3}})
    sys.stdout.write(last)  # valid final line without a newline
