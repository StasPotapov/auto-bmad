"""Write the compact Codex model settings without expanding level routes."""

import copy
import tomllib

import agent_config
import ext
import setup_agents
from roles import ROLES


def from_advanced(cfg):
    plans = {level: agent_config.resolve(cfg, level)["roles"] for level in ("fast", "normal", "deep")}
    fields = ("model", "effort")
    for plan in plans.values():
        for role, profile in plan.items():
            if (profile["adapter"] != "codex" or profile["read_only"] != (role in agent_config.REVIEWERS) or
                    profile.get("arguments") or profile.get("capability_requirements") or "effort" not in profile):
                raise ValueError("these advanced profiles cannot be compacted losslessly; keep the advanced config")
    normal = plans["normal"]
    settings = {key: copy.deepcopy(normal["implementer"][key]) for key in fields}
    settings.update(review_model=normal["reviewer"]["model"], review_effort=normal["reviewer"]["effort"])
    defaults = agent_config.codex_defaults()
    settings = {key: value for key, value in settings.items() if value != defaults[key]}
    expected = agent_config.codex_roles(settings, "normal")
    for role in ROLES:
        changes = {key: copy.deepcopy(normal[role][key]) for key in fields if normal[role][key] != expected[role][key]}
        if changes:
            settings.setdefault("roles", {})[role] = changes
    for level in ("fast", "deep"):
        expected = agent_config.codex_roles(settings, level)
        for role in ROLES:
            changes = {key: copy.deepcopy(plans[level][role][key]) for key in fields
                       if plans[level][role][key] != expected[role][key]}
            if changes:
                settings.setdefault("levels", {}).setdefault(level, {}).setdefault("roles", {})[role] = changes
    return settings


