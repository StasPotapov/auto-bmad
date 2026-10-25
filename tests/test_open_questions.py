"""Unit tests for open_questions.py: file name from config, English scaffolding, old files.
python3 -m unittest discover tests"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import open_questions as q  # noqa: E402

ARTIFACTS = os.path.join("_bmad-output", "implementation-artifacts")

EXISTING = """# Epic 2 — open questions

<!-- auto-bmad:open-questions epic=2 -->

A header a human edited.

**Updated:** 2026-10-01 · **with open questions:** 1

<!-- story:2-1 -->
## Story 2-1 — an earlier section (blocked)

Spec: [spec-2-1-x.md](spec-2-1-x.md) · commit `abc1234`

Item.

<!-- /story:2-1 -->

A human's note.
"""


class OpenQuestionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        os.makedirs(os.path.join(self.repo, ARTIFACTS))
        self.env = mock.patch.dict(os.environ, {"AUTO_BMAD_CONFIG": os.path.join(self.repo, "absent.toml")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_script(self, *argv, stdin=""):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["open_questions.py", *argv, "--repo", self.repo]), \
                mock.patch.object(sys, "stdin", io.StringIO(stdin)), redirect_stdout(out), \
                redirect_stderr(io.StringIO()):
            code = q.main()
        return code, json.loads(out.getvalue())

    def read(self, name):
        with open(os.path.join(self.repo, ARTIFACTS, name), encoding="utf-8") as fh:
            return fh.read()

    def test_default_name_and_english_scaffolding(self):
        code, res = self.run_script("--story", "3-2", "--title", "Import", "--commit", "none",
                                    "--status", "blocked", stdin="**Item**\n- What is wrong: x")
        self.assertEqual(code, 0)
        self.assertEqual(res["questions_file"], os.path.join(ARTIFACTS, "epic-3-open-questions.md"))
        text = self.read("epic-3-open-questions.md")
        self.assertIn("# Epic 3 — open questions", text)
        self.assertIn("**Updated:**", text)
        self.assertIn("## Story 3-2 — Import (blocked)", text)
        self.assertIn("no commit", text)

    def test_config_does_not_change_the_name(self):
        with open(os.path.join(self.repo, ".auto-bmad.toml"), "w", encoding="utf-8") as fh:
            fh.write('[run]\nquestions_file = "epic-{epic}-questions.md"\n')
        code, res = self.run_script("--story", "1-1", stdin="Item")
        self.assertEqual(code, 0)
        self.assertTrue(res["path"].endswith("epic-1-open-questions.md"))

    def test_existing_file_keeps_header_sections_and_notes(self):
        with open(os.path.join(self.repo, ARTIFACTS, "epic-2-open-questions.md"), "w", encoding="utf-8") as fh:
            fh.write(EXISTING)
        code, res = self.run_script("--story", "2-3", "--title", "New", "--commit", "def5678",
                                    stdin="New item")
        self.assertEqual((code, res["action"], res["sections"]), (0, "added", 2))
        text = self.read("epic-2-open-questions.md")
        self.assertEqual(text.count("**Updated:**"), 1)
        self.assertNotIn("2026-10-01", text)
        self.assertIn("A header a human edited.", text)
        self.assertIn("## Story 2-1 — an earlier section (blocked)", text)
        self.assertIn("A human's note.", text)
        self.assertIn("commit `def5678`", text)

    def test_none_removes_section(self):
        self.run_script("--story", "4-1", stdin="Item")
        code, res = self.run_script("--story", "4-1", "--none")
        self.assertEqual((code, res["action"]), (0, "removed"))
        code, res = self.run_script("--story", "4-1", "--none")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
