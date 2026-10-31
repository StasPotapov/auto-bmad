import copy
import os
from pathlib import Path
import sys
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_config
import ext
import setup_agents
import test_setup_agents


class CompactConfigTest(unittest.TestCase):
    def test_builtin_models_and_permissions_on_all_levels(self):
        for level in ("fast", "normal", "deep"):
            out = agent_config.resolve({"execution": {"backend": "cli"}}, level)
            for role, selected in out["roles"].items():
                review = role in agent_config.REVIEWERS
                self.assertEqual(selected["model"], "gpt-6-astra" if review else "gpt-6.1-sol")
                self.assertEqual(selected["effort"], "high")
                self.assertEqual(selected["permissions"], "read-only" if review else "workspace-write")
        self.assertEqual(agent_config.resolve({})["backend"], "legacy-plugin")

    def test_common_level_and_role_settings(self):
        cfg = {"execution": {"backend": "cli"}, "executors": {"codex": {
            "model": "common", "review_model": "review", "effort": "medium",
            "roles": {"verifier": {"model": "browser"}},
            "levels": {"fast": {"model": "fast-model", "review_effort": "low"},
                       "deep": {"review_model": "deep-review", "roles": {"verifier": {"effort": "high"}}}}}}}
        original = copy.deepcopy(cfg)
        normal = agent_config.resolve(cfg, "normal")["roles"]
        fast = agent_config.resolve(cfg, "fast")["roles"]
        deep = agent_config.resolve(cfg, "deep")["roles"]
        self.assertEqual(normal["implementer"]["model"], "common")
        self.assertEqual(fast["implementer"]["model"], "fast-model")
        self.assertEqual(fast["reviewer"]["effort"], "low")
        self.assertEqual(deep["reviewer"]["model"], "deep-review")
        self.assertEqual(deep["verifier"]["model"], "browser")
        self.assertEqual(deep["verifier"]["effort"], "high")
        self.assertEqual(cfg, original)

    def test_invalid_inactive_levels_fail_closed(self):
        for settings in ({"levels": {"turbo": {}}}, {"modle": "typo"},
                         {"levels": {"deep": {"roles": {"unknown": {"model": "test"}}}}},
                         {"levels": {"deep": {"timeout": 0}}},
                         {"roles": {"reviewer": {"permissions": "workspace-write"}}}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                agent_config.resolve({"execution": {"backend": "cli"}, "executors": {"codex": settings}}, "fast")
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            agent_config.resolve({"execution": {"backend": "cli"}, "executors": {"codxe": {}}})


class CompactSetupTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_setup_agents.AgentSetupTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.repo, self.config = self.fixture.repo, self.fixture.config
        self.cli, self.codex = self.fixture.cli, self.fixture.codex

    def test_defaults_need_no_model_and_do_not_duplicate_routes(self):
        out = self.cli("agent", "--agent", "codex", "--add", "--write")
        self.assertTrue(out["defaults_used"])
        cfg = tomllib.loads(self.config.read_text())
        self.assertEqual(cfg["executors"]["codex"], {})
        self.assertNotIn("agents", cfg)
        self.assertNotIn("routing", cfg)
        self.assertEqual(agent_config.read(str(self.repo))["backend"], "legacy-plugin")
        with patch.dict(os.environ, {ext.EXECUTOR_ENV: "codex"}):
            self.assertEqual(agent_config.read(str(self.repo))["roles"]["reviewer"]["model"], "gpt-6-astra")

    def test_level_and_local_changes_preserve_other_levels(self):
        self.cli("agent", "--agent", "codex", "--model", "shared", "--write")
        self.cli("agent", "--agent", "codex", "--level", "fast", "--model", "quick", "--write")
        original = self.config.read_bytes()
        self.cli("agent", "--agent", "codex", "--level", "deep", "--review-model", "local-review",
                 "--layer", "local", "--write")
        self.assertEqual(agent_config.read(str(self.repo), "fast")["roles"]["implementer"]["model"], "quick")
        self.assertEqual(agent_config.read(str(self.repo), "normal")["roles"]["implementer"]["model"], "shared")
        self.assertEqual(agent_config.read(str(self.repo), "deep")["roles"]["reviewer"]["model"], "local-review")
        self.assertEqual(self.config.read_bytes(), original)

    def test_preview_reports_requested_level_and_accepts_unrelated_local_override(self):
        self.cli("agent", "--agent", "codex", "--model", "shared", "--write")
        self.cli("agent", "--agent", "codex", "--level", "deep", "--model", "slow", "--write")
        self.cli("agent", "--agent", "codex", "--level", "deep", "--review-model", "local-review",
                 "--layer", "local", "--write")
        normal = self.cli("agent", "--agent", "codex", "--model", "shared-new", "--write")
        self.assertEqual(normal["resolved_roles"]["implementer"]["model"], "shared-new")
        fast = self.cli("agent", "--agent", "codex", "--level", "fast", "--model", "quick", "--write")
        self.assertEqual(fast["resolved_roles"]["implementer"]["model"], "quick")
        self.assertEqual(agent_config.read(str(self.repo), "deep")["roles"]["reviewer"]["model"], "local-review")
        self.cli("agent", "--agent", "codex", "--level", "deep", "--review-model", "conflict", "--write", ok=False)

    def test_project_compaction_never_copies_local_values_and_local_compaction_preserves_them(self):
        self.codex("--write")
        before = self.config.read_bytes()
        local = self.repo / ".auto-bmad.local.toml"
        original_local = '[agents.setup-codex-write]\nmodel="local-model"\nexecutable="/machine-only/codex"\n'
        local.write_text(original_local)
        self.cli("agent", "--agent", "codex", "--compact", "--write", ok=False)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(local.read_text(), original_local)
        self.cli("agent", "--agent", "codex", "--compact", "--layer", "local", "--write")
        self.assertEqual(self.config.read_bytes(), before)
        selected = agent_config.read(str(self.repo))["roles"]["implementer"]
        self.assertEqual(selected["model"], "local-model")
        self.assertEqual(selected["executable"], "/machine-only/codex")

    def test_compaction_preserves_every_role_at_every_level(self):
        self.config.write_text('[roles.implementer]\nmodel="sonnet"\n')
        self.codex("--review-model", "test-review", "--write")
        cfg = tomllib.loads(self.config.read_text())
        cfg["agents"]["deep-review"] = {**cfg["agents"]["setup-codex-review"], "model": "deep-review"}
        cfg["routing"]["deep"]["reviewer"] = {"agent": "deep-review"}
        self.config.write_text(setup_agents.edit(self.config.read_text(), {"agents": cfg["agents"], "routing": cfg["routing"]}))
        before = self.config.read_bytes()
        saved = {level: agent_config.read(str(self.repo), level)["roles"] for level in ("fast", "normal", "deep")}
        out = self.cli("agent", "--agent", "codex", "--compact", "--write")
        self.assertEqual(Path(out["backup"]).read_bytes(), before)
        compact = tomllib.loads(self.config.read_text())
        self.assertNotIn("routing", compact)
        self.assertEqual(compact["roles"]["implementer"]["model"], "sonnet")
        for level, previous in saved.items():
            now = agent_config.read(str(self.repo), level)["roles"]
            for role in previous:
                self.assertEqual({k:v for k,v in now[role].items() if k != "profile_id"},
                                 {k:v for k,v in previous[role].items() if k != "profile_id"})
