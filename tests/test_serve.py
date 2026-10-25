"""Tests for extensions/mockmatch/serve.py: the port goes into the command, a busy port is
skipped, the own server is reused and stopped. python3 -m unittest discover tests"""
import http.server
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVE = os.path.join(HERE, "..", "extensions", "mockmatch", "serve.py")
_spec = importlib.util.spec_from_file_location("serve", SERVE)
serve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve)


def run(repo, *args):
    proc = subprocess.run([sys.executable, SERVE, *args], cwd=repo, capture_output=True, text=True,
                          timeout=60)
    return proc.returncode, json.loads(proc.stdout)


def some_free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CommandFor(unittest.TestCase):
    def test_port_reaches_the_command(self):
        self.assertEqual(serve.command_for("npm run dev", 5174), "npm run dev -- --port 5174")
        self.assertEqual(serve.command_for("cd web && pnpm run dev", 5174), "cd web && pnpm run dev --port 5174")
        self.assertEqual(serve.command_for("python3 -m http.server 8000", 8001), "python3 -m http.server 8001")
        self.assertEqual(serve.command_for("make dev PORT={port}", 9000), "make dev PORT=9000")
        self.assertEqual(serve.command_for("./run.sh", 9000), "./run.sh")


class Serve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        with open(os.path.join(self.repo, "index.html"), "w") as fh:
            fh.write("<h1>site</h1>")
        # A foreign service on the port from url: it answers, but it is not this project.
        self.busy = some_free_port()
        self.other = http.server.HTTPServer(("127.0.0.1", self.busy), http.server.SimpleHTTPRequestHandler)
        threading.Thread(target=self.other.serve_forever, daemon=True).start()

    def tearDown(self):
        run(self.repo, "stop")
        self.other.shutdown()
        self.other.server_close()
        self.tmp.cleanup()

    def test_busy_port_skipped_own_server_reused_and_stopped(self):
        url = f"http://localhost:{self.busy}"
        code, out = run(self.repo, "start", "--serve", "python3 -m http.server", "--url", url, "--wait", "20")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["started"])
        self.assertNotEqual(out["port"], self.busy)
        self.assertTrue(serve.answers(out["url"]))
        code, again = run(self.repo, "start", "--serve", "python3 -m http.server", "--url", url)
        self.assertEqual((code, again["started"], again["port"]), (0, False, out["port"]))
        self.assertIn("serve.py stop", again["cleanup"])
        code, stopped = run(self.repo, "stop")
        self.assertTrue(stopped["stopped"])

    def test_server_that_exits_is_an_error_with_the_log(self):
        code, out = run(self.repo, "start", "--serve", "echo boom; exit 3", "--url",
                        f"http://localhost:{self.busy}", "--wait", "10")
        self.assertEqual(code, 1)
        self.assertIn("boom", out["log_tail"])


if __name__ == "__main__":
    unittest.main()
