"""Coding CLI interface probes and the initial Codex JSONL adapter.

Kimi and Claude are detected but fail closed for execution until permissions and
their result contracts have passed their own live tests. No model calls in detect.
"""

import json
import os
import re
import shutil
import subprocess
import time

from agent_runtime import ProtocolError

CAPABILITIES = {"noninteractive", "structured_events", "structured_final", "stdin_prompt",
                "model_selection", "read_only_enforcement", "cwd", "session_resume",
                "usage_reporting", "cancel_process_group", "engine_delegation_bridge"}


def detect(profile, timeout=10):
    deadline = time.monotonic() + timeout
    executable = shutil.which(profile["executable"])
    if not executable:
        raise ValueError(f"executable not found: {profile['executable']}")
    executable = os.path.abspath(executable)
    env = {k: os.environ[k] for k in profile["environment_allowlist"] if k in os.environ}
    adapter = profile["adapter"]
    outputs = []
    for args in (["--version"], ["exec", "--help"] if adapter == "codex" else ["--help"]):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError(f"{adapter}: interface probe timed out")
        try:
            result = subprocess.run([executable, *args], capture_output=True, text=True,
                                    env=env, timeout=remaining)
        except subprocess.TimeoutExpired as e:
            raise ValueError(f"{adapter}: interface probe timed out") from e
        if result.returncode:
            raise ValueError(f"{adapter}: interface probe failed (exit {result.returncode})")
        outputs.append(result.stdout)
    version, help_text = outputs
    # A path to an unrelated binary must not be accepted just because --help succeeds.
    marker = {"codex": "codex-cli", "kimi": "kimi", "claude": "Claude Code"}[adapter]
    matches = marker in version if adapter != "kimi" else (
        re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", version.strip()) and marker in help_text.lower())
    if not matches:
        raise ValueError(f"{adapter}: unexpected CLI version/help output")
    caps = {key: "unknown" for key in CAPABILITIES}
    if adapter == "codex":
        for flag in ("--json", "--output-schema", "--sandbox", "--model", "--cd", "--config"):
            if flag not in help_text:
                raise ValueError(f"codex: required flag {flag} absent from installed CLI")
        for key in ("noninteractive", "structured_events", "structured_final", "stdin_prompt",
                    "model_selection", "read_only_enforcement", "cwd", "usage_reporting"):
            caps[key] = "supported"
    elif adapter == "kimi":
        for key in ("noninteractive", "structured_events", "model_selection"):
            caps[key] = "supported"
    caps["engine_delegation_bridge"] = "supported" if adapter == "codex" else "unsupported"
    # TERM/KILL of a process group is available; detached descendant behaviour is not proven.
    return {"executable": executable, "version": version.strip(), "capabilities": caps}


def validate(profile, detection, *, engine=False):
    if profile["adapter"] != "codex":
        raise ValueError(f"{profile['adapter']}: execution is not enabled; permission/result contract unverified")
    effort = profile.get("effort")
    if effort is not None and effort not in ("minimal", "low", "medium", "high", "xhigh"):
        raise ValueError(f"codex: unsupported effort {effort!r}")
    required = list(profile["capability_requirements"])
    if engine:
        required.append("engine_delegation_bridge")
    if profile["permissions"] == "read-only":
        required.append("read_only_enforcement")
    for key in required:
        if key not in CAPABILITIES:
            raise ValueError(f"unknown capability {key!r}")
        status = detection["capabilities"].get(key, "unknown")
        if status != "supported":
            raise ValueError(f"codex: capability {key} is {status}")


def argv(profile, detection, cwd, schema, result):
    validate(profile, detection)
    args = [detection["executable"], "exec", "-C", cwd, "--model", profile["model"],
            "--sandbox", profile["permissions"], "--json", "--output-schema", str(schema),
            "-o", str(result)]
    if profile.get("effort"):
        args.extend(["-c", "model_reasoning_effort=" + json.dumps(profile["effort"])])
    return [*args, "-"]


class CodexResult:
    """Transport success requires both a completed turn and a structured final message."""

    def __init__(self):
        self.completed = False
        self.final = None
        self.usage = None
        self.failure = None
        self.thread = None

    def consume(self, event):
        kind = event.get("type")
        if kind == "thread.started":
            self.thread = event.get("thread_id")
        elif kind == "turn.completed":
            self.completed = True
            self.usage = event.get("usage")
        elif kind in ("turn.failed", "error"):
            self.failure = event.get("error") or event.get("message") or "agent failed"
        elif kind == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict):
                raise ProtocolError("invalid item.completed")
            if item.get("type") == "agent_message":
                self.final = item.get("text")

    def finish(self, exit_code):
        if self.failure is not None or exit_code:
            return {"execution_status": "failed", "error": {"kind": "process", "message": str(self.failure or
                    f"CLI exit {exit_code}")}, "resume_handle": self.thread}
        if not self.completed or not isinstance(self.final, str):
            raise ProtocolError("missing completed turn or final message")
        result = json.loads(self.final)
        if not isinstance(result, dict):
            raise ProtocolError("final result must be a JSON object")
        return {"execution_status": "completed", "result": result, "usage": self.usage,
                "resume_handle": self.thread}


def result_parser(profile):
    parsers = {"codex": CodexResult}
    factory = parsers.get(profile["adapter"])
    if factory is None:
        raise ValueError(f"{profile['adapter']}: result protocol is not enabled")
    return factory()
