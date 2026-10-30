"""Run one prepared BMAD story through a configured CLI controller and its supervised role broker."""

import argparse
import json
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import threading
import fcntl
import time
from types import SimpleNamespace

import agent_adapters
import agent_dispatch
from agent_runtime import atomic_json, execute
from common import ARTIFACTS, SPRINT_REL, frontmatter, git, parse_story, baseline, spec_index, story_commits
from ext import load, hook_timeout
from execution_state import canonical, lease, current_lease_fd, revision, ControllerWatch
from gitexclude import ensure_excluded
from story_broker import Broker
import testrun
import verify
import stub
import cli_stats
import cli_verifier

HERE = Path(__file__).resolve().parent
CONTROLLER_SCHEMA = {"type": "object", "properties": {
    "status": {"type": "string", "enum": ["done", "blocked"]},
    **{key: {"type": "string"} for key in ("report", "spec", "verified_tree", "questions")}},
    "required": ["status", "report", "spec", "verified_tree", "questions"], "additionalProperties": False}


def local_json(script, root, args):
    result = subprocess.run([sys.executable, str(HERE / script), *args, "--repo", str(root)],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError(result.stdout.strip() or result.stderr.strip())
    return json.loads(result.stdout)


def tests(root, command, timeout, broker, rerun=False):
    return broker.tests(command, timeout)


def clean(root):
    result = git(str(root), "status", "--porcelain")
    if result.returncode:
        raise ValueError("cannot verify the worktree state")
    return not result.stdout.strip()


def tests_idle(root):
    path = Path(testrun.state(str(root), "lock"))
    if not path.exists():
        return True
    with path.open("r") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(lock, fcntl.LOCK_UN)
        return True


def controller_prompt(broker, target, spec):
    commands = {action: shlex.join([sys.executable, str(HERE / "agent_dispatch.py"), action,
                "--manifest", str(broker.manifest_path), "--session", str(broker.session_path)])
                for action in ("execute", "execute-batch", "checkpoint", "commit", "rollback")}
    entry = str(spec) if spec else f"Story {target['epic']}.{target['story']} from epic {target['epic']}: {target['stories'][0]['title']}"
    return """You are the BMAD story controller. Read the prepared workflow and execute its complete native lifecycle.
Do not invoke Claude Skill/Agent tools or native subagents. The CLI broker replaces only delegation and Git transport.
Never merge, push, switch branches, stage, commit or reset through shell tools. The broker owns Git writes.
Preserve the project's activation steps/on_complete, spec gates, AC, triage, verification and fix/loopback policies.
Do not update sprint-status.yaml or open-questions tracking: the outer run owns tracking.
Engine entry is the exact intent or sole existing spec path below. Never replace an existing spec path with a new intent.
The host has already checked Git metadata writability with git add --refresh; do not repeat Git writes in the sandbox.
Keep baseline_revision equal to review_base_commit for every pass and repair, including the step-03 Baseline action.
This pinned baseline covers the whole story even when earlier passes or check-task commits advanced HEAD.
Every delegated task uses a JSON request file with role, task_id, base_commit (CURRENT full HEAD), prompt (original handoff).
For EVERY role, including compiler-lite and all review layers, task_id MUST equal the exact story field below.
Do not invent per-role task IDs or append labels to it. The broker assigns unique attempt IDs itself.
For reviewer requests add layer_id and diff_file (the absolute path named in the original layer prompt). The broker
binds that path to an authoritative diff against review_base_commit below, including new files. Preserve each layer's
claims/context restrictions and pass its original payload unchanged. Use execute-batch for all active review layers
in one request array, launch them together, and read their results only after the batch returns. Unknown layer IDs
use reviewer on deep, reviewer-lite for intent-alignment, otherwise reviewer-mid. Other roles use execute.
Commands are listed below; add --request <absolute JSON file> for execute/execute-batch/commit/rollback. Checkpoint needs no file.
Stay in the foreground and wait for each command to finish. If the command tool yields a handle, join that handle;
do not write files, launch another job or continue the workflow while a handoff is active. The broker transfers the
writer lease from controller to implementer and back. Failed/missing/blocked handoffs must HALT blocked, not fallback.
All tests, full or partial, MUST go through auto-bmad test --session SESSION_PATH --repo WORKTREE, optionally --command.
All stubs MUST use --run SESSION_ID. Complete verification after code patches. Do not leave test commands running.
On engine Finalize: write the complete spec status done, Auto Run Result, triage log and followup flag, then call
checkpoint after final verification and refresh the final diff file as the native workflow directs. Keep that code_tree.
Use broker commit with {"message":"<engine commit message>"}; it stages the reviewed changes and spec in this branch.
No other Git-write path is permitted. Return the schema JSON: status, report, spec absolute path, verified_tree
(the checkpoint's code_tree), questions (concrete residual risks/decisions, empty if none). HALT blocked on ambiguity.
This controller does not implement the story itself around BMAD; leaf implementation and review use the broker.
For intent_gap/bad_spec rollback, save the native KEEP/spec/triage notes and call rollback with {"reason":"intent_gap"}
or {"reason":"bad_spec"}. It backs up the owned code diff before restoring code and never removes the spec.
Native implementation-session re-engagement is not supported by this bridge yet. Follow the native fallback:
apply only its permitted trivial patches in the controller, record that fallback, then repeat verification and refresh diff.
Never describe a fresh implementer session as re-engagement. Other implementation work uses its delegated role.
""" + json.dumps({"workflow": broker.manifest["workflow"], "entry": entry, "story": broker.story,
                    "review_base_commit": broker.base, "pass": broker.passno, "level": broker.manifest["level"],
                    "active_review_layers": broker.manifest["review_layers"], "bridge_commands": commands,
                    "SESSION_PATH": str(broker.session_path), "SESSION_ID": broker.id, "WORKTREE": str(broker.root)},
                   ensure_ascii=False, indent=2)


def invoke(broker, target, spec, detection):
    broker.passno += 1
    broker.round = 0
    broker.stop.controller_done.clear()
    (broker.private / "tests-closed").unlink(missing_ok=True)
    broker.require_implementer = spec is None or frontmatter(spec)[0].get("status") not in ("done", "in-review")
    profile = broker.manifest["roles"]["story-runner"]
    attempt = broker.private / f"controller-{broker.passno}"
    schema = broker.private / "controller-schema.json"
    atomic_json(schema, CONTROLLER_SCHEMA)
    result = {}

    def run():
        try:
            parser = agent_adapters.result_parser(profile)
            result.update(execute(agent_adapters.argv(profile, detection, str(broker.root), schema,
                                  broker.private / f"controller-{broker.passno}.answer.json"),
                                  cwd=str(broker.root), env=broker.environment(profile["environment_allowlist"]),
                                  stdin=controller_prompt(broker, target, spec), directory=attempt,
                                  timeout=profile["timeout"], consume=parser.consume, finish=parser.finish,
                                  cancel=broker.stop, lease_fd=broker.lease_fd, cleanup_session=broker.session_path,
                                  snapshot=parser.snapshot,
                                  metadata={"role": "story-runner", "adapter": profile["adapter"],
                                            "model_requested": profile["model"], "profile_id": profile["profile_id"]}))
        except BaseException as e:
            result.update(execution_status="failed", error=str(e))
        finally:
            broker.stop.controller_done.set()

    worker = threading.Thread(target=run)
    worker.start()
    try:
        while worker.is_alive():
            broker.serve()
            worker.join(0.05)
    finally:
        if worker.is_alive():
            broker.stop.event.set()
            worker.join()
    if any(not (broker.private / "outbox" / p.name).exists() for p in (broker.state / "inbox").glob("*.json")):
        raise ValueError("controller exited with an unfinished handoff")
    atomic_json(broker.private / f"controller-{broker.passno}.result.json", result)
    if result.get("execution_status") != "completed":
        raise ValueError(f"controller {result.get('execution_status')}; inspect {attempt}")
    answer = result.get("result")
    if (not isinstance(answer, dict) or set(answer) != set(CONTROLLER_SCHEMA["required"]) or
            any(not isinstance(v, str) for v in answer.values()) or answer["status"] not in ("done", "blocked")):
        raise ValueError("invalid controller result")
    if answer["status"] != "done":
        raise ValueError("engine blocked: " + answer["report"])
    return answer


def validate_story(broker, answer, branch, sprint_before):
    path = broker.spec()
    if Path(answer["spec"]).resolve() != path.resolve():
        raise ValueError("controller reported another spec")
    fields, lists = frontmatter(path)
    if fields.get("status") != "done" or baseline(fields) != broker.base:
        raise ValueError("spec is not done or has a different review baseline")
    text = path.read_text()
    if any(section not in text for section in ("## Tasks & Acceptance", "## Verification", "## Review Triage Log", "## Spec Change Log", "## Auto Run Result")):
        raise ValueError("native BMAD result artifacts are incomplete")
    if not broker.commits or broker.commits[-1]["pass"] != broker.passno or revision(broker.root) != broker.commits[-1]["head_commit"]:
        raise ValueError("engine did not finalize through its broker commit")
    if answer["verified_tree"] != broker.commits[-1]["code_tree"] or broker.tree() != answer["verified_tree"]:
        raise ValueError("code changed since final verification")
    if any(r["result"].get("execution_status") != "completed" or r["result"].get("result", {}).get("status") != "done"
           for r in broker.records if r["pass"] == broker.passno):
        raise ValueError("a delegated role did not complete")
    if git(str(broker.root), "symbolic-ref", "--quiet", "HEAD").stdout.strip() != branch:
        raise ValueError("controller switched branches")
    if git(str(broker.root), "merge-base", "--is-ancestor", broker.base, "HEAD").returncode:
        raise ValueError("controller rewrote the baseline")
    if not clean(broker.root):
        raise ValueError("engine left uncommitted changes")
    if (broker.root / SPRINT_REL).read_bytes() != sprint_before:
        raise ValueError("engine changed sprint tracking before finishing")
    if (lists.get("deferred", 0) or fields.get("followup_review_recommended") == "true") and not answer["questions"].strip():
        raise ValueError("residual risks require concrete questions in the controller result")
    return path, fields


def cleanup(broker):
    problems = cli_verifier.cleanup(broker)
    directory = Path(testrun.state(str(broker.root)))
    until = time.monotonic() + 3
    while directory.exists() and time.monotonic() < until:
        live = testrun.live_runs(str(broker.root))
        if not any(r.get("session") == str(broker.session_path) for r in live.values()) and tests_idle(broker.root):
            break
        time.sleep(0.1)
    if directory.exists() and (testrun.live_runs(str(broker.root)) or not tests_idle(broker.root)):
        problems.append("test workers remain; inspect the preserved worktree")
    for item in stub.listing(str(broker.root))[0]["stubs"]:
        if item.get("tree") == str(broker.root) and item.get("run") == broker.id:
            result, code = stub.stop(str(broker.root), item["name"])
            if code:
                problems.append(result)
    return problems


def run_story(manifest_path, arg, timeout=None):
    manifest = json.loads(Path(manifest_path).read_text())
    root, _ = canonical(manifest["repo"])
    with lease(root):
        _, plan = agent_dispatch.validate_manifest(manifest)
        target = local_json("plan_run.py", root, ["--arg", arg])
        if target["mode"] != "story" or target["count"] != 1 or target["level"] != manifest["level"]:
            raise ValueError("run accepts one story at the prepared level; epic/waves are not enabled")
        if not manifest.get("review_layers") or manifest.get("review_conditions"):
            raise ValueError("no active BMAD review layers in this prepared engine")
        if not clean(root):
            raise ValueError("run requires a clean worktree; existing changes are preserved")
        ensure_excluded(str(root), ".auto-bmad/")
        test_state = Path(testrun.state(str(root)))
        if test_state.exists() and (testrun.live_runs(str(root)) or not tests_idle(root)):
            raise ValueError("tests are already running in this worktree")
        story = f"{target['epic']}-{target['story']}"
        broker = Broker(root, manifest_path, story, revision(root), current_lease_fd())
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        for sig in previous:
            signal.signal(sig, lambda *_: broker.stop.event.set())
        result = {"execution_status": "failed", "story_completed": False, "story": story,
                  "session": str(broker.session_path), "worktree": str(root), "merge_policy": "manual"}
        try:
            cfg, _, _ = load(str(root), strict=True)
            profile = plan["roles"]["story-runner"]
            broker.stop.deadline = time.monotonic() + (timeout or profile["timeout"])
            needed = {"story-runner", "implementer"}
            if manifest["level"] != "deep":
                needed.add("compiler-lite")
            if cfg.get("run", {}).get("triage_subagent"):
                needed.add("triager")
            if any(v.get("kind", "agent") == "agent" for v in cfg.get("verify", [])):
                needed.add("verifier")
            needed.update("reviewer" if manifest["level"] == "deep" else
                          "reviewer-lite" if layer == "intent-alignment" else "reviewer-mid" for layer in manifest["review_layers"])
            detections = {}
            for role in needed:
                if broker.stop.is_set():
                    raise ValueError("run cancelled during preflight")
                profile = plan["roles"][role]
                if role in agent_dispatch.REVIEWERS and profile["permissions"] != "read-only":
                    raise ValueError("reviewer profiles must be read-only")
                detected = agent_adapters.detect(profile, timeout=min(10, max(0.001, broker.stop.deadline - time.monotonic())))
                agent_adapters.validate(profile, detected)
                detections[role] = detected
            profile = plan["roles"]["story-runner"]
            if profile["permissions"] != "workspace-write":
                raise ValueError("story controller needs workspace-write permissions for its spec")
            branch = git(str(root), "symbolic-ref", "--quiet", "HEAD").stdout.strip()
            if not branch:
                raise ValueError("story execution requires its own branch")
            sprint_before = (root / SPRINT_REL).read_bytes()
            initial_base = revision(root)
            broker.command(["git", "add", "--refresh", "--", "."], "metadata-check")
            if not clean(root):
                raise ValueError("Git metadata check changed the worktree")
            index = spec_index(str(root))
            existing = index.get(parse_story(story), [])
            if len(existing) > 1:
                raise ValueError("ambiguous existing spec")
            spec = Path(existing[0]) if existing else None
            if spec:
                fields, _ = frontmatter(spec)
                if fields.get("status") == "blocked":
                    raise ValueError("existing spec is blocked; resolve its questions before resuming")
                broker.base = baseline(fields) or initial_base
                own = story_commits(str(spec), str(root), fields)
                if own.get("later"):
                    raise ValueError("other code commits follow this story; exact-base review would include unrelated work")
                if own.get("first"):
                    paths = git(str(root), "diff", "--name-only", "-z", broker.base, initial_base)
                    if paths.returncode:
                        raise ValueError("cannot inspect existing story ownership")
                    broker.initial_owned_paths = set(filter(None, paths.stdout.split("\0")))
            command, test_timeout = verify.command_check(str(root), "project-tests")
            before = tests(root, command, test_timeout, broker, rerun="red") if command and manifest["level"] != "fast" else None
            broker.baseline_test_verdict = before["verdict"] if before else None
            atomic_json(broker.private / "baseline-test.json", before)
            if not clean(root):
                raise ValueError("baseline tests changed the worktree")
            fix_limit = cfg.get("verify_limits", {}).get(manifest["level"], 0)
            checks, scenario = None, None
            outcomes, details, previous_problems = {}, {}, {}
            external_skips = []
            for fix in range(fix_limit + 1):
                for _ in range({"fast": 1, "normal": 2, "deep": 3}[manifest["level"]]):
                    answer = invoke(broker, target, spec, detections["story-runner"])
                    spec, fields = validate_story(broker, answer, branch, sprint_before)
                    if fields.get("followup_review_recommended") != "true":
                        break
                if checks is None:
                    checks = json.loads(broker.command([sys.executable, str(HERE / "verify.py"), "plan",
                             "--repo", str(root), "--story", story, "--title", target["stories"][0]["title"],
                             "--base", initial_base, "--commit", revision(root), "--level", manifest["level"]],
                             "verify-plan", codes=(0, 2)))
                    scenario = dict(answer)
                problems = []
                for item in checks["verifiers"]:
                    name = item["name"]
                    if fix and outcomes.get(name) != "problem" and name != "project-tests":
                        continue
                    if item["kind"] == "agent":
                        verdict = cli_verifier.run(broker, item, target, scenario, broker.base,
                                                   fix + 1, previous_problems.get(name, []))
                    elif item["kind"] == "command":
                        cmd, seconds = verify.command_check(str(root), name)
                        verdict = tests(root, cmd, seconds, broker) if cmd else {"verdict": "skipped", "reason": "no configured command"}
                    else:
                        raise ValueError(f"unsupported verification kind: {item['kind']}")
                    if item["name"] == "project-tests" and verdict["verdict"] == "problem" and before and before["verdict"] == "problem":
                        verdict["verdict"] = "skipped"
                        external_skips.append({"name": item["name"], "reason": "the configured command also failed on the fresh pre-story baseline"})
                    outcomes[name], details[name] = verdict["verdict"], verdict
                    previous_problems[name] = verdict.get("problems") or [verdict.get("tail", "")]
                    if verdict["verdict"] == "problem" and item["on_fail"] == "fix":
                        problems.extend(f"{name}: {p}" for p in previous_problems[name])
                if not problems:
                    notes = [f"{name}: " + "; ".join(detail.get("problems") or [detail.get("tail", "")])
                             for name, detail in details.items() if detail["verdict"] == "problem"]
                    notes += [f"{name}: skipped — {detail['reason']}" for name, detail in details.items()
                              if detail["verdict"] == "skipped" and detail.get("reason")]
                    if notes:
                        answer["questions"] = "\n\n".join(filter(None, [answer["questions"], *notes]))
                    if not clean(root) or broker.tree() != answer["verified_tree"]:
                        raise ValueError("post-story checks changed the verified worktree")
                    break
                if fix == fix_limit:
                    raise ValueError("post-story verification fix limit exhausted")
                problems_file = broker.private / f"fix-{fix + 1}.md"
                problems_file.write_text("\n".join(problems))
                data, code = verify.cmd_fix_spec(SimpleNamespace(spec=str(spec), passno=fix + 1,
                              problems_file=str(problems_file), commit_story=None), str(root))
                if code:
                    raise ValueError(data.get("error", "cannot prepare check fixes"))
                broker.command(["git", "add", "--", ":(literal)" + str(spec.relative_to(root))], "fix-spec-stage")
                broker.command(["git", "commit", "-m", f"spec: check fixes for story {story}, attempt {fix + 1}"], "fix-spec-commit")
            if broker.stop.is_set():
                raise ValueError("run cancelled")
            agent_dispatch.validate_manifest(manifest)
            finish_path = broker.private / "finish.json"
            verification = {"status": "problem" if "problem" in outcomes.values() else "pass" if "pass" in outcomes.values() else "skipped",
                            "fixes": fix, "checks": outcomes, "details": details}
            atomic_json(finish_path, {"epic": target["epic"], "level": manifest["level"], "stub_run": broker.id, "stories": [{
                "story": story, "title": target["stories"][0]["title"], "spec": str(spec), "commit": revision(root),
                "status": "done", "questions": answer["questions"],
                "verify": verification}]})
            finish = json.loads(broker.command([sys.executable, str(HERE / "story_finish.py"), "--repo", str(root),
                                               "--input", str(finish_path)], "finish", codes=(0, 2),
                                               timeout=hook_timeout(cfg, ("verify-done", "story-done"))))
            if not finish["ok"]:
                raise ValueError("tracking finalization failed; inspect run artifacts")
            if not clean(root) or broker.tree() != answer["verified_tree"]:
                result["execution_status"] = "needs_attention"
                raise ValueError("finishing changed the verified code tree; inspect hook output before continuing")
            result.update(execution_status="completed", story_completed=True, spec=str(spec),
                          head_commit=revision(root), base_commit=initial_base, report=answer["report"],
                          questions=answer["questions"], skipped_checks=checks["skipped"] + external_skips,
                          verification=verification, finish=finish)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as e:
            result["error"] = str(e)
            if broker.stop.is_set():
                result["execution_status"] = "timed_out" if broker.stop.deadline and time.monotonic() >= broker.stop.deadline else "cancelled"
        finally:
            broker.close("stopping")
            try:
                remaining = cleanup(broker)
                if remaining:
                    result.update(execution_status="needs_attention", story_completed=False, cleanup=remaining)
            except (OSError, ValueError, stub.Unknown) as e:
                result.update(execution_status="needs_attention", story_completed=False, cleanup=str(e))
            broker.close(result["execution_status"])
            atomic_json(broker.private / "result.json", result)
            result["statistics"] = cli_stats.publish(root, broker.session_path)
            atomic_json(broker.private / "result.json", result)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", nargs="?", default="start", choices=("start", "status", "cancel"))
    ap.add_argument("--manifest")
    ap.add_argument("--arg")
    ap.add_argument("--session")
    ap.add_argument("--timeout", type=int)
    ap.add_argument("--allow-model", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.action in ("status", "cancel"):
            if not args.session:
                raise ValueError("status/cancel require --session")
            path = Path(args.session).resolve(strict=True)
            session = json.loads(path.read_text())
            _, common = canonical(session["repo"])
            if not path.is_relative_to(common / "auto-bmad-sessions") or path.name != "session.json":
                raise ValueError("invalid controller session")
            if args.action == "cancel":
                (path.parent / "cancel").touch(exist_ok=True)
            out = session
            out["active"] = ControllerWatch(session["repo"], path).alive()
            if session["status"] == "running" and not out["active"]:
                out["status"] = "cancelling" if (path.parent / "cancel").exists() else "interrupted"
        else:
            if not args.allow_model:
                raise ValueError("story execution requires explicit --allow-model")
            if not args.manifest or not args.arg or (args.timeout is not None and args.timeout <= 0):
                raise ValueError("run requires --manifest, --arg and a positive optional timeout")
            out = run_story(args.manifest, args.arg, args.timeout)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as e:
        out = {"execution_status": "failed", "error": str(e), "story_completed": False}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if (args.action != "start" and "error" not in out) or out.get("story_completed") else 2


if __name__ == "__main__":
    sys.exit(main())
