"""Opt-in CLI execution config. Legacy model/effort settings stay in roles.py."""

import argparse
import copy
import hashlib
import json
import re
import sys

from ext import load
from roles import ROLES, resolve as legacy_roles

PROFILE_KEYS = {"adapter", "executable", "arguments", "model", "effort", "permissions", "timeout",
                "environment_allowlist", "output_protocol", "capability_requirements"}
EXECUTION_KEYS = {"schema_version", "backend", "merge_policy"}
PROTOCOLS = {"codex": "codex-jsonl-v1", "kimi": "kimi-stream-json-v1", "claude": "claude-json-v1"}
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


def table(value, where):
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a table")
    return value


def keys(value, allowed, where):
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{where}: unknown keys: {', '.join(sorted(unknown))}")


def strings(value, where):
    if not isinstance(value, list) or not all(isinstance(v, str) and v and "\0" not in v for v in value):
        raise ValueError(f"{where} must be an array of nonempty strings")
    return value


def profile(name, raw):
    raw = table(raw, f"agents.{name}")
    keys(raw, PROFILE_KEYS, f"agents.{name}")
    adapter = raw.get("adapter")
    if adapter not in PROTOCOLS:
        raise ValueError(f"agents.{name}.adapter: expected {', '.join(PROTOCOLS)}")
    out = {"arguments": [], "timeout": 3600, "environment_allowlist": ["PATH", "HOME", "TMPDIR"],
           "capability_requirements": [], "output_protocol": PROTOCOLS[adapter], **copy.deepcopy(raw)}
    for field in ("executable", "model", "permissions", "output_protocol"):
        val = out.get(field)
        if not isinstance(val, str) or not val.strip() or "\0" in val or val.startswith("CONFIGURE_"):
            raise ValueError(f"agents.{name}.{field}: expected a configured nonempty string")
    if out["output_protocol"] != PROTOCOLS[adapter]:
        raise ValueError(f"agents.{name}.output_protocol: incompatible with {adapter}")
    if out["permissions"] not in ("read-only", "workspace-write"):
        raise ValueError(f"agents.{name}.permissions: expected read-only or workspace-write")
    if type(out["timeout"]) is not int or out["timeout"] <= 0:
        raise ValueError(f"agents.{name}.timeout: expected a positive integer")
    if "effort" in out and (not isinstance(out["effort"], str) or not out["effort"]):
        raise ValueError(f"agents.{name}.effort: expected a nonempty string")
    for field in ("arguments", "environment_allowlist", "capability_requirements"):
        strings(out[field], f"agents.{name}.{field}")
    for env in out["environment_allowlist"]:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env):
            raise ValueError(f"agents.{name}.environment_allowlist: invalid variable name")
    # No escape hatch for model, cwd, sandbox, rules, hook trust or config overrides.
    if out["arguments"]:
        raise ValueError(f"agents.{name}.arguments: no additional flags are approved in contract v1")
    return out


def resolve(cfg, level="normal"):
    if level not in ("fast", "normal", "deep"):
        raise ValueError(f"unknown level {level!r}")
    execution = table(cfg.get("execution", {}), "execution")
    keys(execution, EXECUTION_KEYS, "execution")
    backend = execution.get("backend", "legacy-plugin")
    if backend not in ("legacy-plugin", "cli"):
        raise ValueError("execution.backend: expected legacy-plugin or cli")
    if type(execution.get("schema_version", 1)) is not int or execution.get("schema_version", 1) != 1:
        raise ValueError("execution.schema_version: only version 1 is supported")
    if execution.get("merge_policy", "manual") != "manual":
        raise ValueError("execution.merge_policy: only manual is supported")
    if backend == "legacy-plugin":
        has_cli = cfg.get("agents") or cfg.get("routing") or any(
            isinstance(v, dict) and "agent" in v for v in table(cfg.get("roles", {}), "roles").values())
        if has_cli and execution.get("backend") != "legacy-plugin":
            raise ValueError("agent profiles require execution.backend = 'cli'; legacy routing is unchanged")
        roles, errors, warnings = legacy_roles(cfg)
        if errors:
            raise ValueError("; ".join(errors))
        return {"schema_version": 1, "backend": backend, "roles": roles, "warnings": warnings}

    profiles = {}
    for name, raw in table(cfg.get("agents", {}), "agents").items():
        if not IDENTIFIER.fullmatch(name):
            raise ValueError(f"invalid agent profile name {name!r}")
        profiles[name] = profile(name, raw)
    routes = table(cfg.get("roles", {}), "roles")
    keys(routes, set(ROLES), "roles")
    routing = table(cfg.get("routing", {}), "routing")
    keys(routing, {"fast", "normal", "deep"}, "routing")
    for lvl, entries in routing.items():
        entries = table(entries, f"routing.{lvl}")
        keys(entries, set(ROLES), f"routing.{lvl}")
        for role, raw in entries.items():
            raw = table(raw, f"routing.{lvl}.{role}")
            keys(raw, {"agent"}, f"routing.{lvl}.{role}")
            if raw.get("agent") not in profiles:
                raise ValueError(f"routing.{lvl}.{role}: unknown agent profile")

    result = {}
    for role in ROLES:
        raw = table(routes.get(role, {}), f"roles.{role}")
        if "agent" in raw:
            keys(raw, {"agent"}, f"roles.{role}")
            if raw["agent"] not in profiles:
                raise ValueError(f"roles.{role}: unknown agent profile {raw['agent']!r}")
        else:
            keys(raw, {"model", "effort", "provider"}, f"roles.{role}")
        name = routing.get(level, {}).get(role, {}).get("agent", raw.get("agent"))
        if name is None:
            defaults, errors, _ = legacy_roles({"roles": {role: raw}})
            if errors:
                raise ValueError("; ".join(errors))
            name = f"legacy:{role}"
            d = defaults[role]
            profiles[name] = {"adapter": "claude", "executable": "claude", "model": d["model"],
                              "effort": d["effort"], "permissions": "workspace-write", "timeout": 3600,
                              "arguments": [], "environment_allowlist": ["PATH", "HOME", "TMPDIR"],
                              "output_protocol": PROTOCOLS["claude"], "capability_requirements": []}
        result[role] = {"profile_id": name, **copy.deepcopy(profiles[name])}
    return {"schema_version": 1, "backend": "cli", "level": level, "merge_policy": "manual",
            "roles": result, "warnings": []}


def read(repo, level="normal"):
    cfg, sources, warnings = load(repo, strict=True)
    out = resolve(cfg, level)
    out["sources"] = [{**s, "path": str(s["path"])} for s in sources]
    out["warnings"] += warnings
    out["config_hash"] = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--level", choices=("fast", "normal", "deep"), default="normal")
    args = ap.parse_args(argv)
    try:
        out, code = read(args.repo, args.level), 0
    except (OSError, ValueError, TypeError, AttributeError) as e:
        out, code = {"error": str(e)}, 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
