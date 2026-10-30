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
from types import SimpleNamespace


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_run_story.StoryTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.root
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
        self.fixture.fixture.git(self.source, "add", ".auto-bmad.toml")
        self.fixture.fixture.git(self.source, "commit", "-qm", "configure through setup")
        before = self.fixture.fixture.git(self.source, "rev-parse", "HEAD").stdout.strip()
        result = run_queue.run(self.source, "1-3", timeout=45)
        self.assertTrue(result["run_completed"], result)
        self.assertEqual(result["done"], 1)
        self.assertEqual(self.fixture.fixture.git(self.source, "rev-parse", "HEAD").stdout.strip(), before)

    def test_failed_story_stops_epic_and_preserves_its_worktree(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "skip-reviews"}):
            result = run_queue.run(self.source, "epic-1", timeout=35)
        self.assertFalse(result["run_completed"], result)
        self.assertEqual(len(result["stories"]), 1)
        self.assertEqual(result["remaining"], ["1-3", "1-4"])
        self.assertTrue(Path(result["worktree"]).exists())
        self.assertEqual((self.source / "app.py").read_text(), "answer = 0\n")

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

    def test_parallel_and_in_place_flags_are_explicitly_refused(self):
        for flags in ("--parallel-fast", "--width 2", "--no-worktree"):
            with self.assertRaises(ValueError):
                run_queue.inspect(self.source, "epic-1 " + flags)

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
        with patch.dict(os.environ, {"AUTO_BMAD_STOP_FILE": str(stop)}):
            result = run_queue.run(self.source, "epic-1", timeout=30)
        self.assertEqual(result["execution_status"], "window", result)
        self.assertNotIn("worktree", result)
        self.assertEqual(result["done"], 0)

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

    def test_hook_question_blocks_before_story_execution(self):
        command = shlex.join([sys.executable, "-c", 'import json;print(json.dumps({"ok":True,"ask":{"question":"Proceed?","options":[]}}))'])
        path = self.source / ".auto-bmad.toml"
        path.write_text(path.read_text() + '\n[[hook]]\nname="fixture-question"\nevents=["run-start"]\ncommand=' + json.dumps(command) + '\n')
        self.commit()
        with patch.dict(os.environ, {"AUTO_BMAD_UNATTENDED": ""}):
            result = run_queue.run(self.source, "epic-1", timeout=35)
        self.assertFalse(result["run_completed"], result)
        self.assertEqual(result["execution_status"], "blocked")
        self.assertEqual(result["stories"], [])
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
