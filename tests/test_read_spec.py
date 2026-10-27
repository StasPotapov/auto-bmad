"""Tests for read_spec.py --result: the run result without reading the spec.
python3 -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS = os.path.join("_bmad-output", "implementation-artifacts")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def run(*args):
    proc = subprocess.run([sys.executable, os.path.join(HERE, "..", "scripts", "read_spec.py"), *args],
                          capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


class ResultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        os.makedirs(os.path.join(self.repo, ARTIFACTS))
        git(self.repo, "init", "-q")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "0")
        self.base = git(self.repo, "rev-parse", "HEAD")
        for name in ("a.py", "b.py"):
            with open(os.path.join(self.repo, name), "w") as fh:
                fh.write("x = 1\n")
        self.spec = os.path.join(self.repo, ARTIFACTS, "spec-1-3-import.md")
        with open(self.spec, "w") as fh:
            fh.write(f"---\ntitle: 'Import'\nstatus: done\nbaseline_revision: {self.base}\n"
                     "deferred:\n  - one\nfollowup_review_recommended: false\n---\n\n"
                     "## Code Map\n\nlong text\n\n## Auto Run Result\n\nDone: import works.\n"
                     "- review: 3 findings\n\n## Review Triage Log\n\n- row\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "story")

    def tearDown(self):
        self.tmp.cleanup()

    def test_result_fields(self):
        code, out = run("--story", "1-3", "--result", "--repo", self.repo)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["auto_run_result"], "Done: import works.\n- review: 3 findings")
        self.assertEqual(out["commit"], git(self.repo, "log", "-1", "--format=%h"))
        self.assertEqual(out["files"], 3)
        self.assertEqual(out["deferred"], 1)

    def test_tracking_commit_after_the_engine_does_not_move_commit(self):
        engine = git(self.repo, "log", "-1", "--format=%h")
        with open(os.path.join(self.repo, ARTIFACTS, "sprint-status.yaml"), "w") as fh:
            fh.write("x\n")
        with open(self.spec, "a") as fh:
            fh.write("\n## Auto Run Result\n\nSecond pass: one risk left.\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "chore: tracking")
        code, out = run("--story", "1-3", "--result", "--repo", self.repo)
        self.assertEqual(out["commit"], engine)
        self.assertEqual(out["files"], 3)
        self.assertEqual(out["auto_run_result"], "Second pass: one risk left.")   # the last section

    def test_bad_or_missing_baseline_gives_null(self):
        for base in ("NO_VCS", "--output=/tmp/x", "deadbeef"):
            with open(self.spec) as fh:
                text = fh.read()
            with open(self.spec, "w") as fh:
                fh.write(text.replace(text.split("baseline_revision: ")[1].split("\n")[0], base, 1))
            code, out = run("--story", "1-3", "--result", "--repo", self.repo)
            self.assertEqual(code, 0, out)
            self.assertIsNone(out["commit"], base)
            self.assertIsNone(out["files"], base)

    def test_without_flag_no_result_fields(self):
        code, out = run("--story", "1-3", "--repo", self.repo)
        self.assertEqual(code, 0)
        self.assertNotIn("auto_run_result", out)


if __name__ == "__main__":
    unittest.main()
