#!/usr/bin/env python3
"""Checks after a story: what to run, running commands, counting fixes, editing the spec for a fix.

Checks are described in the config ([[verify]], layers as for hooks, see ext.py). Fields:
  name          — the name; layers merge by it and fixes are counted by it;
  kind          — "command" (no model: a command, verdict by exit code)
                  or "agent" (subagent auto-bmad:bmad-verifier following instructions);
  levels        — levels the check runs on (default normal and deep);
  command       — for kind=command; "@test_command" — the test command from preflight;
  detect        — a command: does the check apply to the story. stdin gets JSON with the
                  diff files {"files": [...], "story", "title"}; exit 0 — yes, otherwise no;
  requires      — a skill the check cannot run without (otherwise skipped + a hint);
  install_hint  — how to install what is missing;
  preflight     — a command preflight.py runs before the run (fields on stdin; 1 — warning, 2 — blocking);
  instructions  — markdown for the subagent (kind=agent), "@plugin/…" — a path in the plugin;
  on_fail       — "fix" (the engine fixes, up to the limit) or "note" (a note only);
  enabled       — false turns it off.
Other check fields (build, apk, apis…) go to the subagent as is.

Fix limit per story — [verify_limits] by level (fast 0 — no checks).

Usage:
    verify.py plan --story 3-2 --base SHA --commit SHA --level normal [--title T] [--repo .]
    verify.py baseline [--repo .]                 # tests before the first story, once per run
    verify.py run --name project-tests [--repo .] # a kind=command check, through testrun.py
    verify.py attempt --story 3-2 --level normal --base SHA [--repo .]   # count a fix, is one more allowed
    verify.py fix-spec --spec PATH --pass N [--repo .] < problems.md   # fix tasks into the spec
    verify.py fix-spec --spec PATH --pass N --problems-file F --commit-story ID   # and commit it

baseline and run go through testrun.py (`auto-bmad test`): the folder's test lock, and the
kept result when the code has not changed since that command ran in this folder.

Always prints JSON on stdout. Exit: 0 — done, 1 — call error, 2 — "not done by rule"
(no checks, fix limit used up, spec in the wrong status), 3 — the tests still run
(`verdict: running`): call the same command again.
"""

import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from common import commit_paths
from ext import expand, load
from gitexclude import ensure_excluded
from preflight import find_test_command
import testrun

STATE = os.path.join(".auto-bmad", "verify")
DEFAULT_LIMITS = {"fast": 0, "normal": 2, "deep": 3}
DEFAULT_LEVELS = ["normal", "deep"]
OWN = ("name", "kind", "levels", "command", "detect", "requires", "install_hint",
       "instructions", "on_fail", "enabled", "timeout", "preflight")


def git(repo, *args):
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout


def changed_files(repo, base, commit):
    code, out = git(repo, "diff", "--name-only", f"{base}..{commit}")
    return [line for line in out.splitlines() if line] if code == 0 else []


def cli_skill(name, repo, include_project=True):
    """Resolve a skill that a CLI verifier can actually read, without Claude's cache."""
    if not isinstance(name, str) or not re.fullmatch(r"[\w-]+(?::[\w-]+)?", name):
        return None
    short = name.rsplit(":", 1)[-1]
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    places = ([Path(repo) / ".agents/skills" / short / "SKILL.md",
               Path(repo) / ".codex/skills" / short / "SKILL.md"] if include_project else [])
    places += [Path.home() / ".agents/skills" / short / "SKILL.md",
              home / "skills" / short / "SKILL.md"]
    places += sorted((home / "plugins/cache").glob("*/*/*/**/SKILL.md"))
    for path in places:
        try:
            head = path.read_text(encoding="utf-8").split("---", 2)
            if len(head) == 3 and re.search(rf"^name:\s*['\"]?{re.escape(short)}['\"]?\s*$", head[1], re.M):
                return str(path.resolve())
        except (OSError, UnicodeError):
            continue
    return None


def skill_available(name, repo, backend=None):
    """The skill is visible to Claude Code: project, user or an installed plugin."""
    if backend is None:
        cfg, _, _ = load(repo)
        backend = cfg.get("execution", {}).get("backend")
    if backend == "cli":
        return cli_skill(name, repo) is not None
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    places = [os.path.join(repo, ".claude", "skills", name, "SKILL.md"),
              os.path.join(home, "skills", name, "SKILL.md")]
    if any(os.path.exists(p) for p in places):
        return True
    for p in glob.glob(os.path.join(home, "plugins", "cache", "*", "*", "*", "**", "SKILL.md"),
                       recursive=True):
        try:
            with open(p, encoding="utf-8") as fh:
                head = fh.read(400)
        except OSError:
            continue
        if re.search(rf"^name:\s*['\"]?{re.escape(name)}['\"]?\s*$", head, re.M):
            return True
    return False


def state_path(repo, name):
    return os.path.join(repo, STATE, name)


