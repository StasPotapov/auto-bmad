import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import shlex
import sys
import time
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import engine
import run_queue
import test_run_story
from execution_state import lease
import worktree
import setup
import run_control
from types import SimpleNamespace


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_run_story.StoryTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.root
        config = self.source / ".auto-bmad.toml"
        config.write_text(config.read_text() + '\n[run]\nparallel="off"\n')
        sprint = self.source / "_bmad-output/implementation-artifacts/sprint-status.yaml"
        sprint.write_text(sprint.read_text() + "  1-4-later: backlog\n")
        self.fixture.fixture.git(self.source, "add", "-A")
        self.fixture.fixture.git(self.source, "commit", "-qm", "queue fixture")
        self.base = self.fixture.fixture.git(self.source, "rev-parse", "HEAD").stdout.strip()
        self.original_prepare = engine.prepare

        def prepare(root, output, level):
            saved = self.fixture.fixture.fixture.root
            self.fixture.fixture.fixture.root = Path(root)

            def render(*args, **kwargs):
                self.fixture.fixture.fixture.render(*args, **kwargs)
                path = Path(root) / "_bmad/render/test/manifest.json"
                data = json.loads(path.read_text())
                data["inputs"]["resolved_values"]["customization.workflow.review_layers"] = [
                    {"id": name, "instruction": "review"} for name in self.fixture.layers]
                path.write_text(json.dumps(data))
                return {"execution_status": "completed"}

            try:
                with patch.object(engine.shutil, "which", return_value="/test/uv"), patch.object(engine, "execute", side_effect=render):
                    return self.original_prepare(root, output, level)
            finally:
                self.fixture.fixture.fixture.root = saved

        self.prepared = patch.object(run_queue.engine, "prepare", side_effect=prepare)
        self.prepared.start()
        self.addCleanup(self.prepared.stop)
        self.addCleanup(self.drain)

    def drain(self):
        for item in worktree.worktree_items(str(self.source)):
            until = time.monotonic() + 8
            while True:
                try:
                    with lease(item["path"]):
                        break
                except ValueError:
                    if time.monotonic() >= until:
                        self.fail("a test run still owns its worktree after cleanup")
                    time.sleep(0.05)

    def test_epic_runs_in_order_and_keeps_source_unchanged(self):
        result = run_queue.run(self.source, "epic-1", timeout=65)
        self.assertTrue(result["run_completed"], result)
        self.assertEqual([s["story"] for s in result["stories"]], ["1-3", "1-4"])
        self.assertEqual(result["done"], 2)
        self.assertEqual(result["left"], 0)
        self.assertTrue(result["branch"].startswith("codex/auto-bmad/epic-1-"))
        self.assertEqual(self.fixture.fixture.git(self.source, "rev-parse", "HEAD").stdout.strip(), self.base)
        self.assertEqual(self.fixture.fixture.git(self.source, "status", "--porcelain").stdout, "")
        text = (Path(result["worktree"]) / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text()
        self.assertIn("1-3-fixture: done", text)
        self.assertIn("1-4-later: done", text)
        self.assertIn("epic-1: done", text)
        self.assertTrue((Path(result["worktree"]) / "later.py").exists())
        self.assertEqual([h["event"] for h in result["hooks"]], ["run-start", "story-start", "story-start", "run-end"])
        import stats
        rows = [r for r in stats.load(str(self.source)) if r.get("source") == "cli"]
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["queue_id"] for r in rows}, {Path(result["session"]).parent.name})
        self.assertTrue(all(r["tokens"]["total"]["usage_complete"] == len(r["calls"]) for r in rows))
        for row in rows:
            self.assertEqual(row["tokens"]["total"]["input_exact"], 100 * len(row["calls"]))
            self.assertEqual(row["tokens"]["total"]["in"], 40 * len(row["calls"]))

    def test_auto_main_lands_completed_epic_with_deferred_editorial_questions(self):
        path = self.source / '.auto-bmad.toml'
        path.write_text(path.read_text().replace('[execution]\n', '[execution]\nmerge_policy="auto-main"\n'))
        self.commit()
        main = self.fixture.main
        branch = self.fixture.fixture.git(main, 'branch', '--show-current').stdout.strip()
        if branch != 'main':
            self.fixture.fixture.git(main, 'branch', '-m', 'main')
        progress = []
        with patch.dict(os.environ, {'FAKE_STORY_MODE': 'editorial-question'}):
            result = run_queue.run(self.source, 'epic-1', timeout=65, progress=progress.append)
        self.assertTrue(result['run_completed'], result)
        self.assertEqual(result['merge']['status'], 'merged')
        self.assertEqual(self.fixture.fixture.git(main, 'rev-parse', 'HEAD').stdout.strip(), result['head_commit'])
        self.assertEqual(progress[-1]['event'], 'run-finished')
        self.assertIn('review its January example', Path(result['report_file']).read_text())
        self.assertTrue(result['token_summary'])

    def test_auto_main_rechecks_scopes_after_integrating_new_main_commit(self):
        path = self.source / '.auto-bmad.toml'
        path.write_text(path.read_text().replace('[execution]\n', '[execution]\nmerge_policy="auto-main"\n') +
                        '\n[project_tests.scopes.ui]\npaths=["app.py","later.py","other.py"]\ncommand="true"\n')
        self.commit()
        main = self.fixture.main
        if self.fixture.fixture.git(main, 'branch', '--show-current').stdout.strip() != 'main':
            self.fixture.fixture.git(main, 'branch', '-m', 'main')
        def progress(event):
            if event['event'] == 'run-started':
                (main / 'other.py').write_text('other = 1\n')
                self.fixture.fixture.git(main, 'add', 'other.py')
                self.fixture.fixture.git(main, 'commit', '-qm', 'concurrent main work')
        with patch.dict(os.environ, {'FAKE_STORY_MODE': 'scoped-tests'}):
            result = run_queue.run(self.source, 'epic-1', timeout=65, progress=progress)
        self.assertTrue(result['run_completed'], result)
        self.assertEqual(result['integration_verification']['verdict'], 'pass')
        self.assertEqual(result['integration_verification']['scopes'], ['ui'])
        self.assertEqual(result['merge']['status'], 'merged')
        self.assertEqual((main / 'other.py').read_text(), 'other = 1\n')

    def test_parallel_wave_hook_questions_are_saved_once(self):
        command = shlex.join([sys.executable, '-c', 'import json;print(json.dumps({"ask":{"question":"Check copy later?"}}))'])
        path = self.source / '.auto-bmad.toml'
        path.write_text(path.read_text() + '\n[[hook]]\nname="wave-question"\nevents=["wave-merged"]\ncommand=' + json.dumps(command) + '\n')
        self.commit()
        arg = 'epic-1 --parallel-fast --width 2'
        result = run_queue.run(self.source, arg, timeout=65, wave_plan=self.waves(arg))
        self.assertTrue(result['run_completed'], result)
        self.assertEqual(len(result['questions']), 1)
        self.assertEqual(Path(result['questions_file']).read_text().count('Check copy later?'), 1)

    def test_setup_profiles_drive_a_complete_story(self):
        args = SimpleNamespace(agent="codex", model="test-model", effort="high", timeout=60,
                               executable=str(Path(__file__).with_name("fake_story_cli.py").resolve()),
                               disable_agent_checks=True, layer="project", write=True)
        out, code = setup.cmd_agent(args, str(self.source))
        self.assertEqual(code, 0, out)
        saved = (self.source / ".auto-bmad.toml").read_text()
        for selected in ("claude", "codex"):
            selection = SimpleNamespace(agent=selected, model=None, effort=None, timeout=None,
                                        layer="project", write=True)
            out, code = setup.cmd_agent(selection, str(self.source))
            self.assertEqual(code, 0, out)
        self.assertTrue(out["profiles_reused"])
        self.assertEqual(tomllib.loads((self.source / ".auto-bmad.toml").read_text()), tomllib.loads(saved))
        out, code = setup.cmd_agent(SimpleNamespace(agent="claude", layer="project", write=True), str(self.source))
        self.assertEqual(code, 0, out)
        saved = (self.source / ".auto-bmad.toml").read_bytes()
        self.fixture.fixture.git(self.source, "add", ".auto-bmad.toml")
        self.fixture.fixture.git(self.source, "commit", "-qm", "configure through setup")
        before = self.fixture.fixture.git(self.source, "rev-parse", "HEAD").stdout.strip()
        package = Path(__file__).resolve().parents[1]
        for helper, backend in (("integrations/codex/skills/auto-bmad/scripts/run.py", "cli"),
                                ("skills/auto-bmad/scripts/run.py", "legacy-plugin")):
            proc = subprocess.run([sys.executable, str(package / helper), "plan", "--repo", str(self.source),
                                   "--arg", "1-3"], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["backend"], backend)
        with patch.dict(os.environ, {"AUTO_BMAD_EXECUTOR": "codex"}):
            result = run_queue.run(self.source, "1-3", timeout=45)
        self.assertTrue(result["run_completed"], result)
        self.assertEqual(result["done"], 1)
        self.assertEqual(self.fixture.fixture.git(self.source, "rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual((self.source / ".auto-bmad.toml").read_bytes(), saved)

    def test_failed_story_stops_epic_and_preserves_its_worktree(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "skip-reviews"}):
            result = run_queue.run(self.source, "epic-1", timeout=35)
        self.assertFalse(result["run_completed"], result)
        self.assertEqual(len(result["stories"]), 1)
        self.assertEqual(result["remaining"], ["1-3", "1-4"])
        self.assertTrue(Path(result["worktree"]).exists())
        self.assertEqual((self.source / "app.py").read_text(), "answer = 0\n")

    def test_nonblocking_editorial_questions_are_saved_and_the_epic_continues(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "editorial-question"}):
            result = run_queue.run(self.source, "epic-1", timeout=65)
        self.assertTrue(result["run_completed"], result)
        self.assertEqual(result["done"], 2)
        self.assertTrue(all(story["questions"] for story in result["stories"]))
        path = Path(result["worktree"]) / "_bmad-output/implementation-artifacts/epic-1-open-questions.md"
        text = path.read_text()
        self.assertIn("<!-- story:1-3 -->", text)
        self.assertIn("<!-- story:1-4 -->", text)
        self.assertIn("review its January example before merge", text)
        self.assertFalse((self.source / path.relative_to(result["worktree"])).exists())

    def test_wave_collects_blocked_questions_without_merging_failed_code(self):
        arg = "epic-1 --parallel-fast --width 2"
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "wave-blocked"}):
            result = run_queue.run(self.source, arg, timeout=65, wave_plan=self.waves(arg))
        self.assertFalse(result["run_completed"], result)
        self.assertEqual(result["done"], 1, result)
        blocked = next(row for row in result["stories"] if row["story"] == "1-3")
        root = Path(result["worktree"])
        self.assertEqual(Path(blocked["questions_file"]).parent, root / "_bmad-output/implementation-artifacts")
        self.assertIn("Resolve the intent.", Path(blocked["questions_file"]).read_text())
        self.assertEqual((root / "app.py").read_text(), "answer = 0\n")
        self.assertTrue((root / "later.py").exists())

    def test_no_implicit_queue_or_story_deadline(self):
        original = run_queue.Queue.command

        def command(queue, script, args, name, **kwargs):
            if name == "story-1-3":
                self.assertIsNone(queue.stop.deadline)
                self.assertIsNone(kwargs["timeout"])
                self.assertNotIn("--timeout", args)
                return {"story": "1-3", "story_completed": False,
                        "execution_status": "blocked", "error": "fixture stop"}
            return original(queue, script, args, name, **kwargs)

        with patch.object(run_queue.Queue, "command", command):
            result = run_queue.run(self.source, "1-3")
        self.assertEqual(result["error"], "fixture stop", result)

    def test_queue_status_exposes_child_inactivity_without_a_stop_decision(self):
        _, common = run_queue.canonical(self.source)
        private = common / "auto-bmad-sessions"
        queue, child = private / "activity-queue", private / "activity-child"
        queue.mkdir(parents=True)
        (queue / "session.json").write_text(json.dumps({"repo": str(self.source), "kind": "queue",
            "status": "running", "planned_stories": ["1-3"]}))
        process = child / "controller-1"
        process.mkdir(parents=True)
        (child / "session.json").write_text(json.dumps({"repo": str(self.source), "queue_id": queue.name,
            "status": "running", "story": "1-3"}))
        (process / "status.json").write_text(json.dumps({"execution_status": "running",
            "call": {"role": "story-runner"}, "watchdog": {
                "state": "suspected_stall", "action": "keep_running", "idle_limit": 3600}}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = run_queue.main(["status", "--session", str(queue / "session.json")])
        self.assertEqual(code, 0, output.getvalue())
        activity = json.loads(output.getvalue())["activity"]
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0]["story"], "1-3")
        self.assertEqual(activity[0]["action"], "keep_running")

    def test_run_end_does_not_blame_hooks_for_preserved_failed_story_edits(self):
        original = run_queue.Queue.command

        def command(queue, script, args, name, **kwargs):
            if name == "story-1-3":
                (queue.root / "app.py").write_text("answer = 42\n")
                return {"story": "1-3", "story_completed": False,
                        "execution_status": "timed_out", "error": "controller timed_out"}
            return original(queue, script, args, name, **kwargs)

        with patch.object(run_queue.Queue, "command", command):
            result = run_queue.run(self.source, "epic-1", timeout=35)
        self.assertEqual(result["execution_status"], "timed_out", result)
        self.assertEqual(result["error"], "controller timed_out")
        self.assertEqual(len(result["stories"]), 1)
        self.assertEqual((Path(result["worktree"]) / "app.py").read_text(), "answer = 42\n")

    def test_run_end_code_mutation_after_failure_keeps_both_errors(self):
        original_command, original_event = run_queue.Queue.command, run_queue.Queue.event

        def command(queue, script, args, name, **kwargs):
            if name == "story-1-3":
                (queue.root / "app.py").write_text("answer = 42\n")
                return {"story": "1-3", "story_completed": False,
                        "execution_status": "timed_out", "error": "controller timed_out"}
            return original_command(queue, script, args, name, **kwargs)

        def event(queue, name, *args, **kwargs):
            if name == "run-end":
                (queue.root / "app.py").write_text("answer = 999\n")
            return original_event(queue, name, *args, **kwargs)

        with patch.object(run_queue.Queue, "command", command), patch.object(run_queue.Queue, "event", event):
            result = run_queue.run(self.source, "epic-1", timeout=35)
        self.assertEqual(result["execution_status"], "needs_attention", result)
        self.assertIn("run-end hooks changed", result["error"])
        self.assertEqual(result["prior_error"], "controller timed_out")

    def test_run_end_detects_unreported_planning_changes_after_failure(self):
        original_command, original_event = run_queue.Queue.command, run_queue.Queue.event

        def command(queue, script, args, name, **kwargs):
            if name == "story-1-3":
                (queue.root / "app.py").write_text("answer = 42\n")
                return {"story": "1-3", "story_completed": False,
                        "execution_status": "timed_out", "error": "controller timed_out"}
            return original_command(queue, script, args, name, **kwargs)

        for untracked in (False, True):
            with self.subTest(untracked=untracked):
                def event(queue, name, *args, **kwargs):
                    if name == "run-end":
                        if untracked:
                            (queue.root / "_bmad-output/unreported.md").write_text("unreported hook change\n")
                        else:
                            sprint = queue.root / "_bmad-output/implementation-artifacts/sprint-status.yaml"
                            sprint.write_text(sprint.read_text().replace("1-3-fixture: backlog", "1-3-fixture: done"))
                    return original_event(queue, name, *args, **kwargs)

                with patch.object(run_queue.Queue, "command", command), patch.object(run_queue.Queue, "event", event):
                    result = run_queue.run(self.source, "epic-1", timeout=35)
                self.assertEqual(result["execution_status"], "needs_attention", result)
                self.assertIn("run-end hooks changed", result["error"])
                self.assertEqual(result["prior_error"], "controller timed_out")

    def test_success_still_requires_a_clean_tree_before_final_hooks(self):
        original = run_queue.Queue.command

        def command(queue, script, args, name, **kwargs):
            result = original(queue, script, args, name, **kwargs)
            if name == "story-1-3":
                self.assertTrue(result["story_completed"], result)
                (queue.root / "app.py").write_text("answer = 999\n")
            return result

        with patch.object(run_queue.Queue, "command", command):
            result = run_queue.run(self.source, "1-3", timeout=35)
        self.assertFalse(result["run_completed"], result)
        self.assertEqual(result["execution_status"], "needs_attention", result)

    def test_stop_after_finishes_requested_story_and_preserves_the_rest(self):
        receipts = []
        result = run_queue.run(self.source, "epic-1", timeout=45,
            progress=lambda event: receipts.append(run_control.request(event["session"], "1.3")) if event["event"] == "run-started" else None)
        self.assertTrue(receipts[0]["accepted"])
        self.assertEqual(result["execution_status"], "stopped", result)
        self.assertFalse(result["run_completed"])
        self.assertEqual(result["remaining"], ["1-4"])
        self.assertTrue(result["stop_target_reached"])
        self.assertEqual(result["stop_after"], "1-3")
        self.assertTrue(result["stories"][0]["head_commit"])
        with self.assertRaisesRegex(ValueError, "no longer running"):
            run_control.request(result["session"], "1-4")

    def test_stop_after_splits_an_unstarted_wave(self):
        sprint = self.source / "_bmad-output/implementation-artifacts/sprint-status.yaml"
        sprint.write_text(sprint.read_text() + "  1-5-dependent: backlog\n")
        self.commit()
        arg = "epic-1 --parallel-fast --width 3"
        plan = self.waves(arg, [["1-3", "1-4", "1-5"]])
        result = run_queue.run(self.source, arg, timeout=65, wave_plan=plan,
            progress=lambda event: run_control.request(event["session"], "1-4") if event["event"] == "run-started" else None)
        self.assertEqual(result["execution_status"], "stopped", result)
        self.assertFalse(result["run_completed"])
        self.assertEqual(result["done"], 2)
        self.assertEqual(result["remaining"], ["1-5"])
        self.assertEqual(result["waves"][0]["deferred"], ["1-5"])

    def test_stop_after_during_a_wave_finishes_already_admitted_siblings(self):
        sprint = self.source / "_bmad-output/implementation-artifacts/sprint-status.yaml"
        sprint.write_text(sprint.read_text() + "  1-5-dependent: backlog\n")
        self.commit()
        arg = "epic-1 --parallel-fast --width 2"
        plan = self.waves(arg, [["1-3", "1-4"], ["1-5"]])
        original, receipts = run_queue.Queue.event, []

        def event(queue, name, story=None, **kwargs):
            if name == "story-start" and story == "1-3":
                receipts.append(run_control.request(queue.session_path, "1-3"))
            return original(queue, name, story, **kwargs)

        with patch.object(run_queue.Queue, "event", event):
            result = run_queue.run(self.source, arg, timeout=65, wave_plan=plan)
        self.assertEqual(result["execution_status"], "stopped", result)
        self.assertEqual(receipts[0]["already_started_after"], ["1-4"])
        self.assertEqual(result["done"], 2)
        self.assertEqual(result["remaining"], ["1-5"])

    def test_stop_after_can_be_moved_to_a_later_story(self):
        original = run_queue.Queue.event

        def event(queue, name, story=None, **kwargs):
            if name == "story-start" and story == "1-3":
                run_control.request(queue.session_path, "1-3")
                run_control.request(queue.session_path, "1-4")
            return original(queue, name, story, **kwargs)

        with patch.object(run_queue.Queue, "event", event):
            result = run_queue.run(self.source, "epic-1", timeout=65)
        self.assertTrue(result["run_completed"], result)
        self.assertEqual(result["stop_after"], "1-4")
        self.assertTrue(result["stop_target_reached"])

    def test_stop_after_can_extend_a_previously_split_wave(self):
        original = run_queue.Queue.event

        def event(queue, name, story=None, **kwargs):
            if name == "story-start" and story == "1-3":
                run_control.request(queue.session_path, "1-4")
            return original(queue, name, story, **kwargs)

        arg = "epic-1 --parallel-fast --width 2"
        with patch.object(run_queue.Queue, "event", event):
            result = run_queue.run(self.source, arg, timeout=65, wave_plan=self.waves(arg),
                progress=lambda state: run_control.request(state["session"], "1-3") if state["event"] == "run-started" else None)
        self.assertTrue(result["run_completed"], result)
        self.assertEqual(result["done"], 2)
        self.assertEqual(result["stop_after"], "1-4")

    def test_stop_after_is_refused_once_clean_stop_finalization_begins(self):
        original, refused = run_queue.Queue.event, []

        def event(queue, name, story=None, **kwargs):
            if name == "run-end":
                try:
                    run_control.request(queue.session_path, "1-4")
                except ValueError as e:
                    refused.append(str(e))
            return original(queue, name, story, **kwargs)

        with patch.object(run_queue.Queue, "event", event):
            result = run_queue.run(self.source, "epic-1", timeout=45,
                progress=lambda state: run_control.request(state["session"], "1-3") if state["event"] == "run-started" else None)
        self.assertEqual(result["execution_status"], "stopped", result)
        self.assertEqual(result["stop_after"], "1-3")
        self.assertTrue(refused)

    def test_stop_after_finalization_error_does_not_return_success(self):
        original = run_queue.Queue.event

        def event(queue, name, story=None, **kwargs):
            if name == "run-end":
                raise ValueError("fixture finalization failed")
            return original(queue, name, story, **kwargs)

        with patch.object(run_queue.Queue, "event", event):
            result = run_queue.run(self.source, "epic-1", timeout=45,
                progress=lambda state: run_control.request(state["session"], "1-3") if state["event"] == "run-started" else None)
        self.assertEqual(result["execution_status"], "needs_attention", result)
        self.assertIn("fixture finalization failed", result["error"])
        with patch.object(run_queue, "run", return_value=result), contextlib.redirect_stdout(io.StringIO()):
            code = run_queue.main(["--repo", str(self.source), "--arg", "epic-1", "--allow-model"])
        self.assertEqual(code, 2)

    def test_dry_plan_does_not_launch_a_model_or_create_a_worktree(self):
        with patch.object(run_queue, "execute") as model:
            out = run_queue.inspect(self.source, "epic-1 --deep")
        model.assert_not_called()
        self.assertFalse(out["model_started"])
        self.assertEqual(out["plan"]["parallel"], "off")

    def test_no_model_flag_refuses_before_mutation(self):
        with patch.object(run_queue, "run") as run, contextlib.redirect_stdout(io.StringIO()):
            code = run_queue.main(["--repo", str(self.source), "--arg", "epic-1"])
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_dirty_source_is_preserved_and_refused(self):
        (self.source / "app.py").write_text("unsaved = True\n")
        with self.assertRaisesRegex(ValueError, "clean"):
            run_queue.run(self.source, "epic-1")
        self.assertEqual((self.source / "app.py").read_text(), "unsaved = True\n")

    def test_parallel_flags_resolve_shared_settings_and_in_place_is_refused(self):
        plan = run_queue.inspect(self.source, "epic-1 --parallel-fast --width 2")
        self.assertEqual(plan["plan"]["parallel"], "aggressive")
        self.assertEqual(plan["plan"]["parallel_width"], 2)
        self.assertTrue(plan["wave_plan_required"])
        with self.assertRaises(ValueError):
            run_queue.inspect(self.source, "epic-1 --no-worktree")

    def waves(self, arg="epic-1 --parallel-fast --width 2", groups=None):
        plan = run_queue.inspect(self.source, arg)
        return {"parallel": plan["plan"]["parallel"], "width": plan["plan"]["parallel_width"],
                "base_commit": plan["base_commit"], "waves": [
                    {"stories": ids, "reason": "independent fixture files"}
                    for ids in (groups or [["1-3", "1-4"]])]}

    def test_wave_runs_workers_concurrently_and_integrates_before_tracking(self):
        arg = "epic-1 --parallel-fast --width 2"
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "wave-rendezvous"}):
            result = run_queue.run(self.source, arg, wave_plan=self.waves(arg))
        self.assertTrue(result["run_completed"], result)
        self.assertEqual(result["done"], 2)
        self.assertTrue(result["waves"][0]["completed"])
        root = Path(result["worktree"])
        self.assertEqual((root / "app.py").read_text(), "answer = 42\n")
        self.assertTrue((root / "later.py").exists())
        sprint = (root / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text()
        self.assertIn("epic-1: done", sprint)
        for row in result["stories"]:
            self.assertNotEqual(Path(row["worktree"]), root)
            self.assertTrue(row["merged"])
            child_sprint = (Path(row["worktree"]) / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text()
            self.assertIn("1-3-fixture: backlog", child_sprint)
        self.assertEqual(self.fixture.fixture.git(self.source, "rev-parse", "HEAD").stdout.strip(), self.base)
        import stats
        rows = stats.load(str(self.source))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["status"] == "done" for row in rows))
        self.assertEqual({row["queue_id"] for row in rows}, {Path(result["session"]).parent.name})

    def test_wave_merges_successful_sibling_when_another_story_fails(self):
        arg = "epic-1 --parallel-fast --width 2"
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "wave-partial"}):
            result = run_queue.run(self.source, arg, timeout=65, wave_plan=self.waves(arg))
        self.assertFalse(result["run_completed"], result)
        self.assertEqual(result["remaining"], ["1-3"])
        self.assertEqual(result["done"], 1)
        self.assertTrue((Path(result["worktree"]) / "later.py").exists())

    def test_scoped_wave_checks_only_its_affected_component(self):
        config = self.source / ".auto-bmad.toml"
        config.write_text(config.read_text() + '\n[project_tests.scopes.ui]\npaths=["app.py","later.py"]\ncommand="true"\n[project_tests.scopes.service]\npaths=["service/**"]\ncommand="false"\n')
        self.commit()
        arg = "epic-1 --parallel-fast --width 2"
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "scoped-tests"}):
            result = run_queue.run(self.source, arg, timeout=70, wave_plan=self.waves(arg))
        self.assertTrue(result["run_completed"], result)
        self.assertEqual(result["waves"][0]["verification"]["scopes"], ["ui"])

    def test_wave_respects_disabled_component_tests(self):
        config = self.source / ".auto-bmad.toml"
        config.write_text(config.read_text().replace('command="true"', 'enabled=false\ncommand="false"') +
                          '\n[project_tests.scopes.ui]\npaths=["app.py","later.py"]\ncommand="false"\n')
        self.commit()
        arg = "epic-1 --parallel-fast --width 2"
        result = run_queue.run(self.source, arg, timeout=70, wave_plan=self.waves(arg))
        self.assertTrue(result["run_completed"], result)
        self.assertEqual(result["waves"][0]["verification"]["verdict"], "skipped")

    def test_later_wave_starts_from_integrated_and_tracked_previous_wave(self):
        sprint = self.source / "_bmad-output/implementation-artifacts/sprint-status.yaml"
        sprint.write_text(sprint.read_text() + "  1-5-dependent: backlog\n")
        self.commit()
        arg = "epic-1 --parallel-fast --width 2"
        plan = self.waves(arg, [["1-3", "1-4"], ["1-5"]])
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "wave-dependency"}):
            result = run_queue.run(self.source, arg, timeout=75, wave_plan=plan)
        self.assertTrue(result["run_completed"], result)
        self.assertEqual(result["done"], 3)
        self.assertTrue(all(wave["completed"] for wave in result["waves"]))
        self.assertEqual([row["wave"] for row in result["stories"]], [1, 1, 2])
        self.assertTrue((Path(result["worktree"]) / "story-1-5.py").exists())

    def test_wave_plan_is_checked_before_worktrees_or_models(self):
        arg = "epic-1 --parallel-fast --width 2"
        plan = self.waves(arg)
        for bad in (None, {**plan, "base_commit": "0" * 40}, {**plan, "width": 3},
                    {**plan, "waves": [{"stories": ["1-4", "1-3"], "reason": "reordered"}]},
                    {**plan, "waves": [{"stories": ["1-3", "1-3"], "reason": "duplicate"}]}):
            with patch.object(run_queue.worktree, "create_cli") as create:
                with self.assertRaises(ValueError):
                    run_queue.run(self.source, arg, wave_plan=bad)
                create.assert_not_called()

    def test_wave_conflict_keeps_unmerged_work_and_finalizes_only_success(self):
        arg = "epic-1 --parallel-fast --width 2"
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "wave-conflict"}):
            result = run_queue.run(self.source, arg, timeout=65, wave_plan=self.waves(arg))
        self.assertFalse(result["run_completed"], result)
        self.assertEqual(result["done"], 1)
        self.assertEqual(result["remaining"], ["1-4"])
        failed = result["stories"][1]
        self.assertIn("app.py", failed["conflicts"])
        self.assertTrue(Path(failed["worktree"]).exists())
        self.assertEqual((Path(result["worktree"]) / "app.py").read_text(), "answer = 42\n")

    def test_wave_combined_test_failure_stops_before_done_tracking(self):
        command = shlex.join([sys.executable, "-c", "from pathlib import Path;assert not (Path('later.py').exists() and 'answer = 42' in Path('app.py').read_text())"])
        config = self.source / ".auto-bmad.toml"
        config.write_text(config.read_text().replace('command="true"', 'command=' + json.dumps(command)))
        self.commit()
        arg = "epic-1 --parallel-fast --width 2"
        result = run_queue.run(self.source, arg, timeout=65, wave_plan=self.waves(arg))
        self.assertFalse(result["run_completed"], result)
        self.assertIn("after the wave merge", result["error"])
        self.assertEqual(result["done"], 0)
        self.assertEqual(result["waves"][0]["verification"]["verdict"], "problem")
        sprint = (Path(result["worktree"]) / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text()
        self.assertIn("1-3-fixture: backlog", sprint)

    def test_wave_keeps_preexisting_test_failure_despite_timing_changes(self):
        command = shlex.join([sys.executable, "-c", "from pathlib import Path;import sys;print('1 failed in 0.14s' if Path('later.py').exists() else '1 failed in 0.13s');sys.exit(1)"])
        config = self.source / ".auto-bmad.toml"
        config.write_text(config.read_text().replace('command="true"', 'command=' + json.dumps(command)))
        self.commit()
        arg = "epic-1 --parallel-fast --width 2"
        result = run_queue.run(self.source, arg, timeout=65, wave_plan=self.waves(arg))
        self.assertTrue(result["run_completed"], result)
        self.assertEqual(result["waves"][0]["verification"]["verdict"], "skipped")

    def test_wave_timeout_preserves_every_worker(self):
        arg = "epic-1 --parallel-fast --width 2"
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "hang"}):
            result = run_queue.run(self.source, arg, timeout=8, wave_plan=self.waves(arg))
        self.assertFalse(result["run_completed"], result)
        self.assertEqual(result["execution_status"], "timed_out")
        self.assertEqual(result["remaining"], ["1-3", "1-4"])
        for row in result["stories"]:
            self.assertTrue(Path(row["worktree"]).exists())

    def test_parallel_setting_is_shared_between_executors(self):
        config = self.source / ".auto-bmad.toml"
        config.write_text(config.read_text().replace('parallel="off"', 'parallel="conservative"\nwidth=2'))
        self.commit()
        with patch.dict(os.environ, {"AUTO_BMAD_EXECUTOR": "codex"}):
            codex = run_queue.inspect(self.source, "epic-1")["plan"]
        legacy = run_queue.run_story.local_json("plan_run.py", self.source, ["--arg", "epic-1"])
        self.assertEqual((codex["parallel"], codex["parallel_width"]), ("conservative", 2))
        self.assertEqual((legacy["parallel"], legacy["parallel_width"]), ("conservative", 2))
        explicit = run_queue.inspect(self.source, "epic-1 --no-parallel")
        self.assertFalse(explicit["wave_plan_required"])

    def commit(self):
        self.fixture.fixture.git(self.source, "add", "-A")
        self.fixture.fixture.git(self.source, "commit", "-qm", "queue scenario")

    def test_done_stories_are_not_reexecuted(self):
        path = self.source / "_bmad-output/implementation-artifacts/sprint-status.yaml"
        path.write_text(path.read_text().replace("1-3-fixture: backlog", "1-3-fixture: done"))
        (self.source / "app.py").write_text("answer = 42\n")
        self.commit()
        result = run_queue.run(self.source, "epic-1", timeout=40)
        self.assertTrue(result["run_completed"], result)
        self.assertEqual([s["story"] for s in result["stories"]], ["1-4"])

    def test_waits_keep_unstarted_stories_in_the_remaining_list(self):
        folder = self.source / "_bmad-output/planning-artifacts"
        folder.mkdir(exist_ok=True, parents=True)
        (folder / "epics.md").write_text("## Epic 1: Fixture\n**Waits:** 1.4 — epic 2\n### Story 1.3: First\nI want answer\n### Story 1.4: Later\nI want later\n")
        self.commit()
        result = run_queue.run(self.source, "epic-1", timeout=40)
        self.assertFalse(result["run_completed"], result)
        self.assertEqual(result["execution_status"], "blocked")
        self.assertEqual(result["remaining"], ["1-4"])
        self.assertEqual(result["done"], 1)

    def test_clean_stop_prevents_worktree_creation(self):
        stop = self.source.parent / "stop"
        stop.touch()
        progress = []
        with patch.dict(os.environ, {"AUTO_BMAD_STOP_FILE": str(stop)}):
            result = run_queue.run(self.source, "epic-1", timeout=30, progress=progress.append)
        self.assertEqual(result["execution_status"], "window", result)
        self.assertNotIn("worktree", result)
        self.assertEqual(result["done"], 0)
        self.assertEqual(progress[0]["session"], result["session"])
        self.assertEqual(progress[0]["event"], "run-started")

    def test_timeout_preserves_run_and_does_not_advance_queue(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "hang"}):
            result = run_queue.run(self.source, "epic-1", timeout=5)
        self.assertEqual(result["execution_status"], "timed_out", result)
        self.assertFalse(result["run_completed"])
        self.assertEqual(result["remaining"], ["1-3", "1-4"])
        self.assertTrue(Path(result["worktree"]).exists())

    def test_local_config_is_carried_without_changing_source(self):
        ignored = self.source / ".gitignore"
        ignored.write_text(ignored.read_text() + ".auto-bmad.local.toml\n")
        self.commit()
        local = self.source / ".auto-bmad.local.toml"
        local.write_text('[run]\nlevel="normal"\n')
        result = run_queue.run(self.source, "1-3", timeout=40)
        self.assertTrue(result["run_completed"], result)
        self.assertEqual((Path(result["worktree"]) / local.name).read_text(), local.read_text())

    def test_hook_question_is_deferred_without_stopping_story_execution(self):
        command = shlex.join([sys.executable, "-c", 'import json;print(json.dumps({"ok":True,"ask":{"question":"Proceed?","options":[]}}))'])
        path = self.source / ".auto-bmad.toml"
        path.write_text(path.read_text() + '\n[[hook]]\nname="fixture-question"\nevents=["run-start","run-end","story-done"]\ncommand=' + json.dumps(command) + '\n')
        self.commit()
        with patch.dict(os.environ, {"AUTO_BMAD_UNATTENDED": ""}):
            result = run_queue.run(self.source, "epic-1", timeout=65)
        self.assertTrue(result["run_completed"], result)
        self.assertEqual(len(result["stories"]), 2)
        self.assertIn("Proceed?", Path(result["questions_file"]).read_text())
        self.assertEqual(result["questions"][0]["hook"], "fixture-question")

    def test_hook_files_are_committed_only_inside_the_run_worktree(self):
        code = ('import json,os;from pathlib import Path;'
                'p=Path("hook.txt");p.write_text("hook evidence\\n");'
                'print(json.dumps({"ok":True,"files":["hook.txt"]}))')
        command = shlex.join([sys.executable, "-c", code])
        path = self.source / ".auto-bmad.toml"
        path.write_text(path.read_text() + '\n[[hook]]\nname="fixture-files"\nevents=["run-start","run-end"]\ncommand=' + json.dumps(command) + '\n')
        self.commit()
        result = run_queue.run(self.source, "1-3", timeout=40)
        self.assertTrue(result["run_completed"], result)
        self.assertTrue((Path(result["worktree"]) / "hook.txt").exists())
        self.assertFalse((self.source / "hook.txt").exists())

    def test_service_environment_reaches_story_finishing(self):
        code = ('import json,sys;from pathlib import Path;p=json.load(sys.stdin);'
                'f=Path(".auto-bmad/hooks-seen.jsonl");f.parent.mkdir(exist_ok=True);'
                'f.open("a").write(json.dumps({"event":p["event"],"unattended":p["unattended"]})+"\\n");'
                'print("{}")')
        command = shlex.join([sys.executable, "-c", code])
        path = self.source / ".auto-bmad.toml"
        path.write_text(path.read_text() + '\n[[hook]]\nname="service-env"\nevents=["verify-done","story-done"]\ncommand=' + json.dumps(command) + '\n')
        self.commit()
        events = self.source.parent / "external-events.jsonl"
        with patch.dict(os.environ, {"AUTO_BMAD_EVENTS_FILE": str(events), "AUTO_BMAD_UNATTENDED": "1",
                                     "TEST_UNLISTED_SECRET": "operator-only"}):
            result = run_queue.run(self.source, "1-3", timeout=40)
        self.assertTrue(result["run_completed"], result)
        seen = [json.loads(line) for line in events.read_text().splitlines()]
        self.assertTrue({"run-start", "story-start", "verify-done", "story-done", "run-end"}.issubset({r["event"] for r in seen}))
        hooks = Path(result["worktree"]) / ".auto-bmad/hooks-seen.jsonl"
        self.assertTrue(all(json.loads(line)["unattended"] for line in hooks.read_text().splitlines()))

    def test_hook_budget_is_not_limited_by_generic_command_timeout(self):
        path = self.source / ".auto-bmad.toml"
        path.write_text(path.read_text() + '\n[[hook]]\nname="long-hook"\nevents=["run-start"]\ncommand="true"\ntimeout=120\n')
        self.commit()
        original, limits = run_queue.Queue.command, []

        def command(queue, script, args, name, *extra, **kwargs):
            if name == "run-start":
                limits.append(kwargs.get("timeout", 60))
            return original(queue, script, args, name, *extra, **kwargs)

        with patch.object(run_queue.Queue, "command", command):
            result = run_queue.run(self.source, "1-3", timeout=40)
        self.assertTrue(result["run_completed"], result)
        self.assertGreaterEqual(limits[0], 120)

    def test_mutated_configuration_cannot_inject_a_run_end_hook(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "tamper-config"}):
            result = run_queue.run(self.source, "epic-1", timeout=35)
        self.assertFalse(result["run_completed"], result)
        self.assertFalse((Path(result["worktree"]) / "UNEXPECTED_HOOK").exists())
        self.assertIn("configuration changed", result["error"])

    def test_hook_commit_does_not_sweep_unreported_staged_code(self):
        code = ('import json,subprocess;from pathlib import Path;'
                'Path("hook.txt").write_text("hook\\n");Path("app.py").write_text("answer = 999\\n");'
                'subprocess.run(["git","add","app.py"],check=True);'
                'print(json.dumps({"ok":True,"files":["hook.txt"]}))')
        command = shlex.join([sys.executable, "-c", code])
        path = self.source / ".auto-bmad.toml"
        path.write_text(path.read_text() + '\n[[hook]]\nname="stager"\nevents=["run-start"]\ncommand=' + json.dumps(command) + '\n')
        self.commit()
        result = run_queue.run(self.source, "1-3", timeout=40)
        self.assertFalse(result["run_completed"], result)
        target = Path(result["worktree"])
        committed = self.fixture.fixture.git(target, "show", "HEAD:app.py").stdout
        self.assertEqual(committed, "answer = 0\n")
        self.assertIn("app.py", self.fixture.fixture.git(target, "diff", "--cached", "--name-only").stdout)


if __name__ == "__main__":
    unittest.main()
