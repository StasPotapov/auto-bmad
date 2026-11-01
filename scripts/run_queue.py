"""CLI entry for one story or an epic, isolated from the caller's branch."""

import argparse
import datetime
from contextlib import nullcontext
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
from ext import load, hook_timeout, EXECUTOR_ENV
import run_story
import plan_run
from story_broker import Stop
import window
import worktree
import cli_waves
import cli_stats
import run_control
import run_completion

HERE = Path(__file__).resolve().parent


def pending_changes(root):
    """Fingerprint saved edits, including planning files excluded from the code tree."""
    digest = hashlib.sha256()
    for args in (("diff", "--binary", "HEAD", "--"), ("diff", "--binary", "--cached", "--")):
        result = git(str(root), *args)
        if result.returncode:
            raise ValueError("cannot inspect pending changes around run-end hooks")
        digest.update(os.fsencode(result.stdout))
        digest.update(b"\0")
    result = git(str(root), "ls-files", "--others", "--exclude-standard", "-z")
    if result.returncode:
        raise ValueError("cannot inspect untracked files around run-end hooks")
    for name in sorted(filter(None, result.stdout.split("\0"))):
        path = root / name
        digest.update(os.fsencode(name) + b"\0")
        content = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def isolated(arg):
    tokens = (arg or "").split()
    if any(t.split("=", 1)[0].lower() == "--no-worktree" for t in tokens):
        raise ValueError("CLI runs require an isolated worktree")
    return arg


def inspect(repo, arg):
    root, _ = canonical(repo)
    cfg, _, _ = load(str(root), strict=True)
    backend = agent_config.resolve(cfg)["backend"]
    if backend != "cli":
        return {"backend": backend, "model_started": False, "note": "use the legacy Claude skill; configure execution.backend=cli for Codex"}
    target = run_story.local_json("plan_run.py", root, ["--arg", isolated(arg)])
    plan = agent_config.resolve(cfg, target["level"])
    return {"backend": "cli", "model_started": False, "plan": target, "roles": plan["roles"],
            "merge_policy": plan["merge_policy"],
            "base_commit": revision(root), "wave_plan_required": cli_waves.required(target)}


