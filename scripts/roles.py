#!/usr/bin/env python3
"""Model and effort of each auto-bmad role: the agent type defaults and the [roles.*] config.

A role is one of the plugin's agent types (agents/bmad-<role>.md). Its default model and
effort are the frontmatter of that file. The config layers (scripts/ext.py) may override
them per role:

    [roles.implementer]
    model = "sonnet"
    effort = "high"

The override reaches the subagent as the `model` and `effort` parameters of the Agent call
that launches it: those parameters win over the type's frontmatter. A file in .claude/agents/
would not work — Claude Code reads agent types once, at session start. The Agent call accepts
only the model aliases below, so an override loses the `[1m]` context of an opus default.

The value "default", or the default itself (`opus[1m]`), clears an override set in a lower
layer. Only the Anthropic provider is supported: a `provider` other than "anthropic" is an error.

Usage:
    roles.py [--repo .]

Always JSON on stdout: {"roles": {role: {...}}, "errors": [...], "warnings": [...]}.
Exit 0 — no errors, 2 — the config has errors (preflight blocks the run), 1 — call error.
"""

import argparse
import json
import os
import re
import sys

from ext import load

AGENTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents")
ROLES = ("story-runner", "implementer", "reviewer", "reviewer-mid", "reviewer-lite",
         "compiler-lite", "verifier")
MODELS = ("sonnet", "opus", "haiku", "fable")          # the Agent tool `model` enum
EFFORTS = ("low", "medium", "high", "xhigh", "max")    # the Agent tool `effort` enum
KEYS = ("model", "effort", "provider")


def agent_type(role):
    return f"auto-bmad:bmad-{role}"


def frontmatter(role):
    """{"model", "effort"} from agents/bmad-<role>.md; a missing file or key — None."""
    out = {"model": None, "effort": None}
    try:
        with open(os.path.join(AGENTS, f"bmad-{role}.md"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return out
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    for key in out:
        k = re.search(rf"^{key}:\s*(\S+)\s*$", m.group(1), re.M) if m else None
        out[key] = k.group(1) if k else None
    return out


def resolve(cfg):
    """→ (roles, errors, warnings). roles[role]["args"] — the Agent parameters to pass, maybe {}."""
    section = cfg.get("roles") or {}
    errors, warnings = [], []
    if not isinstance(section, dict):
        return resolve({})[0], ["[roles] must be a table of [roles.<role>] tables"], []
    for name in section:
        if name not in ROLES:
            warnings.append(f"[roles.{name}]: unknown role, ignored — roles: {', '.join(ROLES)}")
    roles = {}
    for role in ROLES:
        given = section.get(role) or {}
        if not isinstance(given, dict):
            errors.append(f"[roles.{role}] must be a table")
            given = {}
        for key in given:
            if key not in KEYS:
                warnings.append(f"[roles.{role}].{key}: unknown key, ignored — keys: {', '.join(KEYS)}")
        default = frontmatter(role)
        args = {}
        provider = given.get("provider", "anthropic")
        if provider != "anthropic":
            errors.append(f"[roles.{role}].provider = {provider!r}: only \"anthropic\" is supported "
                          "for now — remove the key or set it to \"anthropic\"")
        for key, allowed in (("model", MODELS), ("effort", EFFORTS)):
            if key not in given:
                continue
            value = given[key]
            if value in ("default", default[key]):
                continue
            if value not in allowed:
                errors.append(f"[roles.{role}].{key} = {value!r}: allowed {', '.join(allowed)}, "
                              "or \"default\"")
            else:
                args[key] = value
        if args.get("model") == "opus" and (default["model"] or "").endswith("[1m]"):
            warnings.append(f"[roles.{role}].model = {args['model']!r}: the default "
                            f"{default['model']} has a 1M context, the override does not")
        roles[role] = {"agent_type": agent_type(role), "default": default, "args": args,
                       "model": args.get("model", default["model"]),
                       "effort": args.get("effort", default["effort"])}
    return roles, errors, warnings


def load_roles(repo):
    """resolve() over the merged config; an unreadable config — the defaults and a warning."""
    try:
        cfg, _, warnings = load(repo)
    except Exception as e:                       # e.g. `hook = "x"`: ext.load expects tables
        cfg, warnings = {}, [f"cannot read the config: {e} — role overrides are not applied"]
    roles, errors, role_warnings = resolve(cfg)
    return roles, errors, warnings + role_warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print(json.dumps({"error": f"no such directory {repo}"}, ensure_ascii=False))
        return 1
    roles, errors, warnings = load_roles(repo)
    print(json.dumps({"roles": roles, "errors": errors, "warnings": warnings},
                     ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
