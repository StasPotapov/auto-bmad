"""Broker test repair admission, evidence freshness and progress accounting."""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from repair_policy import limits
from story_broker import Broker


class TestRepairsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.b = Broker.__new__(Broker)
        b = self.b
        b.root = Path(self.tmp.name)
        b.private = b.root
        b.repair_limits = limits({})
        b.repair_counts = dict(spec=2, review=5, tests=0)
        b.test_failures = {}
        b.latest_tests = {}
        b.repaired_tests = set()
        b.pending_test_repair = None
        b.test_no_progress = 0
        b.blocked_reason = None
        b.session = {}
        b.passno = 1
        b.round = 0
        b.require_implementer = False
        b.save = Mock()
        b.tree = Mock(return_value="v1")

    def observe(self, verdict="problem", tail="FAILED tests/a.py::a", command="pytest", code=1):
        return self.b.observe_test(self.b.root, command, 30, None, self.b.tree(),
                                   dict(verdict=verdict, tail=tail, command=command, code=code))

    def test_test_attempt_does_not_need_remaining_spec_or_review_budget(self):
        failure = self.observe()
        self.b.begin_test_repair(failure["failure_id"])
        self.assertEqual(self.b.repair_counts, dict(spec=2, review=5, tests=1))
        with self.assertRaisesRegex(ValueError, "same failed check"):
            self.b.begin_test_repair(failure["failure_id"])
        self.observe(command="unrelated", verdict="pass", code=0)
        self.assertIsNotNone(self.b.pending_test_repair)
        self.observe(verdict="pass", code=0)
        self.assertIsNone(self.b.pending_test_repair)

    def test_cached_red_result_after_declared_attempt_is_no_progress(self):
        for expected in range(1, 4):
            failure = self.observe()
            self.b.begin_test_repair(failure["failure_id"])
            result = self.observe()
            self.assertEqual(self.b.test_no_progress, expected)
        self.assertIn("no progress", result["repair_blocked"])
        self.assertEqual(self.b.repair_counts["tests"], 3)

    def test_plain_repeated_checks_are_not_attempts(self):
        for _ in range(5):
            self.observe()
        self.assertEqual(self.b.test_no_progress, 0)
        self.assertEqual(self.b.repair_counts["tests"], 0)

    def test_stale_and_superseded_failures_cannot_authorize_repairs(self):
        failure = self.observe()
        self.b.tree.return_value = "v2"
        with self.assertRaisesRegex(ValueError, "stale"):
            self.b.begin_test_repair(failure["failure_id"])
        self.b.tree.return_value = "v1"
        self.observe(verdict="pass", code=0)
        with self.assertRaisesRegex(ValueError, "current host-issued"):
            self.b.begin_test_repair(failure["failure_id"])

    def test_environment_failure_refunds_attempt_and_invalidates_old_evidence(self):
        failure = self.observe()
        self.b.begin_test_repair(failure["failure_id"])
        result = self.observe(tail="Cannot connect to the Docker daemon")
        self.assertIn("environment unavailable", result["repair_blocked"])
        self.assertEqual(self.b.repair_counts, dict(spec=2, review=5, tests=0))
        self.assertIsNone(self.b.pending_test_repair)
        self.assertEqual(self.b.test_no_progress, 0)
        with self.assertRaisesRegex(ValueError, "current host-issued"):
            self.b.begin_test_repair(failure["failure_id"])

    def test_red_repaired_check_still_blocks_after_rerun(self):
        failure = self.observe()
        self.b.begin_test_repair(failure["failure_id"])
        self.observe()
        self.observe(verdict="pass", code=0, command="full-suite")
        self.assertIsNone(self.b.pending_test_repair)
        with self.assertRaisesRegex(ValueError, "repaired checks must pass"):
            self.b.check_repaired_tests()
        self.observe(verdict="pass", code=0)
        self.b.check_repaired_tests()
        self.b.tree.return_value = "changed-after-green"
        with self.assertRaisesRegex(ValueError, "current code"):
            self.b.check_repaired_tests()

    def test_repair_can_restore_exact_red_baseline_without_false_stall(self):
        b = self.b
        baseline = dict(verdict="problem", code=1, command="pytest", tail="old failure B")
        b.scoped_tests = SimpleNamespace(cfg={"baseline": True}, baselines={"backend": baseline},
                                        baseline_root=b.root / "baseline")
        b.test_scope_config = {}
        with patch("story_broker.project_tests.fingerprint", return_value="v1"):
            failed = b.observe_test(b.root, "pytest", 30, "backend", "v1",
                                    {**baseline, "tail": "new failure A and old failure B"})
            b.begin_test_repair(failed["failure_id"])
            b.test_no_progress = 2
            restored = b.observe_test(b.root, "pytest", 30, "backend", "v1", baseline)
            self.assertEqual(restored["verdict"], "skipped")
            self.assertTrue(restored["baseline_equivalent"])
            self.assertEqual(b.test_no_progress, 0)
            self.assertIsNone(b.blocked_reason)
            b.check_repaired_tests()
            b.latest_tests[("pytest", 30, "backend")]["result"] = {"verdict": "skipped"}
            with self.assertRaisesRegex(ValueError, "repaired checks must pass"):
                b.check_repaired_tests()
