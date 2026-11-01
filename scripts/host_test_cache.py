"""Green host receipts shared by sequential stories in the same worktree.

Receipts live in protected Git metadata, never in the writable agent's test directory.
Callers hold the repository resource lock and the worktree test lock.
"""

import hashlib
import json
from pathlib import Path
import time

from agent_runtime import atomic_json

MAX_AGE = 24 * 60 * 60
KEEP = 40


class Cache:
    def __init__(self, common, root, manifest, environment):
        # Wave identity is orchestration metadata, not a test input. Other environment
        # changes (including test flags and credentials) invalidate without storing values.
        env = {k: v for k, v in environment.items() if k != "AUTO_BMAD_WAVE"}
        identity = [str(root), manifest.get("config_hash"), manifest.get("engine_fingerprint"), env]
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        self.root = Path(common) / "auto-bmad-test-cache" / digest
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.root.resolve().is_relative_to(Path(common).resolve()):
            raise ValueError("host test cache escapes Git metadata")

    def path(self, tree, command, timeout):
        key = hashlib.sha256(json.dumps([tree, command, timeout]).encode()).hexdigest()
        return self.root / (key + ".json")

    def get(self, tree, command, timeout):
        path = self.path(tree, command, timeout)
        try:
            data = json.loads(path.read_text())
            result = data["result"]
            if (not path.is_symlink() and 0 <= time.time() - data["at"] <= MAX_AGE
                    and result.get("verdict") == "pass" and result.get("code") == 0):
                return {**result, "reused": True}
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return None

    def put(self, tree, command, timeout, result):
        if result.get("verdict") != "pass" or result.get("code") != 0:
            return
        atomic_json(self.path(tree, command, timeout), {"at": time.time(), "result": result})
        paths = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in paths[KEEP:]:
            path.unlink(missing_ok=True)

    def clear(self):
        for path in self.root.glob("*.json"):
            path.unlink(missing_ok=True)
