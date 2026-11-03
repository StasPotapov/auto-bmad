"""Native Codex role selection. Model calls belong to the surrounding chat."""

import argparse
import copy
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

from ext import load
from roles import resolve as legacy_roles
from role_catalog import ROLES, REVIEWERS, ACCEPTED_ROLES, role_overrides, alias_warnings

PROFILE_KEYS = {"adapter", "executable", "arguments", "model", "effort", "permissions", "timeout",
                "environment_allowlist", "output_protocol", "capability_requirements", "read_only"}
EXECUTION_KEYS = {"schema_version", "backend", "merge_policy"}
PROTOCOLS = {"codex": "codex-jsonl-v1"}
TRANSPORT_FIELDS = {"executable", "arguments", "permissions", "timeout", "environment_allowlist", "output_protocol", "capability_requirements"}
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
CODEX_FIELDS = {"model", "effort", "review_model", "review_effort", "executable", "timeout", "environment_allowlist"}
ROLE_FIELDS = {"model", "effort", "executable", "timeout", "environment_allowlist"}


def codex_defaults():
    with (Path(__file__).resolve().parents[1] / "agents/codex-defaults.toml").open("rb") as stream:
        return tomllib.load(stream)


def advanced(cfg):
    return bool(cfg.get("agents") or cfg.get("routing") or any(
        isinstance(row, dict) and "agent" in row for row in table(cfg.get("roles", {}), "roles").values()))


def compact_codex(cfg):
    executors = table(cfg.get("executors", {}), "executors")
    keys(executors, {"codex", "claude"}, "executors")
    return "codex" in executors or not advanced(cfg)


def codex_roles(settings, level):
    settings = table(settings, "executors.codex")
    keys(settings, CODEX_FIELDS | {"levels", "roles"}, "executors.codex")
    levels = table(settings.get("levels", {}), "executors.codex.levels")
    keys(levels, {"fast", "normal", "deep"}, "executors.codex.levels")
    for values in (settings, *levels.values()):
        values = table(values, "executors.codex settings")
        for field in ("model", "effort", "review_model", "review_effort"):
            if field in values:
                value = values[field]
                if not isinstance(value, str) or not value.strip() or "\0" in value or value.startswith("CONFIGURE_"):
                    raise ValueError(f"executors.codex.{field}: expected a configured nonempty string")
    roles = table(settings.get("roles", {}), "executors.codex.roles")
    keys(roles, ACCEPTED_ROLES, "executors.codex.roles")
    for role, values in roles.items():
        keys(table(values, f"executors.codex.roles.{role}"), ROLE_FIELDS, f"executors.codex.roles.{role}")
        profile("codex-" + role, {"model": "validation-default", **values})
    for name, values in levels.items():
        keys(table(values, f"executors.codex.levels.{name}"), CODEX_FIELDS | {"roles"}, f"executors.codex.levels.{name}")
        overrides = table(values.get("roles", {}), f"executors.codex.levels.{name}.roles")
        keys(overrides, ACCEPTED_ROLES, f"executors.codex.levels.{name}.roles")
        for role, entry in overrides.items():
            keys(table(entry, role), ROLE_FIELDS, f"executors.codex.levels.{name}.roles.{role}")
            profile("codex-" + role, {"model": "validation-default", **entry})
    common = {**codex_defaults(), **{k: v for k, v in settings.items() if k in CODEX_FIELDS}}
    chosen = {**common, **{k: v for k, v in levels.get(level, {}).items() if k in CODEX_FIELDS}}
    result = {}
    for role in ROLES:
        review = role in REVIEWERS
        raw = {"adapter": "codex", "executable": chosen.get("executable", "codex"),
               "model": chosen["review_model" if review else "model"],
               "effort": chosen["review_effort" if review else "effort"],
               "permissions": "read-only" if review else "workspace-write"}
        raw.update({k: chosen[k] for k in ("timeout", "environment_allowlist") if k in chosen})
        raw.update(role_overrides(roles, levels.get(level, {}).get("roles", {}), role, level))
        normalized = profile("codex-" + role, raw)
        identity = "codex-" + hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()[:12]
        result[role] = role_profile(role, identity, normalized)
    return result


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
    """Read native settings and validate old transport fields without executing them."""
    raw = table(raw, f"agents.{name}")
    keys(raw, PROFILE_KEYS, f"agents.{name}")
    if raw.get("adapter", "codex") != "codex":
        raise ValueError(f"agents.{name}.adapter: native Codex cannot use another executor")
    for field in ("model", "effort"):
        value = raw.get(field, "high" if field == "effort" else None)
        if not isinstance(value, str) or not value.strip() or "\0" in value or value.startswith("CONFIGURE_"):
            raise ValueError(f"agents.{name}.{field}: expected a configured nonempty string")
    if raw.get("permissions", "workspace-write") not in ("read-only", "workspace-write", "inherited"):
        raise ValueError(f"agents.{name}.permissions: unsupported permission mode")
    if "timeout" in raw and (type(raw["timeout"]) is not int or raw["timeout"] <= 0):
        raise ValueError(f"agents.{name}.timeout: expected a positive integer")
    if "read_only" in raw and type(raw["read_only"]) is not bool:
        raise ValueError(f"agents.{name}.read_only: expected a boolean")
    for field in ("arguments", "environment_allowlist", "capability_requirements"):
        if field in raw:
            strings(raw[field], f"agents.{name}.{field}")
    if raw.get("arguments") or raw.get("capability_requirements"):
        raise ValueError(f"agents.{name}: custom CLI arguments/capabilities cannot migrate to native agents")
    for env in raw.get("environment_allowlist", []):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env):
            raise ValueError(f"agents.{name}.environment_allowlist: invalid variable name")
    if raw.get("output_protocol", "codex-jsonl-v1") != "codex-jsonl-v1":
        raise ValueError(f"agents.{name}.output_protocol: unsupported legacy protocol")
    return {"adapter": "codex", "model": raw["model"], "effort": raw.get("effort", "high"),
            "permissions": "inherited", "read_only": raw.get("read_only", raw.get("permissions") == "read-only")}


