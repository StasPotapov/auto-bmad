import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cli_verifier
import verify
import verifier_tools


class VerifierTest(unittest.TestCase):
    def test_parses_actionable_problems_and_artifact(self):
        out = cli_verifier.parse("VERDICT: problem\nMODE: feature\nARTIFACT: .auto-bmad/board.html\n"
                                 "PROBLEMS:\n1. Expected title is missing.\n2. Console error on submit.\n\nChecked form.")
        self.assertEqual(out["problems"], ["Expected title is missing.", "Console error on submit."])
        self.assertEqual(out["artifact"], ".auto-bmad/board.html")

    def test_malformed_report_is_explicit_skip(self):
        self.assertEqual(cli_verifier.parse("Looks good.")["verdict"], "skipped")
        self.assertIn("outside the contract", cli_verifier.parse("Looks good.")["reason"])

    def test_duplicate_verdict_or_problem_without_details_fails_closed(self):
        for report in ("VERDICT: pass\nVERDICT: problem", "VERDICT: problem\nPROBLEMS:\n"):
            with self.assertRaises(ValueError):
                cli_verifier.parse(report)

    def test_cli_skill_uses_codex_paths_and_never_claude_only_install(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HOME": tmp, "CODEX_HOME": tmp + "/codex"}):
            root = Path(tmp)
            claude = root / ".claude/skills/fixture/SKILL.md"
            claude.parent.mkdir(parents=True)
            claude.write_text("---\nname: fixture\n---\n")
            self.assertIsNone(verify.cli_skill("fixture", tmp))
            skill = root / ".agents/skills/fixture/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: fixture\n---\nCheck the page.")
            self.assertEqual(verify.cli_skill("fixture", tmp), str(skill.resolve()))
            self.assertTrue(verify.skill_available("fixture", tmp, backend="cli"))
            self.assertIsNone(verify.cli_skill("../fixture", tmp))

    def test_project_skill_wins_over_user_skill(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HOME": tmp}):
            root = Path(tmp)
            for place in (root, root / "project"):
                skill = place / ".agents/skills/fixture/SKILL.md"
                skill.parent.mkdir(parents=True)
                skill.write_text("---\nname: fixture\n---\n")
            self.assertEqual(verify.cli_skill("fixture", str(root / "project")),
                             str((root / "project/.agents/skills/fixture/SKILL.md").resolve()))

    def test_missing_browser_dependencies_without_browser_do_not_block_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = root / "session.json"
            session.write_text(json.dumps({"repo": str(root)}))
            (root / "verifier-cleanup.json").write_text(json.dumps({"repo": str(root),
                "project": str(root / ".auto-bmad/browser"), "browser_cli": "/missing/mockmatch"}))
            with patch.object(cli_verifier, "execute", return_value={"execution_status": "completed"}) as execute:
                self.assertEqual(cli_verifier.cleanup_session(session), [])
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.args[0][-1], "stop")

    def test_browser_bridge_accepts_only_scoped_tool_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            broker = SimpleNamespace(root=root, state=root / ".auto-bmad/runs/id", private=root / ".git/session", verifying=True,
                     session={"writer": "verifier"}, verifier_tool={"cli": "/installed/mockmatch", "fields": {
                         "serve": "npm run dev", "url": "http://localhost:5173"}})
            self.assertEqual(verifier_tools.argv(broker, ["assert", "Hello"]), ["/installed/mockmatch", "assert", "Hello"])
            cmd = verifier_tools.argv(broker, ["serve", "start", "--serve", "npm run dev", "--url", "http://localhost:5173"])
            self.assertEqual(cmd[1], str(cli_verifier.SERVE))
            self.assertIn(str(broker.private / "browser/design"), verifier_tools.argv(broker, ["pull", "https://example.test/design"]))
            for arguments in (["serve", "start", "--serve", "rm -rf /", "--url", "http://localhost:5173"],
                              ["doctor", "--install"], ["_daemon"], ["board", "--open"],
                              ["compare", "--design", "/etc/passwd"], ["shot", "../../escape"],
                              ["pull", "https://example.test/design", "--out", str(root / "outside")],
                              ["pull", "https://example.test/design", "--o", "/tmp/escape"],
                              ["open", "file:///etc/passwd"]):
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    verifier_tools.argv(broker, arguments)
            for arguments in (["batch", "goto file:///etc/passwd", "ui"],
                              ["compare", "--design", "index.html", "--site", "file:///etc/passwd"],
                              ["compare", "--design", "index.html", "--site", "https://example.test", "--site", "file:///etc/passwd"]):
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    verifier_tools.argv(broker, arguments)
            broker.verifying = False
            with self.assertRaises(ValueError):
                verifier_tools.argv(broker, ["close"])

    def test_browser_cli_comes_from_user_install_and_server_defaults_are_inferred(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HOME": tmp, "CODEX_HOME": tmp + "/codex"}):
            home = Path(tmp).resolve()
            root = home / "project"
            root.mkdir()
            (root / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "*"}}))
            for base, content in ((root, "project code must not execute"), (home, "trusted user CLI")):
                skill = base / ".agents/skills/mockmatch"
                (skill / "bin").mkdir(parents=True)
                (skill / "SKILL.md").write_text("---\nname: mockmatch\n---\n")
                (skill / "bin/mockmatch").write_text(content)
            private = home / "session"
            private.mkdir()
            state = root / ".auto-bmad/run"
            state.mkdir(parents=True)
            broker = SimpleNamespace(root=root, private=private, state=state, session_path=private / "session.json",
                                     manifest_path=private / "manifest.json")
            wrapper = verifier_tools.prepare(broker, {"fields": {}})
            self.assertTrue(wrapper.exists())
            self.assertEqual(Path(broker.verifier_tool["cli"]).read_text(), "trusted user CLI")
            self.assertEqual(broker.verifier_tool["fields"], {"serve": "npm run dev", "url": "http://localhost:5173"})
            (home / ".agents/skills/mockmatch/bin/mockmatch").unlink()
            self.assertIsNone(verifier_tools.prepare(broker, {"fields": {}}))

    def test_design_output_paths_work_as_inputs_to_subsequent_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            broker = SimpleNamespace(root=root, private=root / ".git/session", verifying=True,
                session={"writer": "verifier"}, verifier_tool={"cli": "/installed/mockmatch", "fields": {}})
            path = Path(verifier_tools.output_path(broker, ".auto-bmad/design")) / "Home.html"
            path.parent.mkdir(parents=True)
            path.write_text("<h1>Design</h1>")
            for name in (".auto-bmad/design/Home.html", "exports/design/Home.html", str(path)):
                self.assertEqual(verifier_tools.argv(broker, ["frames", name])[-1], str(path))
            run = broker.private / "browser/build/mockmatch/fixture-run"
            run.mkdir(parents=True)
            self.assertEqual(verifier_tools.argv(broker, ["board", "fixture-run"])[-1], str(run))


if __name__ == "__main__":
    unittest.main()
