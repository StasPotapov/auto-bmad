import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_config
from execution_state import lease
import setup
import setup_agents

SCRIPT = Path(setup.__file__).resolve()
FAKE = Path(__file__).with_name("fake_story_cli.py").resolve()


class AgentSetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.env = patch.dict(os.environ, {"AUTO_BMAD_CONFIG": str(self.repo / "absent.toml")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = self.repo / ".auto-bmad.toml"

    def cli(self, *args, ok=True):
        proc = subprocess.run([sys.executable, str(SCRIPT), *args, "--repo", str(self.repo)],
                              capture_output=True, text=True)
        result = json.loads(proc.stdout)
        if ok:
            self.assertEqual(proc.returncode, 0, result)
        else:
            self.assertNotEqual(proc.returncode, 0, result)
            self.assertFalse(result.get("written"))
        return result

    def codex(self, *args, **kwargs):
        return self.cli("agent", "--agent", "codex", "--model", "test-model",
                        "--executable", str(FAKE), "--disable-agent-checks", *args, **kwargs)

    def test_legacy_init_and_config_keep_their_backend(self):
        self.cli("init", "--write")
        original = self.config.read_bytes()
        self.cli("init", "--write", ok=False)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(agent_config.read(str(self.repo))["backend"], "legacy-plugin")

    def test_preview_has_no_files_or_model_calls(self):
        result = self.codex()
        self.assertFalse(result["model_started"])
        self.assertFalse(self.config.exists())
        self.assertFalse((self.repo / ".auto-bmad").exists())
        with patch("agent_adapters.detect") as detect:
            setup_agents.configure(str(self.repo), "", self.args())
        detect.assert_not_called()

    def args(self, **kwargs):
        from types import SimpleNamespace
        values = dict(agent="codex", model="test-model", executable=str(FAKE), effort="high",
                      timeout=3600, disable_agent_checks=True, layer="project", write=False)
        return SimpleNamespace(**(values | kwargs))

    def test_migration_preserves_old_settings_and_exact_backup(self):
        old = ('# owner\r\n[run]\r\nlevel="deep" # keep\r\nparallel="aggressive"\r\n'
               '[roles.implementer]\r\nmodel="sonnet"\r\neffort="medium"\r\n'
               '[[hook]]\r\nname="journal"\r\nevents=["story-done"]\r\n'
               'command="echo done"\r\n[[verify]]\r\nname="project-tests"\r\ncommand="pytest -q"\r\n')
        self.config.write_bytes(old.encode())
        out = self.codex("--review-model", "test-review", "--review-effort", "medium", "--env", "JAVA_HOME", "--write")
        self.assertEqual(Path(out["backup"]).read_bytes(), old.encode())
        self.assertEqual(Path(out["backup"]).stat().st_mode & 0o777, 0o600)
        cfg = tomllib.loads(self.config.read_text())
        for key in ("run", "roles", "hook"):
            self.assertEqual(cfg[key], tomllib.loads(old)[key])
        self.assertIn('level="deep" # keep\r\n', self.config.read_bytes().decode())
        for level in ("fast", "normal", "deep"):
            resolved = agent_config.read(str(self.repo), level)
            self.assertTrue(all(p["adapter"] == "codex" for p in resolved["roles"].values()))
            self.assertEqual(resolved["roles"]["reviewer"]["permissions"], "read-only")
            self.assertEqual(resolved["roles"]["reviewer"]["model"], "test-review")
            self.assertEqual(resolved["roles"]["implementer"]["model"], "test-model")
            self.assertIn("JAVA_HOME", resolved["roles"]["implementer"]["environment_allowlist"])
        self.assertEqual(next(v for v in cfg["verify"] if v["name"] == "project-tests")["command"], "pytest -q")

    def test_repeated_selection_is_idempotent(self):
        self.codex("--write")
        content = self.config.read_bytes()
        out = self.codex("--write")
        self.assertFalse(out["written"])
        self.assertIsNone(out["backup"])
        self.assertEqual(self.config.read_bytes(), content)

    def test_agent_checks_are_preserved_by_default(self):
        out = self.cli("agent", "--agent", "codex", "--model", "test-model", "--write")
        self.assertEqual(out["disabled_agent_checks"], [])
        self.assertFalse(tomllib.loads(self.config.read_text()).get("verify"))
        out = self.codex("--write")
        self.assertEqual(set(out["disabled_agent_checks"]), {"adbm", "mockmatch"})

    def test_codex_migration_keeps_mockmatch_project_settings_enabled(self):
        original = ('[[verify]]\nname="mockmatch"\nenabled=true\nserve="npm run dev"\n'
                    'url="http://localhost:5173"\ndesign="design/home.html"\n')
        self.config.write_text(original)
        self.cli("agent", "--agent", "codex", "--model", "test-model", "--write")
        cfg = tomllib.loads(self.config.read_text())
        self.assertEqual(cfg["verify"], tomllib.loads(original)["verify"])

    def test_custom_agent_check_is_preserved_when_disabled(self):
        self.config.write_text('[[verify]]\nname="custom"\nkind="agent"\ninstructions="keep me"\n')
        self.codex("--write")
        item = next(v for v in tomllib.loads(self.config.read_text())["verify"] if v["name"] == "custom")
        self.assertEqual(item["instructions"], "keep me")
        self.assertFalse(item["enabled"])

    def test_local_override_blocks_project_change_and_can_be_configured(self):
        local = self.repo / ".auto-bmad.local.toml"
        local.write_text('[execution]\nbackend="legacy-plugin"\n')
        out = self.codex("--write", ok=False)
        self.assertIn("higher config layer", out["error"])
        self.assertFalse(self.config.exists())
        self.codex("--layer", "local", "--write")
        self.assertEqual(agent_config.read(str(self.repo))["backend"], "cli")
        self.assertEqual(subprocess.run(["git", "-C", str(self.repo), "check-ignore", str(local)],
                                       capture_output=True).returncode, 0)

    def test_local_profile_or_checks_override_cannot_silently_win(self):
        local = self.repo / ".auto-bmad.local.toml"
        for text in ('[agents.setup-codex-write]\nmodel="another-model"\n',
                     '[[verify]]\nname="adbm"\nenabled=true\n'):
            local.write_text(text)
            self.codex("--write", ok=False)
            self.assertFalse(self.config.exists())

    def test_tracked_local_config_is_not_rewritten_as_a_private_selection(self):
        local = self.repo / ".auto-bmad.local.toml"
        local.write_text("# tracked local\n")
        subprocess.run(["git", "-C", str(self.repo), "add", local.name], check=True)
        self.codex("--layer", "local", "--write", ok=False)
        self.assertEqual(local.read_text(), "# tracked local\n")

    def test_switch_to_native_preserves_legacy_role_settings(self):
        self.config.write_text('[roles.implementer]\nmodel="sonnet"\n')
        self.codex("--write")
        saved = tomllib.loads(self.config.read_text())
        self.cli("agent", "--agent", "claude", "--write")
        cfg = tomllib.loads(self.config.read_text())
        self.assertEqual(cfg["agents"], saved["agents"])
        self.assertEqual(cfg["routing"], saved["routing"])
        plan = agent_config.read(str(self.repo))
        self.assertEqual(plan["backend"], "legacy-plugin")
        self.assertEqual(plan["roles"]["implementer"]["model"], "sonnet")

    def test_one_config_switches_executors_without_replacing_saved_profiles(self):
        self.config.write_text('[roles.implementer]\nmodel="sonnet"\neffort="medium"\n'
                               '[[verify]]\nname="project-tests"\ncommand="scripts/check.sh"\n'
                               '[[hook]]\nname="fixture"\nevents=["story-done"]\ncommand="true"\n')
        self.codex("--review-model", "test-review", "--review-effort", "low", "--effort", "xhigh",
                   "--timeout", "123", "--env", "JAVA_HOME", "--write")
        saved = tomllib.loads(self.config.read_text())
        profiles = {level: agent_config.read(str(self.repo), level)["roles"] for level in ("fast", "normal", "deep")}
        self.cli("agent", "--agent", "claude", "--write")
        self.assertEqual(agent_config.read(str(self.repo))["roles"]["implementer"]["model"], "sonnet")
        self.cli("agent", "--agent", "codex", "--write")
        self.assertEqual(tomllib.loads(self.config.read_text()), saved)
        for level in profiles:
            self.assertEqual(agent_config.read(str(self.repo), level)["roles"], profiles[level])
        repeated = self.cli("agent", "--agent", "codex", "--write")
        self.assertFalse(repeated["written"])
        self.assertIsNone(repeated["backup"])

    def test_local_executor_selection_reuses_project_profiles_without_copying_them(self):
        self.codex("--write")
        original = self.config.read_bytes()
        self.cli("agent", "--agent", "claude", "--layer", "local", "--write")
        self.cli("agent", "--agent", "codex", "--layer", "local", "--write")
        local = tomllib.loads((self.repo / ".auto-bmad.local.toml").read_text())
        self.assertEqual(set(local), {"execution"})
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(agent_config.read(str(self.repo))["roles"]["implementer"]["model"], "test-model")

    def test_reuse_never_silently_changes_missing_or_foreign_cli_profiles(self):
        self.cli("agent", "--agent", "codex", "--write", ok=False)
        self.assertFalse(self.config.exists())
        self.codex("--write")
        self.cli("agent", "--agent", "claude", "--write")
        original = self.config.read_bytes()
        self.cli("agent", "--agent", "codex", "--effort", "high", "--write", ok=False)
        self.assertEqual(self.config.read_bytes(), original)
        self.config.write_text(self.config.read_text().replace('"codex"', '"kimi"'))
        foreign = self.config.read_bytes()
        self.cli("agent", "--agent", "codex", "--write", ok=False)
        self.assertEqual(self.config.read_bytes(), foreign)

    def test_local_native_choice_masks_project_cli_without_editing_project(self):
        self.codex("--write")
        original = self.config.read_bytes()
        out = self.cli("agent", "--agent", "claude", "--layer", "local", "--write")
        self.assertTrue(any("inactive" in note for note in out["notes"]))
        checked = self.cli("check")
        self.assertTrue(any("inactive" in note for note in checked["execution"]["warnings"]))
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(agent_config.read(str(self.repo))["backend"], "legacy-plugin")
        import roles
        from ext import load
        self.assertFalse(roles.resolve(load(str(self.repo), strict=True)[0])[1])

    def test_project_native_choice_masks_personal_cli_without_editing_personal(self):
        preview = self.codex()
        personal = self.repo / "personal.toml"
        personal.write_text(preview["content"])
        with patch.dict(os.environ, {"AUTO_BMAD_CONFIG": str(personal)}):
            self.cli("agent", "--agent", "claude", "--write")
            self.assertEqual(agent_config.read(str(self.repo))["backend"], "legacy-plugin")
        self.assertEqual(personal.read_text(), preview["content"])

    def test_disabled_adapters_model_typos_and_broken_toml_leave_files_alone(self):
        for agent in ("kimi", "claude-cli"):
            self.cli("agent", "--agent", agent, "--write", ok=False)
            self.assertFalse(self.config.exists())
        self.cli("agent", "--agent", "codex", "--write", ok=False)
        self.codex("--env", "INVALID-ENV", "--write", ok=False)
        self.codex("--timeout", "0", "--write", ok=False)
        self.config.write_text('[broken\n')
        original = self.config.read_bytes()
        self.codex("--write", ok=False)
        self.assertEqual(self.config.read_bytes(), original)

    def test_new_codex_init_and_existing_force_guard(self):
        self.cli("init", "--agent", "codex", "--model", "test-model", "--disable-agent-checks",
                 "--test-command", "python3 -m unittest", "--write")
        self.assertEqual(agent_config.read(str(self.repo))["backend"], "cli")
        original = self.config.read_bytes()
        self.cli("init", "--agent", "codex", "--model", "another-model", "--force", "--write", ok=False)
        self.assertEqual(self.config.read_bytes(), original)

    def test_native_role_and_headless_do_not_overwrite_cli_configuration(self):
        self.codex("--write")
        original = self.config.read_bytes()
        self.cli("role", "--role", "implementer", "--model", "sonnet", "--write", ok=False)
        out = self.cli("headless", "--write")
        self.assertIn("--allow-model", out["command"])
        self.assertFalse(out["written"])
        self.assertFalse((self.repo / setup.HEADLESS).exists())
        self.assertEqual(self.config.read_bytes(), original)

    def test_config_and_backup_symlinks_cannot_escape(self):
        outside = self.repo.parent / (self.repo.name + "-outside")
        outside.mkdir()
        self.addCleanup(lambda: outside.rmdir())
        target = outside / "config.toml"
        target.write_text("")
        self.addCleanup(target.unlink)
        self.config.symlink_to(target)
        self.codex("--write", ok=False)
        self.assertEqual(target.read_text(), "")
        self.config.unlink()
        self.config.write_text("# old\n")
        (self.repo / ".auto-bmad").symlink_to(outside, target_is_directory=True)
        self.codex("--write", ok=False)
        self.assertEqual(self.config.read_text(), "# old\n")

    def test_active_source_lease_blocks_writing(self):
        with lease(self.repo):
            self.codex("--write", ok=False)
        self.assertFalse(self.config.exists())

    def test_check_reports_cli_blockers_and_choices_without_inference(self):
        self.codex("--write")
        with patch.object(setup.mcp_status, "status"), patch("engine.inspect", return_value={"execution_ready": True}):
            out, _ = setup.cmd_check(str(self.repo))
        self.assertTrue(out["execution"]["ok"], out["execution"])
        self.assertFalse(out["execution"]["model_started"])
        self.assertFalse(next(v for v in out["agents"] if v["id"] == "kimi")["available"])
        self.codex("--executable", "nonexistent-auto-bmad-cli", "--write")
        with patch("engine.inspect", return_value={"execution_ready": True}):
            out, _ = setup.cmd_check(str(self.repo))
        self.assertFalse(out["execution"]["ok"])


class TomlEditTest(unittest.TestCase):
    def test_inline_dotted_quoted_keys_and_multiline_content(self):
        for source in (
            'execution = { backend="legacy-plugin" }\nrun.level="deep"\n',
            '"execution"."backend"="legacy-plugin"\n["odd.key"]\nx=1979-05-27T07:32:00Z\n',
            '["execution"] # note\nbackend="legacy-plugin"\n[custom]\ntext="""\n[execution]\nnot a header\n"""\n',
            '[execution]\nbackend="legacy-plugin"\n[custom]\narray=[\n"x",\n"y"\n]\nnan=nan\n',
        ):
            result = setup_agents.edit(source, {"execution": {"backend": "cli"}})
            expected = tomllib.loads(source)
            expected["execution"] = {"backend": "cli"}
            self.assertTrue(setup_agents.equal(tomllib.loads(result), expected))

    def test_atomic_write_refuses_a_stale_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            path = Path(tmp) / ".auto-bmad.toml"
            path.write_text("# changed\n")
            with self.assertRaisesRegex(ValueError, "changed during setup"):
                setup_agents.write(tmp, path, "# old\n", "# new\n")
            self.assertEqual(path.read_text(), "# changed\n")