def role_profile(role, identity, selected):
    return {"profile_id": identity, **copy.deepcopy(selected), "agent_type": "default",
            "read_only": role in REVIEWERS or selected.get("read_only", False),
            "prompt": str(Path(__file__).resolve().parents[1] / "prompts" / "roles" / f"{role}.md")}


def migration_warnings(cfg):
    warnings = alias_warnings(cfg)
    if cfg.get("execution", {}).get("backend") == "cli":
        warnings.append("execution.backend='cli' is retired; using native Codex subagents in the chat. Run setup agent --agent codex --select to save the migration.")
    def has_transport(value):
        return isinstance(value, dict) and (bool(set(value) & TRANSPORT_FIELDS) or any(has_transport(v) for v in value.values()))
    if has_transport(cfg.get("executors", {}).get("codex", {})) or any(
            has_transport(p) for p in cfg.get("agents", {}).values()):
        warnings.append("Saved CLI transport settings are inactive: native agents inherit the chat permissions and environment; model and effort are preserved. Read-only is an instruction, not a separate sandbox.")
    return warnings


def resolve(cfg, level="normal"):
    if level not in ("fast", "normal", "deep"):
        raise ValueError(f"unknown level {level!r}")
    execution = table(cfg.get("execution", {}), "execution")
    keys(execution, EXECUTION_KEYS, "execution")
    backend = execution.get("backend", "legacy-plugin")
    if backend not in ("legacy-plugin", "native", "cli"):
        raise ValueError("execution.backend: expected legacy-plugin or native")
    if type(execution.get("schema_version", 1)) is not int or execution.get("schema_version", 1) != 1:
        raise ValueError("execution.schema_version: only version 1 is supported")
    merge_policy = execution.get("merge_policy", "manual")
    if merge_policy not in ("manual", "auto-main"):
        raise ValueError("execution.merge_policy: expected manual or auto-main")
    if backend == "legacy-plugin":
        has_cli = cfg.get("agents") or cfg.get("routing") or any(
            isinstance(v, dict) and "agent" in v for v in table(cfg.get("roles", {}), "roles").values())
        if has_cli and execution.get("backend") != "legacy-plugin":
            raise ValueError("agent profiles require execution.backend = 'native'; legacy routing is unchanged")
        roles, errors, warnings = legacy_roles(cfg, level)
        if errors:
            raise ValueError("; ".join(errors))
        for name, role in roles.items():
            role.update(adapter="claude", profile_id="claude-" + name,
                        permissions="inherited", read_only=name in REVIEWERS,
                        prompt=str(Path(__file__).resolve().parents[1] / "prompts" / "roles" / f"{name}.md"))
        return {"schema_version": 1, "backend": backend, "level": level,
                "merge_policy": merge_policy, "roles": roles, "warnings": warnings}

    if compact_codex(cfg):
        settings = table(cfg.get("executors", {}), "executors").get("codex", {})
        # Validate every level before a run, including overrides for inactive levels.
        plans = {name: codex_roles(settings, name) for name in ("fast", "normal", "deep")}
        return {"schema_version": 1, "backend": "native", "level": level, "merge_policy": merge_policy,
                "roles": plans[level], "configuration": "compact", "warnings": migration_warnings(cfg)}

    profiles = {}
    for name, raw in table(cfg.get("agents", {}), "agents").items():
        if not IDENTIFIER.fullmatch(name):
            raise ValueError(f"invalid agent profile name {name!r}")
        profiles[name] = profile(name, raw)
    routes = table(cfg.get("roles", {}), "roles")
    keys(routes, ACCEPTED_ROLES, "roles")
    routing = table(cfg.get("routing", {}), "routing")
    keys(routing, {"fast", "normal", "deep"}, "routing")
    for lvl, entries in routing.items():
        entries = table(entries, f"routing.{lvl}")
        keys(entries, ACCEPTED_ROLES, f"routing.{lvl}")
        for role, raw in entries.items():
            raw = table(raw, f"routing.{lvl}.{role}")
            keys(raw, {"agent"}, f"routing.{lvl}.{role}")
            if raw.get("agent") not in profiles:
                raise ValueError(f"routing.{lvl}.{role}: unknown agent profile")

    result = {}
    for role in ROLES:
        raw = role_overrides(routes, {}, role, level)
        if "agent" in raw:
            keys(raw, {"agent", "model", "effort", "provider"}, f"roles.{role}")
            if raw["agent"] not in profiles:
                raise ValueError(f"roles.{role}: unknown agent profile {raw['agent']!r}")
        else:
            keys(raw, {"model", "effort", "provider"}, f"roles.{role}")
        selected_route = role_overrides(routes, routing.get(level, {}), role, level)
        name = selected_route.get("agent", raw.get("agent"))
        if name is None:
            raise ValueError(f"roles.{role}: native migration requires an explicit Codex route; no fallback to Claude")
        result[role] = role_profile(role, name, profiles[name])
    return {"schema_version": 1, "backend": "native", "level": level, "merge_policy": merge_policy,
            "roles": result, "warnings": migration_warnings(cfg)}


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