def configure(repo, before, args, original):
    raw = tomllib.loads(before)
    layer = args.layer if hasattr(args, "layer") else "project"
    adding = getattr(args, "add", False)
    converting = getattr(args, "compact", False) and not agent_config.compact_codex(raw if layer == "project" else original)
    if getattr(args, "compact", False) and layer == "project" and not agent_config.compact_codex(original) and not converting:
        raise ValueError("advanced settings are inherited; compact them in --layer local instead")
    # Shared files must never acquire values from personal/local layers during conversion.
    source = raw if layer == "project" else original
    settings = (from_advanced(ext.executor_config(source, "codex")) if converting else
                copy.deepcopy(raw.get("executors", {}).get("codex", {})))
    # Transport settings are not meaningful for native agents; keep model/effort at every level.
    def strip_transport(values):
        for key in agent_config.TRANSPORT_FIELDS:
            values.pop(key, None)
        for value in values.values():
            if isinstance(value, dict):
                strip_transport(value)
    strip_transport(settings)
    converted_settings = copy.deepcopy(settings)
    updates = {}
    if converting:
        updates["routing"] = None
        roles = copy.deepcopy(raw.get("roles", {}))
        for values in roles.values():
            values.pop("agent", None)
        updates["roles"] = {key: value for key, value in roles.items() if value} or None
        profiles = {key: value for key, value in raw.get("agents", {}).items()
                    if key not in ("setup-codex-write", "setup-codex-review")}
        updates["agents"] = profiles or None
    options = {key: getattr(args, key, None) for key in
               ("model", "effort", "review_model", "review_effort", "executable", "timeout")}
    level = getattr(args, "model_level", None)
    destination = settings
    if level and (any(value is not None for value in options.values()) or getattr(args, "env", None) is not None):
        destination = settings.setdefault("levels", {}).setdefault(level, {})
    role = getattr(args, "role", None)
    if role:
        if any(options[key] is not None for key in ("review_model", "review_effort", "executable", "timeout")) or getattr(args, "env", None):
            raise ValueError("a role override accepts model and effort only")
        destination = destination.setdefault("roles", {}).setdefault(role, {})
    destination.update({key: value for key, value in options.items() if value is not None})
    if getattr(args, "env", None) is not None:
        destination["environment_allowlist"] = list(dict.fromkeys(["PATH", "HOME", "TMPDIR", *args.env]))
    executors = copy.deepcopy(raw.get("executors", {}))
    executors["codex"] = settings
    updates["executors"] = executors
    execution = copy.deepcopy(raw.get("execution", {}))
    if not adding:
        execution.update(schema_version=1, backend="native")
        execution.setdefault("merge_policy", original.get("execution", {}).get("merge_policy", "manual"))
    elif "backend" not in original.get("execution", {}) and agent_config.advanced(original):
        execution["backend"] = "legacy-plugin"
    if execution or "execution" in raw:
        updates["execution"] = execution
    text = setup_agents.edit(before, updates)
    candidate = setup_agents.effective(repo, text, layer)
    target = ext.executor_config(candidate, "codex")
    if not agent_config.compact_codex(target):
        raise ValueError("a higher config layer overrides compact settings; select --layer local")
    plans = {level: agent_config.resolve(target, level) for level in ("fast", "normal", "deep")}
    if not adding and candidate.get("execution", {}).get("backend", "legacy-plugin") != "native":
        raise ValueError("a higher config layer overrides the selected backend; select --layer local")
    # A local model override must not silently defeat a requested project edit.
    if converting:
        migration_updates = {**updates, "executors": {**executors, "codex": converted_settings}}
        migration = setup_agents.effective(repo, setup_agents.edit(before, migration_updates), layer)
        for run_level in ("fast", "normal", "deep"):
            previous = agent_config.resolve(ext.executor_config(original, "codex"), run_level)["roles"]
            migrated = agent_config.resolve(ext.executor_config(migration, "codex"), run_level)["roles"]
            for migrated_role, selected in migrated.items():
                if {k:v for k,v in selected.items() if k not in ("profile_id", "prompt")} != {
                        k:v for k,v in previous[migrated_role].items() if k not in ("profile_id", "prompt")}:
                    raise ValueError("compaction would change inherited/local role settings; use --layer local")
    if any(value is not None for value in options.values()) or getattr(args, "env", None) is not None:
        intended = setup_agents.effective(repo, text, layer, through_layer=True)
        declared = intended.get("executors", {}).get("codex", {})
        requested = {key for key, value in options.items() if value is not None}
        if getattr(args, "env", None) is not None:
            requested.add("environment_allowlist")
        for run_level in ((level,) if level else ("fast", "normal", "deep")):
            expected = agent_config.resolve(ext.executor_config(intended, "codex"), run_level)["roles"]
            overrides = declared.get("levels", {}).get(run_level, {})
            for key in requested:
                if not level and key in overrides:
                    continue
                review_only = key.startswith("review_")
                field = key.removeprefix("review_")
                for checked_role in ((role,) if role else ROLES):
                    if field in ("model", "effort") and (checked_role in agent_config.REVIEWERS) != review_only and not role:
                        continue
                    if not role and (field in declared.get("roles", {}).get(checked_role, {}) or field in overrides.get("roles", {}).get(checked_role, {})):
                        continue
                    if plans[run_level]["roles"][checked_role][field] != expected[checked_role][field]:
                        raise ValueError("a higher config layer overrides the requested models; select --layer local")
    disabled = []
    if getattr(args, "disable_agent_checks", False):
        disabled = [item["name"] for item in candidate["verify"] if item.get("kind", "agent") != "command"]
        checks = copy.deepcopy(raw.get("verify", []))
        for name in disabled:
            entry = next((item for item in checks if item.get("name") == name), None)
            if entry is None:
                entry = {"name": name}
                checks.append(entry)
            entry["enabled"] = False
        updates["verify"] = checks
        text = setup_agents.edit(before, updates)
        candidate = setup_agents.effective(repo, text, layer)
        if any(item.get("kind", "agent") != "command" for item in candidate["verify"]):
            raise ValueError("a higher config layer enables agent checks; select --layer local")
    agent_config.resolve(candidate)
    if setup_agents.equal(raw, tomllib.loads(text)):
        text = before
    return {"content": text, "agent": "codex", "backend": candidate.get("execution", {}).get("backend", "legacy-plugin"),
            "mode": "add" if adding else "select", "profile_backend": "native", "configuration": "compact",
            "profiles_reused": not converting and "codex" in original.get("executors", {}) and not any(
                value is not None for value in options.values()) and getattr(args, "env", None) is None,
            "defaults_used": not settings, "resolved_roles": plans[level or "normal"]["roles"],
            "disabled_agent_checks": disabled, "model_started": False,
            "notes": ["Shared models apply to all levels; levels/roles override them. Native agents inherit chat permissions. Merge policy is preserved; push remains manual."] + agent_config.migration_warnings(original)}


