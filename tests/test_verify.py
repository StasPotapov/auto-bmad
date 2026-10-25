import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import verify  # noqa: E402

SPEC = """---
title: 'x'
status: 'done'
---

<intent-contract>
## Intent
untouchable
</intent-contract>

## Tasks & Acceptance

**Execution:**
- `a.kt` -- do it -- why

## Spec Change Log

## Review Triage Log
"""


def run(*args, stdin=None):
    proc = subprocess.run([sys.executable, os.path.join(HERE, "..", "scripts", "verify.py"), *args],
                          capture_output=True, text=True, input=stdin)
    return proc.returncode, json.loads(proc.stdout)


class Verify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        g = ["git", "-C", self.repo]
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        subprocess.run(g + ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "0"], check=True)
        open(os.path.join(self.repo, "settings.gradle.kts"), "w").close()
        os.makedirs(os.path.join(self.repo, "app/src/main/res/layout"))
        open(os.path.join(self.repo, "app/src/main/res/layout/a.xml"), "w").close()
        with open(os.path.join(self.repo, "logic.kt"), "w") as fh:
            fh.write("fun f() = 1\n")
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "1"], check=True)
        self.env = os.environ.get("AUTO_BMAD_CONFIG")
        os.environ["AUTO_BMAD_CONFIG"] = os.path.join(self.repo, "none.toml")
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.repo, "claude")

    def tearDown(self):
        if self.env is None:
            os.environ.pop("AUTO_BMAD_CONFIG", None)
        else:
            os.environ["AUTO_BMAD_CONFIG"] = self.env
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.tmp.cleanup()

    def plan(self, level="normal"):
        return run("plan", "--story", "1-1", "--base", "HEAD~1", "--commit", "HEAD", "--level", level,
                   "--repo", self.repo)

    def test_fast_has_no_checks(self):
        code, out = self.plan("fast")
        self.assertEqual(code, 2)

    def test_adbm_detected_but_skipped_without_skill(self):
        code, out = self.plan()
        self.assertEqual([s["name"] for s in out["skipped"]], ["adbm"])
        self.assertIn("plugin install adbm", out["skipped"][0]["install_hint"])

    def test_adbm_planned_when_skill_present(self):
        d = os.path.join(self.repo, "claude", "skills", "adbm")
        os.makedirs(d)
        open(os.path.join(d, "SKILL.md"), "w").close()
        code, out = self.plan()
        names = [v["name"] for v in out["verifiers"]]
        self.assertIn("adbm", names)
        adbm = next(v for v in out["verifiers"] if v["name"] == "adbm")
        self.assertTrue(adbm["instructions"].endswith("extensions/adbm/verify.md"))
        self.assertEqual(adbm["fields"], {"bug_before_after": True})

    def test_non_ui_diff_skips_adbm(self):
        with open(os.path.join(self.repo, "logic.kt"), "a") as fh:
            fh.write("fun g() = 2\n")
        g = ["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g + ["commit", "-qam", "2"], check=True)
        code, out = self.plan()
        self.assertNotIn("adbm", [v["name"] for v in out["verifiers"]] + [s["name"] for s in out["skipped"]])

    def test_attempt_counts_fixes_up_to_limit(self):
        results = [run("attempt", "--story", "1-1", "--level", "normal", "--repo", self.repo) for _ in range(3)]
        self.assertEqual([c for c, _ in results], [0, 0, 2])
        self.assertEqual(results[1][1]["fixes"], 2)

    def test_fix_spec_reopens_spec_outside_contract(self):
        spec = os.path.join(self.repo, "spec-1-1-x.md")
        with open(spec, "w") as fh:
            fh.write(SPEC)
        code, out = run("fix-spec", "--spec", spec, "--pass", "1", "--repo", self.repo,
                        stdin="1. The Save button is hidden — settings screen — assert failed\n")
        self.assertEqual(code, 0)
        text = open(spec).read()
        self.assertIn("status: 'in-progress'", text)
        contract = text[text.index("<intent-contract>"):text.index("</intent-contract>")]
        self.assertNotIn("Save", contract)
        tasks = text[text.index("## Tasks & Acceptance"):text.index("## Spec Change Log")]
        self.assertIn("The Save button is hidden", tasks)
        log = text[text.index("## Spec Change Log"):text.index("## Review Triage Log")]
        self.assertIn("attempt 1", log)
        code, _ = run("fix-spec", "--spec", spec, "--pass", "2", "--repo", self.repo, stdin="x\n")
        self.assertEqual(code, 2)                # already in-progress — not added a second time

    def test_run_skips_when_baseline_red(self):
        with open(os.path.join(self.repo, ".auto-bmad.toml"), "w") as fh:
            fh.write('[[verify]]\nname = "project-tests"\ncommand = "exit 1"\n')
        self.assertEqual(run("baseline", "--repo", self.repo)[1]["verdict"], "problem")
        code, out = run("run", "--name", "project-tests", "--repo", self.repo)
        self.assertEqual((out["verdict"], out["baseline"]), ("skipped", "problem"))


if __name__ == "__main__":
    unittest.main()
