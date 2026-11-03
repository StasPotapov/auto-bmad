"""Validate native role configuration and resources without invoking a model or CLI."""

import argparse
import json
from pathlib import Path
import sys

import agent_config


def check(repo, level):
    plan = agent_config.read(repo, level)
    profiles = {}
    for role, profile in plan["roles"].items():
        path = Path(profile["prompt"])
        profiles[role] = {"model": profile["model"], "effort": profile["effort"],
                          "prompt": str(path), "ready": path.is_file(),
                          "read_only_instruction": profile["read_only"]}
        if not path.is_file():
            profiles[role]["error"] = "native role instructions are missing"
    return {"schema_version": 1, "backend": plan["backend"], "config_hash": plan["config_hash"],
            "profiles": profiles, "ok": all(p["ready"] for p in profiles.values()),
            "warnings": plan["warnings"], "permissions": "inherited",
            "host_capabilities_checked": False, "inference_checked": False, "model_started": False,
            "note": "The main chat must verify native spawn/message/wait tools, supported models and available slots before execution. No AI client executable or separate authentication probe is required."}


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
