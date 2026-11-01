"""Detached component-test orchestration for native clients with bounded caller waits."""

from contextlib import nullcontext
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

from agent_runtime import atomic_json
from common import git
from execution_state import canonical, current_lease_fd, lease
import project_tests
import testrun


def worker(request_path):
    path = Path(request_path)
    request = json.loads(path.read_text())
    root = Path(request["repo"])
    private = path.parent
    try:
        with lease(root):
            root_fd = current_lease_fd()

            def execute(command, seconds, where, scope):
                seconds = request.get("timeout") or seconds
                with (nullcontext() if where == root else lease(where)):
                    owners = tuple(sorted({root_fd, current_lease_fd()}))
                    while True:
                        result, code = testrun.run(str(where), command, seconds, wait=seconds + 60,
                                                  rerun=request["rerun"], component=scope,
                                                  scope_config=request["config"]["project_tests"], owner_fds=owners)
                        if code != 3:
                            break
                    if code:
                        raise ValueError(result.get("error", "component tests did not finish"))
                    return result

            runner = project_tests.Runner(root, request["base"], request["config"], private, execute)
            if request["rerun"]:
                runner.baselines.clear()
            before = project_tests.fingerprint(root, runner.cfg, "@all")
            result, code = runner.run(), 0
            after = project_tests.fingerprint(root, runner.cfg, "@all")
            complete = all(project_tests.completed(check) for check in result["checks"].values())
            receipt = {"id": request["id"], "tree": after if before == after and complete else None,
                       "result": result, "code": code}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as e:
        receipt = {"id": request["id"], "result": {"error": str(e)}, "code": 1}
    atomic_json(private / "native-result.json", receipt)


def run(repo, base, cfg, wait, rerun=False, timeout=None):
    root, common = canonical(repo)
    commit = git(str(root), "rev-parse", "--verify", "--end-of-options", str(base) + "^{commit}")
    if commit.returncode:
        raise ValueError("scoped tests require an exact existing baseline commit")
    base = commit.stdout.strip()
    strategy = project_tests.settings(cfg)
    frozen = {"project_tests": strategy}
    identity = hashlib.sha256(json.dumps([str(root), base, frozen, timeout], sort_keys=True).encode()).hexdigest()
    private = common / "auto-bmad-test-baselines" / identity
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    answer = private / "native-result.json"
    pid_path = private / "native.pid"
    request_path = private / "native-request.json"
    proc = None
    with (private / "native-launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = testrun.read_json(pid_path)
        if record and testrun.live(record):
            run_id = record["id"]
        else:
            saved = testrun.read_json(answer)
            fresh = answer.exists() and time.time() - answer.stat().st_mtime <= testrun.RECENT
            if (saved and saved.get("tree") == project_tests.fingerprint(root, strategy, "@all")
                    and (not rerun or fresh) and not saved["code"]):
                return {**saved["result"], "reused": True}, 0
            run_id = uuid.uuid4().hex
            atomic_json(request_path, {"id": run_id, "repo": str(root), "base": base,
                                      "config": frozen, "timeout": timeout, "rerun": rerun})
            with (private / "native-worker.log").open("a") as log:
                proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(request_path)],
                                        stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            from stub import proc_info
            info = proc_info(proc.pid) or {}
            atomic_json(pid_path, {"id": run_id, "pid": proc.pid, "start": info.get("start")})
    deadline = time.monotonic() + wait
    while True:
        saved = testrun.read_json(answer)
        if saved and saved.get("id") == run_id:
            return saved["result"], saved["code"]
        done = proc.poll() is not None if proc else not testrun.live(record)
        if done:
            saved = testrun.read_json(answer)
            if saved and saved.get("id") == run_id:
                return saved["result"], saved["code"]
            return {"error": "component test worker stopped without a result", "log": str(private / "native-worker.log")}, 1
        if time.monotonic() >= deadline:
            return {"verdict": "running", "log": str(private / "native-worker.log"),
                    "note": "component tests continue in the background; repeat the same command to join"}, 3
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    worker(sys.argv[1])
