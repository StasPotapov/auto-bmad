import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import shutil
import shlex
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import engine
import run_story
import stub
import testrun
from execution_state import lease
import test_agent_dispatch


class StoryTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_agent_dispatch.DispatchTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.main = self.fixture.main
        self.cli = Path(__file__).with_name("fake_story_cli.py").resolve()
        config = self.root / ".auto-bmad.toml"
        text = config.read_text().replace('executable="codex"', 'executable=' + json.dumps(str(self.cli)))
        text = text.replace('[roles.reviewer-mid]\nagent="dev"', '[roles.reviewer-mid]\nagent="read"')
        text = text.replace('[roles.reviewer-lite]\nagent="dev"', '[roles.reviewer-lite]\nagent="read"')
        text += '\n[[verify]]\nname="project-tests"\ncommand="true"\n'
        for section in ('[agents.dev]\n', '[agents.read]\n'):
            text = text.replace(section, section + 'environment_allowlist=["PATH","HOME","TMPDIR","AUTO_BMAD_CONFIG","FAKE_STORY_MODE"]\n')
        config.write_text(text)
        self.fixture.git(self.root, "config", "user.name", "Test")
        self.fixture.git(self.root, "config", "user.email", "test@example.invalid")
        self.fixture.git(self.root, "config", "commit.gpgsign", "false")
        sprint = self.root / "_bmad-output/implementation-artifacts/sprint-status.yaml"
        sprint.parent.mkdir(parents=True, exist_ok=True)
        sprint.write_text('development_status:\n  epic-1: in-progress\n  1-3-fixture: backlog\n')
        self.fixture.git(self.root, "add", "-A")
        self.fixture.git(self.root, "commit", "-qm", "story fixture")
        self.base = self.fixture.git(self.root, "rev-parse", "HEAD").stdout.strip()
        self.layers = ["intent-alignment", "edge-case-hunter", "blind-hunter"]
        output = self.root.parent / "story-package"
        shutil.rmtree(self.root / "_bmad/render")

        def render(*args, **kwargs):
            self.fixture.fixture.render(*args, **kwargs)
            path = self.root / "_bmad/render/test/manifest.json"
            data = json.loads(path.read_text())
            data["inputs"]["resolved_values"]["customization.workflow.review_layers"] = [
                {"id": name, "instruction": "review"} for name in self.layers]
            path.write_text(json.dumps(data))
            return {"execution_status": "completed"}

        self.render = render
        with patch.object(engine.shutil, "which", return_value="/test/uv"), patch.object(engine, "execute", side_effect=render):
            engine.prepare(self.root, output)
        self.manifest = output / "manifest.json"

    def prepare(self, level="normal"):
        shutil.rmtree(self.root / "_bmad/render")
        output = self.root.parent / ("package-" + str(time.time_ns()))
        with patch.object(engine.shutil, "which", return_value="/test/uv"), patch.object(engine, "execute", side_effect=self.render):
            engine.prepare(self.root, output, level)
        self.manifest = output / "manifest.json"

    def save_config(self, text):
        (self.root / ".auto-bmad.toml").write_text(text)
        self.fixture.git(self.root, "add", ".auto-bmad.toml")
        self.fixture.git(self.root, "commit", "-qm", "fixture config")
        self.base = self.fixture.git(self.root, "rev-parse", "HEAD").stdout.strip()

    def agent_check(self, extra="", builtin=False, on_fail="fix"):
        instructions = self.root / "check.md"
        instructions.write_text("Check the running page. Return VERDICT and PROBLEMS.\n")
        text = (self.root / ".auto-bmad.toml").read_text()
        text += ('\n[[verify]]\nname="browser-fixture"\nkind="agent"\ninstructions=' +
                 json.dumps("@plugin/extensions/mockmatch/verify.md" if builtin else str(instructions)) +
                 '\non_fail=' + json.dumps(on_fail) + '\n' + extra)
        self.fixture.git(self.root, "add", "check.md")
        self.save_config(text)
        self.prepare()

    def test_agent_verifier_is_host_owned_and_counted_in_statistics(self):
        self.agent_check()
        result = run_story.run_story(self.manifest, "1-3", timeout=40)
        self.assertTrue(result["story_completed"], result)
        self.assertEqual(result["verification"]["checks"]["browser-fixture"], "pass")
        detail = result["verification"]["details"]["browser-fixture"]
        self.assertEqual(detail["artifact"], ".auto-bmad/check.html")
        from cli_stats import collect_session
        calls = collect_session(Path(result["session"]))[0]["calls"]
        verifier = [c for c in calls if c["role"] == "verifier"]
        self.assertEqual(len(verifier), 1)
        self.assertEqual(verifier[0]["check_name"], "browser-fixture")
        self.assertEqual(verifier[0]["usage_status"], "complete")

    def test_registered_checks_from_leaf_and_controller_use_the_host_environment(self):
        command = shlex.join([sys.executable, "-c", "import os,socket;assert os.environ['TEST_UNLISTED_SECRET']=='host-check';s=socket.socket();s.bind(('127.0.0.1',0));s.close()"])
        config = (self.root / ".auto-bmad.toml").read_text().replace('command="true"', 'command=' + json.dumps(command))
        self.save_config(config)
        self.prepare()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "host-tests", "TEST_UNLISTED_SECRET": "host-check"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=45)
        self.assertTrue(result["story_completed"], result)
        session = json.loads(Path(result["session"]).read_text())
        self.assertEqual(session["host_tests"]["version"], 1)
        self.assertEqual(session["host_tests"]["checks"]["project-tests"]["command"], command)
        self.assertGreaterEqual(len(list((Path(result["session"]).parent / "test-outbox").glob("*.json"))), 2)

    def test_scoped_frontend_story_never_runs_the_backend_baseline_or_tests(self):
        text = (self.root / ".auto-bmad.toml").read_text()
        text += '\n[project_tests.scopes.frontend]\npaths=["app.py"]\ncommand="true"\n[project_tests.scopes.backend]\npaths=["backend/**"]\ncommand="false"\n'
        self.save_config(text)
        self.prepare()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "scoped-tests"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=45)
        self.assertTrue(result["story_completed"], result)
        check = result["verification"]["details"]["project-tests"]
        self.assertEqual(check["scopes"], ["frontend"])
        self.assertTrue((Path(result["session"]).parent / "baseline-code").exists())

    def test_read_only_reviewers_cannot_execute_registered_host_checks(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "review-host-tests"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=45)
        self.assertTrue(result["story_completed"], result)
        answers = Path(result["session"]).parent / "test-outbox"
        rows = [json.loads(path.read_text()) for path in answers.glob("*.json")]
        self.assertEqual(len(rows), len(self.layers))
        self.assertTrue(all("cannot run host project checks" in row["error"] for row in rows))

    @unittest.skipUnless(os.environ.get("AUTO_BMAD_SANDBOX_SMOKE") == "1", "requires installed Codex sandbox")
    def test_registered_check_crosses_the_real_sandbox_without_granting_model_network(self):
        command = shlex.join([sys.executable, "-c", "import os,socket;assert os.environ['TEST_UNLISTED_SECRET']=='host-check';s=socket.socket();s.bind(('127.0.0.1',0));s.close()"])
        self.save_config((self.root / ".auto-bmad.toml").read_text().replace('command="true"', 'command=' + json.dumps(command)))
        self.prepare()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "host-tests-sandbox", "TEST_UNLISTED_SECRET": "host-check"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=50)
        self.assertTrue(result["story_completed"], result)

    @unittest.skipUnless(os.environ.get("AUTO_BMAD_BROWSER_SMOKE") == "1", "requires installed mockmatch and Chromium")
    def test_real_browser_bridge_from_codex_workspace_sandbox(self):
        self.agent_check('requires="mockmatch"\nserve="python3 -m http.server {port} --bind 127.0.0.1 --directory .auto-bmad/check-site"\n'
                         'url="http://127.0.0.1:18821"\n', builtin=True)
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "verifier-browser"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=90)
        self.assertTrue(result["story_completed"], result)
        self.assertEqual(result["verification"]["checks"]["browser-fixture"], "pass")
        directory = Path(result["session"]).parent
        self.assertFalse((directory / "browser-server/mockmatch-serve.json").exists())
        self.assertFalse((directory / "browser/build/mockmatch/session.json").exists())

    def test_agent_problem_reenters_reviewed_fix_loop_with_original_context(self):
        self.agent_check()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "verifier-fix"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=60)
        self.assertTrue(result["story_completed"], result)
        self.assertEqual(result["verification"]["fixes"], 1)
        self.assertTrue((self.root / "fixed.py").exists())
        prompt = (self.root / ".auto-bmad/verifier-prompt.txt").read_text()
        self.assertIn("Attempt: 2", prompt)
        self.assertIn("expected repaired page", prompt)
        self.assertIn("Base: " + self.base, prompt)
        records = json.loads((Path(result["session"]).parent / "roles.json").read_text())
        self.assertEqual(sum(r["request"]["role"] == "verifier" for r in records), 2)
        self.assertTrue(all(r["review_base"] == self.base for r in records))

    def test_agent_note_remains_visible(self):
        self.agent_check(on_fail="note")
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "verifier-note"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=40)
        self.assertTrue(result["story_completed"], result)
        self.assertIn("Browser assertion failed", result["questions"])
        self.assertEqual(result["verification"]["status"], "problem")

    def test_agent_cannot_change_code_or_advance_tracking(self):
        self.agent_check()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "verifier-mutate"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=40)
        self.assertFalse(result["story_completed"], result)
        self.assertIn("backlog", (self.root / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text())
        self.assertEqual((self.root / "app.py").read_text(), "answer = 999\n")

    def test_verifier_timeout_returns_writer_lease(self):
        self.agent_check('timeout=1\n')
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "verifier-hang"}), \
                patch.object(run_story.cli_verifier, "cleanup", wraps=run_story.cli_verifier.cleanup) as cleanup:
            result = run_story.run_story(self.manifest, "1-3", timeout=40)
        self.assertFalse(result["story_completed"], result)
        self.assertEqual(cleanup.call_count, 2)
        with lease(self.root):
            pass

    def test_agent_skip_never_becomes_pass(self):
        self.agent_check()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "verifier-skipped"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=40)
        self.assertTrue(result["story_completed"], result)
        self.assertEqual(result["verification"]["checks"]["browser-fixture"], "skipped")
        self.assertIn("browser dependencies unavailable", result["questions"])

    def test_verifier_can_use_session_test_runner_after_controller_exits(self):
        self.agent_check()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "verifier-test"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=40)
        self.assertTrue(result["story_completed"], result)

    def test_resumed_story_verifier_uses_original_spec_baseline(self):
        self.agent_check()
        original_base = self.base
        spec = self.root / "_bmad-output/implementation-artifacts/spec-1-3-fixture.md"
        spec.write_text(f"---\nstatus: in-progress\nbaseline_revision: {original_base}\n---\n")
        self.fixture.git(self.root, "add", str(spec))
        self.fixture.git(self.root, "commit", "-qm", "fixture resume metadata")
        result = run_story.run_story(self.manifest, "1-3", timeout=40)
        self.assertTrue(result["story_completed"], result)
        self.assertIn("Base: " + original_base, (self.root / ".auto-bmad/verifier-prompt.txt").read_text())

    def test_agent_cleanup_is_not_executed_as_host_shell_code(self):
        self.agent_check()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "verifier-cleanup"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=40)
        self.assertFalse(result["story_completed"], result)
        self.assertIn("cleanup", result["error"])
        self.assertFalse((self.root / "UNEXPECTED_CLEANUP").exists())

    def test_complete_story_uses_role_broker_and_finishes_tracking(self):
        result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        self.assertEqual(result["merge_policy"], "manual")
        self.assertIn("1-3-fixture: done", (self.root / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text())
        self.assertEqual((self.root / "app.py").read_text(), "answer = 42\n")
        self.assertEqual((self.main / "app.py").read_text(), "answer = 0\n")
        records = json.loads((Path(result["session"]).parent / "roles.json").read_text())
        self.assertEqual({r["request"].get("layer_id") for r in records if r["request"]["role"] != "implementer"}, set(self.layers))
        self.assertTrue(all(r["review_base"] == self.base for r in records))
        self.assertTrue(all(r["diff_hash"] for r in records if r["request"]["role"] != "implementer"))
        self.assertEqual(self.fixture.git(self.root, "status", "--porcelain").stdout, "")

    def test_missing_review_results_cannot_complete_story(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "skip-reviews"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=25)
        self.assertFalse(result["story_completed"])
        self.assertIn("backlog", (self.root / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text())

    def test_timeout_cancels_nested_writer_and_keeps_changes(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "hang"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=2)
        self.assertEqual(result["execution_status"], "timed_out", result)
        self.assertEqual((self.root / "app.py").read_text(), "answer = 42\n")

    def test_idle_leaf_is_stopped_without_a_whole_story_deadline(self):
        text = (self.root / ".auto-bmad.toml").read_text().replace(
            '[agents.dev]\n', '[agents.dev]\ntimeout=2\n')
        self.save_config(text)
        self.prepare()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "hang"}):
            result = run_story.run_story(self.manifest, "1-3")
        self.assertEqual(result["execution_status"], "stalled", result)
        self.assertEqual(result["cause"]["role"], "implementer")
        self.assertFalse(result["story_completed"])
        self.assertLess(result["seconds"], 15)
        self.assertEqual((self.root / "app.py").read_text(), "answer = 42\n")
        with lease(self.root):
            pass
        with lease(self.root):
            pass

    def test_model_opt_in_is_required_before_any_controller_launch(self):
        with patch.object(run_story, "run_story") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_story.main(["--manifest", str(self.manifest), "--arg", "1-3"]), 2)
        run.assert_not_called()

    def test_implementer_cannot_impersonate_a_review_layer(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "forge-reviews"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=30)
        self.assertFalse(result["story_completed"], result)
        self.assertEqual(self.fixture.git(self.root, "rev-parse", "HEAD").stdout.strip(), self.base)

    def test_fast_checkpoint_runs_configured_tests_even_if_controller_skips_them(self):
        self.prepare("fast")
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "skip-tests"}):
            result = run_story.run_story(self.manifest, "1-3 --fast", timeout=30)
        self.assertTrue(result["story_completed"], result)
        proof = json.loads((Path(result["session"]).parent / "verification-1-0.json").read_text())
        self.assertEqual(proof["test"]["command"], "true")
        self.assertEqual(proof["test"]["verdict"], "pass")

    def test_fast_checkpoint_cannot_commit_with_red_configured_tests(self):
        config = (self.root / ".auto-bmad.toml").read_text().replace('command="true"', 'command="false"')
        self.save_config(config)
        self.prepare("fast")
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "skip-tests"}):
            result = run_story.run_story(self.manifest, "1-3 --fast", timeout=30)
        self.assertFalse(result["story_completed"], result)
        self.assertEqual(self.fixture.git(self.root, "rev-parse", "HEAD").stdout.strip(), self.base)

    def test_forged_worktree_test_cache_cannot_authorize_commit(self):
        config = (self.root / ".auto-bmad.toml").read_text().replace('command="true"', 'command="false"')
        self.save_config(config)
        self.prepare("fast")
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "forge-tests"}):
            result = run_story.run_story(self.manifest, "1-3 --fast", timeout=30)
        self.assertFalse(result["story_completed"], result)
        self.assertEqual(self.fixture.git(self.root, "rev-parse", "HEAD").stdout.strip(), self.base)

    def test_external_check_fix_keeps_full_story_baseline(self):
        config = (self.root / ".auto-bmad.toml").read_text() + ('\n[[verify]]\nname="fixture-repair"\n'
                 'kind="command"\ncommand="test -f fixed.py"\non_fail="fix"\n')
        self.save_config(config)
        self.prepare()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "check-fix"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=45)
        self.assertTrue(result["story_completed"], result)
        records = json.loads((Path(result["session"]).parent / "roles.json").read_text())
        self.assertEqual({r["pass"] for r in records}, {1, 2})
        self.assertTrue(all(r["review_base"] == self.base for r in records))
        self.assertTrue((self.root / "fixed.py").exists())
        session = json.loads(Path(result["session"]).read_text())
        self.assertEqual(session["repair_counts"], {"spec": 0, "review": 0, "tests": 1})
        self.assertNotIn("spec: check fixes", self.fixture.git(self.root, "log", "--format=%s").stdout)

    def test_relative_user_config_and_note_failure_reach_final_questions(self):
        user = self.main.parent / "user.toml"
        user.write_text('[[verify]]\nname="fixture-note"\nkind="command"\ncommand="false"\non_fail="note"\n')
        with patch.dict(os.environ, {"AUTO_BMAD_CONFIG": os.path.relpath(user, Path.cwd())}):
            self.prepare()
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        self.assertIn("fixture-note", result["questions"])
        data = json.loads((Path(result["session"]).parent / "finish.json").read_text())
        self.assertEqual(data["stories"][0]["verify"]["status"], "problem")

    def test_cleanup_failure_is_reported_by_session_status(self):
        with patch.object(run_story, "cleanup", return_value=["fixture process remains"]):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertEqual(result["execution_status"], "needs_attention", result)
        self.assertFalse(result["story_completed"])
        self.assertEqual(json.loads(Path(result["session"]).read_text())["status"], "needs_attention")

    def test_session_liveness_does_not_need_process_listing(self):
        with patch.object(stub, "proc_info", side_effect=AssertionError("ps forbidden")):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)

    def test_binary_test_output_does_not_fail_successful_verification(self):
        command = shlex.join([sys.executable, "-c", "import sys;sys.stdout.buffer.write(bytes([255]))"])
        config = (self.root / ".auto-bmad.toml").read_text().replace('command="true"', 'command=' + json.dumps(command))
        self.save_config(config)
        self.prepare()
        result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        self.assertEqual(result["verification"]["status"], "pass")

    def test_host_verification_receives_project_build_environment(self):
        config = (self.root / ".auto-bmad.toml").read_text()
        config = config.replace('"FAKE_STORY_MODE"]', '"FAKE_STORY_MODE","TEST_BUILD_ENV"]')
        config = config.replace('command="true"', 'command=' + json.dumps('test "$TEST_BUILD_ENV" = ready'))
        self.save_config(config)
        self.prepare()
        with patch.dict(os.environ, {"TEST_BUILD_ENV": "ready"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        self.assertEqual(result["verification"]["status"], "pass")
        before = json.loads((Path(result["session"]).parent / "baseline-test.json").read_text())
        self.assertEqual(before["verdict"], "pass")

    def test_story_finishing_respects_configured_hook_timeouts(self):
        config = (self.root / ".auto-bmad.toml").read_text() + ('\n[[hook]]\nname="slow-budget"\n'
                 'events=["verify-done","story-done"]\ncommand="true"\ntimeout=120\n')
        self.save_config(config)
        self.prepare()
        from story_broker import Broker
        original, limits = Broker.command, []

        def command(broker, argv, name, *args, **kwargs):
            if name == "finish":
                limits.append(kwargs.get("timeout", 60))
            return original(broker, argv, name, *args, **kwargs)

        with patch.object(Broker, "command", command):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        self.assertGreaterEqual(limits[0], 240)

    def test_finishing_hook_cannot_silently_change_verified_code(self):
        code = 'import json;from pathlib import Path;Path("app.py").write_text("answer = 999\\n");print(json.dumps({"ok":True,"files":["app.py"]}))'
        config = (self.root / ".auto-bmad.toml").read_text() + ('\n[[hook]]\nname="code-mutator"\n'
                 'events=["story-done"]\ncommand=' + json.dumps(shlex.join([sys.executable, "-c", code])) + '\n')
        self.save_config(config)
        self.prepare()
        result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertFalse(result["story_completed"], result)
        self.assertEqual(result["execution_status"], "needs_attention")
        self.assertEqual((self.root / "app.py").read_text(), "answer = 999\n")

    def test_red_baseline_skip_is_explicit_in_final_result(self):
        config = (self.root / ".auto-bmad.toml").read_text().replace('command="true"', 'command="false"')
        self.save_config(config)
        self.prepare()
        result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        self.assertEqual(result["verification"]["checks"]["project-tests"], "skipped")
        self.assertTrue(any(item["name"] == "project-tests" and "baseline" in item["reason"] for item in result["skipped_checks"]))

    def test_old_red_baseline_is_retested_before_story(self):
        directory = Path(testrun.state(str(self.root)))
        directory.mkdir(parents=True)
        key = testrun.key_of(str(self.root), "true")
        cached = directory / (key + ".json")
        testrun.write_json(str(cached), {"verdict": "problem", "code": 1, "command": "true", "tail": "old environment failure"})
        os.utime(cached, (time.time() - 3600, time.time() - 3600))
        result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        before = json.loads((Path(result["session"]).parent / "baseline-test.json").read_text())
        self.assertEqual(before["verdict"], "pass")
        self.assertFalse(before["reused"])

    def prepare_test_repair_fixture(self):
        # A local check with explicit failing IDs gives the host objective progress evidence.
        script = self.root / "check_fixture.py"
        script.write_text("""import os, sys
from pathlib import Path
values = {}
exec(Path('app.py').read_text(), values)
step = values.get('repair_step', 0)
mode = os.environ.get('FAKE_STORY_MODE', '')
if '--full' in sys.argv:
    p = Path('.auto-bmad/full-check-count')
    p.parent.mkdir(exist_ok=True)
    p.write_text(str(int(p.read_text()) + 1 if p.exists() else 1))
if values['answer'] == 0:
    sys.exit(0)
needed = 11 if mode == 'test-limit' else 1 if mode == 'test-final-gate' else 10
remaining = max(0, needed-step)
if mode == 'test-no-progress':
    remaining = 1
if mode == 'test-final-gate' and '--full' in sys.argv:
    remaining = 1
if mode == 'test-red-target' and '--full' in sys.argv:
    remaining = 0
for i in range(remaining):
    print(f'FAILED tests/fixture.py::case_{i} - error at attempt {step}')
sys.exit(1 if remaining else 0)
""")
        cmd = shlex.join([sys.executable, "check_fixture.py"])
        cfg = (self.root / ".auto-bmad.toml").read_text().replace('command="true"', 'command=' + json.dumps(cmd + ' --full'))
        cfg += '\n[project_tests.development.fixture]\ncommand=' + json.dumps(cmd) + '\ntargets=["check_fixture.py"]\n'
        self.fixture.git(self.root, "add", "check_fixture.py")
        self.save_config(cfg)
        self.prepare()

    def run_test_repair_fixture(self, mode):
        self.prepare_test_repair_fixture()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": mode}):
            result = run_story.run_story(self.manifest, "1-3", timeout=120)
        session = json.loads(Path(result["session"]).read_text())
        return result, session

    def test_all_three_repair_budgets_are_independent_and_survive_full_gate(self):
        result, session = self.run_test_repair_fixture("test-mixed")
        self.assertTrue(result["story_completed"], result)
        self.assertEqual(session["repair_counts"], {"spec": 2, "review": 5, "tests": 10})
        self.assertGreaterEqual(int((self.root / ".auto-bmad/full-check-count").read_text()), 2)
        records = json.loads((Path(result["session"]).parent / "roles.json").read_text())
        reviews = [r for r in records if r["request"]["role"] in ("reviewer", "reviewer-mid", "reviewer-lite")]
        self.assertEqual(len(reviews), len(self.layers))
        self.assertTrue(all(r["round"] == 17 for r in reviews))
        self.assertEqual(session["test_no_progress"], 0)

    def test_three_test_repairs_without_progress_block_and_preserve_code(self):
        result, session = self.run_test_repair_fixture("test-no-progress")
        self.assertEqual(result["execution_status"], "blocked", result)
        self.assertIn("no progress", result["report"])
        self.assertEqual(session["repair_counts"], {"spec": 0, "review": 0, "tests": 3})
        self.assertEqual(session["test_no_progress"], 3)
        self.assertIn("repair_step = 3", (self.root / "app.py").read_text())

    def test_test_budget_stops_eleventh_attempt_despite_progress(self):
        result, session = self.run_test_repair_fixture("test-limit")
        self.assertEqual(result["execution_status"], "blocked", result)
        self.assertEqual(session["repair_counts"], {"spec": 0, "review": 0, "tests": 10})
        self.assertIn("repair_step = 10", (self.root / "app.py").read_text())

    def test_targeted_green_cannot_replace_full_final_tests(self):
        result, session = self.run_test_repair_fixture("test-final-gate")
        self.assertEqual(result["execution_status"], "blocked", result)
        self.assertIn("full final gate failed", result["report"])
        self.assertEqual(session["repair_counts"], {"spec": 0, "review": 0, "tests": 1})

    def test_full_green_cannot_hide_a_still_red_repaired_target(self):
        result, session = self.run_test_repair_fixture("test-red-target")
        self.assertEqual(result["execution_status"], "blocked", result)
        self.assertIn("repaired targeted check still red", result["report"])
        self.assertEqual(session["repair_counts"], {"spec": 0, "review": 0, "tests": 1})

    def test_code_repair_preserves_work_without_rollback(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "code-fix"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        self.assertIn("# preserve working code\nrepair_0 = True", (self.root / "app.py").read_text())
        self.assertFalse(list(self.root.glob("_bmad-output/implementation-artifacts/rollback-*.patch")))
        records = json.loads((Path(result["session"]).parent / "roles.json").read_text())
        self.assertEqual(sum(r["request"]["role"] == "implementer" for r in records), 1)
        self.assertTrue(all(r["round"] == 1 for r in records if r["request"]["role"] != "implementer"))

    def test_nontrivial_code_repair_delegates_without_reimplementation(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "code-fix-delegated"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        self.assertIn("# preserve working code\nrepaired = True", (self.root / "app.py").read_text())
        self.assertFalse(list(self.root.glob("_bmad-output/implementation-artifacts/rollback-*.patch")))

    def test_delegated_triage_receives_in_place_repair_policy(self):
        self.save_config((self.root / ".auto-bmad.toml").read_text() + "\n[run]\ntriage_subagent=true\n")
        self.prepare()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "code-fix-triager"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        self.assertIn("repair_0 = True", (self.root / "app.py").read_text())
        self.assertFalse(list(self.root.glob("_bmad-output/implementation-artifacts/rollback-*.patch")))

    def test_code_repair_requires_new_review_round(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "repair-stale-reviews"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        records = json.loads((Path(result["session"]).parent / "roles.json").read_text())
        self.assertEqual(len([r for r in records if r["request"]["role"].startswith("reviewer")]), 6)

    def test_code_repair_invalidates_old_checkpoint_even_for_same_tree(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "repair-stale-checkpoint"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)

    def test_changed_code_cannot_use_reviews_without_declaring_repair(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "repair-unannounced-edit"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)

    def test_configured_budget_allows_third_repair_then_preserves_work(self):
        self.save_config((self.root / ".auto-bmad.toml").read_text() + "\n[repair_limits]\nreview = 3\n")
        self.prepare()
        profile = Path(json.loads(self.manifest.read_text())["profile"]).read_text()
        self.assertIn('\\"review\\": 3', profile)
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "repair-budget"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertEqual(result["execution_status"], "blocked", result)
        self.assertIn("repair_2 = True", (self.root / "app.py").read_text())
        self.assertFalse(result["story_completed"])
        self.assertFalse(list(self.root.glob("_bmad-output/implementation-artifacts/rollback-*.patch")))
        self.assertIn("another repair cycle", Path(result["questions_file"]).read_text())

    def test_zero_budget_keeps_initial_implementation(self):
        self.save_config((self.root / ".auto-bmad.toml").read_text() + "\n[repair_limits]\nreview = 0\n")
        self.prepare()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "repair-zero"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertEqual(result["execution_status"], "blocked", result)
        self.assertEqual((self.root / "app.py").read_text(), "answer = 42\n# preserve working code\n")

    def test_bad_spec_rollback_preserves_backup_and_rereviews_reimplementation(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "bad-spec"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        records = json.loads((Path(result["session"]).parent / "roles.json").read_text())
        self.assertEqual({r["round"] for r in records}, {0, 1})
        self.assertTrue(all(r["round"] == 1 for r in records if r["request"]["role"] != "implementer"))
        self.assertTrue(list(self.root.glob("_bmad-output/implementation-artifacts/rollback-*.patch")))

    def test_intent_gap_keeps_patch_and_blocks_tracking(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "intent-gap"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertFalse(result["story_completed"], result)
        self.assertIn("intent gap", result["error"])
        self.assertEqual((self.root / "app.py").read_text(), "answer = 0\n")
        saved = list(self.root.glob("_bmad-output/implementation-artifacts/rollback-*.patch"))
        self.assertEqual(len(saved), 1)
        self.assertIn("answer = 42", saved[0].read_text())
        self.assertIn("backlog", (self.root / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text())
        self.assertEqual(result["execution_status"], "blocked", result)
        self.assertEqual(result["questions"], "Resolve the intent.")
        self.assertTrue(result["finish"]["ok"], result)
        self.assertIn("Resolve the intent.", Path(result["questions_file"]).read_text())
        self.assertTrue(self.fixture.git(self.root, "log", "-1", "--format=%s").stdout.startswith("docs: open questions"))

    def test_blocked_finalization_refuses_hooks_from_a_changed_config(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "intent-gap-tamper"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertEqual(result["execution_status"], "needs_attention", result)
        self.assertIn("config changed", result["blocked_finish_error"])
        self.assertEqual(result["questions"], "Resolve the intent.")
        self.assertFalse((self.root / "UNEXPECTED_HOOK").exists())

    def test_blocker_before_spec_is_saved_without_marking_the_story_done(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "early-block"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertEqual(result["execution_status"], "blocked", result)
        self.assertFalse(result["spec"])
        self.assertIn("Restore the required project access", Path(result["questions_file"]).read_text())
        self.assertEqual((self.root / "app.py").read_text(), "answer = 0\n")
        self.assertIn("backlog", (self.root / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text())

    def test_host_check_fix_limit_is_saved_as_a_blocked_question(self):
        self.agent_check()
        text = (self.root / ".auto-bmad.toml").read_text() + '\n[repair_limits]\nreview=0\n'
        self.save_config(text)
        self.prepare()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "verifier-note"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=40)
        self.assertEqual(result["execution_status"], "blocked", result)
        self.assertIn("review repair limit exhausted", result["error"])
        self.assertIn("Browser assertion failed", Path(result["questions_file"]).read_text())
        self.assertIn("backlog", (self.root / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text())

    def test_followup_reenters_engine_with_existing_spec_and_original_base(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "followup"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=35)
        self.assertTrue(result["story_completed"], result)
        records = json.loads((Path(result["session"]).parent / "roles.json").read_text())
        self.assertEqual({r["pass"] for r in records}, {1, 2})
        self.assertTrue(all(r["review_base"] == self.base for r in records))
        self.assertEqual(sum(r["request"]["role"] == "implementer" for r in records), 1)

    def test_controller_death_cancels_descendants_before_releasing_lease(self):
        env = {**os.environ, "FAKE_STORY_MODE": "hang"}
        script = Path(run_story.__file__).resolve()
        proc = subprocess.Popen([sys.executable, str(script), "--manifest", str(self.manifest),
                                 "--arg", "1-3", "--allow-model", "--timeout", "30"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        try:
            marker = self.root / ".auto-bmad/fake-role.pid"
            until = time.monotonic() + 12
            while not marker.exists() and proc.poll() is None and time.monotonic() < until:
                time.sleep(0.05)
            self.assertTrue(marker.exists(), proc.poll())
            children = [int(p.read_text()) for p in self.root.glob(".auto-bmad/fake-*.pid")]
            proc.kill()
            proc.communicate(timeout=10)
            until = time.monotonic() + 6
            while any(stub.proc_info(pid) for pid in children) and time.monotonic() < until:
                time.sleep(0.05)
            self.assertTrue(all(stub.proc_info(pid) is None for pid in children))
            with lease(self.root):
                pass
            self.assertEqual((self.root / "app.py").read_text(), "answer = 42\n")
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=10)

    def test_timeout_stops_session_test_workers_and_releases_their_lock(self):
        with patch.dict(os.environ, {"FAKE_STORY_MODE": "test-hang"}):
            result = run_story.run_story(self.manifest, "1-3", timeout=6)
        self.assertEqual(result["execution_status"], "timed_out", result)
        self.assertTrue(run_story.tests_idle(self.root))

    def test_controller_waits_for_active_host_check_beyond_idle_limit(self):
        self.controller_waits_for_host_check("host-tests", 8)

    def test_controller_waits_for_checkpoint_host_check_beyond_idle_limit(self):
        self.controller_waits_for_host_check("success", 14)

    def controller_waits_for_host_check(self, mode, delay):
        command = shlex.join([sys.executable, "-c", (
            "from pathlib import Path;import time;"
            "changed=Path('app.py').read_text()=='answer = 42\\n';"
            "Path('.auto-bmad/host-check-started').touch() if changed else None;"
            f"time.sleep({delay}) if changed else None")])
        text = (self.root / ".auto-bmad.toml").read_text().replace(
            'command="true"', 'command=' + json.dumps(command))
        text = text.replace('[roles.story-runner]\nagent="dev"', '[roles.story-runner]\nagent="controller"')
        text += ('\n[agents.controller]\nadapter="codex"\nexecutable=' + json.dumps(str(self.cli)) +
                 '\nmodel="test-model"\npermissions="workspace-write"\ntimeout=6\n'
                 'environment_allowlist=["PATH","HOME","TMPDIR","FAKE_STORY_MODE"]\n')
        self.save_config(text)
        self.prepare()
        with patch.dict(os.environ, {"FAKE_STORY_MODE": mode}):
            result = run_story.run_story(self.manifest, "1-3", timeout=40)
        self.assertTrue((self.root / ".auto-bmad/host-check-started").exists(), result)
        self.assertTrue(result["story_completed"], result)
        private = Path(result["session"]).parent
        controller = json.loads((private / "controller-1.result.json").read_text())
        self.assertEqual(controller["execution_status"], "completed", controller)
        self.assertGreater(controller["seconds"], 6)
        self.assertTrue(run_story.tests_idle(self.root))
        with lease(self.root):
            pass
        self.assertEqual((self.root / "app.py").read_text(), "answer = 42\n")

    def test_host_death_holds_execution_lease_until_detached_tests_stop(self):
        proc = subprocess.Popen([sys.executable, str(Path(run_story.__file__).resolve()), "--manifest",
                                 str(self.manifest), "--arg", "1-3", "--allow-model", "--timeout", "30"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env={**os.environ, "FAKE_STORY_MODE": "test-hang"})
        try:
            until = time.monotonic() + 15
            workers = []
            while proc.poll() is None and time.monotonic() < until:
                workers = [json.loads(p.read_text()) for p in self.root.glob(".auto-bmad/tests/*.pid")]
                if workers and not run_story.tests_idle(self.root):
                    break
                time.sleep(0.05)
            self.assertTrue(workers)
            proc.kill()
            proc.communicate(timeout=10)
            until = time.monotonic() + 8
            while True:
                try:
                    with lease(self.root):
                        self.assertTrue(run_story.tests_idle(self.root), "writer lease returned before the test group stopped")
                        self.assertTrue(all(stub.proc_info(w["pid"]) is None for w in workers))
                    break
                except ValueError:
                    if time.monotonic() > until:
                        self.fail("execution lease did not return after process cleanup")
                    time.sleep(0.005)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=10)

    def test_cleanup_timeout_does_not_unlock_a_stopped_session_worker(self):
        proc = subprocess.Popen([sys.executable, str(Path(run_story.__file__).resolve()), "--manifest",
                                 str(self.manifest), "--arg", "1-3", "--allow-model", "--timeout", "30"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env={**os.environ, "FAKE_STORY_MODE": "test-hang"})
        worker = None
        try:
            until = time.monotonic() + 15
            while proc.poll() is None and time.monotonic() < until:
                workers = [json.loads(p.read_text()) for p in self.root.glob(".auto-bmad/tests/*.pid")]
                if workers and not run_story.tests_idle(self.root):
                    worker = workers[0]["pid"]
                    break
                time.sleep(0.05)
            self.assertIsNotNone(worker)
            os.kill(worker, signal.SIGSTOP)
            session = next((self.main / ".git/auto-bmad-sessions").glob("*/session.json"))
            with contextlib.redirect_stdout(io.StringIO()):
                run_story.main(["cancel", "--session", str(session)])
            stdout, stderr = proc.communicate(timeout=15)
            self.assertEqual(json.loads(stdout)["execution_status"], "needs_attention", stderr)
            with self.assertRaisesRegex(ValueError, "active execution"), lease(self.root):
                pass
        finally:
            if worker and stub.proc_info(worker):
                os.kill(worker, signal.SIGCONT)
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=10)
        until = time.monotonic() + 6
        while True:
            try:
                with lease(self.root):
                    self.assertTrue(run_story.tests_idle(self.root))
                break
            except ValueError:
                if time.monotonic() >= until:
                    self.fail("cleanup did not release its inherited execution lease")
                time.sleep(0.05)
    def test_cancel_marker_stops_running_session(self):
        env = {**os.environ, "FAKE_STORY_MODE": "hang"}
        proc = subprocess.Popen([sys.executable, str(Path(run_story.__file__).resolve()),
                                 "--manifest", str(self.manifest), "--arg", "1-3", "--allow-model"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        try:
            until = time.monotonic() + 12
            marker = self.root / ".auto-bmad/fake-role.pid"
            while not marker.exists() and proc.poll() is None and time.monotonic() < until:
                time.sleep(0.05)
            self.assertTrue(marker.exists())
            session = next((self.main / ".git/auto-bmad-sessions").glob("*/session.json"))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_story.main(["cancel", "--session", str(session)]), 0)
            stdout, stderr = proc.communicate(timeout=10)
            self.assertEqual(json.loads(stdout)["execution_status"], "cancelled", stderr)
            with lease(self.root):
                pass
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
