import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
import json
import hashlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import engine
import engine_profile
import roles
import write_profile


class ProfileTest(unittest.TestCase):
    def test_cli_transport_preserves_quality_and_level_limits(self):
        for level in ("fast", "normal", "deep"):
            original = tomllib.loads(write_profile.build(level))["workflow"]
            generated = tomllib.loads(engine_profile.build(level))["workflow"]
            self.assertEqual(original.get("review_layers", []), generated.get("review_layers", []))
            for fact in (write_profile.FACT_A, write_profile.FACT_B,
                         write_profile.FACT_C.format(n=write_profile.REPAIR_LIMIT[level])):
                self.assertIn(fact, [value.strip() for value in generated["persistent_facts"]])
            text = engine_profile.build(level, True, "pytest")
            self.assertNotIn("auto-bmad:bmad-", text)
            self.assertNotIn("completion notification", text)
            self.assertNotIn("timeout: 600000", text)
            self.assertNotIn("run_in_background", text)
            self.assertIn("CLI delegation bridge unavailable", text)
            self.assertIn("one row per finding", text)
            self.assertIn("pytest", text)


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        skill = self.root / engine.ENGINE_REL
        skill.mkdir(parents=True)
        for name in engine.REQUIRED:
            (skill / name).write_text("fixture")
        (skill / "customize.toml").write_text('[workflow]\npersistent_facts=[]\nimplementation_handoff="x"\n'
            'review_layers=[]\nactivation_steps_prepend=[]\nactivation_steps_append=[]\non_complete=""\n')
        scripts = self.root / "_bmad/scripts"
        scripts.mkdir(parents=True)
        for name in ("render_skill.py", "config_utils.py"):
            (scripts / name).write_text("fixture")
        (self.root / "_bmad/custom").mkdir()
        config = '[execution]\nbackend="cli"\n[agents.dev]\nadapter="codex"\nexecutable="codex"\n'
        config += 'model="test-model"\npermissions="workspace-write"\n'
        for role in roles.ROLES:
            config += f'[roles.{role}]\nagent="dev"\n'
        (self.root / ".auto-bmad.toml").write_text(config)
        self.env = patch.dict(os.environ, {"AUTO_BMAD_CONFIG": str(self.root / "absent.toml")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.output = Path(self.tmp.name) / "package"

    def render(self, *args, **kwargs):
        log = kwargs["directory"]
        log.mkdir()
        workflow = self.root / "_bmad/render/test/workflow.md"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("rendered snapshot")
        (workflow.parent / "manifest.json").write_text(json.dumps({"outputs": {
            "workflow.md": hashlib.sha256(workflow.read_bytes()).hexdigest()}, "inputs": {"resolved_values": {
            "customization.workflow.review_layers": []}}}))
        (log / "stdout.jsonl").write_text(f"read and follow {workflow}\n")
        self.assertEqual(args[0][1:3], ["run", "--no-cache"])
        self.assertEqual(kwargs["env"]["UV_OFFLINE"], "1")
        return {"execution_status": "completed"}

    def test_prepares_snapshot_without_starting_a_model(self):
        with patch.object(engine.shutil, "which", return_value="/test/uv"), \
                patch.object(engine, "execute", side_effect=self.render):
            result = engine.prepare(self.root, self.output)
        self.assertFalse(result["execution_ready"])
        self.assertFalse(result["model_started"])
        self.assertTrue((self.output / "manifest.json").is_file())
        self.assertIn("CLI host transport policy", Path(result["profile"]).read_text())

    def test_refuses_human_profile_before_rendering_or_creating_output(self):
        profile = self.root / "_bmad/custom/bmad-build-auto.user.toml"
        profile.write_text("my settings")
        with patch.object(engine, "execute") as render, self.assertRaisesRegex(ValueError, "not owned"):
            engine.prepare(self.root, self.output)
        render.assert_not_called()
        self.assertEqual(profile.read_text(), "my settings")
        self.assertFalse(self.output.exists())

    def test_missing_empty_custom_directory_is_created_for_a_fresh_worktree(self):
        (self.root / "_bmad/custom").rmdir()
        with patch.object(engine.shutil, "which", return_value="/test/uv"), patch.object(engine, "execute", side_effect=self.render):
            result = engine.prepare(self.root, self.output)
        self.assertTrue(Path(result["profile"]).is_file())

    def test_readiness_receipt_is_bound_to_the_engine_fingerprint(self):
        fingerprint = engine.inspect(self.root)["fingerprint"]
        receipt = Path(self.tmp.name) / "receipt.json"
        receipt.write_text(json.dumps({"engine_fingerprint": fingerprint, "story_completed": True,
                                      "execution_status": "completed", "adapter": "codex"}))
        with patch.object(engine, "VALIDATION", receipt):
            self.assertTrue(engine.inspect(self.root)["execution_ready"])
            (self.root / engine.ENGINE_REL / "workflow.md").write_text("new engine")
            self.assertFalse(engine.inspect(self.root)["execution_ready"])

    def test_refuses_snapshot_symlink_before_writing_anything(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.root / "_bmad/render").symlink_to(outside, target_is_directory=True)
        with patch.object(engine, "execute") as render, self.assertRaisesRegex(ValueError, "snapshot directory"):
            engine.prepare(self.root, self.output)
        render.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
