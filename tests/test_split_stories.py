"""Split stories of BMad ("2-6a-<slug>", "### Story 2.6a: …") across the scripts.
python3 -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import common  # noqa: E402
import stats  # noqa: E402

ART = os.path.join("_bmad-output", "implementation-artifacts")
STATUS = """development_status:
  epic-2: in-progress
  2-6-base: done
  2-6a-first-half: in-progress
  2-6b-second-half: backlog
  2-10-late: backlog
  epic-2-retrospective: optional
"""


def run(script, *args):
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args],
                       capture_output=True, text=True, timeout=60)
    return p.returncode, json.loads(p.stdout)


class SplitStories(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.art = os.path.join(self.repo, ART)
        os.makedirs(self.art)
        with open(os.path.join(self.art, "sprint-status.yaml"), "w") as fh:
            fh.write(STATUS)
        os.environ["AUTO_BMAD_CONFIG"] = os.path.join(self.repo, "absent.toml")

    def tearDown(self):
        os.environ.pop("AUTO_BMAD_CONFIG", None)
        self.tmp.cleanup()

    def write(self, name, text="---\nstatus: in-progress\n---\n"):
        with open(os.path.join(self.art, name), "w") as fh:
            fh.write(text)

    def test_common_grammar(self):
        self.assertEqual(common.parse_story("2-6a"), (2, "6a"))
        self.assertEqual(common.parse_story("2.06A"), (2, "6a"))
        self.assertIsNone(common.parse_story("2-6ab"))
        self.assertEqual(sorted(["7", "6b", "10", "6", "6a"], key=common.num_order), ["6", "6a", "6b", "7", "10"])
        self.assertEqual(common.STORY_KEY.match("2-6a-first-half").groups(), ("2", "6a", "first-half"))
        self.assertEqual(common.STORY_KEY.match("2-6-a-slug").groups(), ("2", "6", "a-slug"))

    def test_plan_default_story_is_the_split_one(self):
        code, out = run("plan_run.py", "--arg", "", "--repo", self.repo)
        self.assertEqual(code, 0)
        self.assertEqual((out["story"], [s["id"] for s in out["stories"]]), ("6a", ["2-6a"]))

    def test_read_spec_tells_split_and_plain_apart(self):
        self.write("spec-2-6-base.md")
        self.write("spec-2-6a-first-half.md")
        code, out = run("read_spec.py", "--story", "2-6a", "--repo", self.repo)
        self.assertEqual((code, out["route"]), (0, "resume"))
        self.assertTrue(out["path"].endswith("spec-2-6a-first-half.md"))
        code, out = run("read_spec.py", "--story", "2-6", "--repo", self.repo)
        self.assertTrue(out["path"].endswith("spec-2-6-base.md"))

    def test_sync_marks_only_the_split_story(self):
        code, _ = run("sync_sprint.py", "--story", "2-6a", "--repo", self.repo)
        self.assertEqual(code, 0)
        text = open(os.path.join(self.art, "sprint-status.yaml")).read()
        self.assertIn("2-6a-first-half: done", text)
        self.assertIn("2-6b-second-half: backlog", text)

    def test_open_questions_order_sections_by_number(self):
        for story in ("2-10", "2-6b", "2-6a"):
            p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "open_questions.py"), "--story", story,
                                "--repo", self.repo], input="Item", capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
        text = open(os.path.join(self.art, "epic-2-open-questions.md")).read()
        heads = [line for line in text.splitlines() if line.startswith("## Story")]
        self.assertEqual(heads, ["## Story 2-6a", "## Story 2-6b", "## Story 2-10"])

    def test_stats_story_id(self):
        self.assertEqual(stats.STORY_RE.search("Story: 2.6a — First half").groups(), ("2", "6a"))
        self.assertIsNone(stats.STORY_RE.search("Story: 2.6ab — x"))
        self.assertEqual(stats.STORY_RE.search("Story: 1.3.").groups(), ("1", "3"))

    def test_uppercase_spec_and_padded_key(self):
        self.write("spec-2-6A-first-half.md")
        code, out = run("read_spec.py", "--story", "2-6a", "--repo", self.repo)
        self.assertEqual(code, 0)
        self.assertTrue(out["path"].endswith("spec-2-6A-first-half.md"))
        with open(os.path.join(self.art, "sprint-status.yaml"), "a") as fh:
            fh.write("  2-011-padded: backlog\n")
        code, _ = run("sync_sprint.py", "--story", "2-11", "--repo", self.repo)
        self.assertEqual(code, 0)
        self.assertIn("2-011-padded: done", open(os.path.join(self.art, "sprint-status.yaml")).read())


if __name__ == "__main__":
    unittest.main()
