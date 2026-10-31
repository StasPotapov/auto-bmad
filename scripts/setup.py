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
                  [--agent codex|claude] [--model ID] [--disable-agent-checks]
                  [--write] [--force]
        .auto-bmad.toml from what the project has; without --write it only shows the text
    setup.py agent --agent codex|claude [--model ID] [--review-model ID] [--effort high]
                   [--disable-agent-checks] [--layer project|local] [--repo .] [--write]
        safely select executor/profiles without resetting existing project settings
    setup.py headless [--repo .] [--write] [--force]
        the permissions file for runs without a human (claude -p --settings …) and the command
    setup.py allow [--repo .]
        the allow rules a run in auto mode needs, and which of them the Claude Code settings
        (user, project, project local) do not have yet; writes nothing
    setup.py local [--repo .] [--write]
        .auto-bmad.local.toml — the config layer of this machine — closed from git: whether it
        is ignored or tracked; --write adds it to .gitignore
    setup.py role --role implementer [--model sonnet] [--effort high] [--layer project|user]
                  [--repo .] [--write]
        the [roles.<role>] table in .auto-bmad.toml (or the personal config); no --model and
        no --effort removes the table of that layer only (a lower layer may still set the role;
        --model default / --effort default clears it). A table the script cannot edit safely
        (a [roles] table, an inline table, a header inside a multiline string) — exit 1, edit by hand

Always JSON on stdout. Exit: 0 — done, 1 — call error, 2 — the file exists (agent init never replaces it).
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import setup_agents
import mcp_status
from plan_run import LEVELS, RUN_PARALLEL, SPRINT_REL, epics_file
from ext import LOCAL_CONFIG
from gitexclude import ensure_line
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
    "Bash(auto-bmad:*)", "Bash(uv run:*)",
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
    project["local"] = local_state(repo)
    st["project"] = project

    st["extras"] = {"adbm": skill_available("adbm", repo) if app else None,
                    "mockmatch": skill_available("mockmatch", repo) if web else None,
                    "claude_design": mcp_status.status() if web else None,
                    "personal_config": personal_config() if os.path.exists(personal_config()) else None}
    st["headless"] = {"settings": HEADLESS if os.path.exists(os.path.join(repo, HEADLESS)) else None}
    st["agents"] = setup_agents.CHOICES
    st["execution"] = execution_status(repo) if project["config"] else {"ok": False, "backend": None}

    order = [("env", "install what is missing: git, uv, Python 3.11+; the project must be a git repository"),
             ("bmad", f"install BMad {'.'.join(map(str, MIN_BMAD))}+ into the project: {BMAD_INSTALL}"),
             ("plan", "make the BMad plan: PRD → architecture → epics (bmad-create-epics-and-stories) "
                      "→ sprint planning (bmad-sprint-planning)"),
             ("project", "write .auto-bmad.toml: setup init --write"),
             ("execution", "choose an agent with setup agent, then resolve its reported blockers")]
    st["next"] = next(({"stage": k, "do": do} for k, do in order if not st[k]["ok"]), None)
    st["ready"] = st["next"] is None
    return st, 0


def execution_status(repo):
    import agent_config
    import doctor
    import engine
    from ext import load
    backend = None
    try:
        cfg, _, _ = load(repo, strict=True)
        configured, _, _ = load(repo, strict=True, apply_executor=False)
        backend = cfg.get("execution", {}).get("backend", "legacy-plugin")
        level = cfg.get("run", {}).get("level", "normal")
        plan = agent_config.resolve(cfg, level)
        if plan["backend"] == "legacy-plugin":
            return {"ok": True, "backend": "legacy-plugin", "warnings": plan["warnings"], "model_started": False,
                    "configured_backend": configured.get("execution", {}).get("backend", "legacy-plugin"),
                    "executor": os.environ.get("AUTO_BMAD_EXECUTOR")}
        result = doctor.check(repo, level)
        unsupported = [v["name"] for v in cfg["verify"] if v.get("kind", "agent") not in ("command", "agent")]
        result["unsupported_agent_checks"] = unsupported
        result["engine"] = engine.inspect(repo)
        result["ok"] = result["ok"] and not unsupported and result["engine"]["execution_ready"]
        result["model_started"] = False
        result["configured_backend"] = configured.get("execution", {}).get("backend", "legacy-plugin")
        result["executor"] = os.environ.get("AUTO_BMAD_EXECUTOR")
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        return {"ok": False, "backend": backend, "error": str(e), "model_started": False}


