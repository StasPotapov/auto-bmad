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
import agent_adapters as adapters
import agent_config
import agent_runtime as runtime
import agent_smoke

FAKE = str(Path(__file__).with_name("fake_cli.py"))


class RuntimeTest(unittest.TestCase):
    def run_fake(self, mode="good", *, timeout=3, cancel=None, max_output=runtime.MAX_OUTPUT):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.attempt = Path(self.tmp.name) / "attempt"
        parser = adapters.CodexResult()
        return runtime.execute([sys.executable, FAKE, mode, "$(touch bad)", "a b", "`literal`"],
                               cwd=self.tmp.name, env=runtime.environment(["PATH"]), stdin="Привет\n",
                               directory=self.attempt, timeout=timeout, consume=parser.consume,
                               finish=parser.finish, cancel=cancel, max_output=max_output)

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
                      "import agent_adapters as a;p=a.CodexResult();"
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

    def test_smoke_preparation_has_its_own_timeout_and_keeps_logs(self):
        with tempfile.TemporaryDirectory() as d:
            logs = Path(d) / "preparation"
            with self.assertRaisesRegex(ValueError, "preparation timed_out"):
                agent_smoke.prepare([sys.executable, FAKE, "hang"], d, {}, logs, 0.2)
            self.assertEqual(json.loads((logs / "status.json").read_text())["execution_status"], "timed_out")


class AdapterTest(unittest.TestCase):
    def profile(self, **extra):
        return agent_config.profile("dev", {"adapter": "codex", "executable": "codex", "model": "test-model",
                                            "permissions": "read-only", **extra})

    def detection(self):
        return {"executable": "/test/codex", "capabilities": {
            "read_only_enforcement": "supported", "engine_delegation_bridge": "unsupported"}}

    def test_codex_argv_keeps_sandbox_and_effort_explicit(self):
        argv = adapters.argv(self.profile(effort="high"), self.detection(), "/test/work tree", "schema", "result")
        self.assertIn('model_reasoning_effort="high"', argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertIn("/test/work tree", argv)
        self.assertNotIn("--dangerously-bypass-hook-trust", argv)

    def test_unverified_backend_and_capabilities_cannot_execute(self):
        for profile, engine in [(self.profile(adapter="kimi", output_protocol="kimi-stream-json-v1"), False),
                                (self.profile(effort="max"), False),
                                (self.profile(), True),
                                (self.profile(capability_requirements=["unknown"]), False)]:
            with self.subTest(profile=profile, engine=engine), self.assertRaises(ValueError):
                adapters.validate(profile, self.detection(), engine=engine)

    def test_help_probe_does_not_start_a_model(self):
        profile = self.profile()
        help_text = "--json --output-schema --sandbox --model --cd --config"
        from subprocess import CompletedProcess
        responses = [CompletedProcess([], 0, "codex-cli test\n", ""), CompletedProcess([], 0, help_text, "")]
        with patch.object(adapters.shutil, "which", return_value="/test/codex"), \
                patch.object(adapters.subprocess, "run", side_effect=responses) as run:
            out = adapters.detect(profile)
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [["/test/codex", "--version"], ["/test/codex", "exec", "--help"]])
        self.assertEqual(out["capabilities"]["engine_delegation_bridge"], "supported")

    def test_relative_cli_path_is_fixed_before_the_cwd_changes(self):
        from subprocess import CompletedProcess
        responses = [CompletedProcess([], 0, "codex-cli test", ""),
                     CompletedProcess([], 0, "--json --output-schema --sandbox --model --cd --config", "")]
        with patch.object(adapters.shutil, "which", return_value="relative/codex"), \
                patch.object(adapters.subprocess, "run", side_effect=responses):
            out = adapters.detect(self.profile())
        self.assertEqual(out["executable"], os.path.abspath("relative/codex"))

    def test_live_smoke_requires_explicit_opt_in_before_any_process(self):
        import contextlib
        import io
        with patch.object(agent_smoke, "smoke") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(agent_smoke.main(["--model", "test-model"]), 2)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
