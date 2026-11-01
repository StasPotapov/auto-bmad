"""Validated host-planned waves, isolated CLI workers and ordered integration."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import hashlib
import re
from pathlib import Path
import sys
import time

from agent_runtime import atomic_json
from agent_runtime import execute
from common import git
from execution_state import revision, resource_lock, lease, current_lease_fd
from ext import hook_timeout
import engine
import run_story
import verify
import worktree
import fcntl
import project_tests

HERE = Path(__file__).resolve().parent


def required(target):
    return target["mode"] == "epic" and target["parallel"] != "off" and target["count"] > 1 and target["parallel_width"] > 1


def validate(plan, target, base):
    ids = [s["id"] for s in target["stories"]]
    if plan is None:
        if required(target):
            raise ValueError("parallel epic requires --wave-plan: read the epic and split independent stories into ordered waves")
        return [{"stories": [s], "reason": "sequential"} for s in ids]
    if not isinstance(plan, dict) or plan.get("base_commit") != base:
        raise ValueError("wave plan must match the current exact source HEAD")
    if plan.get("parallel") != target["parallel"] or plan.get("width") != target["parallel_width"]:
        raise ValueError("wave plan mode/width differ from the resolved shared run settings")
    waves = plan.get("waves")
    width = target["parallel_width"] if target["parallel"] != "off" else 1
    if not isinstance(waves, list) or not waves:
        raise ValueError("wave plan requires nonempty waves")
    for wave in waves:
        if (not isinstance(wave, dict) or set(wave) != {"stories", "reason"}
                or not isinstance(wave["stories"], list) or not 1 <= len(wave["stories"]) <= width
                or not all(isinstance(s, str) for s in wave["stories"])
                or not isinstance(wave["reason"], str) or not wave["reason"].strip()):
            raise ValueError("each wave requires story IDs within the configured width and a reason")
    if [s for w in waves for s in w["stories"]] != ids:
        raise ValueError("waves must partition the exact story queue in order, without omissions or duplicates")
    return waves


def tests(queue, name, parent_fd, root=None, command=None, timeout=None):
    root = Path(root or queue.root)
    if command is None:
        command, timeout = verify.command_check(str(root), "project-tests")
    if not command:
        return {"verdict": "skipped", "reason": "no configured project test command"}
    seconds = max(1, min(timeout, int(queue.stop.deadline - time.monotonic()))) if queue.stop.deadline is not None else timeout
    folder = root / ".auto-bmad/tests"
    folder.mkdir(parents=True, exist_ok=True)
    with resource_lock(root, queue.stop) as resource_fd, (folder / "lock").open("a") as lock:
        while True:
            if queue.stop.is_set():
                raise ValueError("run cancelled while waiting for wave tests")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.05)
        directory = queue.private / (name + "-" + str(time.time_ns()))
        result = execute(["sh", "-c", command], cwd=str(root), env=queue.env, stdin="",
                         directory=directory, timeout=seconds, structured=False, consume=lambda _: None,
                         finish=lambda code: {"execution_status": "completed" if code == 0 else "failed"},
                         cancel=queue.stop, manage_signals=False, lease_fd=parent_fd,
                         lease_fds=(queue.source_fd, resource_fd, lock.fileno()) + (() if current_lease_fd() is None else (current_lease_fd(),)))
        if result["execution_status"] not in ("completed", "failed") or result.get("error"):
            raise ValueError(f"wave tests {result['execution_status']}; inspect {directory}")
        output = (directory / "stdout.jsonl").read_text(errors="replace") + (directory / "stderr.log").read_text(errors="replace")
        return {"verdict": "pass" if result["execution_status"] == "completed" else "problem",
                "code": result["exit_code"], "command": command, "seconds": result["seconds"],
                "tail": "\n".join(output.splitlines()[-60:]), "log": str(directory)}


def merge(queue, result):
    head, tip = revision(queue.root), result["head_commit"]
    if revision(result["worktree"]) != tip or not run_story.clean(result["worktree"]):
        raise ValueError("story worktree changed after verification; preserved without merging")
    if git(str(queue.root), "merge-base", "--is-ancestor", result["base_commit"], tip).returncode:
        raise ValueError("story result no longer descends from its wave base")
    proc = git(str(queue.root), "merge-tree", "--write-tree", "--name-only", "--no-messages", head, tip)
    lines = proc.stdout.splitlines()
    if proc.returncode or not lines:
        result["conflicts"] = lines[1:]
        raise ValueError(f"merge conflict for story {result['story']}; its worktree and branch are preserved")
    commit = git(str(queue.root), "commit-tree", lines[0].strip(), "-p", head, "-p", tip,
                 "-m", f"merge: story {result['story']} — auto-bmad wave")
    if commit.returncode:
        raise ValueError(commit.stderr.strip() or "cannot create wave merge commit")
    sha = commit.stdout.strip()
    proc = git(str(queue.root), "merge", "--ff-only", "-q", sha)
    if proc.returncode:
        raise ValueError(proc.stderr.strip() or "cannot advance the isolated run branch")
    result.update(merged=True, merge_commit=sha)


def failure_signature(result):
    lines = []
    for line in result.get("tail", "").splitlines():
        if re.search(r"\b\d+ (?:failed|passed|skipped|errors?|warnings?)\b", line):
            line = re.sub(r"\bin \d+(?:\.\d+)?s\b", "in <duration>s", line)
        line = re.sub(r"^(Ran \d+ tests? in )\d+(?:\.\d+)?s$", r"\1<duration>s", line)
        lines.append(line)
    return result.get("command"), result.get("code"), "\n".join(lines)


def finish_timeout(cfg, count):
    return hook_timeout(cfg, ("verify-done", "story-done") * count + ("wave-merged",))


def record_blocked(queue, jobs, target, number):
    rows = [row for row, _ in jobs if row.get("execution_status") == "blocked" and row.get("blocked_finish_input")]
    if not rows:
        return
    cfg, _, _ = run_story.load(str(queue.root), strict=True)
    if queue.config_hash != hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest():
        raise ValueError("configuration changed; refusing to execute modified blocked-story hooks")
    tree = queue.command("testrun.py", ["--repo", str(queue.root), "--tree"], "blocked-tree")["tree"]
    payload = {"epic": target["epic"], "level": target["level"], "stories": []}
    for row in rows:
        child = json.loads(Path(row["blocked_finish_input"]).read_text())["stories"][0]
        # A failed branch is preserved, not merged; its spec is not present in the shared artifacts folder.
        payload["stories"].append({**child, "spec": ""})
    path = queue.private / f"wave-{number}-blocked.json"
    atomic_json(path, payload)
    finished = queue.command("story_finish.py", ["--repo", str(queue.root), "--input", str(path)],
        "wave-blocked", codes=(0, 2), timeout=hook_timeout(cfg, ("story-blocked",) * len(rows)))
    after = queue.command("testrun.py", ["--repo", str(queue.root), "--tree"], "blocked-final-tree")["tree"]
    if (not finished["ok"] or not tree or tree != after or not run_story.clean(queue.root) or
            any("no auto-bmad marker" in w for w in finished.get("warnings", []))):
        raise ValueError("blocked-story questions finalization failed; inspect the preserved run")
    for row in rows:
        row.update(finalization_pending=False, finish=finished,
                   questions_file=str(queue.root / run_story.questions_file(target["epic"])))
        saved = Path(row["session"]).parent / "result.json"
        child = json.loads(saved.read_text())
        child.update(finalization_pending=False, finish=finished, questions_file=row["questions_file"])
        atomic_json(saved, child)


def run(queue, wave, number, target, out, parent_fd):
    for story in wave["stories"]:
        queue.event("story-start", story, owned=True)
    if not run_story.clean(queue.root):
        raise ValueError("story-start hooks left uncommitted changes before the wave")
    base = revision(queue.root)
    scope_cfg, _, _ = run_story.load(str(queue.root), strict=True)
    scoped = project_tests.enabled(scope_cfg)
    before = queue.command("testrun.py", ["--repo", str(queue.root), "--tree"], "wave-tree")["tree"]
    baseline = {"verdict": "skipped"} if scoped else tests(queue, "wave-baseline", parent_fd)
    if not run_story.clean(queue.root) or before != queue.command(
            "testrun.py", ["--repo", str(queue.root), "--tree"], "wave-baseline-tree")["tree"]:
        raise ValueError("wave baseline changed the worktree")
    jobs = []
    for story in wave["stories"]:
        if queue.stop.is_set():
            raise ValueError("run cancelled before launching the wave")
        made = worktree.create_cli(str(queue.root), story)
        row = {"story": story, "worktree": made["path"], "branch": made["branch"],
               "wave": number, "story_completed": False, "execution_status": "starting"}
        out["stories"].append(row)
        queue.data["stories"] = out["stories"]
        queue.save()
        if made.get("error"):
            raise ValueError(made["error"])
        package = queue.private / f"wave-{number}-{story}"
        engine.prepare(made["path"], package, target["level"])
        jobs.append((row, package / "manifest.json"))
    queue.data.update(active_story=None, active_stories=wave["stories"])
    queue.save()

    def worker(row, manifest):
        seconds = max(1, int(queue.stop.deadline - time.monotonic())) if queue.stop.deadline is not None else None
        deadline_args = ["--timeout", str(seconds)] if seconds is not None else []
        try:
            return queue.execute([sys.executable, str(HERE / "run_story.py"), "--manifest", str(manifest),
                                  "--arg", f"{row['story']} --{target['level']}", "--allow-model",
                                  "--defer-finish", *deadline_args],
                                 "wave-story-" + row["story"], codes=(0, 2), timeout=seconds + 5 if seconds is not None else None,
                                 cwd=row["worktree"], parent_fd=parent_fd,
                                 env={**queue.env, "AUTO_BMAD_WAVE": str(number)})
        except (OSError, ValueError, RuntimeError) as e:
            return {"execution_status": "failed", "story_completed": False, "error": str(e)}

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(worker, row, manifest): row for row, manifest in jobs}
        for future in as_completed(futures):
            row = futures[future]
            result = future.result()
            row.update(result)
            row["isolated_completed"] = row.pop("story_completed", False)
            row["story_completed"] = False
            queue.data["active_stories"] = [s for s in queue.data["active_stories"] if s != row["story"]]
            queue.save()
    if queue.stop.is_set():
        raise ValueError("run cancelled; all wave worktrees are preserved")
    if revision(queue.root) != base or not run_story.clean(queue.root):
        raise ValueError("run worktree changed during the wave; results are preserved without merging")
    record_blocked(queue, jobs, target, number)
    # Merge only verified successes, in queue order; one blocked story does not lose its siblings.
    merged = []
    errors = []
    for row, _ in jobs:
        if not row.get("isolated_completed"):
            errors.append(row.get("error", f"story {row['story']} did not complete"))
            continue
        try:
            merge(queue, row)
            merged.append(row)
        except ValueError as e:
            row.update(execution_status="needs_attention", error=str(e))
            errors.append(str(e))
    if merged:
        if scoped:
            def execute_scope(command, timeout, where, scope):
                from contextlib import nullcontext
                with (nullcontext() if where == queue.root else lease(where)):
                    return tests(queue, "wave-scope-" + scope, parent_fd, where, command, timeout)
            checked = project_tests.Runner(queue.root, base, scope_cfg, queue.private / f"wave-{number}-checks", execute_scope).run()
        else:
            checked = tests(queue, "wave-tests", parent_fd)
        wave["verification"] = checked
        same_failure = (baseline.get("verdict") == checked.get("verdict") == "problem"
                        and failure_signature(baseline) == failure_signature(checked))
        if same_failure:
            wave["verification"] = {**checked, "verdict": "skipped", "reason": "same failure on the pre-wave baseline"}
        if checked.get("verdict") == "problem" and not same_failure:
            raise ValueError("project tests failed after the wave merge; preserved for inspection")
        if checked.get("verdict") not in ("pass", "skipped") and not same_failure:
            raise ValueError("wave verification did not finish")
        tree = queue.command("testrun.py", ["--repo", str(queue.root), "--tree"], "wave-verified-tree")["tree"]
        if not tree or not run_story.clean(queue.root):
            raise ValueError("wave checks changed the worktree")
        cfg, _, _ = run_story.load(str(queue.root), strict=True)
        if queue.config_hash != hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest():
            raise ValueError("configuration changed; refusing to execute modified finishing hooks")
        payload = {"epic": target["epic"], "level": target["level"], "wave": number, "stories": []}
        for row in merged:
            child = json.loads(Path(row["finish_input"]).read_text())["stories"][0]
            child.update(spec=str(queue.root / Path(row["spec"]).relative_to(row["worktree"])), commit=row["merge_commit"])
            payload["stories"].append(child)
        path = queue.private / f"wave-{number}-finish.json"
        atomic_json(path, payload)
        finished = queue.command("story_finish.py", ["--repo", str(queue.root), "--input", str(path)],
                                 "wave-finish", codes=(0, 2), timeout=finish_timeout(cfg, len(merged)))
        wave["finish"] = finished
        if not finished["ok"] or not run_story.clean(queue.root):
            raise ValueError("wave tracking finalization failed; inspect the preserved run")
        after = queue.command("testrun.py", ["--repo", str(queue.root), "--tree"], "wave-final-tree")["tree"]
        if tree != after:
            raise ValueError("wave finishing hooks changed the verified code tree")
        for row in merged:
            row.update(story_completed=True, finalization_pending=False)
            saved = Path(row["session"]).parent / "result.json"
            child = json.loads(saved.read_text())
            child.update(finalization_pending=False, integrated_commit=row["merge_commit"])
            atomic_json(saved, child)
            out["remaining"].remove(row["story"])
    wave["completed"] = not errors and bool(merged)
    queue.save()
    if errors:
        out.update(execution_status="needs_attention", error="; ".join(errors))
