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
    def test_each_layer_keeps_its_own_identity_at_every_level(self):
        for level in ("fast", "normal", "deep"):
            text = "\n".join(tomllib.loads(engine_profile.build(level))["workflow"]["persistent_facts"])
            for layer in ("blind-hunter", "edge-case-hunter", "intent-alignment", "verification-gap"):
                self.assertIn(json.dumps(layer) + ": " + json.dumps(layer), text)
            self.assertIn("role context-compiler", text)
            for tier in ("reviewer-mid", "reviewer-lite", "compiler-lite"):
                self.assertNotIn(tier, text)

    def test_native_transport_preserves_quality_and_level_limits(self):
        for level in ("fast", "normal", "deep"):
            original = tomllib.loads(write_profile.build(level))["workflow"]
            generated = tomllib.loads(engine_profile.build(level))["workflow"]
            self.assertEqual(original.get("review_layers", []), generated.get("review_layers", []))
            # Native actor ownership changes, but every quality rule survives.
            restored = [value.strip().replace("a fresh triager's closure check", "the orchestrator's closure check")
                        .replace("may be applied by the assigned implementer", "may be applied by the controller")
                        .replace("Only a fresh triager may accept", "Only the orchestrator may accept")
                        .replace("a fresh triager checks every closure row", "the orchestrator checks every closure row")
                        .replace("the completed triager's current-code validation", "the orchestrator's current-code validation")
                        .replace("through the root, after persisting it in the epic's open-questions file",
                                 "for the orchestrator to persist in the epic's open-questions file")
                        for value in generated["persistent_facts"]]
            for fact in (write_profile.FACT_A, write_profile.FACT_B,
                         write_profile.CODE_FIX_POLICY, write_profile.FACT_AUTONOMY):
                self.assertIn(fact, restored)
            text = engine_profile.build(level, True, "pytest")
            self.assertNotIn("auto-bmad:bmad-", text)
            self.assertNotIn("completion notification", text)
            self.assertNotIn("timeout: 600000", text)
            self.assertNotIn("run_in_background", text)
            self.assertIn("Native host transport policy", text)
            self.assertIn("fork_turns=none", text)
            self.assertNotIn("agent_dispatch", text)
            self.assertIn("one row per finding", text)
            self.assertIn("pytest", text)
            self.assertIn("Native repair budgets per story run", text)
            self.assertNotIn("Before each repair batch call auto-bmad verify attempt", text)

    def test_native_checkpoint_contract_replaces_legacy_controller_ownership(self):
        for level in ("fast", "normal", "deep"):
            for legacy_triage in (False, True):
                with self.subTest(level=level, legacy_triage=legacy_triage):
                    text = "\n".join(tomllib.loads(engine_profile.build(level, legacy_triage, "pytest"))
                                     ["workflow"]["persistent_facts"])
                    for obsolete in ("Use followup_task for an idle existing agent", "controllers and children",
                                     "the controller waits while implementation writes",
                                     "The main chat records review attestations, runs native session check",
                                     "Do not merge branches, update sprint tracking", "policy's fallback",
                                     "Only the orchestrator may accept", "the orchestrator checks every closure row",
                                     "orchestrator's closure check", "may be applied by the controller"):
                        self.assertNotIn(obsolete, text)
                    for contract in ("thin-root-v1", "zero child slots", "fork_turns=none",
                                     "new checkpoint always gets a fresh agent",
                                     "The root never reads source, diffs, full reports, test logs or rendered workflows",
                                     "never runs or waits for tests", "never decides technical acceptance or semantic revalidation",
                                     "A fresh story-runner explicitly assigned integration/finalization owns",
                                     "A finite verifier runs native session check", "completed registered triager ID",
                                     "complete/finalize record-batch request", "returns ready",
                                     "first observes host completion and registers task-result",
                                     "A live finalizer must never complete/finalize itself",
                                     "Only a fresh triager may accept", "ALL original active-layer reports"):
                        self.assertIn(contract, text)

    def test_legacy_triage_switch_cannot_restore_root_or_controller_triage(self):
        self.assertEqual(engine_profile.build("normal", False, "pytest"),
                         engine_profile.build("normal", True, "pytest"))


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
        config = '[execution]\nbackend="native"\n[agents.dev]\nadapter="codex"\nexecutable="codex"\n'
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
        self.assertTrue(result["execution_ready"])
        self.assertFalse(result["model_started"])
        self.assertTrue((self.output / "manifest.json").is_file())
        self.assertIn("Native host transport policy", Path(result["profile"]).read_text())

    def test_prepared_artifact_keeps_roles_and_finite_native_contract(self):
        with patch.object(engine.shutil, "which", return_value="/test/uv"), \
                patch.object(engine, "execute", side_effect=self.render):
            result = engine.prepare(self.root, self.output, "deep")
        profile_bytes = Path(result["profile"]).read_bytes()
        self.assertEqual(profile_bytes, (self.output / "profile.toml").read_bytes())
        self.assertEqual(hashlib.sha256(profile_bytes).hexdigest(), result["profile_hash"])
        facts = tomllib.loads(profile_bytes.decode())["workflow"]["persistent_facts"]
        text = "\n".join(facts)
        self.assertIn("thin-root-v1", text)
        self.assertIn("Each task has zero child slots", text)
        self.assertIn("completed registered triager ID", text)
        self.assertIn("first observes host completion and registers task-result", text)
        self.assertNotIn("Use followup_task for an idle existing agent", text)
        self.assertNotIn("runs native session check, and accepts complete", text)
        self.assertEqual(result["delegation"]["transport"], "native-subagents")
        self.assertEqual(set(result["roles"]), set(roles.ROLES))
        for profile in result["roles"].values():
            self.assertEqual(profile["model"], "test-model")

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

    def test_contract_readiness_does_not_claim_live_agent_validation(self):
        result = engine.inspect(self.root)
        self.assertTrue(result["execution_ready"])
        self.assertFalse(result["inference_checked"])
        self.assertFalse(result["host_capabilities_checked"])
        before = result["fingerprint"]
        (self.root / engine.ENGINE_REL / "workflow.md").write_text("new engine")
        self.assertNotEqual(before, engine.inspect(self.root)["fingerprint"])

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
