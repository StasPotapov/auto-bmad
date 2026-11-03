import json
import os
import sys
import tempfile
import threading
import signal
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import codex_events as adapters
import agent_runtime as runtime

FAKE = str(Path(__file__).with_name("fake_cli.py"))


class RuntimeTest(unittest.TestCase):
    def run_fake(self, mode="good", *, timeout=3, cancel=None, max_output=runtime.MAX_OUTPUT,
                 idle_timeout=None, idle_pause=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.attempt = Path(self.tmp.name) / "attempt"
        parser = adapters.CodexResult()
        return runtime.execute([sys.executable, FAKE, mode, "$(touch bad)", "a b", "`literal`"],
                               cwd=self.tmp.name, env=runtime.environment(["PATH"]), stdin="Привет\n",
                               directory=self.attempt, timeout=timeout, consume=parser.consume,
                               finish=parser.finish, cancel=cancel, max_output=max_output,
                               idle_timeout=idle_timeout, idle_pause=idle_pause)

    def test_meaningful_progress_can_outlive_the_idle_limit(self):
        out = self.run_fake("progress", timeout=None, idle_timeout=0.2)
        self.assertEqual(out["execution_status"], "completed", out)
        self.assertGreater(out["seconds"], 0.8)

    def test_chatter_and_duplicate_events_cannot_hide_confirmed_stalls(self):
        for mode in ("chatter", "duplicate", "duplicate-new-id", "closed-pipes"):
            with self.subTest(mode=mode):
                out = self.run_fake(mode, timeout=None, idle_timeout=0.15)
                self.assertEqual(out["execution_status"], "stalled", out)
                self.assertEqual(out["watchdog"]["state"], "stalled")
                self.assertEqual(out["watchdog"]["action"], "stop")
                self.assertIn("confirmation_elapsed", out["watchdog"])
                self.assertLess(out["seconds"], 2)

    def test_supervised_work_pauses_idle_checks_but_not_an_explicit_deadline(self):
        out = self.run_fake("progress", timeout=None, idle_timeout=0.05, idle_pause=lambda: True)
        self.assertEqual(out["execution_status"], "completed", out)
        out = self.run_fake("hang", timeout=0.2, idle_timeout=0.05, idle_pause=lambda: True)
        self.assertEqual(out["execution_status"], "timed_out", out)

    def test_progress_returning_during_confirmation_keeps_work_running(self):
        out = self.run_fake("silent", timeout=None, idle_timeout=0.6)
        self.assertEqual(out["execution_status"], "completed", out)
        self.assertGreater(out["seconds"], 0.8)

    def test_terminal_event_without_newline_preempts_idle_stop(self):
        out = self.run_fake("late-final", timeout=None, idle_timeout=1)
        self.assertEqual(out["execution_status"], "completed", out)

    def test_observed_terminal_object_does_not_allow_trailing_garbage(self):
        out = self.run_fake("invalid-terminal", idle_timeout=0.1)
        self.assertEqual(out["execution_status"], "failed", out)
        self.assertEqual(out["error"]["kind"], "protocol")

    def test_output_pipes_left_open_after_exit_have_a_bounded_drain(self):
        try:
            with patch.object(runtime, "POST_EXIT_DRAIN", 0.2), patch.object(runtime, "terminate", wraps=runtime.terminate) as terminate:
                out = self.run_fake("detached-pipe", timeout=None, idle_timeout=1)
            terminate.assert_not_called()
            self.assertEqual(out["execution_status"], "needs_attention", out)
            self.assertEqual(out["error"]["kind"], "cleanup_failed")
            self.assertIn("output pipes", out["error"]["message"])
            self.assertLess(out["seconds"], 2)
        finally:
            marker = Path(self.tmp.name) / "detached.pid"
            if marker.exists():
                try:
                    os.kill(int(marker.read_text()), signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def test_idle_confirmation_is_cancelled_by_supervised_work(self):
        started = time.monotonic()
        out = self.run_fake("silent", timeout=None, idle_timeout=0.3,
                            idle_pause=lambda: 0.4 <= time.monotonic() - started < 0.8)
        self.assertEqual(out["execution_status"], "completed", out)

    def test_distinct_file_edits_are_progress_even_when_the_path_is_the_same(self):
        parser = adapters.CodexResult()
        event = {"type": "item.completed", "item": {
            "id": "first", "type": "file_change", "changes": [{"path": "app.py", "kind": "update"}]}}
        self.assertTrue(parser.consume(event))
        self.assertFalse(parser.consume(event))
        event["item"]["id"] = "second"
        self.assertTrue(parser.consume(event))

    def test_drains_both_streams_and_preserves_literal_argv(self):
        with patch.dict(os.environ, {"AUTO_BMAD_FAKE_SECRET": "must-not-leak"}):
            out = self.run_fake()
        self.assertEqual(out["execution_status"], "completed")
        self.assertEqual(out["result"]["stdin"], "Привет\n")
        self.assertEqual(out["result"]["arguments"], ["$(touch bad)", "a b", "`literal`"])
        self.assertFalse(out["result"]["secret_seen"])
        self.assertFalse((Path(self.tmp.name) / "bad").exists())
        self.assertEqual((self.attempt.stat().st_mode & 0o777), 0o700)
        self.assertEqual(json.loads((self.attempt / "status.json").read_text())["execution_status"], "completed")
        self.assertGreater((self.attempt / "stderr.log").stat().st_size, 65536)

    def test_bad_streams_and_missing_results_fail_closed(self):
        for mode in ("malformed", "empty", "error", "exit-failure"):
            with self.subTest(mode=mode):
                out = self.run_fake(mode)
                self.assertEqual(out["execution_status"], "failed")
                self.assertIn(out["error"]["kind"], ("protocol", "process"))

    def test_output_limit_stops_the_child(self):
        out = self.run_fake("flood", max_output=10000)
        self.assertEqual(out["execution_status"], "failed")
        self.assertIn("output limit", out["error"]["message"])

    def test_timeout_stops_even_a_child_ignoring_term(self):
        out = self.run_fake("hang", timeout=0.2)
        self.assertEqual(out["execution_status"], "timed_out")
        self.assertIsNotNone(out["exit_code"])
        self.assertLess(out["seconds"], 2)

    def test_cleanup_failure_preserves_the_timeout_cause(self):
        original = runtime.wait_cleanup

        def cleanup(proc):
            original(proc)
            raise RuntimeError("fixture cleanup failed")

        with patch.object(runtime, "wait_cleanup", side_effect=cleanup):
            out = self.run_fake("hang", timeout=0.2)
        self.assertEqual(out["execution_status"], "needs_attention")
        self.assertEqual(out["termination_status"], "timed_out")
        self.assertEqual(out["error"]["kind"], "cleanup_failed")

    def test_cancel_also_works_when_the_child_closes_its_pipes(self):
        stop = threading.Event()
        timer = threading.Timer(0.2, stop.set)
        timer.start()
        try:
            out = self.run_fake("closed-pipes", cancel=stop)
        finally:
            timer.cancel()
        self.assertEqual(out["execution_status"], "cancelled")
        self.assertLess(out["seconds"], 2)

    def test_attempt_directory_is_never_reused(self):
        self.run_fake()
        with self.assertRaises(FileExistsError):
            runtime.execute([sys.executable], cwd=self.tmp.name, env={}, stdin="", directory=self.attempt,
                            timeout=1, consume=lambda x: None, finish=lambda x: {})

    def test_sigterm_of_controller_stops_the_cli_before_releasing_control(self):
        with tempfile.TemporaryDirectory() as d:
            attempt = Path(d) / "attempt"
            script = ("import sys;sys.path.insert(0,sys.argv[1]);import agent_runtime as r;"
                      "import codex_events as a;p=a.CodexResult();"
                      "result=r.execute([sys.executable,sys.argv[2],'hang'],cwd=sys.argv[3],env={},stdin='',"
                      "directory=sys.argv[4],timeout=30,consume=p.consume,finish=p.finish);"
                      "print(result['execution_status'])")
            proc = subprocess.Popen([sys.executable, "-c", script, str(Path(runtime.__file__).parent),
                                     FAKE, d, str(attempt)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True)
            child = None
            try:
                until = time.monotonic() + 5
                while time.monotonic() < until:
                    try:
                        child = json.loads((attempt / "status.json").read_text()).get("pid")
                    except (FileNotFoundError, ValueError):
                        pass
                    if child:
                        break
                    time.sleep(0.01)
                self.assertIsNotNone(child)
                proc.send_signal(signal.SIGTERM)
                out, err = proc.communicate(timeout=3)
                self.assertEqual(proc.returncode, 0, err)
                self.assertEqual(out.strip(), "cancelled")
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
                if child:
                    try:
                        os.killpg(child, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
