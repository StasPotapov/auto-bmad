"""Agent selection for setup; preserve other settings and validate the effective layers."""

import copy
import datetime
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import tomllib
import uuid

import agent_config
import ext
from execution_state import lease
from gitexclude import ensure_excluded
from roles import ROLES

CHOICES = [
    {"id": "codex", "name": "Codex CLI", "available": True, "backend": "cli"},
    {"id": "claude", "name": "Claude Code (native plugin)", "available": True, "backend": "legacy-plugin"},
    {"id": "kimi", "name": "Kimi CLI", "available": False,
     "reason": "permission/result contract not validated"},
    {"id": "claude-cli", "name": "Claude CLI", "available": False,
     "reason": "permission/result contract not validated"},
]
REVIEWERS = {"reviewer", "reviewer-mid", "reviewer-lite"}


def value(v):
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        return str(v).lower()
    if isinstance(v, (datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, list):
        return "[" + ", ".join(value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{value(k)} = {value(x)}" for k, x in v.items()) + " }"
    raise ValueError(f"unsupported TOML value: {type(v).__name__}")


def equal(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(v, b[k]) for k, v in a.items())
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    return a == b


def tables(path, data):
    header = ".".join(value(k) for k in path)
    if isinstance(data, list):
        return "".join(f"\n[[{header}]]\n" + "".join(f"{value(k)} = {value(v)}\n" for k, v in row.items())
                       for row in data)
    simple = {k: v for k, v in data.items() if not isinstance(v, dict)}
    out = f"\n[{header}]\n" if simple or not data else ""
    out += "".join(f"{value(k)} = {value(v)}\n" for k, v in simple.items())
    return out + "".join(tables([*path, k], v) for k, v in data.items() if isinstance(v, dict))


def edit(text, updates):
    """Replace selected top-level sections, retaining every other statement verbatim.

    tomllib frames complete statements, including multiline strings/arrays and quoted
    dotted keys. A semantic comparison rejects any accidental change outside updates.
    """
    expected = tomllib.loads(text)
    kept, pending, section = [], "", None
    for line in text.splitlines(keepends=True):
        pending += line
        try:
            parsed = tomllib.loads(pending)
        except tomllib.TOMLDecodeError:
            continue
        code = next((s.strip() for s in pending.splitlines() if s.strip() and not s.lstrip().startswith("#")), "")
        if code.startswith("["):
            section = next(iter(parsed))
        root = section if section is not None else next(iter(parsed), None)
        if not parsed or root not in updates:
            kept.append(pending)
        pending = ""
    if pending:
        raise ValueError("cannot frame TOML statements safely")
    for key, data in updates.items():
        expected.pop(key, None)
        if data is not None:
            expected[key] = data
    result = "".join(kept).rstrip() + "\n"
    result += "".join(tables([k], v) for k, v in updates.items() if v is not None)
    if not equal(tomllib.loads(result), expected):
        raise ValueError("TOML edit would change unrelated settings; no files written")
    return result


def effective(repo, text, layer):
    cfg = {}
    for name, path in ext.layers(repo):
        if name == layer:
            data = tomllib.loads(text)
        elif ext.layer_exists(path):
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        else:
            continue
        cfg = ext.merge(cfg, data)
    for name in ext.NAMED:
        if not isinstance(cfg.get(name, []), list) or not all(isinstance(v, dict) for v in cfg.get(name, [])):
            raise ValueError(f"{name} must be an array of tables")
        cfg[name] = [v for v in cfg.get(name, []) if v.get("enabled", True) is not False]
    return cfg


def configure(repo, before, a):
    agent = a.agent
    if agent not in ("codex", "claude"):
        raise ValueError(f"{agent}: execution is not enabled; choose Codex CLI or native Claude Code")
    layer = getattr(a, "layer", "project")
    raw = tomllib.loads(before)
    adding = getattr(a, "add", False)
    original_cfg = effective(repo, before, layer)
    default_backend = original_cfg.get("execution", {}).get("backend", "legacy-plugin")
    if default_backend not in ("cli", "legacy-plugin"):
        raise ValueError("invalid configured execution backend")

    def candidate_config(text):
        cfg = effective(repo, text, layer)
        return ext.executor_config(cfg, agent) if adding else cfg

    updates = {}
    execution = copy.deepcopy(raw.get("execution", {}))
    execution.update(schema_version=1, backend="cli" if agent == "codex" else "legacy-plugin", merge_policy="manual")
    updates["execution"] = execution
    disabled = []
    if agent == "codex":
        model = getattr(a, "model", None)
        profiles = copy.deepcopy(raw.get("agents", {}))
        generated = None
        if model:
            generated = {}
            for name, permissions, review in (("setup-codex-write", "workspace-write", False),
                                               ("setup-codex-review", "read-only", True)):
                profile = {"adapter": "codex", "executable": getattr(a, "executable", None) or "codex",
                           "model": (getattr(a, "review_model", None) or model) if review else model,
                           "effort": (getattr(a, "review_effort", None) or a.effort or "high") if review else (a.effort or "high"),
                           "permissions": permissions, "timeout": a.timeout if a.timeout is not None else 3600,
                           "environment_allowlist": ["PATH", "HOME", "TMPDIR", *(getattr(a, "env", None) or [])]}
                # Reuse schema/permission validation, including placeholder and env-name checks.
                generated[name] = agent_config.profile(name, profile)
                profiles[name] = profile
            updates["agents"] = profiles
            routing = copy.deepcopy(raw.get("routing", {}))
            for level in ("fast", "normal", "deep"):
                routing[level] = {role: {"agent": "setup-codex-review" if role in REVIEWERS else "setup-codex-write"}
                                  for role in ROLES}
            updates["routing"] = routing
        elif any(getattr(a, k, None) is not None for k in ("effort", "review_model", "review_effort", "executable", "timeout", "env")):
            raise ValueError("changing Codex profile options requires --model; omit options to reuse saved profiles")
        candidate = edit(before, updates)
        cfg = candidate_config(candidate)
        if generated is None:
            if cfg.get("execution", {}).get("backend") != "cli":
                raise ValueError("a higher config layer overrides the selected backend; select --layer local")
            for level in ("fast", "normal", "deep"):
                saved = agent_config.resolve(cfg, level)
                if any(p["adapter"] != "codex" or (role in REVIEWERS and p["permissions"] != "read-only")
                       for role, p in saved["roles"].items()):
                    raise ValueError("no complete saved Codex profile; configure --model with the exact model ID first")
        disabled = [v["name"] for v in cfg["verify"] if v.get("kind", "agent") != "command"]
        if not getattr(a, "disable_agent_checks", False):
            disabled = []
        if disabled:
            checks = copy.deepcopy(raw.get("verify", []))
            for name in disabled:
                entry = next((v for v in checks if v.get("name") == name), None)
                if entry is None:
                    entry = {"name": name}
                    checks.append(entry)
                entry["enabled"] = False
            updates["verify"] = checks
    else:
        if any(getattr(a, k, None) for k in ("model", "review_model", "executable", "env")):
            raise ValueError("CLI model/executable options do not apply to native Claude; use setup role")
    text = edit(before, updates)
    cfg = candidate_config(text)
    if cfg.get("execution", {}).get("backend") != execution["backend"]:
        raise ValueError("a higher config layer overrides the selected backend; select --layer local")
    for level in ("fast", "normal", "deep"):
        plan = agent_config.resolve(cfg, level)
        if plan["backend"] != execution["backend"]:
            raise ValueError("a higher config layer overrides the selected backend; select --layer local")
        if agent == "codex":
            for role, p in plan["roles"].items() if generated is not None else []:
                name = "setup-codex-review" if role in REVIEWERS else "setup-codex-write"
                if p["profile_id"] != name or any(p[k] != v for k, v in generated[name].items()):
                    raise ValueError(f"a higher config layer overrides {role}; select --layer local")
            if getattr(a, "disable_agent_checks", False) and any(v.get("kind", "agent") != "command" for v in cfg["verify"]):
                raise ValueError("a higher config layer enables agent checks; select --layer local")
    if adding:
        # Adding CLI profiles must keep an implicit native default explicit, so legacy
        # callers can distinguish saved profiles from an unselected CLI configuration.
        execution = copy.deepcopy(raw.get("execution", {}))
        if "backend" not in original_cfg.get("execution", {}):
            execution["backend"] = default_backend
        updates["execution"] = execution
        text = edit(before, updates)
        actual = effective(repo, text, layer)
        if actual.get("execution", {}).get("backend", "legacy-plugin") != default_backend:
            raise ValueError("adding a profile would change the configured default executor")
        agent_config.resolve(actual)
    if equal(raw, tomllib.loads(text)):
        text = before
    return {"content": text, "agent": agent, "backend": default_backend if adding else execution["backend"],
            "mode": "add" if adding else "select", "profile_backend": "cli" if agent == "codex" else "legacy-plugin",
            "profiles_reused": agent == "codex" and generated is None,
            "disabled_agent_checks": disabled, "model_started": False,
            "notes": ["CLI epics are sequential; merge and push remain manual."] if agent == "codex" else plan["warnings"]}


def write(repo, path, before, text):
    root, path = Path(repo).resolve(), Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("setup config must be a regular file inside the project")
    with lease(root):
        if path.name == ext.LOCAL_CONFIG and subprocess.run(
                ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", path.name],
                capture_output=True).returncode == 0:
            raise ValueError("machine-local config is tracked; use setup local to inspect it before changing it")
        current = path.read_bytes().decode("utf-8") if path.exists() else ""
        if current != before:
            raise ValueError("config changed during setup; retry the preview")
        if current == text:
            return None
        backup = None
        if path.exists():
            directory = root / ".auto-bmad/setup-backups"
            if not directory.resolve().is_relative_to(root):
                raise ValueError("setup backup directory escapes the project")
            directory.mkdir(parents=True, exist_ok=True)
            backup = directory / (uuid.uuid4().hex + ".toml")
            with backup.open("x", encoding="utf-8") as fh:
                os.chmod(backup, 0o600)
                fh.write(before)
        if not ensure_excluded(str(root), ".auto-bmad/"):
            raise ValueError("cannot exclude setup backups from git")
        if path.name == ext.LOCAL_CONFIG and not ensure_excluded(str(root), ext.LOCAL_CONFIG):
            raise ValueError("cannot exclude the machine-local config from git")
        fd, temporary = tempfile.mkstemp(prefix=".auto-bmad-setup-", dir=root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            if path.exists():
                os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return str(backup) if backup else None


def add_options(parser, required=False):
    parser.add_argument("--agent", choices=tuple(v["id"] for v in CHOICES), required=required)
    parser.add_argument("--model", help="exact CLI model ID; required when creating/updating Codex profiles, omitted to reuse saved profiles")
    parser.add_argument("--effort", choices=("minimal", "low", "medium", "high", "xhigh"))
    parser.add_argument("--review-model")
    parser.add_argument("--review-effort", choices=("minimal", "low", "medium", "high", "xhigh"))
    parser.add_argument("--executable", help="CLI executable name or absolute path")
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--env", action="append", help="additional environment variable name passed to roles")
    parser.add_argument("--disable-agent-checks", action="store_true", help="explicitly select command checks only")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--add", action="store_true", help="add/update executor settings without changing the configured default")
    mode.add_argument("--select", action="store_true", help="explicitly select the default executor (the standalone CLI default)")
