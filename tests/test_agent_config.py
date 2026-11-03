"""Native role descriptors preserve configuration and fail closed on invalid routes."""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_config
import roles
import ext


def config():
    return {"execution": {"backend": "cli"}, "agents": {
        "dev": {"adapter": "codex", "executable": "codex", "model": "test-model",
                "permissions": "workspace-write"},
        "review": {"adapter": "codex", "executable": "codex", "model": "test-review",
                   "permissions": "read-only"}},
        "roles": {role: {"agent": "dev"} for role in roles.ROLES}}


class AgentConfigTest(unittest.TestCase):
    def test_auto_main_is_opt_in_for_compact_and_advanced_profiles(self):
        for cfg in ({'execution': {'backend': 'cli'}}, config()):
            self.assertEqual(agent_config.resolve(cfg)['merge_policy'], 'manual')
            cfg['execution']['merge_policy'] = 'auto-main'
            self.assertEqual(agent_config.resolve(cfg)['merge_policy'], 'auto-main')
            cfg['execution']['merge_policy'] = 'force'
            with self.assertRaises(ValueError):
                agent_config.resolve(cfg)

    def assert_legacy_roles_preserved(self, cfg, actual):
        expected, errors, _ = roles.resolve(cfg)
        self.assertFalse(errors)
        self.assertEqual(set(actual), set(expected))
        for name, legacy in expected.items():
            self.assertEqual({key: actual[name][key] for key in legacy}, legacy)
            self.assertEqual(actual[name]["adapter"], "claude")
            self.assertEqual(actual[name]["permissions"], "inherited")
            self.assertTrue(Path(actual[name]["prompt"]).is_file())

    def test_legacy_values_are_preserved_with_native_metadata(self):
        cfg = {"roles": {"implementer": {"model": "sonnet", "effort": "high"}}}
        self.assert_legacy_roles_preserved(cfg, agent_config.resolve(cfg)["roles"])

    def test_levels_route_profiles_without_mutating_input(self):
        cfg = config()
        cfg["routing"] = {"deep": {"blind-hunter": {"agent": "review"}}}
        before = copy.deepcopy(cfg)
        self.assertEqual(agent_config.resolve(cfg, "normal")["roles"]["blind-hunter"]["adapter"], "codex")
        out = agent_config.resolve(cfg, "deep")
        self.assertEqual(out["roles"]["blind-hunter"]["model"], "test-review")
        self.assertEqual(cfg, before)

    def test_missing_routes_explicitly_report_legacy_claude(self):
        cfg = config()
        del cfg["roles"]["verifier"]
        with self.assertRaisesRegex(ValueError, "explicit Codex route"):
            agent_config.resolve(cfg)

    def test_bad_profiles_and_routes_do_not_fall_back(self):
        changes = [lambda c: c["agents"]["dev"].update(adapter="kimi"),
                   lambda c: c["roles"]["implementer"].update(agent="missing"),
                   lambda c: c["roles"]["implementer"].update(unknown="opus"),
                   lambda c: c["agents"]["dev"].update(timeout=True),
                   lambda c: c["agents"]["dev"].update(arguments=["--ignore-rules"]),
                   lambda c: c["agents"]["dev"].update(permissions="danger-full-access"),
                   lambda c: c["agents"]["dev"].update(model="CONFIGURE_MODEL"),
                   lambda c: c["agents"]["dev"].update(output_protocol="wrong"),
                   lambda c: c.update(routing={"deep": {"unknown": {"agent": "dev"}}})]
        for change in changes:
            cfg = config()
            change(cfg)
            with self.subTest(config=cfg), self.assertRaises(ValueError):
                agent_config.resolve(cfg)

    def test_new_routes_cannot_run_through_old_plugin(self):
        self.assertTrue(roles.resolve(config())[1])
        self.assertTrue(roles.resolve({"roles": {"implementer": {"agent": "dev"}}})[1])
        with self.assertRaises(ValueError):
            agent_config.resolve({"roles": {"implementer": {"agent": "dev"}}})

    def test_direct_cli_route_and_native_overrides_coexist(self):
        cfg = config()
        cfg["roles"]["implementer"].update(model="sonnet", effort="low", provider="anthropic")
        original = copy.deepcopy(cfg)
        cli = agent_config.resolve(ext.executor_config(cfg, "codex"))["roles"]["implementer"]
        native = agent_config.resolve(ext.executor_config(cfg, "claude"))["roles"]["implementer"]
        self.assertEqual((cli["profile_id"], cli["model"]), ("dev", "test-model"))
        self.assertEqual((native["model"], native["effort"]), ("sonnet", "low"))
        self.assertEqual(cfg, original)

    def test_explicit_native_selection_masks_inherited_cli_routes(self):
        cfg = config()
        cfg["execution"]["backend"] = "legacy-plugin"
        cfg["roles"]["implementer"]["model"] = "sonnet"
        original = copy.deepcopy(cfg)
        resolved = agent_config.resolve(cfg)
        self.assertEqual(resolved["backend"], "legacy-plugin")
        self.assertEqual(resolved["roles"]["implementer"]["model"], "sonnet")
        self.assert_legacy_roles_preserved(cfg, resolved["roles"])
        self.assertFalse(roles.resolve(cfg)[1])
        self.assertTrue(resolved["warnings"])
        self.assertEqual(cfg, original)
        del cfg["execution"]
        with self.assertRaises(ValueError):
            agent_config.resolve(cfg)

    def test_four_layers_and_strict_reader(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            files = [root / f"{i}.toml" for i in range(4)]
            files[0].write_text('[execution]\nbackend="cli"\n[agents.dev]\nadapter="codex"\n'
                                'executable="codex"\nmodel="one"\npermissions="workspace-write"\n')
            files[1].write_text('[agents.dev]\nmodel="two"\n')
            files[2].write_text("".join(f'[roles.{role}]\nagent="dev"\n' for role in roles.ROLES))
            files[3].write_text('[agents.dev]\nmodel="three"\n')
            with patch.object(ext, "layers", return_value=list(zip(["defaults", "user", "project", "local"], files))):
                out = agent_config.read(d)
                self.assertEqual(out["roles"]["implementer"]["model"], "three")
                self.assertEqual(len(out["sources"]), 4)
                files[3].write_text('[broken')
                with self.assertRaisesRegex(ValueError, "cannot read config layer"):
                    agent_config.read(d)
                self.assertTrue(ext.load(d)[2])  # old callers still get a warning

    def test_cli_alias_preserves_models_and_returns_native_only_contract(self):
        cfg = {"execution": {"backend": "cli", "merge_policy": "auto-main"},
               "executors": {"codex": {"model": "saved", "effort": "high",
                   "executable": "/removed/codex", "environment_allowlist": ["PATH"],
                   "levels": {"deep": {"review_model": "saved-review"}}}}}
        before = copy.deepcopy(cfg)
        out = agent_config.resolve(cfg, "deep")
        self.assertEqual(out["backend"], "native")
        self.assertEqual(out["merge_policy"], "auto-main")
        self.assertEqual(out["roles"]["implementer"]["model"], "saved")
        self.assertEqual(out["roles"]["blind-hunter"]["model"], "saved-review")
        self.assertTrue(any("retired" in line for line in out["warnings"]))
        for role, selected in out["roles"].items():
            self.assertEqual(selected["permissions"], "inherited")
            self.assertNotIn("executable", selected)
            self.assertNotIn("environment_allowlist", selected)
            self.assertTrue(Path(selected["prompt"]).is_file())
        self.assertEqual(cfg, before)

    def test_native_doctor_does_not_probe_cli_or_claim_live_support(self):
        import doctor
        plan = agent_config.resolve({"execution": {"backend": "native"}})
        plan["config_hash"] = "test"
        with patch.object(agent_config, "read", return_value=plan), patch("subprocess.run") as subprocess_run:
            out = doctor.check("unused", "normal")
        subprocess_run.assert_not_called()
        self.assertTrue(out["ok"])
        self.assertFalse(out["inference_checked"])
        self.assertFalse(out["host_capabilities_checked"])
        self.assertEqual(out["permissions"], "inherited")

    def test_strict_loading_rejects_broken_or_inaccessible_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            broken = root / "broken"
            broken.symlink_to(root / "missing")
            for path in (broken, broken / "config.toml"):
                with patch.object(ext, "layers", return_value=[("local", str(path))]):
                    with self.assertRaisesRegex(ValueError, "cannot read config layer"):
                        ext.load(d, strict=True)
                    self.assertEqual(ext.load(d)[2], [])
            with patch.object(ext, "layers", return_value=[("local", str(root / "denied"))]), \
                    patch.object(ext.os, "lstat", side_effect=PermissionError("denied")):
                with self.assertRaisesRegex(ValueError, "denied"):
                    ext.load(d, strict=True)


if __name__ == "__main__":
    unittest.main()
