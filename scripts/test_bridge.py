"""Named project checks delegated to the already-authorized host controller."""

import json
from pathlib import Path
import time
import uuid

from agent_runtime import atomic_json
from execution_state import canonical, ControllerWatch


def session(repo, path):
    root, common = canonical(repo)
    path = Path(path).resolve(strict=True)
    if path.name != "session.json" or path.parent.parent != common / "auto-bmad-sessions":
        raise ValueError("invalid controller test session")
    data = json.loads(path.read_text())
    if data.get("repo") != str(root):
        raise ValueError("test session belongs to another worktree")
    return path, data, root


def check_name(data, command, name):
    checks = data.get("host_tests", {}).get("checks", {})
    if command:
        return next((key for key, value in checks.items() if value["command"] == command), None)
    return name if name in checks else None


def request(repo, path, name, rerun=False, targets=None):
    path, data, root = session(repo, path)
    if data.get("host_tests", {}).get("version") != 1 or name not in data["host_tests"]["checks"]:
        raise ValueError("only registered project checks can run through the host test bridge")
    state = (root / data["state_rel"]).resolve(strict=True)
    inbox = state / "tests-inbox"
    if not state.is_relative_to(root / ".auto-bmad") or inbox.is_symlink():
        raise ValueError("test inbox escapes the worktree")
    watch = ControllerWatch(root, path)
    if not watch.tests_alive():
        raise ValueError("test controller is no longer active")
    ticket = uuid.uuid4().hex + ".json"
    atomic_json(inbox / ticket, {"check": name, **({"rerun": True} if rerun else {}),
                               **({"targets": targets} if targets is not None else {})})
    answer = path.parent / "test-outbox" / ticket
    while True:
        if answer.exists():
            return json.loads(answer.read_text())
        if not watch.tests_alive():
            raise ValueError("controller ended before the registered check completed")
        time.sleep(0.05)
