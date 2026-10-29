import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import engine
import execution_state as state


class EngineTest(unittest.TestCase):
    def test_inspection_hashes_contract_without_executing_sources(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            skill = root / engine.ENGINE_REL
            skill.mkdir(parents=True)
            for name in engine.REQUIRED:
                (skill / name).write_text("this must never execute")
            (skill / "customize.toml").write_text('[workflow]\npersistent_facts=[]\nimplementation_handoff="x"\n'
                'review_layers=[]\nactivation_steps_prepend=[]\nactivation_steps_append=[]\non_complete=""\n')
            scripts = root / "_bmad/scripts"
            scripts.mkdir(parents=True)
            for name in ("render_skill.py", "config_utils.py"):
                (scripts / name).write_text('raise Exception("do not run during inspect")')
            first = engine.inspect(d)
            self.assertFalse(first["execution_ready"])
            (skill / "workflow.md").write_text("changed engine")
            self.assertNotEqual(engine.inspect(d)["fingerprint"], first["fingerprint"])
            (skill / "workflow.md").unlink()
            (skill / "workflow.md").symlink_to("/etc/hosts")
            with self.assertRaises(ValueError):
                engine.inspect(d)


class LeaseTest(unittest.TestCase):
    def test_inherited_guard_keeps_lease_after_normal_parent_context_exit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
            with state.lease(root):
                child = subprocess.Popen([sys.executable, "-c", "input()"], stdin=subprocess.PIPE,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         pass_fds=(state.current_lease_fd(),))
            try:
                with self.assertRaisesRegex(ValueError, "active execution"), state.lease(root):
                    pass
            finally:
                child.communicate(input=b"done\n", timeout=5)
            with state.lease(root):
                pass

    def test_competing_processes_and_symlink_alias_share_one_lock(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
            alias = Path(d) / "alias"
            alias.symlink_to(root, target_is_directory=True)
            script = ("import sys;sys.path.insert(0,sys.argv[1]);import execution_state as s;"
                      "\nwith s.lease(sys.argv[2]): print('acquired')")
            argv = [sys.executable, "-c", script, str(Path(state.__file__).parent), str(alias)]
            with state.lease(root):
                result = subprocess.run(argv, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("active execution", result.stderr)
            self.assertEqual(subprocess.run(argv, capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
