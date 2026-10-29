"""Inspect or prepare the BMAD engine. Preparation renders instructions; it never starts a model."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path

import agent_config
from agent_runtime import atomic_json, environment, execute
from execution_state import lease
from gitexclude import ensure_excluded
from ext import load
import engine_profile
from verify import resolve_command
from write_profile import MARKER, triage_setting

ENGINE_REL = Path(".claude/skills/bmad-build-auto")
REQUIRED = ("SKILL.md", "workflow.md", "step-01-clarify-and-route.md", "step-02-plan.md",
            "step-03-implement.md", "step-04-review.md", "spec-template.md", "customize.toml")
VALIDATION = Path(__file__).resolve().parent.parent / "docs/multi-agent/CODEX_STORY_SMOKE.json"


def validated(fingerprint):
    try:
        proof = json.loads(VALIDATION.read_text())
        return (proof.get("engine_fingerprint") == fingerprint and proof.get("story_completed") is True
                and proof.get("execution_status") == "completed" and proof.get("adapter") == "codex")
    except (OSError, ValueError, AttributeError):
        return False


def inspect(repo):
    root = Path(repo).resolve(strict=True)
    skill = (root / ENGINE_REL).resolve(strict=True)
    if not skill.is_relative_to(root):
        raise ValueError("engine skill escapes the project root")
    for name in REQUIRED:
        if not (skill / name).is_file():
            raise ValueError(f"missing engine file: {name}")
    paths = sorted(set(skill.rglob("*.md")) | set(skill.rglob("*.toml")))
    paths += [root / "_bmad/scripts/render_skill.py", root / "_bmad/scripts/config_utils.py"]
    files = {}
    for path in paths:
        target = path.resolve(strict=True)
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError(f"engine file escapes the project or is not a file: {path}")
        files[str(path.relative_to(root))] = hashlib.sha256(target.read_bytes()).hexdigest()
    customization = tomllib.loads((skill / "customize.toml").read_text())
    workflow = customization.get("workflow", {})
    for key, kind in (("persistent_facts", list), ("implementation_handoff", str),
                      ("review_layers", list), ("activation_steps_prepend", list),
                      ("activation_steps_append", list), ("on_complete", str)):
        if not isinstance(workflow.get(key), kind):
            raise ValueError(f"unsupported engine contract: workflow.{key} missing or wrong type")
    layers = workflow["review_layers"]
    if not all(isinstance(layer, dict) and isinstance(layer.get("id"), str) and
               isinstance(layer.get("instruction"), str) for layer in layers):
        raise ValueError("unsupported engine review layer contract")
    ids = [layer["id"] for layer in layers]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate engine review layer IDs")
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    ready = validated(fingerprint)
    return {"schema_version": 1, "repo": str(root), "skill": str(skill), "files": files,
            "fingerprint": fingerprint, "review_layers": ids, "contract_inspected": True,
            "execution_ready": ready, "inference_checked": False,
            "blocking": [] if ready else ["this engine fingerprint has no successful Codex story smoke receipt"]}


def write_profile(path, content):
    if path.is_symlink():
        raise ValueError("refusing a symlink engine profile")
    if path.exists() and MARKER not in path.read_text(encoding="utf-8")[:400]:
        raise ValueError("a human wrote the engine profile; it is left untouched")
    fd, tmp = tempfile.mkstemp(prefix=".profile-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def prepare(repo, output, level="normal"):
    root = Path(repo).resolve(strict=True)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("output directory must be new")
    with lease(root):
        cfg, _, _ = load(str(root), strict=True)
        plan = agent_config.resolve(cfg, level)
        config_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
        if plan["backend"] != "cli":
            raise ValueError("engine prepare requires execution.backend = 'cli'")
        contract = inspect(str(root))
        render_dir = root / "_bmad/render"
        if render_dir.is_symlink() or not render_dir.resolve().is_relative_to(root):
            raise ValueError("engine snapshot directory escapes the project")
        custom = root / "_bmad/custom"
        if custom.is_symlink() or not custom.resolve().is_relative_to(root):
            raise ValueError("engine customization directory escapes the project")
        custom.mkdir(exist_ok=True)
        profile = custom / "bmad-build-auto.user.toml"
        if profile.is_symlink() or (profile.exists() and MARKER not in profile.read_text()[:400]):
            raise ValueError("engine profile is not owned by auto-bmad; left untouched")
        uv = shutil.which("uv")
        if not uv:
            raise ValueError("uv is required by the engine renderer entry")
        triage, warning = triage_setting(cfg)
        if warning:
            raise ValueError(warning)
        check = next((item for item in cfg.get("verify", []) if item.get("name") == "project-tests"), None)
        command = resolve_command(check, str(root)) if check and check.get("kind") == "command" else None
        content = engine_profile.build(level, triage, command)
        if not ensure_excluded(str(root), "_bmad/custom/bmad-build-auto.user.toml"):
            raise ValueError("cannot exclude the generated engine profile")
        output.mkdir(mode=0o700)
        (output / "profile.toml").write_text(content, encoding="utf-8")
        write_profile(profile, content)
        renderer = root / "_bmad/scripts/render_skill.py"
        render_env = environment(["PATH", "HOME", "TMPDIR"])
        render_env["UV_OFFLINE"] = "1"
        result = execute([os.path.abspath(uv), "run", "--no-cache", str(renderer),
                          "--project-root", str(root), "--skill", contract["skill"]],
                         cwd=str(root), env=render_env, stdin="",
                         directory=output / "render", timeout=60, structured=False, consume=lambda _: None,
                         finish=lambda code: {"execution_status": "completed" if code == 0 else "failed"})
        if result["execution_status"] != "completed":
            raise ValueError(f"engine render {result['execution_status']}; inspect {output / 'render'}")
        instruction = (output / "render/stdout.jsonl").read_text().strip()
        prefix = "read and follow "
        if not instruction.startswith(prefix) or "\n" in instruction:
            raise ValueError("unsupported engine renderer output; expected one workflow instruction")
        workflow = Path(instruction[len(prefix):]).resolve(strict=True)
        render_root = (root / "_bmad/render").resolve(strict=True)
        if not render_root.is_relative_to(root) or not workflow.is_relative_to(render_root) or workflow.name != "workflow.md":
            raise ValueError("rendered workflow escapes the engine snapshot directory")
        native = json.loads((workflow.parent / "manifest.json").read_text())
        layers = native["inputs"]["resolved_values"]["customization.workflow.review_layers"]
        snapshot_hashes = native["outputs"]
        if not isinstance(layers, list) or not isinstance(snapshot_hashes, dict):
            raise ValueError("unsupported renderer manifest")
        blocking = list(contract["blocking"])
        unsupported = sorted({p["adapter"] for p in plan["roles"].values() if p["adapter"] != "codex"})
        if unsupported:
            blocking.append("configured CLI adapters are not yet validated: " + ", ".join(unsupported))
        out = {"schema_version": 1, "repo": str(root), "workflow": str(workflow), "config_hash": config_hash,
               "engine_fingerprint": contract["fingerprint"], "roles": plan["roles"],
               "workflow_hash": hashlib.sha256(workflow.read_bytes()).hexdigest(), "level": level,
               "profile": str(profile), "profile_hash": hashlib.sha256(content.encode()).hexdigest(),
               "review_layers": [item["id"] for item in layers if item.get("instruction")],
               "review_conditions": [item["id"] for item in layers if item.get("instruction") and item.get("when")],
               "snapshot_hashes": snapshot_hashes,
               "execution_ready": contract["execution_ready"] and all(p["adapter"] == "codex" for p in plan["roles"].values()),
               "delegation": {"entrypoint": str(Path(__file__).with_name("agent_dispatch.py").resolve()),
                              "python": sys.executable,
                              "request_fields": ["role", "task_id", "base_commit", "prompt"],
                              "model_opt_in_required": True, "status": "story-broker-experimental"},
               "blocking": blocking, "model_started": False, "inference_checked": False}
        atomic_json(output / "manifest.json", out)
        return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("inspect", "prepare"))
    ap.add_argument("--repo", default=".")
    ap.add_argument("--output", help="new private directory for the prepared manifest and renderer logs")
    ap.add_argument("--level", default="normal", choices=("fast", "normal", "deep"))
    args = ap.parse_args(argv)
    try:
        if args.action == "prepare" and not args.output:
            raise ValueError("prepare requires --output <new-directory>")
        out = prepare(args.repo, args.output, args.level) if args.action == "prepare" else inspect(args.repo)
        code = 0
    except (OSError, ValueError, TypeError, AttributeError) as e:
        out, code = {"error": str(e), "execution_ready": False}, 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
