import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import project_tests as checks
import setup_tests
import testrun


STRATEGY = {"ignore": ["docs/**"], "scopes": {
    "ui": {"paths": ["ui/**"], "command": "true"},
    "service": {"paths": ["service/**"], "command": "false"}}}


class StrategyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        for path in ("ui/app.js", "service/app.py", "scripts/check.sh"):
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("initial\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True)

    def test_selection_uses_components_and_defaults_shared_files_to_all(self):
        self.assertEqual(checks.select(STRATEGY, ["ui/new/deep.js", "docs/design.md"]), ["ui"])
        self.assertEqual(checks.select(STRATEGY, ["service/app.py"]), ["service"])
        self.assertEqual(checks.select(STRATEGY, ["ui/app.js", "service/app.py"]), ["ui", "service"])
        self.assertEqual(checks.select(STRATEGY, ["scripts/check.sh"]), ["ui", "service"])
        self.assertEqual(checks.select(STRATEGY, ["docs/design.md", "_bmad-output/spec.md"]), [])
        self.assertEqual(checks.select({**STRATEGY, "fallback": {"command": "whole project"}}, ["scripts/check.sh", "ui/app.js"]), ["@all"])

    def test_component_cache_keeps_unrelated_changes_but_invalidates_shared_changes(self):
        before = checks.fingerprint(self.root, STRATEGY, "ui")
        (self.root / "service/app.py").write_text("backend changed\n")
        self.assertEqual(checks.fingerprint(self.root, STRATEGY, "ui"), before)
        (self.root / "scripts/check.sh").write_text("shared changed\n")
        self.assertNotEqual(checks.fingerprint(self.root, STRATEGY, "ui"), before)

    def test_full_boundaries_override_ignored_docs_and_component_ownership(self):
        cfg = {**STRATEGY, "fallback": {"command": "all"}, "full_on_multiple": True,
               "full_paths": ["ui/config.*", "docs/DESIGN.md", "_bmad-output/**/imports/brand/**"]}
        self.assertEqual(checks.select(cfg, ["ui/config.js"]), ["@all"])
        self.assertEqual(checks.select(cfg, ["docs/DESIGN.md"]), ["@all"])
        self.assertEqual(checks.select(cfg, ["ui/app.js", "service/app.py"]), ["@all"])
        brand = self.root / "_bmad-output/ux/imports/brand/logo.svg"
        brand.parent.mkdir(parents=True)
        brand.write_text("original")
        self.assertEqual(checks.select(cfg, [str(brand.relative_to(self.root))]), ["@all"])
        original = checks.fingerprint(self.root, cfg, "ui")
        brand.write_text("changed")
        self.assertNotEqual(original, checks.fingerprint(self.root, cfg, "ui"))
        doc = self.root / "docs/DESIGN.md"
        doc.parent.mkdir()
        doc.write_text("first")
        before = checks.fingerprint(self.root, cfg, "service")
        doc.write_text("second")
        self.assertNotEqual(before, checks.fingerprint(self.root, cfg, "service"))

    def test_semantic_changes_escalate_new_modified_and_removed_api_calls(self):
        cfg = {**STRATEGY, "fallback": {"command": "all"}, "full_patterns": [r"fetch\("]}
        (self.root / "ui/app.js").write_text("fetch('/api/x')\n")
        self.assertEqual(checks.selection(self.root, self.base, cfg), ["@all"])
        before = checks.fingerprint(self.root, cfg, "service")
        (self.root / "ui/app.js").write_text("fetch('/api/y')\n")
        self.assertNotEqual(before, checks.fingerprint(self.root, cfg, "service"))
        self.git("add", ".")
        self.git("commit", "-qm", "api")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        (self.root / "ui/app.js").write_text("removed\n")
        self.assertEqual(checks.selection(self.root, base, cfg), ["@all"])
        (self.root / "ui/app.js").write_text("fetch('/api/y')\n")
        (self.root / "ui/new.js").write_text("fetch('/api/new')\n")
        self.assertEqual(checks.selection(self.root, base, cfg), ["@all"])

    def test_explicit_full_gate_does_not_narrow_to_component(self):
        cfg = {**STRATEGY, "baseline": False, "fallback": {"command": "all"}}
        (self.root / "ui/app.js").write_text("isolated")
        calls = []
        runner = checks.Runner(self.root, self.base, {"project_tests": cfg}, self.root / ".git/private",
            lambda command, timeout, root, scope: calls.append(scope) or {"verdict": "pass", "code": 0})
        self.assertEqual(runner.run(force_full=True)["scopes"], ["@all"])
        self.assertEqual(calls, ["@all"])

    def test_native_component_result_is_reused_after_other_component_changes(self):
        result, code = testrun.run(str(self.root), "true", component="ui", scope_config=STRATEGY)
        self.assertEqual((code, result["verdict"]), (0, "pass"))
        (self.root / "service/app.py").write_text("changed service\n")
        result, code = testrun.run(str(self.root), "true", component="ui", scope_config=STRATEGY)
        self.assertTrue(result["reused"])

    def test_disabled_scopes_are_not_active(self):
        self.assertFalse(checks.enabled({"project_tests": STRATEGY, "verify": []}))
        self.assertFalse(checks.enabled({"project_tests": STRATEGY, "verify": [
            {"name": "project-tests", "kind": "command", "enabled": False}]}))

    def configure_native(self, command, baseline=True):
        import native_tests
        strategy = {"baseline": baseline, "scopes": {"ui": {"paths": ["ui/**"], "command": command}}}
        plan = self.root / ".git/test-plan.json"
        plan.write_text(json.dumps(strategy))
        setup_tests.configure(SimpleNamespace(plan=str(plan), layer="project", write=True), self.root)
        self.git("add", ".auto-bmad.toml")
        self.git("commit", "-qm", "test strategy")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        (self.root / "ui/app.js").write_text("changed ui\n")
        return native_tests, base, {"project_tests": strategy}

    def test_native_scopes_return_running_then_join_the_whole_plan(self):
        native, base, cfg = self.configure_native("sleep 1; true")
        result, code = native.run(self.root, base, cfg, wait=0)
        self.assertEqual((code, result["verdict"]), (3, "running"))
        result, code = native.run(self.root, base, cfg, wait=15)
        self.assertEqual((code, result["verdict"]), (0, "pass"))
        self.assertEqual(result["scopes"], ["ui"])

    def test_native_worker_keeps_joining_a_leaf_queued_for_resources(self):
        native, base, cfg = self.configure_native("true", baseline=False)
        request = self.root / ".git/native-test-request.json"
        request.write_text(json.dumps({"id": "fixture", "repo": str(self.root), "base": base,
                                       "config": cfg, "rerun": False, "timeout": 1}))
        with patch.object(native.testrun, "run", side_effect=[
                ({"verdict": "running"}, 3),
                ({"verdict": "pass", "code": 0, "tail": ""}, 0)]) as run:
            native.worker(request)
        self.assertEqual(run.call_count, 2)
        saved = json.loads((request.parent / "native-result.json").read_text())
        self.assertEqual(saved["result"]["verdict"], "pass")

    def test_matching_timeouts_are_not_preexisting_failures_or_cached_results(self):
        native, base, cfg = self.configure_native("sleep 3")
        for _ in range(2):
            result, code = native.run(self.root, base, cfg, wait=15, timeout=1)
            self.assertEqual((code, result["verdict"]), (0, "problem"), result)
            self.assertIsNone(result["checks"]["ui"]["code"])
            self.assertFalse(result["reused"])
        private = next((self.root / ".git/auto-bmad-test-baselines").iterdir())
        self.assertEqual(json.loads((private / "baselines.json").read_text())["results"], {})
        self.assertIsNone(json.loads((private / "native-result.json").read_text())["tree"])

    def test_native_rerun_refreshes_the_persisted_baseline(self):
        # An environment repair makes the baseline green while the story still fails.
        import shlex
        marker = self.root / ".git/environment-ready"
        command = "test -f " + shlex.quote(str(marker)) + " && test " + shlex.quote("$(cat ui/app.js)") + " = initial"
        # Keep shell substitution intentional inside the command, not shell-quoted as literal.
        command = command.replace(shlex.quote("$(cat ui/app.js)"), '"$(cat ui/app.js)"')
        native, base, cfg = self.configure_native(command)
        first, code = native.run(self.root, base, cfg, wait=15)
        self.assertEqual((code, first["verdict"]), (0, "skipped"))
        marker.touch()
        for directory in (self.root / ".git/auto-bmad-test-baselines").iterdir():
            receipt = directory / "native-result.json"
            old = time.time() - testrun.RECENT - 10
            os.utime(receipt, (old, old))
            # Existing leaf receipts also predate this environment repair.
            for where in (self.root, directory / "baseline-code"):
                for kept in (where / ".auto-bmad/tests").glob("*.json"):
                    os.utime(kept, (old, old))
        result, code = native.run(self.root, base, cfg, wait=15, rerun=True)
        self.assertEqual((code, result["verdict"]), (0, "problem"), result)
        self.assertEqual(result["checks"]["ui"]["verdict"], "problem")

    def test_verify_run_requires_base_and_uses_the_affected_component(self):
        plan = self.root / ".git/test-plan.json"
        plan.write_text(json.dumps({**STRATEGY, "baseline": False}))
        setup_tests.configure(SimpleNamespace(plan=str(plan), layer="project", write=True), self.root)
        self.git("add", ".auto-bmad.toml")
        self.git("commit", "-qm", "test strategy")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        (self.root / "ui/app.js").write_text("changed ui\n")
        args = [sys.executable, str(Path(checks.__file__).with_name("verify.py")),
                "run", "--name", "project-tests", "--repo", str(self.root)]
        missing = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("--base", json.loads(missing.stdout)["error"])
        result = subprocess.run(args + ["--base", base], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(json.loads(result.stdout)["scopes"], ["ui"])
        self.assertEqual(json.loads(result.stdout)["verdict"], "pass")

    def test_diff_includes_committed_uncommitted_untracked_and_rename_source(self):
        self.git("mv", "ui/app.js", "service/moved.js")
        self.git("commit", "-qm", "move")
        (self.root / "ui/new.js").write_text("new\n")
        changed = checks.files(self.root, self.base)
        self.assertIn("ui/app.js", changed)
        self.assertIn("service/moved.js", changed)
        self.assertIn("ui/new.js", changed)
        self.assertEqual(checks.select(STRATEGY, changed), ["ui", "service"])

    def test_baseline_runs_only_the_affected_component_at_its_exact_base(self):
        (self.root / "ui/app.js").write_text("changed\n")
        calls = []
        def execute(command, timeout, where, scope):
            calls.append((scope, where, (where / "ui/app.js").read_text()))
            return {"verdict": "pass", "code": 0, "tail": "", "reused": False}
        runner = checks.Runner(self.root, self.base, {"project_tests": STRATEGY}, self.root / ".git/test-baseline", execute)
        result = runner.run()
        self.assertEqual(result["scopes"], ["ui"])
        self.assertEqual([v[0] for v in calls], ["ui", "ui"])
        self.assertEqual([v[2] for v in calls], ["initial\n", "changed\n"])

    def test_setup_inspects_mobile_and_web_without_running_or_writing(self):
        (self.root / "ui/package.json").write_text(json.dumps({"scripts": {"test": "test runner", "build": "build runner"}}))
        mobile = self.root / "mobile"
        mobile.mkdir()
        (mobile / "build.gradle.kts").write_text('plugins { id("com.android.application") }')
        result = setup_tests.inspect(self.root)
        self.assertEqual({c["path"] for c in result["components"]}, {"ui", "mobile"})
        self.assertTrue(all(c["requires_confirmation"] for c in result["components"]))
        self.assertFalse((self.root / ".auto-bmad.toml").exists())

    def test_setup_records_real_development_and_build_mapping_and_reports_legacy_gaps(self):
        legacy = setup_tests.native_readiness(STRATEGY)
        self.assertFalse(legacy['automatic_full_fallback'])
        self.assertFalse(legacy['full_baseline_required'])
        self.assertEqual(len(legacy['gaps']), 2)
        chosen = {**STRATEGY,
            'development': {'unit': {'command': 'scripts/test-one', 'targets': ['tests/test_*.py']}},
            'build': {'compile': {'command': 'scripts/compile', 'timeout': 60}}}
        plan = self.root / '.git/registered-checks.json'
        plan.write_text(json.dumps(chosen))
        result, code = setup_tests.configure(SimpleNamespace(plan=str(plan), layer='project', write=True), self.root)
        self.assertEqual(code, 0)
        self.assertEqual(result['strategy'], chosen)
        self.assertEqual(result['native_verification']['gaps'], [])
        inspected = setup_tests.inspect(self.root)['native_verification']
        self.assertEqual(inspected['development'], ['unit'])
        self.assertEqual(inspected['build'], ['compile'])

    def test_setup_preview_then_write_preserves_other_sections_and_creates_backup(self):
        target = self.root / ".auto-bmad.toml"
        before = '[run]\nlevel="deep"\n[[hook]]\nname="keep"\nevents=["run-start"]\ncommand="true"\n'
        target.write_text(before)
        plan = self.root / ".git/test-plan.json"
        plan.write_text(json.dumps(STRATEGY))
        args = SimpleNamespace(plan=str(plan), layer="project", write=False)
        result, code = setup_tests.configure(args, self.root)
        self.assertEqual(code, 0)
        self.assertFalse(result["written"])
        self.assertEqual(target.read_text(), before)
        args.write = True
        result, code = setup_tests.configure(args, self.root)
        self.assertEqual(code, 0)
        self.assertEqual(Path(result["backup"]).read_text(), before)
        self.assertIn('name="keep"', target.read_text())


if __name__ == "__main__":
    unittest.main()
