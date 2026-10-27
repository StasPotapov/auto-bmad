"""Tests for story_finish.py and the SessionEnd hook script.
python3 -m unittest discover tests"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import session_end  # noqa: E402
import story_finish as sf  # noqa: E402

ARTIFACTS = os.path.join("_bmad-output", "implementation-artifacts")
SPRINT = """generated: 2026-10-01
last_updated: 2026-10-01

development_status:
  epic-1: in-progress
  1-1-first: done
  1-2-second: review
  1-3-third: backlog
  epic-1-retrospective: optional
"""
HOOK = """import json, sys
p = json.load(sys.stdin)
out = {"ok": True, "message": p["event"] + ":" + str(p.get("story"))}
if p["event"] == "story-done":
    open("board.md", "w").write(p["story"])
    out["files"] = ["board.md"]
    out["link"] = "https://board/" + p["story"]
print(json.dumps(out))
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


class FinishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "proj")
        os.makedirs(os.path.join(self.repo, ARTIFACTS))
        with open(os.path.join(self.repo, ARTIFACTS, "sprint-status.yaml"), "w") as fh:
            fh.write(SPRINT)
        git(self.repo, "init", "-q")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@t")
        hook = os.path.join(self.tmp.name, "hook.py")
        with open(hook, "w") as fh:
            fh.write(HOOK)
        config = os.path.join(self.tmp.name, "user.toml")
        with open(config, "w") as fh:
            fh.write('[[hook]]\nname = "h"\nevents = ["story-done", "story-blocked", "verify-done", '
                     f'"wave-merged", "run-end"]\ncommand = "python3 {hook}"\n'
                     '[[hook]]\nname = "broken"\nevents = ["run-end"]\ncommand = "echo not-json"\n')
        self.env = mock.patch.dict(os.environ, {"AUTO_BMAD_CONFIG": config})
        self.env.start()
        for k in ("AUTO_BMAD_DEADLINE", "AUTO_BMAD_UNATTENDED", "AUTO_BMAD_EVENTS_FILE"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_finish(self, spec, *extra):
        path = os.path.join(self.tmp.name, "finish.json")
        with open(path, "w") as fh:
            json.dump(spec, fh)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = sf.main(["--input", path, "--repo", self.repo, *extra])
        return code, json.loads(out.getvalue())

    def sprint(self):
        with open(os.path.join(self.repo, ARTIFACTS, "sprint-status.yaml"), encoding="utf-8") as fh:
            return fh.read()

    def status(self):
        return git(self.repo, "status", "--porcelain")

    def test_done_story_one_commit_events_and_hook_files(self):
        code, out = self.run_finish({"epic": 1, "level": "normal", "stories": [
            {"story": "1-2", "title": "Second", "spec": "", "commit": "abc1234",
             "questions": "**Item**\n- What is wrong: x",
             "verify": {"status": "pass", "fixes": 0, "checks": {"project-tests": "pass"}}}]})
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"])
        self.assertEqual(self.status(), "")
        log = git(self.repo, "log", "--format=%s").splitlines()
        self.assertEqual(log[1], "chore: story 1-2 → done in sprint tracking")
        self.assertEqual(log[0], "story-done:1-2")           # the hook's files, with its message
        files = git(self.repo, "show", "--name-only", "--format=", "HEAD~1").split()
        self.assertEqual(sorted(files), sorted([os.path.join(ARTIFACTS, "epic-1-open-questions.md"),
                                                os.path.join(ARTIFACTS, "sprint-status.yaml")]))
        self.assertIn("1-2-second: done", self.sprint())
        steps = [s["step"] for s in out["steps"]]
        self.assertEqual(steps[0], "verify-done 1-2")
        self.assertLess(steps.index("commit"), steps.index("story-done 1-2"))
        self.assertIn("verify-done:1-2", out["messages"])
        self.assertEqual(out["links"][0]["link"], "https://board/1-2")

    def test_story_without_questions_commits_only_tracking(self):
        code, out = self.run_finish({"stories": [{"story": "1-2", "commit": "abc"}]})
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ARTIFACTS, "epic-1-open-questions.md")))
        self.assertEqual(self.status(), "")
        self.assertIn("chore: story 1-2", git(self.repo, "log", "--format=%s"))

    def test_blocked_story_commits_questions_and_run_end_and_one_failure_does_not_stop_others(self):
        code, out = self.run_finish({"epic": 1, "stories": [
            {"story": "1-3", "title": "Third", "status": "blocked", "commit": "none",
             "questions": "### Where it stopped\n- x"}],
            "run_end": {"status": "blocked", "done": 0, "left": 1}})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.status(), "")
        subjects = git(self.repo, "log", "--format=%s")
        self.assertIn("docs: open questions for epic 1 — story 1-3 blocked", subjects)
        self.assertIn("1-3-third: backlog", self.sprint())
        steps = [s["step"] for s in out["steps"]]
        self.assertIn("story-blocked 1-3", steps)
        self.assertIn("run-end", steps)
        self.assertTrue(any("broken" in w for w in out["warnings"]))  # a hook error is a warning

    def test_failed_step_is_reported_and_the_rest_runs(self):
        code, out = self.run_finish({"epic": 1, "stories": [
            {"story": "1-3", "status": "blocked", "questions": ""}],
            "run_end": {"status": "blocked"}})
        self.assertEqual(code, 2)
        self.assertEqual(out["failed"], ["questions 1-3"])
        self.assertIn("run-end", [s["step"] for s in out["steps"]])

    def test_wave_syncs_all_stories_in_one_commit(self):
        code, out = self.run_finish({"epic": 1, "wave": 1, "stories": [
            {"story": "1-2"}, {"story": "1-3", "questions": "Item"}]})
        self.assertEqual(code, 0, out)
        self.assertIn("chore: stories 1-2, 1-3 → done in sprint tracking", git(self.repo, "log", "--format=%s"))
        self.assertIn("epic-1: done", self.sprint())
        self.assertIn("wave-merged", [s["step"] for s in out["steps"]])

    def test_resumed_story_already_done_is_not_a_failure(self):
        code, out = self.run_finish({"stories": [{"story": "1-1"}]})
        self.assertEqual(code, 0, out)
        self.assertIsNone(out["commit"])

    def test_session_records_stats_without_failing(self):
        code, out = self.run_finish({"epic": 1}, "--session", "no-such-session")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["steps"][-1]["step"], "stats")

    def test_bad_input(self):
        code, out = self.run_finish({"stories": [{"story": "x"}]})
        self.assertEqual(code, 1)
        self.assertIn("story id", out["error"])
        code, out = self.run_finish({"stories": [{"story": "1-2", "status": "merged"}]})
        self.assertEqual(code, 1)
        code, out = self.run_finish({"stories": ["1-2"]})
        self.assertEqual(code, 1)
        code, out = self.run_finish({"stories": [{"story": "1-2", "status": "Done"}]})
        self.assertEqual(code, 0, out)                         # case does not matter

    def test_story_missing_from_tracking_fails_sync(self):
        code, out = self.run_finish({"stories": [{"story": "1-2"}, {"story": "1-9"}]})
        self.assertEqual(code, 2)
        self.assertEqual(out["failed"], ["sync"])
        self.assertIn("1-9", out["steps"][0]["detail"])
        self.assertEqual(self.status(), "")                    # 1-2 is still synced and committed

    def test_questions_go_to_the_story_epic_file(self):
        code, out = self.run_finish({"epic": 2, "stories": [
            {"story": "1-3", "status": "blocked", "questions": "x"}]})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.status(), "")
        self.assertIn("epic 1", git(self.repo, "log", "-1", "--format=%s"))


class SessionEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.transcript = os.path.join(self.tmp.name, "s1.jsonl")
        open(self.transcript, "w").close()
        git(self.tmp.name, "init", "-q")

    def tearDown(self):
        self.tmp.cleanup()

    def meta(self, agent_type):
        sub = os.path.join(self.tmp.name, "s1", "subagents")
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, f"agent-{agent_type.split(':')[-1]}.meta.json"), "w") as fh:
            json.dump({"agentType": agent_type}, fh)

    def run_hook(self):
        data = {"session_id": "s1", "transcript_path": self.transcript, "cwd": self.tmp.name}
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(data))), \
                mock.patch.object(session_end, "launch") as launch:
            self.assertEqual(session_end.main(), 0)
        return launch

    def test_session_without_story_runner_is_skipped(self):
        self.meta("Explore")
        self.assertFalse(self.run_hook().called)

    def test_story_runner_session_records_in_background(self):
        self.meta("auto-bmad:bmad-story-runner")
        launch = self.run_hook()
        command = launch.call_args[0][0]
        self.assertEqual(command[2:5], ["record", "--session", "s1"])
        self.assertEqual(os.path.realpath(command[-1]), os.path.realpath(self.tmp.name))

    def test_not_a_git_repo_or_not_an_object_is_skipped(self):
        self.meta("auto-bmad:bmad-story-runner")
        os.rename(os.path.join(self.tmp.name, ".git"), os.path.join(self.tmp.name, "git-off"))
        self.assertFalse(self.run_hook().called)
        with mock.patch.object(sys, "stdin", io.StringIO("[1]")):
            self.assertEqual(session_end.main(), 0)


if __name__ == "__main__":
    unittest.main()
