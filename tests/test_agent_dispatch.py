import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_dispatch
import engine
from execution_state import lease, revision
import test_engine_profile


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_engine_profile.PrepareTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.main = self.fixture.root
        config = self.main / ".auto-bmad.toml"
        config.write_text(config.read_text().replace('[roles.reviewer]\nagent="dev"',
                          '[roles.reviewer]\nagent="read"') +
                          '[agents.read]\nadapter="codex"\nexecutable="codex"\nmodel="test-review"\npermissions="read-only"\n')
        (self.main / ".gitignore").write_text('_bmad/render/\n.auto-bmad/\n*.user.toml\n')
        (self.main / "_bmad/custom/.gitkeep").write_text("")
        (self.main / "app.py").write_text("answer = 0\n")
        self.git(self.main, "add", "-A")
        self.git(self.main, "-c", "user.name=test", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                 "commit", "-qm", "baseline")
        self.root = self.main.parent / "isolated"
        self.git(self.main, "worktree", "add", "-b", "test-role", str(self.root), "HEAD")
        self.fixture.root = self.root
        with patch.object(engine.shutil, "which", return_value="/test/uv"), \
                patch.object(engine, "execute", side_effect=self.fixture.render):
            engine.prepare(self.root, self.fixture.output)
        self.manifest = self.fixture.output / "manifest.json"
        self.request = self.root.parent / "request.json"
        self.role("implementer")

    def git(self, root, *args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)

    def role(self, role):
        self.request.write_text(json.dumps({"role": role, "task_id": "1-3", "base_commit": revision(self.root),
                                           "prompt": "Read the supplied spec and follow its original handoff."}))

    def dispatch(self, mode="read"):
        fake = str(Path(__file__).with_name("fake_role_cli.py"))
        detection = {"executable": sys.executable, "capabilities": {"read_only_enforcement": "supported"}}
        with patch.object(agent_dispatch.agent_adapters, "detect", return_value=detection), \
                patch.object(agent_dispatch.agent_adapters, "argv", return_value=[sys.executable, fake, mode]):
            return agent_dispatch.dispatch(self.manifest, self.request)

    def test_implementer_routes_and_preserves_change_evidence(self):
        with patch.object(agent_dispatch, "execute", wraps=agent_dispatch.execute) as run:
            result = self.dispatch("write")
        prompt = run.call_args.kwargs["stdin"]
        self.assertIn("You write code from a ready specification", prompt)
        self.assertIn("auto-bmad test", prompt)
        self.assertNotIn("timeout: 600000", prompt)
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["profile_id"], "dev")
        self.assertFalse(result["story_completed"])
        self.assertIn("app.py", result["changed_files"])
        self.assertTrue((Path(result["attempt"]) / "result.json").is_file())

    def test_reviewer_uses_its_profile_and_detects_unexpected_writes(self):
        self.role("reviewer")
        self.assertEqual(self.dispatch()["profile_id"], "read")
        result = self.dispatch("write")
        self.assertEqual(result["execution_status"], "failed")
        self.assertEqual(result["error"]["kind"], "permission")
        self.assertEqual((self.root / "app.py").read_text(), "answer = 42\n")

    def test_stale_config_base_and_malformed_result_fail_closed(self):
        self.assertEqual(self.dispatch("invalid")["error"]["kind"], "protocol")
        request = json.loads(self.request.read_text())
        request["base_commit"] = "0" * 40
        self.request.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError, "exact base"):
            self.dispatch()
        self.role("implementer")
        config = self.root / ".auto-bmad.toml"
        config.write_text(config.read_text() + '[run]\ntriage_subagent=false\n')
        with self.assertRaisesRegex(ValueError, "config changed"):
            self.dispatch()

    def test_controller_lease_prevents_another_writer(self):
        with lease(self.root), self.assertRaisesRegex(ValueError, "active execution"):
            self.dispatch()

    def test_changed_engine_profile_is_rejected_without_starting_a_role(self):
        profile = self.root / "_bmad/custom/bmad-build-auto.user.toml"
        profile.write_text(profile.read_text() + "# changed\n")
        with patch.object(agent_dispatch, "execute") as run, self.assertRaisesRegex(ValueError, "engine profile changed"):
            self.dispatch()
        run.assert_not_called()

    def test_submodule_contents_are_included_in_read_only_fingerprint(self):
        source = self.main.parent / "library-source"
        source.mkdir()
        self.git(source, "init", "-q")
        (source / "app.py").write_text("answer = 0\n")
        self.git(source, "add", ".")
        self.git(source, "-c", "user.name=test", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                 "commit", "-qm", "library")
        self.git(self.root, "-c", "protocol.file.allow=always", "submodule", "add", str(source), "library")
        self.role("reviewer")
        self.assertEqual(self.dispatch()["execution_status"], "completed")
        result = self.dispatch("write-submodule")
        self.assertEqual(result["error"]["kind"], "permission")

    def test_main_tree_is_never_an_execution_target(self):
        data = json.loads(self.manifest.read_text())
        data["repo"] = str(self.main)
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "main tree"):
            self.dispatch()

    def test_branch_switch_is_reported_without_erasing_the_work(self):
        result = self.dispatch("switch-branch")
        self.assertEqual(result["execution_status"], "failed")
        self.assertIn("branch", result["error"]["message"])
        self.assertTrue((Path(result["attempt"]) / "result.json").is_file())

    def test_no_model_consent_means_no_dispatch(self):
        with patch.object(agent_dispatch, "dispatch") as run, contextlib.redirect_stdout(io.StringIO()):
            code = agent_dispatch.main(["execute", "--manifest", str(self.manifest), "--request", str(self.request)])
        self.assertEqual(code, 2)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
