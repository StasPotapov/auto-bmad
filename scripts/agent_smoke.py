"""Explicit opt-in model smoke: one Codex CLI launch in a disposable Git repository."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import agent_adapters as adapters
import agent_config
from agent_runtime import atomic_json, environment, execute
from execution_state import lease

SCHEMA = {"type": "object", "properties": {"status": {"type": "string", "enum": ["done"]},
          "marker": {"type": "string", "enum": ["auto-bmad-smoke"]}},
          "required": ["status", "marker"], "additionalProperties": False}
EXPECTED = {"status": "done", "marker": "auto-bmad-smoke"}


def prepare(argv, repo, env, directory, timeout):
    result = execute(argv, cwd=str(repo), env=env, stdin="", directory=directory, timeout=timeout,
                     consume=lambda _: None, structured=False,
                     finish=lambda code: {"execution_status": "completed" if code == 0 else "failed"})
    if result["execution_status"] != "completed":
        raise ValueError(f"smoke preparation {result['execution_status']}; logs: {directory}")


def smoke(model, executable="codex", timeout=60):
    started = time.monotonic()

    def remaining():
        left = timeout - (time.monotonic() - started)
        if left <= 0:
            raise ValueError("smoke deadline exceeded during preparation")
        return left

    profile = agent_config.profile("smoke", {"adapter": "codex", "executable": executable,
                  "model": model, "permissions": "read-only", "timeout": timeout})
    detection = adapters.detect(profile, timeout=remaining())
    adapters.validate(profile, detection)
    root = Path(tempfile.mkdtemp(prefix="auto-bmad-smoke-"))
    os.chmod(root, 0o700)
    repo = root / "repo"
    repo.mkdir()
    env = environment(profile["environment_allowlist"])
    prepare(["git", "init", "-q", str(repo)], repo, env, root / "initialize", remaining())
    prepare(["git", "-C", str(repo), "-c", "user.name=auto-bmad-smoke",
             "-c", "user.email=smoke@example.invalid", "-c", "commit.gpgsign=false",
             "commit", "--allow-empty", "-qm", "smoke baseline"], repo, env, root / "baseline", remaining())
    schema = root / "schema.json"
    atomic_json(schema, SCHEMA)
    parser = adapters.CodexResult()
    with lease(repo):
        result = execute(adapters.argv(profile, detection, str(repo), schema, root / "answer.json"),
                         cwd=str(repo), env=env,
                         stdin='Return exactly {"status":"done","marker":"auto-bmad-smoke"}. '
                               'Do not call tools, read files, write files, or delegate to other agents.',
                         directory=root / "attempt", timeout=remaining(), consume=parser.consume, finish=parser.finish)
    result.update(model_requested=model, cli_version=detection["version"], directory=str(root),
                  bmad_execution_checked=False)
    if result.get("execution_status") == "completed" and result.get("result") != EXPECTED:
        result.update(execution_status="failed", error={"kind": "protocol", "message": "unexpected smoke result"})
    atomic_json(root / "result.json", result)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--allow-model", action="store_true", help="explicit consent for this one live CLI launch")
    ap.add_argument("--model", required=True)
    ap.add_argument("--executable", default="codex")
    ap.add_argument("--timeout", type=int, default=60, choices=range(1, 61), metavar="1..60")
    args = ap.parse_args(argv)
    if not args.allow_model:
        print(json.dumps({"error": "live smoke requires --allow-model; no process was launched"}))
        return 2
    try:
        out = smoke(args.model, args.executable, args.timeout)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        out = {"execution_status": "failed", "error": str(e)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("execution_status") == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
