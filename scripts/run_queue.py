"""CLI entry for one story or a sequential epic, isolated from the caller's branch."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
import uuid

import agent_adapters
import agent_config
from agent_runtime import atomic_json, execute
from common import git, SPRINT_REL
import engine
from execution_state import canonical, current_lease_fd, lease, revision
from ext import load, hook_timeout
import run_story
import plan_run
from story_broker import Stop
import window
import worktree

HERE = Path(__file__).resolve().parent


def sequential(arg):
    tokens = (arg or "").split()
    if any(t in ("--parallel-fast", "--width", "--no-worktree") for t in tokens):
        raise ValueError("CLI runs require an isolated worktree and sequential stories; waves are not enabled")
    return " ".join([*tokens, "--no-parallel"])


def inspect(repo, arg):
    root, _ = canonical(repo)
    cfg, _, _ = load(str(root), strict=True)
    backend = agent_config.resolve(cfg)["backend"]
    if backend != "cli":
        return {"backend": backend, "model_started": False, "note": "use the legacy Claude skill; configure execution.backend=cli for Codex"}
    target = run_story.local_json("plan_run.py", root, ["--arg", sequential(arg)])
    plan = agent_config.resolve(cfg, target["level"])
    return {"backend": "cli", "model_started": False, "plan": target, "roles": plan["roles"]}


class Queue:
    def __init__(self, source, common, target, timeout, cfg):
        self.source, self.root = source, source
        self.id = uuid.uuid4().hex
        self.private = common / "auto-bmad-sessions" / self.id
        self.private.mkdir(parents=True, mode=0o700)
        self.session_path = self.private / "session.json"
        self.stop = Stop(self.private / "cancel")
        self.source_fd = current_lease_fd()
        self.stop.deadline = time.monotonic() + timeout
        self.env = dict(os.environ)
        self.config_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
        self.env["PATH"] = str(HERE.parent / "bin") + os.pathsep + self.env.get("PATH", os.defpath)
        for key in ("AUTO_BMAD_CONFIG", "AUTO_BMAD_EVENTS_FILE", window.ENV_LIMITS,
                    window.ENV_STOP_FILE, window.ENV_LIVE_FILE):
            if self.env.get(key):
                self.env[key] = os.path.abspath(os.path.expanduser(self.env[key]))
        self.data = {"schema_version": 1, "kind": "queue", "repo": str(source), "status": "running",
                     "mode": target["mode"], "epic": target["epic"], "level": target["level"],
                     "planned_stories": [s["id"] for s in target["stories"]], "active_story": None,
                     "stories": [], "merge_policy": "manual"}
        self.finished = threading.Event()
        self.save()
        atomic_json(self.private / "pulse.json", {"at": time.monotonic()})
        self.thread = threading.Thread(target=self.pulse, daemon=True)
        self.thread.start()

    def pulse(self):
        while not self.finished.wait(0.1):
            try:
                atomic_json(self.private / "pulse.json", {"at": time.monotonic()})
            except OSError:
                self.stop.event.set()
                return

    def save(self):
        atomic_json(self.session_path, self.data)

    def command(self, script, args, name, codes=(0,), timeout=60):
        return self.execute([sys.executable, str(HERE / script), *args], name, codes, timeout)

    def execute(self, argv, name, codes=(0,), timeout=60, env=None):
        folder = self.private / (uuid.uuid4().hex + "-" + name)
        result = execute(argv, cwd=str(self.root), env=self.env if env is None else env,
                         stdin="", directory=folder, timeout=timeout, consume=lambda _: None, structured=False,
                         finish=lambda code: {"execution_status": "completed" if code in codes else "failed"},
                         cancel=self.stop, manage_signals=False, lease_fd=current_lease_fd(), lease_fds=(self.source_fd,))
        if result["execution_status"] != "completed":
            raise ValueError(f"{name} {result['execution_status']}; inspect {folder}")
        raw = (folder / "stdout.jsonl").read_text()
        return json.loads(raw) if argv[0] == sys.executable else raw

    def event(self, event, story=None, end=None):
        with lease(self.root):
            cfg, _, _ = load(str(self.root), strict=True)
            if hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest() != self.config_hash:
                raise ValueError("configuration changed; refusing to execute modified hooks")
            args = ["fire", event, "--repo", str(self.root), "--epic", str(self.data["epic"]), "--level", self.data["level"]]
            if story:
                args += ["--story", story]
            if end:
                args += ["--status", end["status"], "--data", json.dumps(end)]
            result = self.command("ext.py", args, event, timeout=hook_timeout(cfg, (event,)))
            files = result.get("files", [])
            if files:
                if any(not isinstance(p, str) or Path(p).is_absolute() or not (self.root / p).resolve().is_relative_to(self.root) for p in files):
                    raise ValueError("hook returned paths outside its worktree")
                self.execute(["git", "add", "--", *[":(literal)" + p for p in files]], "hook-stage")
                changed = git(str(self.root), "diff", "--cached", "--name-only", "--", *[":(literal)" + p for p in files]).stdout.strip()
                if changed:
                    self.execute(["git", "commit", "-m", f"chore: files from auto-bmad hook ({event})", "--",
                                  *[":(literal)" + p for p in files]], "hook-commit")
            self.data.setdefault("hooks", []).append(result)
            self.save()
            asks = result.get("asks", [])
            if asks:
                self.data["questions"] = asks
                raise ValueError("a configured hook requires an answer; inspect the saved session questions")

    def finish(self, status):
        self.data.update(status=status, active_story=None)
        self.save()
        self.finished.set()
        self.thread.join()


def run(repo, arg, timeout=None):
    source, common = canonical(repo)
    with lease(source):
        initial = inspect(source, arg)
        if initial["backend"] != "cli":
            raise ValueError("run requires execution.backend=cli; legacy Claude execution is separate")
        target, profiles = initial["plan"], initial["roles"]
        entries, error = plan_run.read_status(str(source / SPRINT_REL))
        if error:
            raise ValueError(error)
        pending = plan_run.collect(entries, target["epic"]) if target["mode"] == "epic" else target["stories"]
        if not run_story.clean(source):
            raise ValueError("source worktree must be clean; existing edits are preserved")
        engine.inspect(source)
        cfg, _, _ = load(str(source), strict=True)
        config_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
        queue = Queue(source, common, target, timeout or profiles["story-runner"]["timeout"] * target["count"], cfg)
        previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        for sig in previous:
            signal.signal(sig, lambda *_: queue.stop.event.set())
        out = {"execution_status": "failed", "run_completed": False, "mode": target["mode"],
               "epic": target["epic"], "session": str(queue.session_path), "source": str(source),
               "merge_policy": "manual", "stories": [], "remaining": [s["id"] for s in pending]}
        try:
            needed = {"story-runner", "implementer"}
            if target["level"] == "deep":
                needed.add("reviewer")
            else:
                needed.update(("compiler-lite", "reviewer-mid", "reviewer-lite"))
            if cfg.get("run", {}).get("triage_subagent"):
                needed.add("triager")
            for role in needed:
                profile = profiles[role]
                if role in ("reviewer", "reviewer-mid", "reviewer-lite") and profile["permissions"] != "read-only":
                    raise ValueError("reviewer profiles must be read-only")
                agent_adapters.validate(profile, agent_adapters.detect(profile), engine=True)
            opening = queue.command("window.py", ["--stage", "next-story"], "window", codes=(0, 2))
            if not opening["take_next"]:
                out.update(execution_status="window", reason=opening["reason"])
                return out
            base = revision(source)
            made = worktree.create_cli(str(source), f"epic-{target['epic']}" if target["mode"] == "epic" else target["stories"][0]["id"])
            out.update(worktree=made["path"], branch=made["branch"], base_commit=base)
            queue.root = Path(made["path"])
            queue.data.update(worktree=str(queue.root), branch=made["branch"], base_commit=base)
            queue.save()
            if made.get("error"):
                raise ValueError(made["error"])
            copied, _, _ = load(str(queue.root), strict=True)
            if hashlib.sha256(json.dumps(copied, sort_keys=True).encode()).hexdigest() != config_hash:
                raise ValueError("configuration changed while creating the run worktree")
            package = queue.private / "prepared"
            engine.prepare(queue.root, package, target["level"])
            manifest = package / "manifest.json"
            queue.event("run-start")
            expected = revision(queue.root)
            selection = f"epic-{target['epic']} --{target['level']} --no-parallel" if target["mode"] == "epic" else f"{target['stories'][0]['id']} --{target['level']}"
            for story in target["stories"]:
                if queue.stop.is_set():
                    raise ValueError("run cancelled before the next story")
                if revision(queue.root) != expected or not run_story.clean(queue.root):
                    raise ValueError("run worktree changed between stories; work is preserved")
                current = queue.command("plan_run.py", ["--repo", str(queue.root), "--arg", selection], "plan")
                if story["id"] not in [s["id"] for s in current["stories"]]:
                    raise ValueError("the next story no longer belongs to the permitted queue")
                boundary = queue.command("window.py", ["--stage", "next-story"], "window", codes=(0, 2))
                if not boundary["take_next"]:
                    out.update(execution_status="window", reason=boundary["reason"])
                    break
                queue.data["active_story"] = story["id"]
                queue.save()
                queue.event("story-start", story["id"])
                remaining_time = max(1, int(queue.stop.deadline - time.monotonic()))
                result = queue.command("run_story.py", ["--manifest", str(manifest), "--arg",
                         f"{story['id']} --{target['level']}", "--allow-model", "--timeout", str(remaining_time)],
                         "story-" + story["id"], codes=(0, 2), timeout=remaining_time + 5)
                out["stories"].append(result)
                queue.data["stories"] = out["stories"]
                queue.save()
                if not result.get("story_completed"):
                    out.update(execution_status=result.get("execution_status", "failed"), error=result.get("error", "story did not complete"))
                    break
                expected = result["head_commit"]
                out["remaining"].remove(story["id"])
            else:
                if target.get("waiting") or target.get("skipped"):
                    out.update(execution_status="blocked", waiting=target.get("waiting", []), skipped=target.get("skipped", []))
                else:
                    out.update(execution_status="completed", run_completed=True)
            if revision(source) != base or not run_story.clean(source):
                out.update(execution_status="needs_attention", run_completed=False, error="source changed during the run")
            before_end = queue.command("testrun.py", ["--repo", str(queue.root), "--tree"], "tree")["tree"]
            queue.event("run-end", end={"status": "done" if out["run_completed"] else out["execution_status"],
                        "done": sum(bool(s.get("story_completed")) for s in out["stories"]), "left": len(out["remaining"])})
            after_end = queue.command("testrun.py", ["--repo", str(queue.root), "--tree"], "tree")["tree"]
            if not before_end or before_end != after_end or not run_story.clean(queue.root):
                out.update(execution_status="needs_attention", run_completed=False, error="run-end hooks changed the verified code tree")
            out["head_commit"] = revision(queue.root)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as e:
            out.update(error=str(e), run_completed=False)
            if out["execution_status"] == "completed":
                out["execution_status"] = "needs_attention"
            if queue.stop.is_set():
                out["execution_status"] = "timed_out" if time.monotonic() >= queue.stop.deadline else "cancelled"
            if queue.data.get("questions"):
                out["execution_status"] = "blocked"
                out["questions"] = queue.data["questions"]
        finally:
            out["done"] = sum(bool(s.get("story_completed")) for s in out["stories"])
            out["left"] = len(out["remaining"])
            out["hooks"] = queue.data.get("hooks", [])
            queue.finish(out["execution_status"])
            atomic_json(queue.private / "result.json", out)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", nargs="?", default="start", choices=("start", "plan", "status", "cancel"))
    ap.add_argument("--repo", default=".")
    ap.add_argument("--arg", default="")
    ap.add_argument("--manifest")
    ap.add_argument("--session")
    ap.add_argument("--timeout", type=int)
    ap.add_argument("--allow-model", action="store_true")
    a = ap.parse_args(argv)
    if a.action in ("status", "cancel") or a.manifest and a.action == "start":
        forwarded = [a.action, "--manifest", a.manifest, "--arg", a.arg] if a.manifest else [a.action, "--session", a.session or ""]
        if a.allow_model:
            forwarded.append("--allow-model")
        if a.timeout is not None:
            forwarded += ["--timeout", str(a.timeout)]
        return run_story.main(forwarded)
    try:
        if a.manifest:
            raise ValueError("plan does not accept --manifest; use --repo")
        if a.action == "plan":
            out = inspect(a.repo, a.arg)
        else:
            if not a.allow_model:
                raise ValueError("run requires explicit --allow-model")
            if a.timeout is not None and a.timeout <= 0:
                raise ValueError("timeout must be positive")
            out = run(a.repo, a.arg, a.timeout)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as e:
        out = {"execution_status": "failed", "run_completed": False, "error": str(e)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if a.action == "plan" and "error" not in out or out.get("run_completed") else 2


if __name__ == "__main__":
    sys.exit(main())
