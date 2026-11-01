import json
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_control
import test_bridge
import run_queue


class ControlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        self.path = self.root / ".git/auto-bmad-sessions/fixture/session.json"
        self.path.parent.mkdir(parents=True)
        self.data = {"repo": str(self.root), "kind": "queue", "status": "running", "control_version": 1,
                     "planned_stories": ["1-1", "1-2"], "started_stories": ["1-1", "1-2"]}
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.data))

    def test_stop_after_normalizes_ids_and_reports_already_started_overshoot(self):
        with patch.object(run_control.ControllerWatch, "alive", return_value=True):
            result = run_control.request(self.path, "1.1")
        self.assertEqual(result["stop_after"], "1-1")
        self.assertEqual(result["already_started_after"], ["1-2"])
        self.assertEqual(run_control.read(self.path.parent, self.data["planned_stories"]), "1-1")

    def test_unknown_story_finished_run_and_old_runtime_are_refused(self):
        with patch.object(run_control.ControllerWatch, "alive", return_value=True):
            with self.assertRaisesRegex(ValueError, "planned queue"):
                run_control.request(self.path, "2-1")
            self.data["status"] = "completed"
            self.save()
            with self.assertRaisesRegex(ValueError, "no longer running"):
                run_control.request(self.path, "1-1")
            self.data.update(status="running", control_version=0)
            self.save()
            with self.assertRaisesRegex(ValueError, "updated runtime"):
                run_control.request(self.path, "1-1")
        self.assertFalse((self.path.parent / "stop-after.json").exists())

    def test_host_bridge_resolves_only_frozen_registered_commands(self):
        data = {"host_tests": {"version": 1, "checks": {"project-tests": {"command": "scripts/check.sh"}}}}
        self.assertEqual(test_bridge.check_name(data, "scripts/check.sh", "other"), "project-tests")
        self.assertEqual(test_bridge.check_name(data, None, "project-tests"), "project-tests")
        self.assertIsNone(test_bridge.check_name(data, "scripts/check.sh; touch surprise", "project-tests"))
        self.assertIsNone(test_bridge.check_name(data, None, "unknown"))
        self.data.update(data)
        self.save()
        with self.assertRaisesRegex(ValueError, "only registered"):
            test_bridge.request(self.root, self.path, "arbitrary command")

    def test_cli_accepts_live_stop_without_model_opt_in_and_clean_stop_exits_zero(self):
        output = io.StringIO()
        with patch.object(run_control.ControllerWatch, "alive", return_value=True), contextlib.redirect_stdout(output):
            code = run_queue.main(["stop-after", "--session", str(self.path), "--story", "1-1"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["accepted"])
        with patch.object(run_queue, "run", return_value={"execution_status": "stopped", "run_completed": False}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_queue.main(["--allow-model"]), 0)


if __name__ == "__main__":
    unittest.main()
