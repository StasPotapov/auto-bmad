"""Explicit, single-role CLI handoff in an existing isolated worktree. No story orchestration."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
import shlex

import agent_adapters
import agent_config
from agent_runtime import atomic_json, environment, execute
from common import git
from engine import inspect
from execution_state import canonical, lease, revision
from ext import load
from gitexclude import ensure_excluded

SCHEMA = {"type": "object", "properties": {
    "status": {"type": "string", "enum": ["done", "blocked"]}, "report": {"type": "string"}},
    "required": ["status", "report"], "additionalProperties": False}
REVIEWERS = {"reviewer", "reviewer-mid", "reviewer-lite"}


def role_instructions(role):
    path = Path(__file__).resolve().parent.parent / "agents" / f"bmad-{role}.md"
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or len(text.split("---", 2)) != 3:
        raise ValueError(f"invalid instruction file for role {role}")
    body = text.split("---", 2)[2].strip()
    if not body:
        raise ValueError(f"missing instructions for role {role}")
    return body.replace('with `timeout: 600000`', 'through the host command tool')


def fingerprint(root):
    """Detect code/spec edits even when a read-only task returns a success message."""
    paths = git(str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if paths.returncode:
        raise ValueError("cannot inspect worktree contents")
    stages = git(str(root), "ls-files", "--stage", "-z")
    if stages.returncode:
        raise ValueError("cannot inspect Git index")
    links = {entry.split("\t", 1)[1] for entry in stages.stdout.split("\0")
             if entry.startswith("160000 ") and "\t" in entry}
    digest = hashlib.sha256(revision(root).encode())
    digest.update(stages.stdout.encode())
    for rel in sorted(set(filter(None, paths.stdout.split("\0")))):
        if rel.startswith(".auto-bmad/"):
            continue
        path = root / rel
        digest.update(os.fsencode(rel) + b"\0")
        if path.is_symlink():
            digest.update(b"link:" + os.fsencode(os.readlink(path)))
        elif rel in links and path.is_dir():
            top = git(str(path), "rev-parse", "--show-toplevel")
            if top.returncode == 0 and Path(top.stdout.strip()).resolve() == path.resolve():
                digest.update(fingerprint(path).encode())
            else:
                # Uninitialized gitlinks may contain user files; include those without following symlinks.
                for directory, dirs, files in os.walk(path, followlinks=False):
                    dirs.sort()
                    for name in sorted(files + [d for d in dirs if (Path(directory) / d).is_symlink()]):
                        item = Path(directory) / name
                        digest.update(os.fsencode(item.relative_to(root)))
                        if item.is_symlink():
                            digest.update(os.fsencode(os.readlink(item)))
                        else:
                            with item.open("rb") as fh:
                                digest.update(hashlib.file_digest(fh, "sha256").digest())
        elif path.is_file():
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"worktree file escapes root: {rel}")
            digest.update(str(path.stat().st_mode).encode())
            with path.open("rb") as fh:
                digest.update(hashlib.file_digest(fh, "sha256").digest())
        elif path.exists():
            raise ValueError(f"unsupported tracked entry: {rel}")
        else:
            digest.update(b"deleted")
    return digest.hexdigest()


def validate_manifest(manifest):
    root, common = canonical(manifest["repo"])
    location = git(str(root), "rev-parse", "--path-format=absolute", "--git-dir")
    if location.returncode or Path(location.stdout.strip()).resolve() == common:
        raise ValueError("agent execution requires a linked worktree; the main tree is not allowed")
    cfg, _, _ = load(str(root), strict=True)
    plan = agent_config.resolve(cfg, manifest["level"])
    if plan["backend"] != "cli" or plan["roles"] != manifest["roles"]:
        raise ValueError("prepared role routes changed; prepare the engine again")
    if hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest() != manifest["config_hash"]:
        raise ValueError("prepared config changed; prepare the engine again")
    if inspect(root)["fingerprint"] != manifest["engine_fingerprint"]:
        raise ValueError("engine sources changed; prepare the engine again")
    workflow = Path(manifest["workflow"]).resolve(strict=True)
    if not workflow.is_relative_to(root / "_bmad/render") or hashlib.sha256(workflow.read_bytes()).hexdigest() != manifest["workflow_hash"]:
        raise ValueError("prepared workflow changed or escaped the project")
    for name, expected in manifest["snapshot_hashes"].items():
        path = workflow.parent / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(workflow.parent) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("prepared snapshot changed; prepare the engine again")
    profile = Path(manifest["profile"])
    if (profile.is_symlink() or not profile.resolve(strict=True).is_relative_to(root / "_bmad/custom") or
            hashlib.sha256(profile.read_bytes()).hexdigest() != manifest["profile_hash"]):
        raise ValueError("prepared engine profile changed; prepare the engine again")
    return root, plan


def dispatch(manifest_path, request_path, *, context=None, cancel=None, lease_fd=None):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(request, dict):
        raise ValueError("manifest and request must be JSON objects")
    required = {"schema_version", "repo", "workflow", "level", "roles", "config_hash", "engine_fingerprint",
            "workflow_hash", "profile", "profile_hash", "snapshot_hashes"}
    if manifest.get("schema_version") != 1 or not required.issubset(manifest):
        raise ValueError("unsupported or incomplete manifest; prepare the engine again")
    if set(request) - {"role", "task_id", "base_commit", "prompt", "layer_id", "diff_file"} or not {
            "role", "task_id", "base_commit", "prompt"}.issubset(request):
        raise ValueError("request requires exactly role, task_id, base_commit and prompt")
    if any(not isinstance(v, str) or not v.strip() or "\0" in v for v in request.values()):
        raise ValueError("request fields must be nonempty strings")
    workflow = Path(manifest["workflow"]).resolve(strict=True)
    root = Path(manifest["repo"]).resolve(strict=True)
    root, common = canonical(root)
    git_dir = git(str(root), "rev-parse", "--path-format=absolute", "--git-dir")
    if git_dir.returncode or Path(git_dir.stdout.strip()).resolve() == common:
        raise ValueError("agent execution requires a linked worktree; the main tree is not allowed")
    with (lease(root) if context is None else context.authorize(root, manifest, request)):
        _, plan = validate_manifest(manifest)
        base = revision(root)
        branch = git(str(root), "symbolic-ref", "--quiet", "HEAD").stdout.strip()
        if request["base_commit"] != base:
            raise ValueError("worktree HEAD differs from the requested exact base commit")
        role = request["role"]
        if role not in plan["roles"] or role == "story-runner":
            raise ValueError("agent execute accepts leaf roles only; story orchestration is not enabled")
        profile = plan["roles"][role]
        instructions = role_instructions(role)
        if context is not None:
            instructions = instructions.replace("auto-bmad test", "auto-bmad test --session " + shlex.quote(str(context.session_path)))
        if role in REVIEWERS and profile["permissions"] != "read-only":
            raise ValueError("reviewer profiles must enforce read-only permissions")
        detected = agent_adapters.detect(profile)
        agent_adapters.validate(profile, detected)
        if not ensure_excluded(str(root), ".auto-bmad/"):
            raise ValueError("cannot exclude runtime state")
        state = root / ".auto-bmad/agents" if context is None else context.private / "attempts"
        if (context is None and not state.resolve().is_relative_to(root)) or state.is_symlink():
            raise ValueError("agent state directory escapes the worktree")
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        attempt = state / uuid.uuid4().hex
        attempt.mkdir(mode=0o700)
        schema = attempt / "schema.json"
        atomic_json(schema, SCHEMA)
        atomic_json(attempt / "request.json", request)
        before = fingerprint(root) if profile["permissions"] == "read-only" else None
        parser = agent_adapters.result_parser(profile)
        prompt = ("Execute ONE BMAD delegated role: " + role + ". Task: " + request["task_id"] + ".\n"
                  "Do not launch agents, switch branches, merge or push. "
                  "Preserve the supplied handoff and its context restrictions. "
                  "Tool names in role instructions describe actions: use this host's available file/command tools. "
                  "Return JSON with status done|blocked and report containing the original role report.\n\n" + request["prompt"])
        prompt = prompt + "\n\nRole instructions (model and effort are set by the configured profile):\n" + instructions
        prompt += ("\n\nTransport envelope: the role's return contract applies INSIDE the report string. "
                   "Preserve its headers/rows there; the final response must be only the schema JSON "
                   "with status and report. Done means this delegated role finished, not that the story is done.")
        result = execute(agent_adapters.argv(profile, detected, str(root), schema, attempt / "answer.json"),
                         cwd=str(root), env=(environment(profile["environment_allowlist"]) if context is None else
                                            context.environment(profile["environment_allowlist"])), stdin=prompt,
                         directory=attempt / "process", timeout=profile["timeout"],
                         consume=parser.consume, finish=parser.finish, cancel=cancel,
                         manage_signals=context is None, lease_fd=lease_fd)
        if result["execution_status"] == "completed":
            answer = result.get("result")
            if (not isinstance(answer, dict) or set(answer) != {"status", "report"} or
                    answer["status"] not in ("done", "blocked") or not isinstance(answer["report"], str)):
                result.update(execution_status="failed", error={"kind": "protocol", "message": "invalid role result"})
        if profile["permissions"] == "read-only" and fingerprint(root) != before:
            result.update(execution_status="failed", error={"kind": "permission", "message": "read-only role changed the worktree"})
        if (git(str(root), "symbolic-ref", "--quiet", "HEAD").stdout.strip() != branch or
                git(str(root), "merge-base", "--is-ancestor", base, "HEAD").returncode):
            result.update(execution_status="failed", error={"kind": "permission", "message": "role changed its branch or rewrote its base"})
        changed = git(str(root), "diff", "--name-only", "-z", base)
        untracked = git(str(root), "ls-files", "--others", "--exclude-standard", "-z")
        if changed.returncode or untracked.returncode:
            raise ValueError(f"cannot collect changed files; attempt is preserved at {attempt}")
        result.update(schema_version=1, task_id=request["task_id"], role=role, profile_id=profile["profile_id"], adapter=profile["adapter"],
                      model_requested=profile["model"], model_observed=None, cli_version=detected.get("version"),
                      role_instruction_hash=hashlib.sha256(instructions.encode()).hexdigest(),
                      layer_id=request.get("layer_id"),
                      base_commit=base, head_commit=revision(root), worktree=str(root), attempt=str(attempt),
                      changed_files=sorted(set(filter(None, (changed.stdout + untracked.stdout).split("\0")))),
                      story_completed=False)
        atomic_json(attempt / "result.json", result)
        return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("execute", "execute-batch", "checkpoint", "commit", "rollback"))
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--request")
    ap.add_argument("--session", help="controller-issued session; the broker owns model consent and writer lease")
    ap.add_argument("--allow-model", action="store_true")
    args = ap.parse_args(argv)
    if not args.allow_model and not args.session:
        print(json.dumps({"error": "agent execution requires explicit --allow-model"}))
        return 2
    try:
        if args.session:
            from story_broker import client
            out = client(args.session, args.manifest, args.action, args.request)
        elif args.action != "execute" or not args.request:
            raise ValueError("batch/checkpoint require a controller session; execute requires --request")
        else:
            out = dispatch(args.manifest, args.request)
    except (OSError, ValueError, KeyError, TypeError) as e:
        out = {"execution_status": "failed", "error": str(e)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("execution_status") == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
