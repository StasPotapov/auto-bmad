"""Unit tests for preflight: why the engine is not in git and how to fix it.
python3 -m unittest discover tests"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import preflight as p  # noqa: E402

ENGINE = ".claude/skills/bmad-build-auto/SKILL.md"


class IgnoreRuleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        os.makedirs(os.path.join(self.repo, ".claude/skills/bmad-build-auto"))
        with open(os.path.join(self.repo, ENGINE), "w") as f:
            f.write("x")

    def tearDown(self):
        self.tmp.cleanup()

    def write_gitignore(self, text):
        with open(os.path.join(self.repo, ".gitignore"), "w") as f:
            f.write(text)

    def test_names_gitignore_line(self):
        self.write_gitignore("*.log\n.claude/skills\n")
        rule = p.ignore_rule(self.repo, ENGINE)
        self.assertEqual(rule, {"file": ".gitignore", "line": 2, "pattern": ".claude/skills"})
        fix = p.engine_fix(ENGINE, rule)
        self.assertIn("line 2", fix)
        self.assertIn("commit .claude/skills", fix)

    def test_not_ignored_just_uncommitted(self):
        self.assertIsNone(p.ignore_rule(self.repo, ENGINE))
        self.assertEqual(p.engine_fix(ENGINE, None), "not committed — commit .claude/skills")

    def test_negation_is_not_ignore(self):
        self.write_gitignore(".claude/*\n!.claude/skills\n")
        self.assertIsNone(p.ignore_rule(self.repo, ENGINE))

    def test_info_exclude(self):
        with open(os.path.join(self.repo, ".git/info/exclude"), "a") as f:
            f.write("_bmad/\n")
        rule = p.ignore_rule(self.repo, "_bmad/scripts/render_skill.py")
        self.assertEqual(rule["file"], ".git/info/exclude")
        self.assertIn("commit _bmad",
                      p.engine_fix("_bmad/scripts/render_skill.py", rule))


if __name__ == "__main__":
    unittest.main()