def cmd_plan(a, repo):
    cfg, _, warnings = load(repo)
    limits = {**DEFAULT_LIMITS, **cfg.get("verify_limits", {})}
    limit = int(limits.get(a.level, 0))
    out = {"story": a.story, "level": a.level, "fix_limit": limit, "verifiers": [],
           "skipped": [], "warnings": warnings}
    if limit <= 0 and a.level == "fast":
        out["note"] = f"no checks on level {a.level}"
        return out, 2
    files = changed_files(repo, a.base, a.commit)
    for v in cfg.get("verify", []):
        name = v.get("name", "?")
        if a.level not in v.get("levels", DEFAULT_LEVELS):
            continue
        if v.get("detect"):
            try:
                proc = subprocess.run(["sh", "-c", expand(v["detect"])], cwd=repo, capture_output=True,
                                      text=True, timeout=60,
                                      input=json.dumps({"files": files, "story": a.story, "title": a.title}))
                applies = proc.returncode == 0
            except (OSError, subprocess.TimeoutExpired) as e:
                out["warnings"].append(f"{name}: detect failed — {e}")
                applies = False
            if not applies:
                continue
        if v.get("requires") and not skill_available(v["requires"], repo):
            out["skipped"].append({"name": name, "reason": f"no skill {v['requires']}",
                                   "install_hint": v.get("install_hint")})
            continue
        item = {"name": name, "kind": v.get("kind", "agent"), "on_fail": v.get("on_fail", "fix")}
        if item["kind"] == "agent":
            item["instructions"] = expand(v.get("instructions"))
            item["skill"] = v.get("requires")
            item["fields"] = {k: val for k, val in v.items() if k not in OWN}
            if cfg.get("execution", {}).get("backend") == "cli":
                item["skill_path"] = cli_skill(v["requires"], repo) if v.get("requires") else None
                item["timeout"] = v.get("timeout")
        out["verifiers"].append(item)
    out["changed_files"] = len(files)
    return out, (0 if out["verifiers"] or out["skipped"] else 2)


def resolve_command(v, repo):
    command = v.get("command") or "@test_command"
    if command == "@test_command":
        command = find_test_command(repo)
    return command


def command_check(repo, name):
    """A kind=command check of the merged config → (command, timeout); turned off, not a
    command check, or no test command — (None, None)."""
    cfg, _, _ = load(repo)
    v = next((x for x in cfg.get("verify", []) if x.get("name") == name), None)
    if not v or v.get("kind", "agent") != "command":
        return None, None
    command = resolve_command(v, repo)
    return (command, v.get("timeout", 1800)) if command else (None, None)