def toml_str(value):
    return json.dumps(value, ensure_ascii=False)


def render_config(repo, level, parallel, width, android, test_command, module=None, web_on=True,
                  design=None):
    lines = ["# auto-bmad settings for this project — the top config layer.",
             "# Written by /auto-bmad:setup; edit by hand as you like. Reference: the auto-bmad README.",
             "",
             "# Run defaults: command flags (--fast, --deep, --no-parallel, --width N) win.",
             "[run]",
             f"level = {toml_str(level)}",
             f"parallel = {toml_str(parallel)}",
             f"width = {width}",
             "# worktree = true  # the run in its own worktree on bmad/<target> (--worktree);",
             "#                  # merge it later with auto-bmad land bmad/<target>",
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
        design = {k: v for k, v in (design or {}).items() if v}
        lines += ["", "# Web: a feature check in a headless browser through the mockmatch skill.",
                  "# The design turns on the check against it: design_project (+ design_file) — a Claude",
                  "# Design project, pulled fresh for each check (needs the claude_design MCP logged in,",
                  "# preflight checks it); design_artifact — a claude.ai Design artifact, compared through",
                  "# its copy in design (claude -p cannot read artifacts); design — a file in the repo",
                  "# (mockmatch pull or import, an HTML mockup or a PNG), also the fallback without the",
                  "# login. frame and widths narrow the check.",
                  "[[verify]]", 'name = "mockmatch"',
                  f"serve = {toml_str(web['serve'])}", f"url = {toml_str(web['url'])}"]
        for key, example in (("design_project", '"https://claude.ai/design/p/<id>?file=Home.dc.html"'),
                             ("design_file", '"Home.dc.html"'),
                             ("design_artifact", '"https://claude.ai/artifact/<id>"'),
                             ("design", '"design/home.html"')):
            lines.append(f"{key} = {toml_str(design[key])}" if key in design else f"# {key} = {example}")
        lines.append("# widths = [1440, 390]")
    elif not web_on and web_app(repo):
        lines += ["", "[[verify]]", 'name = "mockmatch"', "enabled = false"]
    return "\n".join(lines) + "\n", app


def cmd_init(a, repo):
    if a.level not in LEVELS or a.parallel not in RUN_PARALLEL or a.width < 1:
        return {"error": f"level from {LEVELS}, parallel from {RUN_PARALLEL}, width ≥ 1"}, 1
    path = os.path.join(repo, CONFIG)
    if getattr(a, "agent", None) and os.path.exists(path):
        return {"path": CONFIG, "exists": True, "written": False,
                "error": "config exists; use setup agent to preserve existing settings (not init --force)"}, 2
    test_command = a.test_command or find_test_command(repo)
    design = {k: getattr(a, k, None) for k in ("design_project", "design_file", "design_artifact", "design")}
    text, app = render_config(repo, a.level, a.parallel, a.width, not a.no_android, test_command,
                              a.android_module, not getattr(a, "no_web", False), design)
    out = {"path": CONFIG, "content": text, "android": app,
           "web": None if getattr(a, "no_web", False) else web_app(repo),
           "test_command": test_command, "written": False}
    if os.path.exists(path) and not a.force:
        out["exists"] = True
        return out, 2 if a.write else 0
    if getattr(a, "agent", None):
        out.update(setup_agents.configure(repo, text, a))
        if a.write:
            before = Path(path).read_bytes().decode("utf-8") if os.path.exists(path) else ""
            out["backup"] = setup_agents.write(repo, path, before, out["content"])
            out["written"] = True
        return out, 0
    if a.write:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        out["written"] = True
    return out, 0


def cmd_agent(a, repo):
    name = LOCAL_CONFIG if a.layer == "local" else CONFIG
    path = Path(repo) / name
    before = path.read_bytes().decode("utf-8") if path.exists() else ""
    out = {"path": str(path), "written": False, **setup_agents.configure(repo, before, a)}
    if a.write:
        out["backup"] = setup_agents.write(repo, path, before, out["content"])
        out["written"] = before != out["content"]
    return out, 0


def drop_table(text, header):
    """The TOML text without the table that starts at `header`, up to the next table."""
    out, skip = [], False
    for line in text.splitlines():
        stripped = line.split("#")[0].strip()
        if re.fullmatch(r"\[\[?[^\[\]]+\]\]?", stripped):
            skip = stripped.replace(" ", "") == header
        if not skip:
            out.append(line)
    return "\n".join(out).rstrip() + "\n" if any(x.strip() for x in out) else ""


def cmd_role(a, repo):
    from ext import load
    if load(repo, strict=True)[0].get("execution", {}).get("backend") == "cli":
        return {"error": "setup role configures native Claude only; use setup agent for CLI profiles"}, 1
    from roles import EFFORTS, MODELS, OPUS_1M, ROLES, frontmatter
    if a.role not in ROLES:
        return {"error": f"role from {', '.join(ROLES)}"}, 1
    if a.model and a.model not in MODELS + ("default", OPUS_1M) or a.effort and a.effort not in EFFORTS + ("default",):
        return {"error": f"model from {', '.join(MODELS + (OPUS_1M,))}, effort from {', '.join(EFFORTS)}, "
                         "or default"}, 1
    if a.model == OPUS_1M and frontmatter(a.role)["model"] != OPUS_1M:
        return {"error": f"{OPUS_1M} only for a role whose agent type has it "
                         f"({', '.join(r for r in ROLES if frontmatter(r)['model'] == OPUS_1M)}); "
                         "use opus for the regular context"}, 1
    path = personal_config() if a.layer == "user" else os.path.join(repo, LOCAL_CONFIG if a.layer == "local" else CONFIG)
    try:
        with open(path, encoding="utf-8") as fh:
            before = fh.read()
    except FileNotFoundError:
        before = ""
    header = f"[roles.{a.role}]"
    values = {k: v for k, v in (("model", a.model), ("effort", a.effort)) if v}
    text = drop_table(before, header)
    table = [header] + [f"{k} = {toml_str(v)}" for k, v in values.items()]
    if values:
        text = (text + "\n" if text else "") + "\n".join(table) + "\n"
    # The edit is line based: check that it changed this role and nothing else.
    try:
        want = tomllib.loads(before)
        got = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return {"error": f"{path}: the edit would not parse ({e}) — set [roles.{a.role}] by hand"}, 1
    want.setdefault("roles", {}).pop(a.role, None)
    if values:
        want["roles"][a.role] = values
    if not want["roles"]:
        want.pop("roles")
    if got != want:
        return {"error": f"{path}: [roles.{a.role}] is written in a form this command does not edit "
                         "— set it by hand"}, 1
    out = {"path": path, "table": "\n".join(table) if values else None,
           "content": text, "written": False}
    if a.write:
        if a.layer == "local":
            out["backup"] = setup_agents.write(repo, path, before, text)
            out["written"] = before != text
        else:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
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


# A rule on the first word of these runs any code: an interpreter or a package manager's
# run. For them the rule takes the whole command, as narrow as the project's own call.
RUNS_ANY_CODE = {"python", "python3", "node", "ruby", "perl", "php", "bash", "sh", "zsh",
                 "deno", "bun", "bunx", "npm", "npx", "pnpm", "yarn", "uv", "uvx", "pipx", "poetry"}


def command_rule(command):
    """The allow rule for a project command: its first word, or the whole command when the
    first word alone would run any code (`python3 -m pytest`, `npm run dev`)."""
    words = command.split()
    if not words:
        return None
    head = os.path.basename(words[0])
    return f"Bash({command.strip() if head in RUNS_ANY_CODE else words[0]}:*)"


def headless_settings(repo):
    allow = list(HEADLESS_ALLOW)
    test_command = configured_test_command(repo) or find_test_command(repo)
    if test_command and command_rule(test_command):
        allow.append(command_rule(test_command))
    if android_app(repo):
        allow += ["Bash(./gradlew:*)", "Bash(adb:*)", "Bash(adbm:*)"]
        full = find_skill_bin("adbm")
        if full:
            allow.append(f"Bash({full}:*)")
    web = web_app(repo)
    if web:
        allow += ["Bash(mockmatch:*)", "Bash(curl:*)",
                  # the design from Claude Design: read-only calls of the claude_design MCP
                  "mcp__claude_design__list_projects", "mcp__claude_design__get_project",
                  "mcp__claude_design__list_files", "mcp__claude_design__render_preview"]
        serve = command_rule(web["serve"].split(" && ")[-1])
        if serve:
            allow.append(serve)
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


# Tools a run calls. The permissions file runs with acceptEdits, so it does not list them;
# in auto mode every call is checked, so they go into allow too. TodoWrite needs no rule:
# it is on Claude Code's built-in safe list.
TOOLS_ALLOW = ["Read", "Glob", "Grep", "Edit", "Write", "Agent", "SendMessage", "Skill",
               "TaskCreate", "TaskUpdate", "TaskList"]

# What auto mode drops from allow on entry (Claude Code docs, "Configure auto mode"):
# `Agent` rules and rules that run any code. Such calls go to the classifier anyway.
AUTO_MODE_DROPS = {"Agent"}

# Prose for autoMode.allow: it tells the classifier what a run does by routine.
AUTO_MODE_ALLOW = [
    "$defaults",
    "auto-bmad runs (the auto-bmad Claude Code plugin with the BMad engine) in this user's "
    "own repositories are routine: starting subagents of the auto-bmad:bmad-* types, "
    "rendering the engine with `uv run` of `_bmad/scripts/render_skill.py`, running the "
    "project's own test command, and committing, branching, merging and git worktrees in "
    "the local repository. Pushing is not part of a run.",
]


def settings_files(repo):
    root = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return [("user", os.path.join(root, "settings.json")),
            ("project", os.path.join(repo, ".claude", "settings.json")),
            ("local", os.path.join(repo, ".claude", "settings.local.json"))]


def parse_rule(rule):
    """`Tool(arg)` → (tool, arg or None). `Bash(git:*)` and `Bash(git *)` give arg `git *`."""
    m = re.fullmatch(r"([\w-]+)\((.*)\)", rule.strip())
    if not m:
        return rule.strip(), None
    arg = m.group(2).strip()
    if arg.endswith(":*"):
        arg = arg[:-2].rstrip() + " *"
    return m.group(1), arg


def matches(have, rule):
    """Does the settings rule `have` match the needed rule `rule`."""
    if have == rule:
        return True
    if rule.startswith("mcp__"):
        server = "__".join(rule.split("__")[:2])
        return have in (server, f"{server}__*")
    htool, harg = parse_rule(have)
    tool, arg = parse_rule(rule)
    if htool != tool:
        return False
    if harg is None or harg in ("*", ""):
        return True
    if arg is None:
        return False
    want = arg.removesuffix(" *")
    if harg.endswith(" *"):                       # word prefix: `git *` covers `git merge`
        prefix = harg[:-2]
        return want == prefix or want.startswith(prefix + " ")
    if harg.endswith("*"):                        # plain prefix: `git*` covers `gitk`
        return want.startswith(harg[:-1])
    return harg == arg                            # an exact rule covers only the exact command


def covered(rule, have):
    """Does one of the rules in `have` allow `rule`: the same rule, a wider prefix or the whole tool."""
    return any(matches(h, rule) for h in have)


def dropped_in_auto_mode(rule):
    tool, arg = parse_rule(rule)
    if rule in AUTO_MODE_DROPS or tool in AUTO_MODE_DROPS:
        return True
    if tool != "Bash" or not arg:
        return False
    words = arg.removesuffix(" *").split()
    # a narrow rule (the whole command) carries over; only the bare word, or `run` of a manager, is dropped
    return bool(words) and os.path.basename(words[0]) in RUNS_ANY_CODE and (
        len(words) == 1 or words[1:2] == ["run"] and len(words) == 2)


def cmd_allow(repo):
    need = TOOLS_ALLOW + headless_settings(repo)["permissions"]["allow"]
    rules, sources = {"allow": set(), "deny": set(), "ask": set()}, []
    for name, path in settings_files(repo):
        try:
            with open(path, encoding="utf-8") as fh:
                perms = json.load(fh).get("permissions") or {}
        except (OSError, ValueError, AttributeError):
            continue
        for kind in rules:
            rules[kind].update(r for r in perms.get(kind) or [] if isinstance(r, str))
        sources.append({"layer": name, "path": path})
    missing = [r for r in need if not covered(r, rules["allow"])]
    # a deny or ask rule wins over allow: such a call is refused or waits for a person
    conflicts = [{"rule": r, kind: sorted(h for h in rules[kind] if matches(h, r))}
                 for r in need for kind in ("deny", "ask") if covered(r, rules[kind])]
    return {"allow": need, "missing": missing,
            "dropped_in_auto_mode": [r for r in need if dropped_in_auto_mode(r)],
            "conflicts": conflicts, "deny": HEADLESS_DENY,
            "auto_mode_allow": AUTO_MODE_ALLOW, "sources": sources}, 0


def local_state(repo):
    """Is .auto-bmad.local.toml out of git → exists, tracked, ignored, in_gitignore, fix.

    Closed means a rule in the project's .gitignore: it holds on every clone. A rule only in
    .git/info/exclude or in the global ignore file holds on this machine alone.
    """
    path = os.path.join(repo, LOCAL_CONFIG)
    tracked = git(repo, "ls-files", "--error-unmatch", "--", LOCAL_CONFIG)[0] == 0
    code, rule = git(repo, "check-ignore", "-v", "--no-index", "--", LOCAL_CONFIG)
    source, _, rest = rule.partition(":")
    pattern = rest.partition(":")[2].split("\t", 1)[0]
    ignored = code == 0 and not pattern.startswith("!")
    in_gitignore = ignored and source == ".gitignore"
    out = {"path": LOCAL_CONFIG, "exists": os.path.exists(path), "tracked": tracked,
           "ignored": ignored, "in_gitignore": in_gitignore}
    if tracked:
        out["fix"] = (f"{LOCAL_CONFIG} is committed, so every machine gets it: "
                      f"git rm --cached {LOCAL_CONFIG}, then setup local --write")
    elif not in_gitignore:
        out["fix"] = (f"close {LOCAL_CONFIG} from git in the project's .gitignore: "
                      "setup local --write adds the line")
    return out


def cmd_local(a, repo):
    out = local_state(repo)
    out["written"] = False
    if a.write and not out["in_gitignore"]:
        written = ensure_line(os.path.join(repo, ".gitignore"), f"/{LOCAL_CONFIG}",
                              "auto-bmad: the config layer of this machine")
        out.update(local_state(repo), written=written)
    return out, 0


def cmd_headless(a, repo):
    from ext import load
    if load(repo, strict=True)[0].get("execution", {}).get("backend") == "cli":
        import shlex
        command = shlex.join([str(Path(__file__).resolve().parents[1] / "bin/auto-bmad"),
                              "--executor", "codex", "run", "--repo", os.path.abspath(repo), "--arg", "epic-<N>", "--allow-model"])
        return {"path": None, "settings": None, "command": command, "written": False,
                "note": "CLI permissions come from agent profiles; no Claude settings file is needed"}, 0
    path = os.path.join(repo, HEADLESS)
    settings = headless_settings(repo)
    command = ('mkdir -p .auto-bmad/runs && '
               'AUTO_BMAD_EXECUTOR=claude claude -p "/auto-bmad:auto-bmad epic-<N>" --permission-mode acceptEdits '
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
    i.add_argument("--design-project", help="Claude Design project id or claude.ai/design/p/<id> link")
    i.add_argument("--design-file", help="the design file inside the Claude Design project")
    i.add_argument("--design-artifact", help="a claude.ai Design artifact link (needs --design: its saved copy)")
    i.add_argument("--design", help="a design file in the repository (a saved copy, a mockup, a PNG)")
    i.add_argument("--test-command")
    setup_agents.add_options(i)
    ag = sub.add_parser("agent", help="select the executor, preview or safely update existing settings")
    setup_agents.add_options(ag, required=True)
    ag.add_argument("--layer", choices=("project", "local"), default="project")
    ag.add_argument("--level", dest="model_level", choices=LEVELS, help="change only this level's compact Codex models")
    ag.add_argument("--write", action="store_true")
    h = sub.add_parser("headless")
    w = sub.add_parser("allow")
    lc = sub.add_parser("local")
    lc.add_argument("--write", action="store_true")
    r = sub.add_parser("role")
    r.add_argument("--role", required=True)
    r.add_argument("--model")
    r.add_argument("--effort")
    r.add_argument("--layer", choices=("project", "user", "local"), default="project")
    r.add_argument("--write", action="store_true")
    for p in (c, i, h, w, r, lc, ag):
        p.add_argument("--repo", default=".")
        p.add_argument("--executor", choices=("codex", "claude"), help="executor of the current host; never changes the saved default")
    for p in (i, h):
        p.add_argument("--write", action="store_true")
        p.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.executor:
        os.environ["AUTO_BMAD_EXECUTOR"] = a.executor
    repo = os.path.abspath(a.repo)
    try:
        if a.cmd == "check":
            out, code = cmd_check(repo)
        elif a.cmd == "init":
            out, code = cmd_init(a, repo)
        elif a.cmd == "agent":
            out, code = cmd_agent(a, repo)
        elif a.cmd == "allow":
            out, code = cmd_allow(repo)
        elif a.cmd == "role":
            out, code = cmd_role(a, repo)
        elif a.cmd == "local":
            out, code = cmd_local(a, repo)
        else:
            out, code = cmd_headless(a, repo)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        out, code = {"error": str(e), "written": False}, 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
