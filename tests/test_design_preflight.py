"""Unit tests for the Claude Design login check: the MCP status parser, the mockmatch
preflight extension and how preflight.py runs the checks' own preflight.
python3 -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import mcp_status  # noqa: E402
import preflight  # noqa: E402

EXT = os.path.join(HERE, "..", "extensions", "mockmatch", "preflight.py")


class ParseStatusTest(unittest.TestCase):
    def test_states(self):
        parse = lambda code, text: mcp_status.parse_status("claude_design", code, text)["state"]  # noqa: E731
        self.assertEqual(parse(0, "claude_design:\n  Status: ✔ Connected\n  Type: http\n"), "connected")
        self.assertEqual(parse(0, "  Status: ⚠ Needs authentication\n"), "auth")
        self.assertEqual(parse(0, "  Status: ✗ Failed to connect\n"), "failed")
        missing = mcp_status.parse_status("claude_design", 1, 'No MCP server named "claude_design".')
        self.assertEqual(missing["state"], "missing")
        self.assertIn("claude mcp add --transport http -s user claude_design", missing["message"])


class ExtensionTest(unittest.TestCase):
    def run_ext(self, fields, state, cwd):
        """Run the extension in-process with a stubbed MCP status."""
        sys.path.insert(0, os.path.dirname(EXT))
        import importlib.util
        spec = importlib.util.spec_from_file_location("mm_preflight", EXT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        old = os.getcwd()
        os.chdir(cwd)
        try:
            with mock.patch.object(mod, "status", return_value={"state": state, "message": "MCP x"}), \
                    mock.patch("sys.stdin") as stdin, mock.patch("sys.stdout") as stdout:
                stdin.read.return_value = json.dumps(fields)
                code = mod.main()
            return code, "".join(c.args[0] for c in stdout.write.call_args_list)
        finally:
            os.chdir(old)

    def test_no_design_project_is_silent(self):
        proc = subprocess.run([sys.executable, EXT], input=json.dumps({"design": "x.html"}),
                              capture_output=True, text=True)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_login_and_fallback(self):
        with tempfile.TemporaryDirectory() as repo:
            fields = {"design_project": "abc"}
            self.assertEqual(self.run_ext(fields, "connected", repo)[0], 0)
            code, text = self.run_ext(fields, "auth", repo)
            self.assertEqual(code, 2)
            self.assertIn("no saved copy", text)
            os.makedirs(os.path.join(repo, "design"))
            open(os.path.join(repo, "design", "home.html"), "w").close()
            code, text = self.run_ext({**fields, "design": "design/home.html"}, "auth", repo)
            self.assertEqual(code, 1)
            self.assertIn("saved copy design/home.html", text)


class VerifyPreflightTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.env = os.environ.get("AUTO_BMAD_CONFIG")
        os.environ["AUTO_BMAD_CONFIG"] = os.path.join(self.repo, "none.toml")

    def tearDown(self):
        if self.env is None:
            os.environ.pop("AUTO_BMAD_CONFIG", None)
        else:
            os.environ["AUTO_BMAD_CONFIG"] = self.env
        self.tmp.cleanup()

    def config(self, text):
        with open(os.path.join(self.repo, ".auto-bmad.toml"), "w") as fh:
            fh.write(text)

    def test_codes_levels_and_fields(self):
        self.config('[[verify]]\nname = "mockmatch"\nenabled = false\n\n'
                    '[[verify]]\nname = "block"\nkind = "agent"\nflag = "x"\n'
                    'preflight = "python3 -c \\"import json,sys; d=json.load(sys.stdin); '
                    'print(d[\'flag\']); sys.exit(2)\\""\n\n'
                    '[[verify]]\nname = "warn"\nlevels = ["deep"]\npreflight = "echo careful; exit 1"\n')
        found = preflight.verify_preflights(self.repo)
        self.assertIn(("block", 2, "x"), found)
        self.assertIn(("warn", 1, "careful"), found)
        self.assertNotIn("mockmatch", [f[0] for f in found])
        self.assertEqual([f[0] for f in preflight.verify_preflights(self.repo, "normal")], ["block"])


if __name__ == "__main__":
    unittest.main()