class Queue:
    def __init__(self, source, common, target, timeout, cfg):
        self.source, self.root = source, source
        self.id = uuid.uuid4().hex
        self.private = common / "auto-bmad-sessions" / self.id
        self.private.mkdir(parents=True, mode=0o700)
        self.session_path = self.private / "session.json"
        self.stop = Stop(self.private / "cancel")
        self.source_fd = current_lease_fd()
        self.stop.deadline = time.monotonic() + timeout if timeout is not None else None
        self.env = dict(os.environ)
        self.env["AUTO_BMAD_QUEUE_ID"] = self.id
        self.config_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
        self.env["PATH"] = str(HERE.parent / "bin") + os.pathsep + self.env.get("PATH", os.defpath)
        for key in ("AUTO_BMAD_CONFIG", "AUTO_BMAD_EVENTS_FILE", window.ENV_LIMITS,
                    window.ENV_STOP_FILE, window.ENV_LIVE_FILE):
            if self.env.get(key):
                self.env[key] = os.path.abspath(os.path.expanduser(self.env[key]))
        self.data = {"schema_version": 1, "kind": "queue", "repo": str(source), "status": "running",
                     "mode": target["mode"], "epic": target["epic"], "level": target["level"],
                     "planned_stories": [s["id"] for s in target["stories"]], "active_story": None,
                     "stories": [], "merge_policy": cfg.get("execution", {}).get("merge_policy", "manual"), "parallel": target["parallel"],
                     "parallel_width": target["parallel_width"], "active_stories": [],
                     "control_version": 1, "control_open": True, "started_stories": []}
        self.finished = threading.Event()
        self.started = time.monotonic()
        self.data["started"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
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

    def execute(self, argv, name, codes=(0,), timeout=60, env=None, cwd=None, parent_fd=None):
        folder = self.private / (uuid.uuid4().hex + "-" + name)
        result = execute(argv, cwd=str(cwd or self.root), env=self.env if env is None else env,
                         stdin="", directory=folder, timeout=timeout, consume=lambda _: None, structured=False,
                         finish=lambda code: {"execution_status": "completed" if code in codes else "failed"},
                         cancel=self.stop, manage_signals=False, lease_fd=parent_fd,
                         lease_fds=(self.source_fd,))
        if result["execution_status"] != "completed":
            raise ValueError(f"{name} {result['execution_status']}; inspect {folder}")
        raw = (folder / "stdout.jsonl").read_text()
        return json.loads(raw) if argv[0] == sys.executable else raw

    def event(self, event, story=None, end=None, owned=False):
        with (nullcontext() if owned else lease(self.root)):
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
            # Hooks may suggest a decision, but an autonomous run never waits for an answer.
            asks = [{"hook": row.get("name"), **row["ask"]} for row in result.get("results", []) if row.get("ask")]
            if asks:
                self.data.setdefault("questions", []).extend(asks)
                self.save()

    def admit(self, wave):
        with run_control.lock(self.private):
            target = run_control.read(self.private, self.data["planned_stories"])
            self.data["stop_after"] = target
            if target:
                completed = {s["story"] for s in self.data["stories"] if s.get("story_completed")}
                if target in completed:
                    self.data["control_open"] = False
                    self.save()
                    return False
                planned = self.data["planned_stories"]
                limit = planned.index(target)
                selected = [s for s in wave["stories"] if planned.index(s) <= limit]
                if not selected:
                    self.data["control_open"] = False
                    self.save()
                    return False
                if selected != wave["stories"]:
                    wave["planned_stories"] = wave["stories"]
                    wave["deferred"] = wave["stories"][len(selected):]
                    wave["stories"] = selected
                    index = self.data["waves"].index(wave)
                    self.data["waves"].insert(index + 1, {
                        "stories": list(wave["deferred"]), "reason": "deferred after the requested stop boundary"})
            self.data.update(active_story=None, active_stories=list(wave["stories"]))
            self.data["started_stories"].extend(wave["stories"])
            self.save()
            return True

    def stop_reached(self):
        with run_control.lock(self.private):
            target = run_control.read(self.private, self.data["planned_stories"])
            reached = bool(target and any(s["story"] == target and s.get("story_completed") for s in self.data["stories"]))
            if reached:
                self.data["control_open"] = False
                self.save()
            return reached

    def finish(self, status, out, close_only=False):
        with run_control.lock(self.private):
            try:
                target = run_control.read(self.private, self.data["planned_stories"])
            except (OSError, ValueError) as e:
                target, status = None, "needs_attention"
                out.update(execution_status=status, run_completed=False, error=str(e))
            if target:
                out["stop_after"] = target
                out["stop_target_reached"] = any(s["story"] == target and s.get("story_completed") for s in out["stories"])
                self.data["stop_after"] = target
            self.data.update(status="running" if close_only else status, control_open=False, active_story=None, active_stories=[])
            if close_only:
                self.save()
                return
            self.data.update(ended=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                             seconds=round(time.monotonic() - self.started, 3))
            self.save()
        self.finished.set()
        self.thread.join()


def run(repo, arg, timeout=None, wave_plan=None, progress=None):
    source, common = canonical(repo)
    with lease(source):
        initial = inspect(source, arg)
        if initial["backend"] != "cli":
            raise ValueError("run requires execution.backend=cli; legacy Claude execution is separate")
        target, profiles = initial["plan"], initial["roles"]
        waves = cli_waves.validate(wave_plan, target, initial["base_commit"])
        entries, error = plan_run.read_status(str(source / SPRINT_REL))
        if error:
            raise ValueError(error)
        pending = plan_run.collect(entries, target["epic"]) if target["mode"] == "epic" else target["stories"]
        if not run_story.clean(source):
            raise ValueError("source worktree must be clean; existing edits are preserved")
        engine.inspect(source)
        cfg, _, _ = load(str(source), strict=True)
        config_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
        queue = Queue(source, common, target, timeout, cfg)
        previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        for sig in previous:
            signal.signal(sig, lambda *_: queue.stop.event.set())
        out = {"execution_status": "failed", "run_completed": False, "mode": target["mode"],
               "epic": target["epic"], "session": str(queue.session_path), "source": str(source),
               "merge_policy": initial["merge_policy"], "stories": [], "remaining": [s["id"] for s in pending],
               "level": target["level"], "language": target.get("language"), "parallel": target["parallel"],
               "parallel_width": target["parallel_width"], "waves": waves}
        queue.data["waves"] = waves
        queue.save()
        merge_target = {}
        try:
            if out["merge_policy"] == "auto-main" and target["mode"] == "epic":
                merge_target = run_completion.target_snapshot(source)
            if progress:
                progress({"event": "run-started", "session": str(queue.session_path),
                          "started": queue.data["started"], "level": target["level"],
                          "parallel": target["parallel"], "waves": waves})
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
            for wave_number, wave in enumerate(waves, 1):
                if queue.stop.is_set():
                    raise ValueError("run cancelled before the next story")
                if queue.stop_reached():
                    out.update(execution_status="stopped", reason="requested story boundary reached")
                    break
                if revision(queue.root) != expected or not run_story.clean(queue.root):
                    raise ValueError("run worktree changed between stories; work is preserved")
                current = queue.command("plan_run.py", ["--repo", str(queue.root), "--arg", selection], "plan")
                if not set(wave["stories"]).issubset(s["id"] for s in current["stories"]):
                    raise ValueError("the next story no longer belongs to the permitted queue")
                boundary = queue.command("window.py", ["--stage", "next-story"], "window", codes=(0, 2))
                if not boundary["take_next"]:
                    out.update(execution_status="window", reason=boundary["reason"])
                    break
                if not queue.admit(wave):
                    out.update(execution_status="stopped", reason="requested story boundary reached")
                    break
                queue.data["active_wave"] = wave_number
                if target["parallel"] != "off":
                    queue.env["AUTO_BMAD_WAVE"] = str(wave_number)
                if len(wave["stories"]) > 1:
                    with lease(queue.root):
                        cli_waves.run(queue, wave, wave_number, target, out, current_lease_fd())
                    expected = revision(queue.root)
                    if not all(s.get("story_completed") for s in out["stories"] if s.get("wave") == wave_number):
                        break
                    continue
                story = next(s for s in target["stories"] if s["id"] == wave["stories"][0])
                queue.data["active_story"] = story["id"]
                queue.save()
                queue.event("story-start", story["id"])
                remaining_time = max(1, int(queue.stop.deadline - time.monotonic())) if queue.stop.deadline is not None else None
                deadline_args = ["--timeout", str(remaining_time)] if remaining_time is not None else []
                result = queue.command("run_story.py", ["--manifest", str(manifest), "--arg",
                         f"{story['id']} --{target['level']}", "--allow-model", *deadline_args],
                         "story-" + story["id"], codes=(0, 2), timeout=remaining_time + 5 if remaining_time is not None else None)
                out["stories"].append(result)
                result["wave"] = wave_number
                queue.data["stories"] = out["stories"]
                queue.save()
                if not result.get("story_completed"):
                    out.update(execution_status=result.get("execution_status", "failed"), error=result.get("error", "story did not complete"))
                    break
                expected = result["head_commit"]
                out["remaining"].remove(story["id"])
                wave["completed"] = True
            else:
                if out["remaining"] and queue.stop_reached():
                    out.update(execution_status="stopped", reason="requested story boundary reached")
                elif target.get("waiting") or target.get("skipped"):
                    out.update(execution_status="blocked", waiting=target.get("waiting", []), skipped=target.get("skipped", []))
                else:
                    out.update(execution_status="completed", run_completed=True)
            if (out["merge_policy"] != "auto-main" or target["mode"] != "epic") and (revision(source) != base or not run_story.clean(source)):
                out.update(execution_status="needs_attention", run_completed=False, error="source changed during the run")
            before_end = queue.command("testrun.py", ["--repo", str(queue.root), "--tree"], "tree")["tree"]
            clean_before_end = run_story.clean(queue.root)
            pending_before_end = pending_changes(queue.root)
            queue.event("run-end", end={"status": "done" if out["run_completed"] else out["execution_status"],
                        "done": sum(bool(s.get("story_completed")) for s in out["stories"]), "left": len(out["remaining"])})
            after_end = queue.command("testrun.py", ["--repo", str(queue.root), "--tree"], "tree")["tree"]
            if (not before_end or before_end != after_end or pending_before_end != pending_changes(queue.root)
                    or ((out["run_completed"] or clean_before_end) and not run_story.clean(queue.root))):
                if out.get("error"):
                    out["prior_error"] = out["error"]
                out.update(execution_status="needs_attention", run_completed=False, error="run-end hooks changed the verified code tree")
            out["head_commit"] = revision(queue.root)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as e:
            out.update(error=str(e), run_completed=False)
            if out["execution_status"] in ("completed", "stopped"):
                out["execution_status"] = "needs_attention"
            if queue.stop.is_set():
                out["execution_status"] = "timed_out" if queue.stop.deadline is not None and time.monotonic() >= queue.stop.deadline else "cancelled"
        finally:
            out["done"] = sum(bool(s.get("story_completed")) for s in out["stories"])
            out["left"] = len(out["remaining"])
            out["hooks"] = queue.data.get("hooks", [])
            queue.finish(out["execution_status"], out, close_only=True)
            out["questions"] = run_completion.deferred_questions(out, out["hooks"])
            try:
                if "worktree" in out:
                    with lease(queue.root):
                        path = run_completion.save_questions(queue.root, target["epic"], queue.id, out["questions"])
                    if path:
                        out["questions_file"] = path
                        out["head_commit"] = revision(queue.root)
                def verify_merge(root, base):
                    current_cfg, _, _ = load(str(root), strict=True)
                    if hashlib.sha256(json.dumps(current_cfg, sort_keys=True).encode()).hexdigest() != config_hash:
                        raise ValueError("configuration changed during integration; refusing modified check commands")
                    import project_tests
                    settings = project_tests.settings(cfg)
                    if settings.get("scopes"):
                        def execute_scope(command, timeout, where, scope):
                            with (nullcontext() if where == root else lease(where)):
                                return cli_waves.tests(queue, "integration-" + scope, current_lease_fd(), where, command, timeout)
                        return project_tests.Runner(root, base, current_cfg, queue.private / "integration-checks", execute_scope).run()
                    return cli_waves.tests(queue, "integration-checks", current_lease_fd())
                run_completion.finalize(source, queue.root, merge_target, out, verify_merge, queue.stop.is_set)
            except (OSError, ValueError, KeyError, TypeError) as error:
                if out.get("error"):
                    out["prior_error"] = out["error"]
                out.update(execution_status="needs_attention", run_completed=False, error=str(error))
                out["merge"] = {"status": "not_merged", "reason": str(error)}
            queue.data.update(status=out["execution_status"], merge=out["merge"], questions=out["questions"])
            queue.finish(out["execution_status"], out)
            out.update(started=queue.data["started"], ended=queue.data["ended"], seconds=queue.data["seconds"])
            atomic_json(queue.private / "result.json", out)
            out["statistics"] = cli_stats.publish(source, queue.session_path)
            try:
                out["token_summary"] = run_completion.token_summary(source, queue.session_path)
            except (OSError, ValueError, KeyError, TypeError) as error:
                out["statistics"]["error"] = str(error)
                out["token_summary"] = []
            try:
                run_completion.publish(queue.private, out, cfg, queue.root)
            except (OSError, ValueError, KeyError, TypeError) as error:
                out["notification_error"] = str(error)
                out["message"] = run_completion.report(out)
                try:
                    (queue.private / "report.md").write_text(out["message"])
                except OSError:
                    pass  # result.json and stderr still carry the delivery error.
            atomic_json(queue.private / "result.json", out)
            if progress:
                progress({"event": "run-finished", "session": str(queue.session_path),
                          "execution_status": out["execution_status"], "merge": out["merge"],
                          "message": out["message"], "report_file": out["report_file"]})
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", nargs="?", default="start", choices=("start", "plan", "status", "cancel", "stop-after"))
    ap.add_argument("--repo", default=".")
    ap.add_argument("--arg", default="")
    ap.add_argument("--manifest")
    ap.add_argument("--session")
    ap.add_argument("--story", help="finish this story, then stop taking work (stop-after)")
    ap.add_argument("--timeout", type=int, help="explicit wall-clock run limit; no implicit run deadline")
    ap.add_argument("--wave-plan", help="JSON wave plan built from the epic and current read-only plan")
    ap.add_argument("--allow-model", action="store_true")
    ap.add_argument("--executor", choices=("codex", "claude"), help="executor for this invocation; never edits project settings")
    a = ap.parse_args(argv)
    if a.executor:
        os.environ[EXECUTOR_ENV] = a.executor
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
        if a.action == "stop-after":
            if not a.session or not a.story:
                raise ValueError("stop-after requires --session and --story")
            out = run_control.request(a.session, a.story)
        elif a.action == "plan":
            out = inspect(a.repo, a.arg)
        else:
            if not a.allow_model:
                raise ValueError("run requires explicit --allow-model")
            if a.timeout is not None and a.timeout <= 0:
                raise ValueError("timeout must be positive")
            wave_plan = json.loads(Path(a.wave_plan).read_text()) if a.wave_plan else None
            out = run(a.repo, a.arg, a.timeout, wave_plan=wave_plan,
                      progress=lambda event: print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as e:
        out = {"execution_status": "failed", "run_completed": False, "error": str(e)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if (a.action in ("plan", "stop-after") and "error" not in out
                 or out.get("run_completed") or out.get("execution_status") == "stopped") else 2


if __name__ == "__main__":
    sys.exit(main())
