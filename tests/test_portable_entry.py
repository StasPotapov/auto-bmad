"""Client adapters plan and inspect the same project without model executables."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PortableEntryTest(unittest.TestCase):
    def test_both_clients_plan_and_doctor_without_model_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "tools"
            scripts.mkdir()
            for name in ("codex", "claude"):
                path = scripts / name
                path.write_text('#!/bin/sh\ntouch "$MODEL_TRAP"\nexit 99\n')
                path.chmod(0o755)
            env = {**os.environ, "AUTO_BMAD_CONFIG": str(root / "absent"),
                   "PATH": str(scripts) + os.pathsep + os.environ["PATH"],
                   "MODEL_TRAP": str(root / "model-started")}
            env.pop("AUTO_BMAD_EXECUTOR", None)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture",
                            "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty",
                            "-qm", "fixture"], check=True)
            artifacts = root / "_bmad-output/implementation-artifacts"
            artifacts.mkdir(parents=True)
            (artifacts / "sprint-status.yaml").write_text(
                "development_status:\n  epic-1: in-progress\n  1-1-fixture: backlog\n")
            (root / ".auto-bmad.toml").write_text(
                '[execution]\nbackend="native"\n[executors.codex]\nmodel="gpt-6.1-sol"\n'
                '[executors.claude]\nmodel="sonnet"\neffort="high"\n')
            before = (root / ".auto-bmad.toml").read_bytes()
            for client, wrapper, backend in (
                ("codex", "integrations/codex/skills/auto-bmad/scripts/run.py", "native"),
                ("claude", "skills/auto-bmad/scripts/run.py", "legacy-plugin"),
            ):
                with self.subTest(client=client):
                    proc = subprocess.run([sys.executable, str(ROOT / wrapper), "plan", "--repo", str(root),
                                           "--arg", "1-1 --normal"], env=env, capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
                    plan = json.loads(proc.stdout)
                    self.assertEqual(plan["backend"], backend)
                    self.assertFalse(plan["model_started"])
                    self.assertEqual(plan["merge_policy"], "manual")
                    for role in plan["roles"].values():
                        self.assertTrue(Path(role["prompt"]).is_file())
                    proc = subprocess.run([str(ROOT / "bin/auto-bmad"), "--executor", client,
                                           "doctor", "--repo", str(root)], env=env, capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
                    result = json.loads(proc.stdout)
                    self.assertTrue(result["ok"])
                    self.assertFalse(result["host_capabilities_checked"])
                    self.assertFalse(result["model_started"])
            self.assertFalse((root / "model-started").exists())
            self.assertEqual((root / ".auto-bmad.toml").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
