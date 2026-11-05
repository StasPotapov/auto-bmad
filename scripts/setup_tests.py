"""Read-only project inspection and explicit, backed-up test strategy configuration."""

import json
import os
from pathlib import Path
import shlex
import tomllib

from ext import load, LOCAL_CONFIG
import project_tests
import setup_agents


def native_readiness(strategy):
    development = sorted(strategy.get('development', {}))
    builds = sorted(strategy.get('build', {}))
    gaps = []
    if not development:
        gaps.append('Register real focused development commands and allowed targets; scopes/fallback do not replace them.')
    if not builds:
        gaps.append('Register real compile/build commands, or explicitly document build_not_applicable in each development request.')
    return {'policy': 'integration-full-v1', 'development': development, 'build': builds,
            'gaps': gaps, 'full_baseline_required': False, 'automatic_full_fallback': False}


def inspect(repo):
    root = Path(repo)
    cfg, _, _ = load(str(root), strict=True)
    current = project_tests.settings(cfg)
    components = []
    skip = {".git", ".auto-bmad", ".claude", "node_modules", ".next", ".venv", "venv", "build", "dist", ".gradle", "_bmad", "_bmad-output"}
    for directory, dirs, files in os.walk(root):
        here = Path(directory)
        rel = here.relative_to(root).as_posix()
        dirs[:] = [d for d in dirs if d not in skip and not (here / d).is_symlink()]
        if len(here.relative_to(root).parts) >= 3:
            dirs[:] = []
        manifests = [name for name in ("package.json", "pyproject.toml", "pubspec.yaml", "build.gradle.kts", "build.gradle", "Package.swift", "Cargo.toml", "go.mod") if name in files]
        if not manifests:
            continue
        commands = []
        prefix = "" if rel == "." else "cd " + shlex.quote(rel) + " && "
        if "package.json" in manifests:
            package = json.loads((here / "package.json").read_text())
            manager = "pnpm" if "pnpm-lock.yaml" in files else "yarn" if "yarn.lock" in files else "npm"
            commands = [prefix + manager + " run " + shlex.quote(name) for name in package.get("scripts", {})
                        if name in ("test", "typecheck", "lint", "build", "e2e") or name.startswith("test:")]
        components.append({"name": here.name, "path": rel, "evidence": manifests,
                           "available_commands": commands, "requires_confirmation": True})
    return {"configured": current, "native_verification": native_readiness(current), "components": components, "shared_files": "fallback command or all scopes",
            "project_check_scripts": [p.relative_to(root).as_posix() for p in sorted((root / "scripts").glob("*check*")) if p.is_file()],
            "notes": ["Commands must prepare their dependencies in an isolated worktree; setup never runs a full baseline.",
                      "New native sessions need focused development targets and compile/build registration; missing coverage is a gap.",
                      "Confirm component boundaries, ignored documentation, shared files and test commands with the user."]}


def configure(args, repo):
    if not args.plan:
        return {**inspect(repo), "written": False}, 0
    data = json.loads(Path(args.plan).read_text())
    chosen = project_tests.settings({"project_tests": data})
    path = Path(repo) / (LOCAL_CONFIG if args.layer == "local" else ".auto-bmad.toml")
    before = path.read_text() if path.exists() else ""
    content = setup_agents.edit(before, {"project_tests": chosen})
    effective = setup_agents.effective(repo, content, args.layer)
    resolved = project_tests.settings(effective)
    if resolved != chosen:
        raise ValueError("another config layer changes the requested test strategy; choose the appropriate layer")
    result = {"path": str(path), "content": content, "strategy": resolved, "native_verification": native_readiness(resolved), "written": False}
    if args.write:
        result["backup"] = setup_agents.write(repo, path, before, content)
        result["written"] = True
    return result, 0
