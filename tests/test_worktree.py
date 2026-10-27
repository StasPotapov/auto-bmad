import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import worktree  # noqa: E402


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class SeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, "_bmad", "custom"))
        sh(self.repo, "git", "init", "-q")
        sh(self.repo, "git", "config", "user.email", "t@t")
        sh(self.repo, "git", "config", "user.name", "t")
        files = {
            ".gitignore": "*.user.toml\n_bmad/cache/\n",
            "_bmad/config.toml": "x = 1\n",
            "_bmad/config.user.toml": "user_skill_level = 'expert'\n",
            "_bmad/custom/bmad-build-auto.user.toml": "level = 'normal'\n",
            "_bmad/cache/blob.bin": "x",
        }
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(self.repo, rel)), exist_ok=True)
            with open(os.path.join(self.repo, rel), "w") as fh:
                fh.write(text)
        sh(self.repo, "git", "add", ".gitignore", "_bmad/config.toml")
        sh(self.repo, "git", "commit", "-qm", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_copies_ignored_bmad_configs(self):
        result, code = worktree.cmd_add(self.repo, "1-1")
        self.assertEqual(code, 0)
        self.assertTrue(result["profile_copied"])
        self.assertEqual(result["seeded"], ["_bmad/config.user.toml",
                                            "_bmad/custom/bmad-build-auto.user.toml"])
        self.assertTrue(os.path.exists(os.path.join(result["path"], "_bmad", "config.user.toml")))
        self.assertFalse(os.path.exists(os.path.join(result["path"], "_bmad", "cache", "blob.bin")))

    def test_seed_into_existing_tree(self):
        other = os.path.join(self.tmp.name, "wt")
        sh(self.repo, "git", "worktree", "add", "-q", other, "HEAD")
        self.assertEqual(worktree.seed(self.repo, other),
                         ["_bmad/config.user.toml", "_bmad/custom/bmad-build-auto.user.toml"])
        self.assertEqual(worktree.seed(self.repo, self.repo), [])

    def test_list_shows_log_and_uncommitted_files(self):
        result, _ = worktree.cmd_add(self.repo, "1-1")
        with open(os.path.join(result["path"], "new.py"), "w") as fh:
            fh.write("x = 1\n")
        with open(os.path.join(result["path"], "тест файл.py"), "w") as fh:
            fh.write("y = 1\n")
        listed, code = worktree.cmd_list(self.repo, with_details=True)
        self.assertEqual(code, 0)
        item = listed["worktrees"][0]
        self.assertEqual(sorted(item["dirty"]), ["new.py", "тест файл.py"])
        self.assertTrue(item["log"][0].endswith("init"))
        self.assertNotIn("dirty", worktree.cmd_list(self.repo)[0]["worktrees"][0])   # only on request

    def test_list_marks_missing_and_broken_worktrees(self):
        result, _ = worktree.cmd_add(self.repo, "1-1")
        with open(os.path.join(result["path"], ".git"), "w") as fh:
            fh.write("gitdir: /nowhere\n")
        item = worktree.cmd_list(self.repo, with_details=True)[0]["worktrees"][0]
        self.assertIsNone(item["dirty"])                  # unknown, not clean
        self.assertIn("error", item)
        import shutil
        shutil.rmtree(result["path"])
        item = worktree.cmd_list(self.repo, with_details=True)[0]["worktrees"][0]
        self.assertTrue(item["missing"])


if __name__ == "__main__":
    unittest.main()
