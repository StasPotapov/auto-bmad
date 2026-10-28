"""Tests of stub.py: background servers of a check, started and stopped by name.
python3 -m unittest discover tests"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import stub  # noqa: E402
import story_finish  # noqa: E402

SCRIPT = os.path.join(HERE, "..", "scripts", "stub.py")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
    return bool(out.strip()) and not out.strip().startswith("Z")


class StubTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.extra = []
        self.env = os.environ.get("AUTO_BMAD_CONFIG")
        os.environ["AUTO_BMAD_CONFIG"] = os.path.join(self.repo, "none.toml")

    def tearDown(self):
        if self.env is None:
            os.environ.pop("AUTO_BMAD_CONFIG", None)
        else:
            os.environ["AUTO_BMAD_CONFIG"] = self.env
        stub.stop(self.repo, every=True)
        for p in self.extra:
            if p.poll() is None:
                p.kill()
                p.wait()
        self.tmp.cleanup()

    def cli(self, *args):
        proc = subprocess.run([sys.executable, SCRIPT, *args[:1], *args[1:]], capture_output=True,
                              text=True, cwd=self.repo)
        return proc.returncode, json.loads(proc.stdout)

    def start(self, name, *command, port=None):
        extra = ["--port", str(port)] if port else []
        return self.cli("start", name, *extra, "--repo", self.repo, "--", *command)

    def test_start_and_stop_a_server_on_a_port(self):
        port = free_port()
        code, out = self.start("web", sys.executable, "-m", "http.server", str(port), port=port)
        self.assertEqual(code, 0, out)
        self.assertTrue(out["started"])
        self.assertTrue(stub.port_busy(port))
        self.assertTrue(os.path.isfile(os.path.join(self.repo, ".auto-bmad", "stubs", "web.json")))
        code, out = self.cli("stop", "web", "--repo", self.repo)
        self.assertEqual(code, 0, out)
        self.assertTrue(out["stubs"][0]["stopped"])
        self.assertTrue(out["stubs"][0]["port_free"])
        self.assertFalse(stub.port_busy(port))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".auto-bmad", "stubs", "web.json")))

    def test_stop_all_and_list(self):
        self.assertEqual(self.start("a", "sleep", "30")[0], 0)
        self.assertEqual(self.start("b", "sleep", "31")[0], 0)
        self.assertEqual([s["name"] for s in self.cli("list", "--repo", self.repo)[1]["stubs"]], ["a", "b"])
        pids = [s["pid"] for s in self.cli("list", "--repo", self.repo)[1]["stubs"]]
        code, out = self.cli("stop", "--all", "--repo", self.repo)
        self.assertEqual(code, 0, out)
        self.assertEqual([s["stopped"] for s in out["stubs"]], [True, True])
        self.assertFalse(any(alive(p) for p in pids))

    def test_another_process_with_the_same_pid_is_left_alone(self):
        self.assertEqual(self.start("a", "sleep", "30")[0], 0)
        path = stub.state_path(self.repo, "a")
        with open(path) as fh:
            state = json.load(fh)
        self.cli("stop", "a", "--repo", self.repo)
        time.sleep(1.1)                         # same command, a later start time
        foreign = subprocess.Popen(["sleep", "30"], start_new_session=True)
        self.extra.append(foreign)
        state.update(pid=foreign.pid, pgid=foreign.pid)       # the pid went to someone else
        with open(path, "w") as fh:
            json.dump(state, fh)
        code, out = self.cli("stop", "a", "--repo", self.repo)
        self.assertEqual(code, 0, out)
        self.assertFalse(out["stubs"][0]["stopped"])
        self.assertIn("another process", out["stubs"][0]["note"])
        self.assertTrue(alive(foreign.pid))

    def test_group_without_its_leader_is_stopped(self):
        code, out = self.start("g", "sh", "-c", "sleep 30 & sleep 1")
        self.assertEqual(code, 0, out)
        time.sleep(1.5)
        self.assertIsNone(stub.proc_info(out["pid"]))
        self.assertTrue(stub.group_members(out["pgid"]))
        code, res = self.cli("stop", "g", "--repo", self.repo)
        self.assertEqual(code, 0, res)
        self.assertTrue(res["stubs"][0]["stopped"])
        self.assertFalse(stub.group_members(out["pgid"]))

    def test_taken_port_and_busy_name_are_refused(self):
        port = free_port()
        self.assertEqual(self.start("web", sys.executable, "-m", "http.server", str(port), port=port)[0], 0)
        code, out = self.start("other", sys.executable, "-m", "http.server", str(port), port=port)
        self.assertEqual(code, 2)
        self.assertIn("taken", out["error"])
        code, out = self.start("web", "sleep", "5")
        self.assertEqual(code, 2)
        self.assertIn("another command", out["error"])
        code, out = self.start("web", sys.executable, "-m", "http.server", str(port), port=port)
        self.assertEqual((code, out["started"]), (0, False))

    def test_command_that_exits_is_an_error(self):
        code, out = self.start("x", "false")
        self.assertEqual(code, 2)
        self.assertIn("exited", out["error"])

    def test_worktree_keeps_stubs_in_the_main_tree(self):
        subprocess.run(["git", "-C", self.repo, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        wt = os.path.join(self.repo, "wt")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", wt], check=True)
        code, out = self.cli("start", "w", "--repo", wt, "--", "sleep", "30")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.repo, ".auto-bmad", "stubs", "w.json")))

    def test_story_finish_stops_forgotten_stubs(self):
        self.assertEqual(self.start("left", "sleep", "30")[0], 0)
        pid = self.cli("list", "--repo", self.repo)[1]["stubs"][0]["pid"]
        out = story_finish.finish({"epic": 1, "run_end": {"status": "done", "done": 1, "left": 0}}, self.repo)
        self.assertIn({"step": "stop stubs", "ok": True, "detail": "left"}, out["steps"])
        self.assertFalse(alive(pid))


if __name__ == "__main__":
    unittest.main()