def cmd_baseline(a, repo):
    cfg, _, _ = load(repo)
    v = next((x for x in cfg.get("verify", []) if x.get("name") == "project-tests"), None)
    if not v:
        return {"note": "the project-tests check is turned off"}, 2
    command = resolve_command(v, repo)
    if not command:
        return {"note": "no test command found in the project"}, 2
    # Red is taken again unless it is this run's: a failure kept from another day would hide
    # the story's breakage behind a red baseline.
    res, code = testrun.run(repo, command, v.get("timeout", 1800), rerun="red")
    if code:
        return res, code
    res.update({"command": command, "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")})
    ensure_excluded(repo, ".auto-bmad/")
    os.makedirs(os.path.join(repo, STATE), exist_ok=True)
    with open(state_path(repo, "baseline.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False)
    return res, 0


def cmd_run(a, repo):
    cfg, _, _ = load(repo)
    v = next((x for x in cfg.get("verify", []) if x.get("name") == a.name), None)
    if not v or v.get("kind", "agent") != "command":
        return {"error": f"no kind=command check named {a.name}"}, 1
    command = resolve_command(v, repo)
    if not command:
        return {"verdict": "skipped", "reason": "no test command found in the project"}, 0
    res, code = testrun.run(repo, command, v.get("timeout", 1800))
    if code:
        return res, code
    try:
        with open(state_path(repo, "baseline.json"), encoding="utf-8") as fh:
            base = json.load(fh)
    except (OSError, ValueError):
        base = None
    res["baseline"] = base.get("verdict") if base else None
    if (a.name == "project-tests" and res["verdict"] == "problem" and base
            and base.get("verdict") == "problem"):
        # The tests failed before the run too: not the story's breakage, the engine must not fix it.
        res["verdict"], res["reason"] = "skipped", "the tests failed before the run too (red baseline)"
    return res, 0


def cmd_attempt(a, repo):
    cfg, _, _ = load(repo)
    limits = {**DEFAULT_LIMITS, **cfg.get("verify_limits", {})}
    limit = int(limits.get(a.level, 0))
    ensure_excluded(repo, ".auto-bmad/")
    os.makedirs(os.path.join(repo, STATE), exist_ok=True)
    path = state_path(repo, f"{a.story}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {"fixes": 0}
    if a.base and st.get("base") != a.base:
        # Another base means a new run of this story: past fixes do not count.
        st = {"fixes": 0, "base": a.base}
    if st["fixes"] >= limit:
        return {"story": a.story, "fixes": st["fixes"], "limit": limit, "fix_allowed": False}, 2
    st["fixes"] += 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(st, fh)
    # fix is the number of this fix: pass it to fix-spec --pass and to "Attempt".
    return {"story": a.story, "fix": st["fixes"], "fixes": st["fixes"], "limit": limit,
            "fix_allowed": True}, 0


FRONT_STATUS = re.compile(r"^(status:\s*)['\"]?([\w-]+)['\"]?\s*$", re.M)


def cmd_fix_spec(a, repo):
    if a.problems_file:
        try:
            with open(a.problems_file, encoding="utf-8") as fh:
                problems = fh.read().strip()
        except OSError as e:
            return {"error": f"the problems file is unreadable: {e}"}, 1
    else:
        problems = sys.stdin.read().strip()
    if not problems:
        return {"error": "no problem list in stdin or --problems-file"}, 1
    try:
        with open(a.spec, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        return {"error": f"the spec is unreadable: {e}"}, 1
    m = FRONT_STATUS.search(text)
    if not m or m.group(2) != "done":
        return {"error": f"the spec is in status {m.group(2) if m else '?'}; fixes are added only to done"}, 2
    if "## Tasks & Acceptance" not in text or "## Spec Change Log" not in text:
        return {"error": "the spec has no Tasks & Acceptance or Spec Change Log section"}, 2
    items = "\n".join(f"- {line.lstrip('-* ').strip()}" for line in problems.splitlines() if line.strip())
    block = (f"\n**Execution — fix after the post-story check, attempt {a.passno}:**\n"
             f"<!-- auto-bmad verify fix {a.passno} -->\n{items}\n"
             "- Fix each problem above in the code so that the repeated check passes; "
             "do not redo earlier tasks.\n")
    i = text.index("## Spec Change Log")
    text = text[:i].rstrip("\n") + "\n" + block + "\n" + text[i:]
    log = (f"\n### {datetime.date.today().isoformat()} — post-story check, attempt {a.passno} (auto-bmad)\n"
           "- Trigger: the check after the story commit found problems (listed in the tasks "
           f"\"fix after the post-story check, attempt {a.passno}\").\n"
           "- Change: fix tasks added to Tasks & Acceptance; the intent contract is untouched.\n"
           "- KEEP: everything done earlier by the spec stays; only the found problems are fixed.\n")
    j = text.index("## Spec Change Log") + len("## Spec Change Log")
    k = text.find("\n## ", j)
    k = len(text) if k < 0 else k
    text = text[:k].rstrip("\n") + "\n" + log + text[k:]
    text = FRONT_STATUS.sub(lambda mm: f"{mm.group(1)}'in-progress'", text, count=1)
    rel = os.path.relpath(os.path.abspath(a.spec), repo)
    if a.commit_story and rel.startswith(".."):
        return {"error": f"the spec is outside the repository, cannot commit it: {a.spec}"}, 1
    with open(a.spec, encoding="utf-8") as fh:
        original = fh.read()
    with open(a.spec, "w", encoding="utf-8") as fh:
        fh.write(text)
    out = {"spec": a.spec, "status": "in-progress", "pass": a.passno, "files": [rel], "commit": None}
    if a.commit_story:
        message = f"spec: fix tasks from checks for story {a.commit_story}, attempt {a.passno}"
        sha, err = commit_paths(repo, [rel], message)
        if err:
            # put the spec back as it was, so the call can be repeated and the tree stays clean
            with open(a.spec, "w", encoding="utf-8") as fh:
                fh.write(original)
            subprocess.run(["git", "-C", repo, "reset", "-q", "--", rel], capture_output=True)
            return {"error": f"the commit failed, the spec is restored: {err}"}, 1
        out["commit"] = sha
    return out, 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    for opt in ("story", "base", "commit", "level"):
        p.add_argument(f"--{opt}", required=True)
    p.add_argument("--title")
    b = sub.add_parser("baseline")
    r = sub.add_parser("run")
    r.add_argument("--name", required=True)
    t = sub.add_parser("attempt")
    t.add_argument("--story", required=True)
    t.add_argument("--level", required=True)
    t.add_argument("--base", help="story base: another base resets the fix counter")
    f = sub.add_parser("fix-spec")
    f.add_argument("--spec", required=True)
    f.add_argument("--pass", dest="passno", type=int, required=True)
    f.add_argument("--problems-file", help="read the problems from this file instead of stdin")
    f.add_argument("--commit-story", metavar="ID", help="commit the spec for this story")
    for x in (p, b, r, t, f):
        x.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    if not os.path.isdir(repo):
        out, code = {"error": f"no such directory {repo}"}, 1
    else:
        out, code = {"plan": cmd_plan, "baseline": cmd_baseline, "run": cmd_run,
                     "attempt": cmd_attempt, "fix-spec": cmd_fix_spec}[a.cmd](a, repo)
    if out.get("error"):
        print(out["error"], file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
