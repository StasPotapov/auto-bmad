"""CLI config is additive and fails closed instead of falling back to another agent."""
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
        "review": {"adapter": "kimi", "executable": "kimi", "model": "test-kimi",
                   "permissions": "read-only"}},
        "roles": {role: {"agent": "dev"} for role in roles.ROLES}}


class AgentConfigTest(unittest.TestCase):
    def test_legacy_output_is_unchanged_without_opt_in(self):
        cfg = {"roles": {"implementer": {"model": "sonnet", "effort": "high"}}}
        self.assertEqual(agent_config.resolve(cfg)["roles"], roles.resolve(cfg)[0])

    def test_levels_route_profiles_without_mutating_input(self):
        cfg = config()
        cfg["routing"] = {"deep": {"reviewer": {"agent": "review"}}}
        before = copy.deepcopy(cfg)
        self.assertEqual(agent_config.resolve(cfg, "normal")["roles"]["reviewer"]["adapter"], "codex")
        out = agent_config.resolve(cfg, "deep")
        self.assertEqual(out["roles"]["reviewer"]["adapter"], "kimi")
        self.assertEqual(cfg, before)

    def test_missing_routes_explicitly_report_legacy_claude(self):
        cfg = config()
        del cfg["roles"]["verifier"]
        out = agent_config.resolve(cfg)["roles"]["verifier"]
        self.assertEqual((out["profile_id"], out["adapter"]), ("legacy:verifier", "claude"))

    def test_bad_profiles_and_routes_do_not_fall_back(self):
        changes = [lambda c: c["roles"]["implementer"].update(agent="missing"),
                   lambda c: c["roles"]["implementer"].update(model="opus"),
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

    def test_four_layers_and_strict_reader(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            files = [root / f"{i}.toml" for i in range(4)]
            files[0].write_text('[execution]\nbackend="cli"\n[agents.dev]\nadapter="codex"\n'
                                'executable="codex"\nmodel="one"\npermissions="workspace-write"\n')
            files[1].write_text('[agents.dev]\nmodel="two"\n')
            files[2].write_text('[roles.implementer]\nagent="dev"\n')
            files[3].write_text('[agents.dev]\nmodel="three"\n')
            with patch.object(ext, "layers", return_value=list(zip(["defaults", "user", "project", "local"], files))):
                out = agent_config.read(d)
                self.assertEqual(out["roles"]["implementer"]["model"], "three")
                self.assertEqual(len(out["sources"]), 4)
                files[3].write_text('[broken')
                with self.assertRaisesRegex(ValueError, "cannot read config layer"):
                    agent_config.read(d)
                self.assertTrue(ext.load(d)[2])  # old callers still get a warning

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
