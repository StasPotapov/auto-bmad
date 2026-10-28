"""Tests for evidence.py: code excerpts for a list of review findings in one call.
python3 -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        git(self.repo, "init", "-q")
        self.write("a.py", "".join(f"line {n}\n" for n in range(1, 41)))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        text = "".join(f"line {n}\n" for n in range(1, 41)).replace("line 30\n", "changed 30\n")
        self.write("a.py", text)
        self.write("new.py", "def parse_date(x):\n    return x\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        with open(os.path.join(self.repo, name), "w") as fh:
            fh.write(text)

    def run_it(self, data, *extra):
        os.makedirs(os.path.join(self.repo, ".auto-bmad", "evidence"), exist_ok=True)
        path = os.path.join(self.repo, ".auto-bmad", "evidence", "spec.json")
        with open(path, "w") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))
        proc = subprocess.run([sys.executable, os.path.join(HERE, "..", "scripts", "evidence.py"),
                               "--input", path, "--repo", self.repo, *extra],
                              capture_output=True, text=True)
        return proc.returncode, json.loads(proc.stdout)

    def test_lines_with_context_and_merged_ranges(self):
        code, out = self.run_it({"findings": [{"id": "1", "file": "a.py", "lines": "10,12-13"}]})
        self.assertEqual(code, 0, out)
        got = out["findings"][0]["code"].split("\n")
        self.assertEqual(got[0], "7: line 7")
        self.assertEqual(got[-1], "16: line 16")
        self.assertEqual(len(got), 10)                       # 7..16, one block, no gap mark

    def test_separate_blocks_and_file_end(self):
        code, out = self.run_it({"findings": [{"id": "1", "file": "a.py", "lines": [2, "39"]}]},
                                "--context", "1")
        got = out["findings"][0]["code"].split("\n")
        self.assertEqual(got, ["1: line 1", "2: line 2", "3: line 3", "…",
                               "38: line 38", "39: line 39", "40: line 40"])

    def test_diff_hunks_touching_the_lines(self):
        data = {"base": self.base, "findings": [{"id": "1", "file": "a.py", "lines": "30", "diff": True},
                                                 {"id": "2", "file": "a.py", "lines": "5", "diff": True}]}
        code, out = self.run_it(data)
        first, second = out["findings"]
        self.assertIn("-line 30", first["diff"])
        self.assertIn("+changed 30", first["diff"])
        self.assertTrue(first["diff"].startswith("@@ "))
        self.assertEqual(second["diff"], "(the diff of this file does not touch these lines)")

    def test_diff_of_an_untracked_file_and_missing_base(self):
        code, out = self.run_it({"base": self.base, "findings": [{"id": "1", "file": "new.py", "diff": True}]})
        self.assertIn("not tracked", out["findings"][0]["diff"])
        code, out = self.run_it({"findings": [{"id": "1", "file": "a.py", "diff": True}]})
        self.assertIn("base revision", out["findings"][0]["error"])
        code, out = self.run_it({"findings": [{"id": "1", "file": "a.py", "diff": True}]}, "--base", self.base)
        self.assertIn("+changed 30", out["findings"][0]["diff"])

    def test_grep_in_the_repository_sees_untracked_files(self):
        code, out = self.run_it({"findings": [{"id": "1", "file": "a.py", "grep": r"parse_date\(",
                                               "grep_in": "."}]})
        grep = out["findings"][0]["grep"]
        self.assertEqual(grep["count"], 1)
        self.assertEqual(grep["hits"], ["new.py:1:def parse_date(x):"])
        self.assertNotIn("code", out["findings"][0])

    def test_grep_defaults_to_the_finding_file(self):
        code, out = self.run_it({"findings": [{"id": "1", "file": "a.py", "grep": "parse_date"}]})
        self.assertEqual(out["findings"][0]["grep"]["count"], 0)

    def test_errors_stay_per_finding(self):
        code, out = self.run_it({"findings": [
            {"id": "1", "file": "missing.py", "lines": "3"},
            {"id": "2", "file": "../outside.py", "lines": "1"},
            {"id": "3", "file": "a.py"},
            {"id": "4", "file": "a.py", "lines": "x-y"},
            {"id": "5", "file": "a.py", "lines": "1"}]})
        self.assertEqual(code, 0)
        errors = [f.get("error") for f in out["findings"]]
        self.assertIn("no such file", errors[0])
        self.assertIn("outside the repository", errors[1])
        self.assertIn("give lines, grep or diff", errors[2])
        self.assertIn("cannot parse lines", errors[3])
        self.assertIsNone(errors[4])

    def test_long_excerpt_is_cut(self):
        self.write("big.py", "".join(f"x{n}\n" for n in range(1, 400)))
        code, out = self.run_it({"findings": [{"id": "1", "file": "big.py", "lines": "1-300"}]})
        self.assertIn("…(cut: ", out["findings"][0]["code"])

    def test_bad_input_is_a_call_error(self):
        code, out = self.run_it("not json")
        self.assertEqual(code, 1)
        self.assertTrue(out["error"])
        code, out = self.run_it({"findings": "x"})
        self.assertEqual(code, 1)

    def test_input_folder_is_excluded_from_git(self):
        self.run_it({"findings": []})
        self.assertNotIn(".auto-bmad", git(self.repo, "status", "--porcelain"))


if __name__ == "__main__":
    unittest.main()
