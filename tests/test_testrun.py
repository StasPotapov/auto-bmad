import json
import os
import subprocess
import shlex
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import testrun  # noqa: E402
import write_profile  # noqa: E402

SCRIPT = os.path.join(HERE, "..", "scripts", "testrun.py")


def cli(*args):
    proc = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.write("app.py", "x = 1\n")
        subprocess.run(["git", "-C", self.repo, "add", "."], check=True)
        subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "-m", "0"], check=True)
        self.count = os.path.join(self.repo, "..", os.path.basename(self.repo) + ".count")

    def tearDown(self):
        if os.path.exists(self.count):
            os.unlink(self.count)
        self.tmp.cleanup()

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def counted(self, tail="true"):
        return f"echo run >> '{self.count}'; {tail}"

    def runs(self):
        if not os.path.exists(self.count):
            return 0
        with open(self.count) as fh:
            return len(fh.read().split())

    def test_green_result_is_reused_for_the_same_code(self):
        res, code = testrun.run(self.repo, self.counted())
        self.assertEqual((code, res["verdict"], res["reused"]), (0, "pass", False))
        res, code = testrun.run(self.repo, self.counted())
        self.assertEqual((res["verdict"], res["reused"]), ("pass", True))
        self.assertEqual(self.runs(), 1)

    def test_a_code_change_runs_again_spec_and_commit_do_not(self):
        testrun.run(self.repo, self.counted())
        self.write("_bmad-output/implementation-artifacts/spec-1-1-x.md", "status: done\n")
        self.assertTrue(testrun.run(self.repo, self.counted())[0]["reused"])
        subprocess.run(["git", "-C", self.repo, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "-m", "1"], check=True)
        self.assertTrue(testrun.run(self.repo, self.counted())[0]["reused"])
        self.write("new.py", "y = 2\n")
        self.assertFalse(testrun.run(self.repo, self.counted())[0]["reused"])
        self.assertEqual(self.runs(), 2)

    def test_another_command_is_another_result(self):
        testrun.run(self.repo, self.counted())
        res, _ = testrun.run(self.repo, self.counted("true # backend"))
        self.assertFalse(res["reused"])
        self.assertEqual(self.runs(), 2)

    def test_failure_is_kept_with_tail_and_rerun_runs_again(self):
        res, code = testrun.run(self.repo, self.counted("echo boom; exit 3"))
        self.assertEqual((code, res["verdict"], res["code"]), (0, "problem", 3))
        self.assertIn("boom", res["tail"])
        self.assertTrue(os.path.exists(res["log"]))
        self.assertTrue(testrun.run(self.repo, self.counted("echo boom; exit 3"))[0]["reused"])
        old = time.time() - testrun.RECENT - 60
        os.utime(os.path.join(self.repo, ".auto-bmad", "tests", f"{res['key']}.json"), (old, old))
        res, _ = testrun.run(self.repo, self.counted("echo boom; exit 3"), rerun=True)
        self.assertFalse(res["reused"])
        self.assertEqual(self.runs(), 2)

    def test_running_answer_then_the_same_call_waits_for_that_run(self):
        res, code = testrun.run(self.repo, self.counted("sleep 2"), wait=0)
        self.assertEqual((code, res["verdict"]), (3, "running"))
        res, code = testrun.run(self.repo, self.counted("sleep 2"), wait=30)
        self.assertEqual((code, res["verdict"], res["reused"]), (0, "pass", False))
        self.assertEqual(self.runs(), 1)

    def test_runs_in_one_folder_do_not_overlap(self):
        spans = os.path.join(self.repo, "..", os.path.basename(self.repo) + ".spans")
        self.addCleanup(lambda: os.path.exists(spans) and os.unlink(spans))
        cmd = "echo start $(date +%s.%N) >> '{0}'; sleep 1; echo end $(date +%s.%N) >> '{0}' # {1}"
        threads = [threading.Thread(target=testrun.run, args=(self.repo, cmd.format(spans, i)))
                   for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with open(spans) as fh:
            marks = [line.split()[0] for line in fh]
        self.assertEqual(marks, ["start", "end", "start", "end"])

    def test_timeout_kills_the_command(self):
        res, _ = testrun.run(self.repo, "sleep 30", timeout=1)
        self.assertEqual(res["verdict"], "problem")
        self.assertIn("did not finish in 1 s", res["tail"])

    def test_state_does_not_dirty_the_tree(self):
        testrun.run(self.repo, "true")
        status = subprocess.run(["git", "-C", self.repo, "status", "--porcelain"],
                                capture_output=True, text=True).stdout
        self.assertEqual(status, "")

    def test_cli_takes_the_project_tests_check(self):
        self.write(".auto-bmad.toml", f'[[verify]]\nname = "project-tests"\ncommand = "{self.counted()}"\n')
        code, out = cli("--repo", self.repo)
        self.assertEqual((code, out["verdict"]), (0, "pass"))
        code, out = cli("--repo", self.repo)
        self.assertTrue(out["reused"])
        history = os.path.join(self.repo, ".auto-bmad", "tests", "history.jsonl")
        with open(history) as fh:
            self.assertEqual([json.loads(line)["reused"] for line in fh], [False, True])

    def test_a_suite_that_changes_the_tree_requires_a_fresh_run(self):
        cmd = self.counted("sleep 2; echo r > report.xml")
        self.assertEqual(testrun.run(self.repo, cmd, wait=0)[1], 3)
        time.sleep(3)
        res, code = testrun.run(self.repo, cmd, wait=30)
        self.assertEqual((code, res["verdict"]), (0, "pass"))
        self.assertFalse(res["reused"])
        self.assertTrue(testrun.run(self.repo, cmd)[0]["reused"])
        self.assertEqual(self.runs(), 2)

    def test_code_changed_after_being_read_does_not_receive_an_unearned_green(self):
        self.write("app.py", "x = 1\n")
        script = ('from pathlib import Path;import time,sys;'
                  'value=Path("app.py").read_text();Path(".auto-bmad/read").touch();end=time.monotonic()+5\n'
                  'while not Path(".auto-bmad/continue").exists() and time.monotonic()<end: time.sleep(.02)\n'
                  'sys.exit(0 if value=="x = 1\\n" else 1)')
        cmd = self.counted(shlex.join([sys.executable, "-c", script]))
        started, _ = testrun.run(self.repo, cmd, wait=0)
        until = time.monotonic() + 5
        while not os.path.exists(os.path.join(self.repo, ".auto-bmad", "read")) and time.monotonic() < until:
            time.sleep(0.02)
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".auto-bmad", "read")))
        self.write("app.py", "x = 2\n")
        self.write(".auto-bmad/continue", "go")
        answer = testrun.state(self.repo, started["key"] + ".answer.json")
        pid = testrun.state(self.repo, started["key"] + ".pid")
        until = time.monotonic() + 5
        while (not os.path.exists(answer) or os.path.exists(pid)) and time.monotonic() < until:
            time.sleep(.02)
        first = testrun.read_json(answer)
        self.assertEqual(first["verdict"], "pass")
        self.assertTrue(first["tree_changed"])
        second, _ = testrun.run(self.repo, cmd, wait=30)
        self.assertEqual(second["verdict"], "problem")
        self.assertFalse(second["reused"])

    def test_a_running_call_joins_while_the_tree_changes(self):
        cmd = self.counted("sleep 3; echo r > report.xml")
        self.assertEqual(testrun.run(self.repo, cmd, wait=0)[1], 3)
        self.write("scratch.txt", "x\n")
        res, code = testrun.run(self.repo, cmd, wait=30)
        self.assertEqual((code, res["verdict"]), (0, "pass"))
        self.assertEqual(self.runs(), 1)

    def test_code_changed_while_waiting_for_the_lock_is_kept_under_the_new_code(self):
        os.makedirs(os.path.join(self.repo, ".auto-bmad", "tests"), exist_ok=True)
        old_key = testrun.key_of(self.repo, "true")
        lock = open(os.path.join(self.repo, ".auto-bmad", "tests", "lock"), "w")
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX)
        out = {}
        t = threading.Thread(target=lambda: out.update(r=testrun.run(self.repo, "true", wait=30)))
        t.start()
        time.sleep(1)
        self.write("app.py", "x = 2\n")
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
        t.join()
        self.assertEqual(out["r"][0]["verdict"], "pass")
        self.assertIsNone(testrun.kept(self.repo, old_key))
        self.assertTrue(testrun.run(self.repo, "true")[0]["reused"])

    def test_a_stale_pid_record_is_not_a_run(self):
        os.makedirs(os.path.join(self.repo, ".auto-bmad", "tests"), exist_ok=True)
        key = testrun.key_of(self.repo, self.counted())
        testrun.write_json(os.path.join(self.repo, ".auto-bmad", "tests", f"{key}.pid"),
                           {"pid": os.getpid(), "start": "Mon Jan  1 00:00:00 2001", "command": self.counted()})
        res, code = testrun.run(self.repo, self.counted(), wait=30)
        self.assertEqual((code, res["verdict"]), (0, "pass"))
        self.assertEqual(self.runs(), 1)

    def test_a_timeout_is_not_kept(self):
        testrun.run(self.repo, self.counted("sleep 30"), timeout=1)
        res, _ = testrun.run(self.repo, self.counted("sleep 30"), timeout=1)
        self.assertFalse(res["reused"])
        self.assertEqual(self.runs(), 2)

    def test_rerun_takes_only_a_fresh_result_red_only_rerun_keeps_green(self):
        testrun.run(self.repo, self.counted())
        res, _ = testrun.run(self.repo, self.counted(), rerun=True)
        self.assertTrue(res["reused"])
        key = res["key"]
        path = os.path.join(self.repo, ".auto-bmad", "tests", f"{key}.json")
        old = time.time() - testrun.RECENT - 60
        os.utime(path, (old, old))
        self.assertTrue(testrun.run(self.repo, self.counted(), rerun="red")[0]["reused"])
        self.assertFalse(testrun.run(self.repo, self.counted(), rerun=True)[0]["reused"])
        self.assertEqual(self.runs(), 2)

    def test_old_red_is_run_again_by_red_rerun(self):
        res, _ = testrun.run(self.repo, self.counted("exit 1"))
        path = os.path.join(self.repo, ".auto-bmad", "tests", f"{res['key']}.json")
        old = time.time() - testrun.RECENT_RED - 60
        os.utime(path, (old, old))
        self.assertFalse(testrun.run(self.repo, self.counted("exit 1"), rerun="red")[0]["reused"])
        self.assertEqual(self.runs(), 2)

    def test_a_turned_off_check_is_no_command(self):
        self.write(".auto-bmad.toml", '[[verify]]\nname = "project-tests"\nenabled = false\n')
        self.write("package.json", '{"scripts": {"test": "true"}}')
        code, out = cli("--repo", self.repo)
        self.assertEqual(code, 1)
        self.assertIn("no test command", out["error"])

    def test_command_takes_the_check_timeout(self):
        self.write(".auto-bmad.toml", '[[verify]]\nname = "project-tests"\ncommand = "true"\ntimeout = 1\n')
        code, out = cli("--command", "sleep 30", "--repo", self.repo)
        self.assertIn("did not finish in 1 s", out["tail"])

    def test_cli_without_a_command_is_an_error(self):
        code, out = cli("--repo", self.repo)
        self.assertEqual(code, 1)
        self.assertIn("no test command", out["error"])


class Profile(unittest.TestCase):
    def test_fact_j_only_with_a_test_command(self):
        self.assertNotIn("auto-bmad test", write_profile.build("normal"))
        text = write_profile.build("normal", test_command="scripts/check.sh")
        self.assertIn("auto-bmad test --repo", text)
        self.assertIn("`scripts/check.sh`", text)


if __name__ == "__main__":
    unittest.main()
