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


class SprintReviewTest(unittest.TestCase):
    """A story in `review` in sprint-status.yaml: a done spec is reviewed again, no spec — ask the human."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        os.makedirs(os.path.join(self.repo, ARTIFACTS))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, sprint, spec_status=None, base_key="baseline_revision"):
        with open(os.path.join(self.repo, ARTIFACTS, "sprint-status.yaml"), "w") as fh:
            fh.write(f"development_status:\n  epic-5: in-progress\n  5-1-tokens: {sprint}\n"
                     "  5-10-other: review\n")
        if spec_status:
            with open(os.path.join(self.repo, ARTIFACTS, "spec-5-1-tokens.md"), "w") as fh:
                fh.write(f"---\ntitle: 'Tokens'\nstatus: '{spec_status}'\n"
                         f"{base_key}: '0b97788d4c02d8a762a11a0abd4cad9ee60f2c20'\n---\n")

    def test_done_spec_in_review_goes_to_review(self):
        self.write("review", "done")
        code, out = run("--story", "5-1", "--repo", self.repo)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["sprint_status"], "review")
        self.assertEqual(out["route"], "review")
        self.assertEqual(out["baseline"], "0b97788d4c02d8a762a11a0abd4cad9ee60f2c20")

    def test_done_spec_with_lagging_tracking_is_sync_only(self):
        for sprint in ("in-progress", "ready-for-dev", "backlog"):
            self.write(sprint, "done")
            code, out = run("--story", "5-1", "--repo", self.repo)
            self.assertEqual(out["route"], "sync-only", sprint)

    def test_unfinished_spec_resumes_whatever_the_sprint_says(self):
        self.write("review", "in-review")
        code, out = run("--story", "5-1", "--repo", self.repo)
        self.assertEqual(out["route"], "resume")

    def test_review_without_spec_asks_the_human(self):
        self.write("review")
        code, out = run("--story", "5-1", "--repo", self.repo)
        self.assertEqual(code, 2)
        self.assertEqual(out["found"], 0)
        self.assertEqual(out["route"], "ask-human")

    def test_backlog_without_spec_has_no_route(self):
        self.write("backlog")
        code, out = run("--story", "5-1", "--repo", self.repo)
        self.assertEqual(code, 2)
        self.assertNotIn("route", out)

    def test_old_baseline_commit_key(self):
        self.write("review", "done", base_key="baseline_commit")
        code, out = run("--story", "5-1", "--repo", self.repo)
        self.assertEqual(out["baseline"], "0b97788d4c02d8a762a11a0abd4cad9ee60f2c20")

    def test_slug_mode_has_no_sprint_status(self):
        self.write("review", "done")
        code, out = run("--slug", "5-1-tokens", "--repo", self.repo)
        self.assertEqual(code, 0, out)
        self.assertIsNone(out["sprint_status"])
        self.assertEqual(out["route"], "sync-only")


class StoryCommitTest(unittest.TestCase):
    """A review story with later stories on top: its own commit, not the last code commit."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        os.makedirs(os.path.join(self.repo, ARTIFACTS))
        git(self.repo, "init", "-q")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "0")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.sprint("review")
        self.put("a.py", "x = 1\n")
        self.put(os.path.join(ARTIFACTS, "spec-5-1-a.md"),
                 f"---\ntitle: 'A'\nstatus: 'done'\nbaseline_revision: '{self.base}'\n---\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "Story 5.1")
        self.story = git(self.repo, "log", "-1", "--format=%h")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, text):
        with open(os.path.join(self.repo, name), "w") as fh:
            fh.write(text)

    def sprint(self, status):
        self.put(os.path.join(ARTIFACTS, "sprint-status.yaml"),
                 f"development_status:\n  epic-5: in-progress\n  5-1-a: {status}\n  5-2-b: done\n")

    def later_story(self):
        self.put("b.py", "y = 2\n")
        self.put(os.path.join(ARTIFACTS, "spec-5-2-b.md"), "---\nstatus: 'done'\n---\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "Story 5.2")

    def test_nothing_after_the_story(self):
        code, out = run("--story", "5-1", "--repo", self.repo)
        self.assertEqual(out["route"], "review")
        self.assertEqual((out["commit"], out["later_commits"]), (self.story, 0))

    def test_later_story_is_counted_and_does_not_take_the_commit(self):
        self.later_story()
        self.put(os.path.join(ARTIFACTS, "spec-5-1-a.md"),
                 f"---\ntitle: 'A'\nstatus: 'done'\nbaseline_revision: '{self.base}'\n---\n\n"
                 "## Auto Run Result\n\nok\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "chore: tracking")      # spec only: not the engine commit
        code, out = run("--story", "5-1", "--result", "--repo", self.repo)
        self.assertEqual((out["commit"], out["later_commits"]), (self.story, 1))
        self.assertEqual(out["files"], 3)

    def test_sync_only_has_no_later_commits_field(self):
        self.sprint("done")
        code, out = run("--story", "5-1", "--repo", self.repo)
        self.assertEqual(out["route"], "sync-only")
        self.assertNotIn("later_commits", out)


if __name__ == "__main__":
    unittest.main()