def configure_claude(repo, before, args, original):
    """Edit the current client's namespace only; historical shared roles remain fallback."""
    raw = tomllib.loads(before)
    layer = getattr(args, "layer", "local")
    adding = getattr(args, "add", False)
    if any(getattr(args, key, None) is not None for key in ("executable", "timeout", "env")):
        raise ValueError("Claude native agents inherit the host environment; CLI transport options do not apply")
    if getattr(args, "advanced", False) or getattr(args, "compact", False):
        raise ValueError("Claude native settings use the client namespace; CLI profile conversion does not apply")
    executors = copy.deepcopy(raw.get("executors", {}))
    settings = copy.deepcopy(executors.get("claude", {}))
    options = {key: getattr(args, key, None) for key in ("model", "effort", "review_model", "review_effort")}
    level, role = getattr(args, "model_level", None), getattr(args, "role", None)
    destination = settings
    if level and any(value is not None for value in options.values()):
        destination = settings.setdefault("levels", {}).setdefault(level, {})
    if role:
        if options["review_model"] is not None or options["review_effort"] is not None:
            raise ValueError("a role override accepts model and effort only")
        destination = destination.setdefault("roles", {}).setdefault(role, {})
    destination.update({key: value for key, value in options.items() if value is not None})
    updates = {}
    if settings or "claude" in executors:
        executors["claude"] = settings
        updates["executors"] = executors
    execution = copy.deepcopy(raw.get("execution", {}))
    if not adding:
        execution.update(schema_version=1, backend="legacy-plugin")
        execution.setdefault("merge_policy", original.get("execution", {}).get("merge_policy", "manual"))
        updates["execution"] = execution
    text = setup_agents.edit(before, updates)
    candidate = setup_agents.effective(repo, text, layer)
    if not adding and candidate.get("execution", {}).get("backend", "legacy-plugin") != "legacy-plugin":
        raise ValueError("a higher config layer overrides the selected backend; select --layer local")
    plans = {name: agent_config.resolve(ext.executor_config(candidate, "claude"), name) for name in ("fast", "normal", "deep")}
    if any(value is not None for value in options.values()):
        intended = setup_agents.effective(repo, text, layer, through_layer=True)
        for name in ((level,) if level else ("fast", "normal", "deep")):
            expected = agent_config.resolve(ext.executor_config(intended, "claude"), name)["roles"]
            declared = intended.get("executors", {}).get("claude", {})
            overrides = declared.get("levels", {}).get(name, {})
            for key, value in options.items():
                if value is None or (not level and key in overrides):
                    continue
                field = key.removeprefix("review_")
                for selected_role in ((role,) if role else ROLES):
                    if not role and key.startswith("review_") and selected_role not in agent_config.REVIEWERS:
                        continue
                    if not role and (field in declared.get("roles", {}).get(selected_role, {}) or field in overrides.get("roles", {}).get(selected_role, {})):
                        continue
                    if plans[name]["roles"][selected_role][field] != expected[selected_role][field]:
                        raise ValueError("a higher config layer overrides the requested models; select --layer local")
    if setup_agents.equal(raw, tomllib.loads(text)):
        text = before
    return {"content": text, "agent": "claude", "backend": candidate.get("execution", {}).get("backend", "legacy-plugin"),
            "mode": "add" if adding else "select", "profile_backend": "legacy-plugin", "configuration": "client-native",
            "profiles_reused": not any(value is not None for value in options.values()),
            "resolved_roles": plans[level or "normal"]["roles"], "disabled_agent_checks": [], "model_started": False,
            "notes": plans[level or "normal"]["warnings"] + ["Claude preferences are independent of Codex; omitted model/effort options preserve prior settings."]}
