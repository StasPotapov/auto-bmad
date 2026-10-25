#!/usr/bin/env python3
"""Sets a project up for auto-bmad: what is there, what is missing, and writing the settings.

The /auto-bmad:setup skill calls these commands and talks to the human; the script itself
asks nothing and writes nothing without --write.

Usage:
    setup.py check [--repo .]
        state by stage: env, bmad, plan, project, extras, headless; `next` is the first
        unfinished stage and what to do
    setup.py init [--repo .] [--level normal] [--parallel conservative] [--width 3]
                  [--no-android] [--android-module M] [--no-web] [--test-command CMD]
                  [--write] [--force]
        .auto-bmad.toml from what the project has; without --write it only shows the text
    setup.py headless [--repo .] [--write] [--force]
        the permissions file for runs without a human (claude -p --settings …) and the command

Always JSON on stdout. Exit: 0 — done, 1 — call error, 2 — the file exists (without --force).
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

from plan_run import LEVELS, RUN_PARALLEL, SPRINT_REL, epics_file
from preflight import find_test_command
from verify import skill_available

CONFIG = ".auto-bmad.toml"
HEADLESS = os.path.join(".claude", "auto-bmad-headless.json")
MANIFEST = os.path.join("_bmad", "_config", "manifest.yaml")
MIN_BMAD = (6, 12)
BMAD_INSTALL = "npx bmad-method install --modules bmm --tools claude-code"
BMAD_UPDATE = "npx bmad-method install --yes --action update --modules bmm"
SKIP_DIRS = {"build", ".gradle", ".git", "node_modules", ".claude", "_bmad", "_bmad-output", ".idea"}

# Unattended permissions: everything the run cannot live without (scripts, engine git, uv render).
# push, reset --hard, clean -f and branch deletion are denied: a human does those.
HEADLESS_ALLOW = [
    "Bash(auto-bmad:*)", "Bash(python3:*)", "Bash(uv:*)",
    "Bash(git status:*)", "Bash(git log:*)", "Bash(git diff:*)", "Bash(git show:*)",
    "Bash(git add:*)", "Bash(git commit:*)", "Bash(git checkout:*)", "Bash(git switch:*)",
    "Bash(git worktree:*)", "Bash(git merge:*)", "Bash(git rev-parse:*)", "Bash(git stash:*)",
    "Bash(ls:*)", "Bash(cat:*)", "Bash(grep:*)", "Bash(sed:*)", "Bash(wc:*)", "Bash(mkdir:*)",
]
HEADLESS_DENY = [
    "Bash(git push:*)", "Bash(git reset --hard:*)", "Bash(git clean -f:*)",
    "Bash(git branch -D:*)", "Bash(rm -rf:*)",
]


def git(repo, *args):
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip()


def bmad_version(repo):
    try:
        with open(os.path.join(repo, MANIFEST), encoding="utf-8") as fh:
            m = re.search(r"^\s*version:\s*['\"]?(\d+)\.(\d+)(?:\.(\d+))?", fh.read(), re.M)
    except OSError:
        return None
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


def walk(repo, name):
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        if name in files:
            yield os.path.join(root, name)


APP_NAMES = ("app", "composeApp", "androidApp", "android")


def android_app(repo, module=None):
    """The Android app module: plugin com.android.application in build.gradle(.kts).

    There may be several app modules (probes, demos): take one by name from APP_NAMES,
    else the first; all go to `candidates`, so setup can ask the human.
    """
    apps = android_apps(repo)
    if not apps:
        return None
    if module:
        chosen = next((x for x in apps if x["module"] == module), None)
        if not chosen:
            return None
    else:
        chosen = next((x for n in APP_NAMES for x in apps if os.path.basename(x["module"]) == n), apps[0])
    return {**chosen, "candidates": [x["module"] for x in apps]}


def android_apps(repo):
    found = []
    for gradle in list(walk(repo, "build.gradle.kts")) + list(walk(repo, "build.gradle")):
        try:
            with open(gradle, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        if not re.search(r"com\.android\.application|android\.application\b|androidApplication\)",
                         text):
            continue
        module_dir = os.path.dirname(gradle)
        if os.path.abspath(module_dir) == os.path.abspath(repo):
            continue
        module = os.path.relpath(module_dir, repo)
        m = re.search(r"applicationId\s*=?\s*\"([\w.]+)\"", text)
        gradle_module = ":" + module.replace(os.sep, ":")
        name = os.path.basename(module_dir)
        found.append({
            "module": module,
            "build": f"./gradlew {gradle_module}:assembleDebug",
            "apk": f"{module}/build/outputs/apk/debug/{name}-debug.apk",
            "package": m.group(1) if m else None,
            "flag_secure": flag_secure(module_dir),
        })
    return sorted(found, key=lambda x: x["module"])


def flag_secure(module_dir):
    for path in glob.glob(os.path.join(module_dir, "src", "**", "*.kt"), recursive=True):
        try:
            with open(path, encoding="utf-8") as fh:
                if "FLAG_SECURE" in fh.read():
                    return True
        except OSError:
            continue
    return False


# Web frameworks in package.json and the dev server port each one uses by default.
WEB_PORTS = {"next": 3000, "nuxt": 3000, "astro": 4321, "@sveltejs/kit": 5173, "vite": 5173,
             "@angular/core": 4200, "gatsby": 8000, "react-scripts": 3000,
             "react": 3000, "vue": 5173, "svelte": 5173, "solid-js": 3000, "preact": 5173, "lit": 5173}
WEB_DIRS = ("", "web", "frontend", "site", "client", "apps/web")
LOCKS = (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"), ("bun.lock", "bun"))


def web_app(repo):
    """The web front end: package.json with a web framework, or a static index.html.

    Looked for in the root and in a few usual folders (WEB_DIRS). → {dir, framework, serve, url}
    or None. The port is the framework's default; setup shows it, the person corrects it.
    """
    for sub in WEB_DIRS:
        root = os.path.join(repo, sub)
        try:
            with open(os.path.join(root, "package.json"), encoding="utf-8") as fh:
                pkg = json.load(fh)
        except (OSError, ValueError):
            pkg = None
        if pkg is not None:
            deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
            framework = next((d for d in WEB_PORTS if d in deps), None)
            scripts = pkg.get("scripts") or {}
            script = next((s for s in ("dev", "start", "serve", "preview") if s in scripts), None)
            if framework and script:
                pm = next((m for lock, m in LOCKS if os.path.exists(os.path.join(root, lock))), "npm")
                serve = f"{pm} run {script}"
                return {"dir": sub or ".", "framework": framework,
                        "serve": f"cd {sub} && {serve}" if sub else serve,
                        "url": f"http://localhost:{WEB_PORTS[framework]}"}
        if os.path.exists(os.path.join(root, "index.html")):
            serve = "python3 -m http.server 8000"
            return {"dir": sub or ".", "framework": "static",
                    "serve": f"cd {sub} && {serve}" if sub else serve, "url": "http://localhost:8000"}
    return None


def personal_config():
    return os.environ.get("AUTO_BMAD_CONFIG") or os.path.expanduser("~/.config/auto-bmad/config.toml")


def find_skill_bin(name):
    """Full path to a skill's CLI (bin/<name>): the skill's agents call it that way, so permissions need it."""
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    for pattern in (os.path.join(home, "skills", name, "bin", name),
                    os.path.join(home, "plugins", "cache", "*", "*", "*", "skills", name, "bin", name)):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return None


def cmd_check(repo):
    st = {}
    py = sys.version_info[:2]
    env = {"git": bool(shutil.which("git")), "uv": bool(shutil.which("uv")),
           "python": f"{py[0]}.{py[1]}", "python_ok": py >= (3, 11),
           "npx": bool(shutil.which("npx"))}
    code, _ = git(repo, "rev-parse", "--git-dir")
    env["git_repo"] = code == 0
    env["ok"] = env["git"] and env["uv"] and env["python_ok"] and env["git_repo"]
    st["env"] = env

    ver = bmad_version(repo)
    bmad = {"installed": ver is not None, "version": ".".join(map(str, ver)) if ver else None,
            "version_ok": bool(ver) and ver[:2] >= MIN_BMAD,
            "engine": os.path.exists(os.path.join(repo, ".claude", "skills", "bmad-build-auto", "SKILL.md")),
            "user_config": os.path.exists(os.path.join(repo, "_bmad", "config.user.toml")),
            "install": BMAD_INSTALL}
    bmad["ok"] = bmad["installed"] and bmad["version_ok"] and bmad["engine"]
    if bmad["installed"] and not (bmad["version_ok"] and bmad["engine"]):
        bmad["update"] = BMAD_UPDATE
    st["bmad"] = bmad

    epics = epics_file(repo)
    plan = {"epics": os.path.relpath(epics, repo) if epics else None,
            "sprint_status": os.path.exists(os.path.join(repo, SPRINT_REL))}
    plan["ok"] = bool(plan["epics"]) and plan["sprint_status"]
    st["plan"] = plan

    app = android_app(repo)
    web = web_app(repo)
    project = {"config": os.path.exists(os.path.join(repo, CONFIG)),
               "test_command": find_test_command(repo), "android": app, "web": web}
    project["ok"] = project["config"]
    st["project"] = project

    st["extras"] = {"adbm": skill_available("adbm", repo) if app else None,
                    "mockmatch": skill_available("mockmatch", repo) if web else None,
                    "personal_config": personal_config() if os.path.exists(personal_config()) else None}
    st["headless"] = {"settings": HEADLESS if os.path.exists(os.path.join(repo, HEADLESS)) else None}

    order = [("env", "install what is missing: git, uv, Python 3.11+; the project must be a git repository"),
             ("bmad", f"install BMad {'.'.join(map(str, MIN_BMAD))}+ into the project: {BMAD_INSTALL}"),
             ("plan", "make the BMad plan: PRD → architecture → epics (bmad-create-epics-and-stories) "
                      "→ sprint planning (bmad-sprint-planning)"),
             ("project", "write .auto-bmad.toml: setup init --write")]
    st["next"] = next(({"stage": k, "do": do} for k, do in order if not st[k]["ok"]), None)
    st["ready"] = st["next"] is None
    return st, 0


def toml_str(value):
    return json.dumps(value, ensure_ascii=False)


def render_config(repo, level, parallel, width, android, test_command, module=None, web_on=True):
    lines = ["# auto-bmad settings for this project — the top config layer.",
             "# Written by /auto-bmad:setup; edit by hand as you like. Reference: the auto-bmad README.",
             "",
             "# Run defaults: command flags (--fast, --deep, --no-parallel, --width N) win.",
             "[run]",
             f"level = {toml_str(level)}",
             f"parallel = {toml_str(parallel)}",
             f"width = {width}",
             "",
             "# Checks after each story (on normal and deep): the whole project test suite."]
    if test_command:
        lines += ["[[verify]]", 'name = "project-tests"', f"command = {toml_str(test_command)}"]
    else:
        lines += ["# No test command found — the project-tests check is skipped. Set it:",
                  "# [[verify]]", '# name = "project-tests"', '# command = "…"']
    app = android_app(repo, module) if android else None
    if app:
        lines += ["", "# Android: a feature check on an emulator through the adbm skill.",
                  "[[verify]]", 'name = "adbm"',
                  f"build = {toml_str(app['build'])}", f"apk = {toml_str(app['apk'])}"]
        if app["package"]:
            lines.append(f"package = {toml_str(app['package'])}")
        lines.append("apis = [35]")
        if app["flag_secure"]:
            lines += ['notes = "The app sets FLAG_SECURE: turn off screenshot protection in its '
                      'settings before taking frames, otherwise the frames are black."']
    elif android is False and android_app(repo):
        lines += ["", "[[verify]]", 'name = "adbm"', "enabled = false"]
    web = web_app(repo) if web_on else None
    if web:
        lines += ["", "# Web: a feature check in a headless browser through the mockmatch skill.",
                  "# design = a design file in the repo (mockmatch pull, an HTML mockup or a PNG)",
                  "# turns on the check against the design; frame and widths narrow it.",
                  "[[verify]]", 'name = "mockmatch"',
                  f"serve = {toml_str(web['serve'])}", f"url = {toml_str(web['url'])}",
                  '# design = "design/home.html"', "# widths = [1440, 390]"]
    elif not web_on and web_app(repo):
        lines += ["", "[[verify]]", 'name = "mockmatch"', "enabled = false"]
    return "\n".join(lines) + "\n", app


def cmd_init(a, repo):
    if a.level not in LEVELS or a.parallel not in RUN_PARALLEL or a.width < 1:
        return {"error": f"level from {LEVELS}, parallel from {RUN_PARALLEL}, width ≥ 1"}, 1
    path = os.path.join(repo, CONFIG)
    test_command = a.test_command or find_test_command(repo)
    text, app = render_config(repo, a.level, a.parallel, a.width, not a.no_android, test_command,
                              a.android_module, not getattr(a, "no_web", False))
    out = {"path": CONFIG, "content": text, "android": app,
           "web": None if getattr(a, "no_web", False) else web_app(repo),
           "test_command": test_command, "written": False}
    if os.path.exists(path) and not a.force:
        out["exists"] = True
        return out, 2 if a.write else 0
    if a.write:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        out["written"] = True
    return out, 0


def configured_test_command(repo):
    """The project-tests command from the merged config, when set explicitly."""
    try:
        from ext import load
        cfg, _, _ = load(repo)
    except Exception:
        return None
    v = next((x for x in cfg.get("verify", []) if x.get("name") == "project-tests"), None)
    command = (v or {}).get("command")
    return None if not command or command.startswith("@") else command


def headless_settings(repo):
    allow = list(HEADLESS_ALLOW)
    test_command = configured_test_command(repo) or find_test_command(repo)
    if test_command:
        allow.append(f"Bash({test_command.split()[0]}:*)")
    if android_app(repo):
        allow += ["Bash(./gradlew:*)", "Bash(adb:*)", "Bash(adbm:*)"]
        full = find_skill_bin("adbm")
        if full:
            allow.append(f"Bash({full}:*)")
    web = web_app(repo)
    if web:
        allow += ["Bash(mockmatch:*)", "Bash(curl:*)",
                  f"Bash({web['serve'].split(' && ')[-1].split()[0]}:*)"]
        full = find_skill_bin("mockmatch")
        if full:
            allow.append(f"Bash({full}:*)")
    seen, uniq = set(), []
    for item in allow:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return {"//": "Permissions for running auto-bmad without a human: claude -p … --settings this file. "
                  "Written by /auto-bmad:setup; push and destructive git commands are denied.",
            "permissions": {"allow": uniq, "deny": HEADLESS_DENY}}


def cmd_headless(a, repo):
    path = os.path.join(repo, HEADLESS)
    settings = headless_settings(repo)
    command = ('mkdir -p .auto-bmad/runs && '
               'claude -p "/auto-bmad:auto-bmad epic-<N>" --permission-mode acceptEdits '
               f'--permission-prompts none --settings {HEADLESS} '
               "--output-format stream-json --verbose > .auto-bmad/runs/run.jsonl")
    out = {"path": HEADLESS, "settings": settings, "command": command, "written": False}
    if os.path.exists(path) and not a.force:
        out["exists"] = True
        return out, 2 if a.write else 0
    if a.write:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        out["written"] = True
    return out, 0


def main():
    ap = argparse.ArgumentParser(description="Set a project up for auto-bmad")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    i = sub.add_parser("init")
    i.add_argument("--level", default="normal")
    i.add_argument("--parallel", default="conservative")
    i.add_argument("--width", type=int, default=3)
    i.add_argument("--no-android", action="store_true")
    i.add_argument("--android-module", help="the app module when there are several (candidates)")
    i.add_argument("--no-web", action="store_true")
    i.add_argument("--test-command")
    h = sub.add_parser("headless")
    for p in (c, i, h):
        p.add_argument("--repo", default=".")
    for p in (i, h):
        p.add_argument("--write", action="store_true")
        p.add_argument("--force", action="store_true")
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    if a.cmd == "check":
        out, code = cmd_check(repo)
    elif a.cmd == "init":
        out, code = cmd_init(a, repo)
    else:
        out, code = cmd_headless(a, repo)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
