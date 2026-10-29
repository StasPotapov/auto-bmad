"""Check configured coding CLIs offline; never starts a model or changes project files."""

import argparse
import json
import sys

import agent_adapters
import agent_config


def check(repo, level):
    plan = agent_config.read(repo, level)
    if plan["backend"] != "cli":
        return {"backend": "legacy-plugin", "note": "use auto-bmad preflight for the legacy workflow", "ok": True}
    profiles = {}
    for role, profile in plan["roles"].items():
        key = profile["profile_id"]
        if key in profiles:
            profiles[key]["roles"].append(role)
            continue
        item = {"roles": [role], "adapter": profile["adapter"], "model": profile["model"],
                "permissions": profile["permissions"], "ready": False}
        try:
            detected = agent_adapters.detect(profile)
            item.update(detected)
            agent_adapters.validate(profile, detected, engine=True)
            item["ready"] = True
        except (OSError, ValueError, TimeoutError) as e:
            item["error"] = str(e)
        profiles[key] = item
    return {"schema_version": 1, "backend": "cli", "config_hash": plan["config_hash"],
            "profiles": profiles, "ok": all(p["ready"] for p in profiles.values()),
            "inference_checked": False}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--level", default="normal", choices=("fast", "normal", "deep"))
    args = ap.parse_args(argv)
    try:
        out = check(args.repo, args.level)
    except (OSError, ValueError, TypeError, AttributeError) as e:
        out = {"ok": False, "error": str(e)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
