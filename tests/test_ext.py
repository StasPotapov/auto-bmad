import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import ext  # noqa: E402

HOOK = """import json, sys
p = json.load(sys.stdin)
out = {"ok": True, "message": p["event"] + ":" + str(p.get("story"))}
if p["event"] == "run-start":
    out["ask"] = {"question": "connect?", "options": [{"id": "yes", "label": "Yes"}]}
if p["event"] == "answer":
    open("answered.txt", "w").write(p["data"]["answer"])
    out["files"] = ["answered.txt"]
print(json.dumps(out))
"""


class Merge(unittest.TestCase):
    def test_executor_context_is_temporary_and_preserves_settings(self):
        cfg = {"execution": {"backend": "legacy-plugin", "merge_policy": "manual"},
               "agents": {"writer": {"model": "test-model"}}}
        with patch.dict(os.environ, {ext.EXECUTOR_ENV: "codex"}):
            selected = ext.executor_config(cfg)
            self.assertEqual(selected["execution"]["backend"], "cli")
            self.assertEqual(selected["execution"]["merge_policy"], "manual")
            self.assertEqual(ext.executor_environment({}), {ext.EXECUTOR_ENV: "codex"})
        self.assertEqual(cfg["execution"]["backend"], "legacy-plugin")
        self.assertEqual(ext.executor_config(selected, "claude"), cfg)
        with self.assertRaises(ValueError):
            ext.executor_config(cfg, "unknown")
        with self.assertRaises(ValueError):
            ext.executor_config({"execution": {"backend": "broken"}}, "codex")

    def test_named_arrays_merge_by_name(self):
        base = {"hook": [{"name": "a", "command": "x", "events": ["run-start"]}],
                "run": {"k": 1, "n": {"x": 1}}}
        extra = {"hook": [{"name": "a", "timeout": 5}, {"name": "b", "command": "y"}],
                 "run": {"n": {"y": 2}}}
        out = ext.merge(base, extra)
        self.assertEqual(out["hook"][0], {"name": "a", "command": "x", "events": ["run-start"], "timeout": 5})
        self.assertEqual(out["hook"][1]["name"], "b")
        self.assertEqual(out["run"], {"k": 1, "n": {"x": 1, "y": 2}})


class Fire(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        hook = os.path.join(self.tmp.name, "hook.py")
        with open(hook, "w") as fh:
            fh.write(HOOK)
        self.user = os.path.join(self.tmp.name, "user.toml")
        with open(self.user, "w") as fh:
            fh.write(f'[[hook]]\nname = "h"\nevents = ["run-start", "story-done"]\n'
                     f'command = "python3 {hook}"\n'
                     '[[hook]]\nname = "broken"\nevents = ["story-done"]\ncommand = "echo not-json"\n')
        self.env = {k: os.environ.get(k) for k in ("AUTO_BMAD_CONFIG", "AUTO_BMAD_DEADLINE",
                                                    "AUTO_BMAD_UNATTENDED", "AUTO_BMAD_EVENTS_FILE")}
        os.environ["AUTO_BMAD_CONFIG"] = self.user
        for k in ("AUTO_BMAD_DEADLINE", "AUTO_BMAD_UNATTENDED", "AUTO_BMAD_EVENTS_FILE"):
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def payload(self, event, **kw):
        p = {"event": event, "repo": self.repo, "unattended": ext.unattended(), "data": {}}
        p.update(kw)
        return p

    def test_hook_runs_only_on_its_events(self):
        out = ext.fire(self.repo, self.payload("story-start", story="1-1"))
        self.assertEqual(out["results"], [])

    def test_bad_json_is_an_error_not_a_stop(self):
        out = ext.fire(self.repo, self.payload("story-done", story="1-1"))
        by = {r["name"]: r for r in out["results"]}
        self.assertTrue(by["h"]["ok"])
        self.assertEqual(by["h"]["message"], "story-done:1-1")
        self.assertFalse(by["broken"]["ok"])
        self.assertIn("not JSON", by["broken"]["error"])

    def test_ask_is_dropped_without_human(self):
        self.assertEqual(len(ext.fire(self.repo, self.payload("run-start"))["asks"]), 1)
        os.environ["AUTO_BMAD_UNATTENDED"] = "1"
        self.assertEqual(ext.fire(self.repo, self.payload("run-start", unattended=True))["asks"], [])

    def test_answer_goes_to_one_hook_and_returns_files(self):
        p = self.payload("answer", data={"answer": "yes"})
        out = ext.fire(self.repo, p, only="h")
        self.assertEqual([r["name"] for r in out["results"]], ["h"])
        self.assertEqual(out["files"], ["answered.txt"])
        with open(os.path.join(self.repo, "answered.txt")) as fh:
            self.assertEqual(fh.read(), "yes")

    def test_project_layer_disables_hook(self):
        with open(os.path.join(self.repo, ".auto-bmad.toml"), "w") as fh:
            fh.write('[[hook]]\nname = "broken"\nenabled = false\n')
        out = ext.fire(self.repo, self.payload("story-done", story="1-1"))
        self.assertEqual([r["name"] for r in out["results"]], ["h"])

    def test_events_log_is_local_and_excluded(self):
        ext.fire(self.repo, self.payload("story-done", story="2-3", commit="abc", title="secret text"))
        with open(os.path.join(self.repo, ".auto-bmad", "events.jsonl")) as fh:
            row = json.loads(fh.readline())
        self.assertEqual((row["event"], row["story"], row["commit"]), ("story-done", "2-3", "abc"))
        self.assertNotIn("title", row)
        with open(os.path.join(self.repo, ".git", "info", "exclude")) as fh:
            self.assertIn(".auto-bmad/", fh.read().split())
        status = subprocess.run(["git", "-C", self.repo, "status", "--porcelain"],
                                capture_output=True, text=True).stdout
        self.assertNotIn(".auto-bmad", status)

    def test_broken_layer_is_skipped_with_warning(self):
        with open(os.path.join(self.repo, ".auto-bmad.toml"), "w") as fh:
            fh.write("[[hook]\n")
        cfg, sources, warnings = ext.load(self.repo)
        self.assertEqual(len(cfg["hook"]), 2)
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
