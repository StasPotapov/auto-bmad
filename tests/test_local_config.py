"""The local config layer .auto-bmad.local.toml: over the project one, seen by every reader.
python3 -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import ext  # noqa: E402
import plan_run  # noqa: E402
import roles  # noqa: E402
import setup  # noqa: E402
import worktree  # noqa: E402


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


class LocalLayerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        sh(self.repo, "git", "init", "-q", "-b", "main")
        sh(self.repo, "git", "config", "user.email", "t@t")
        sh(self.repo, "git", "config", "user.name", "t")
        write(self.repo, ".auto-bmad.toml",
              '[run]\nlevel = "fast"\nwidth = 2\n\n[roles.implementer]\nmodel = "sonnet"\n\n'
              '[[verify]]\nname = "project-tests"\ncommand = "make test"\n')
        self.env = os.environ.get("AUTO_BMAD_CONFIG")
        os.environ["AUTO_BMAD_CONFIG"] = os.path.join(self.repo, "none.toml")

    def tearDown(self):
        if self.env is None:
            os.environ.pop("AUTO_BMAD_CONFIG", None)
        else:
            os.environ["AUTO_BMAD_CONFIG"] = self.env
        self.tmp.cleanup()

    def local(self, text):
        write(self.repo, ".auto-bmad.local.toml", text)

    def test_local_layer_wins_over_the_project(self):
        self.local('[run]\nlevel = "deep"\n\n[[verify]]\nname = "project-tests"\ncommand = "make quick"\n')
        cfg, sources, _ = ext.load(self.repo)
        self.assertEqual([s["layer"] for s in sources], ["defaults", "project", "local"])
        self.assertEqual(cfg["run"], {"level": "deep", "width": 2})
        tests = next(v for v in cfg["verify"] if v["name"] == "project-tests")
        self.assertEqual(tests["command"], "make quick")
        self.assertEqual(tests["kind"], "command")                     # merged by name, defaults kept

    def test_readers_see_the_local_layer(self):
        self.local('[run]\nparallel = "off"\n\n[roles.implementer]\neffort = "max"\n')
        self.assertEqual(plan_run.run_defaults(self.repo), {"level": "fast", "parallel": "off", "width": 2})
        found, errors, _ = roles.load_roles(self.repo)
        self.assertEqual(errors, [])
        self.assertEqual((found["implementer"]["model"], found["implementer"]["effort"]), ("sonnet", "max"))

    def test_no_local_file_changes_nothing(self):
        cfg, sources, _ = ext.load(self.repo)
        self.assertEqual([s["layer"] for s in sources], ["defaults", "project"])
        self.assertEqual(cfg["run"]["level"], "fast")

    def test_setup_local_closes_it_from_git(self):
        self.local('[run]\nlevel = "deep"\n')
        args = SimpleNamespace(write=False)
        out, _ = setup.cmd_local(args, self.repo)
        self.assertEqual((out["exists"], out["tracked"], out["ignored"]), (True, False, False))
        self.assertIn("setup local --write", out["fix"])
        out, _ = setup.cmd_local(SimpleNamespace(write=True), self.repo)
        self.assertTrue(out["written"])
        self.assertTrue(out["ignored"])
        self.assertNotIn(".auto-bmad.local.toml", sh(self.repo, "git", "status", "--porcelain"))
        self.assertEqual(setup.cmd_check(self.repo)[0]["project"]["local"]["ignored"], True)
        out, _ = setup.cmd_local(SimpleNamespace(write=True), self.repo)
        self.assertFalse(out["written"])                               # once only

    def test_a_rule_outside_the_project_gitignore_is_not_enough(self):
        self.local('[run]\nlevel = "deep"\n')
        with open(os.path.join(self.repo, ".git", "info", "exclude"), "a") as fh:
            fh.write("/.auto-bmad.local.toml\n")
        out, _ = setup.cmd_local(SimpleNamespace(write=False), self.repo)
        self.assertEqual((out["ignored"], out["in_gitignore"]), (True, False))
        self.assertIn(".gitignore", out["fix"])
        out, _ = setup.cmd_local(SimpleNamespace(write=True), self.repo)
        self.assertTrue(out["in_gitignore"])
        with open(os.path.join(self.repo, ".gitignore")) as fh:
            self.assertIn("/.auto-bmad.local.toml", fh.read())

    def test_a_negated_rule_does_not_count(self):
        write(self.repo, ".gitignore", "*.toml\n!.auto-bmad.local.toml\n")
        out, _ = setup.cmd_local(SimpleNamespace(write=False), self.repo)
        self.assertEqual((out["ignored"], out["in_gitignore"]), (False, False))
        out, _ = setup.cmd_local(SimpleNamespace(write=True), self.repo)
        self.assertTrue(out["in_gitignore"])

    def test_preflight_warns_when_it_is_committed(self):
        self.local('[run]\nlevel = "deep"\n')
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "init")
        proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, "preflight.py"), "--repo", self.repo],
                              capture_output=True, text=True, env=dict(os.environ))
        out = json.loads(proc.stdout)
        self.assertTrue(any(".auto-bmad.local.toml is committed" in w for w in out["warnings"]), out)

    def test_worktree_run_takes_the_local_layer_along(self):
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "init")
        self.local('[run]\nlevel = "deep"\n')
        result, code = worktree.cmd_start(self.repo, "epic-1")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["left_in_main"], [".auto-bmad.local.toml"])     # not ignored yet
        self.assertEqual(sh(result["path"], "git", "status", "--porcelain"), "")
        self.assertEqual(ext.load(result["path"])[0]["run"]["level"], "deep")    # read from the main tree
        setup.cmd_local(SimpleNamespace(write=True), self.repo)
        sh(self.repo, "git", "add", ".gitignore")
        sh(self.repo, "git", "commit", "-qm", "ignore the local layer")
        sh(result["path"], "git", "merge", "-q", "main")
        result, _ = worktree.cmd_start(self.repo, "epic-1")
        self.assertIn(".auto-bmad.local.toml", result["seeded"])                   # ignored: copied
        self.assertEqual(sh(result["path"], "git", "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
