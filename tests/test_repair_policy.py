"""Configuration validation and layer precedence for review repair budgets."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ext
from repair_policy import DEFAULT_LIMITS, limits, test_progress


class RepairPolicyTest(unittest.TestCase):
    def test_defaults_and_partial_override(self):
        self.assertEqual(limits({}), DEFAULT_LIMITS)
        self.assertEqual(limits({"repair_limits": {"tests": 8}}), {"spec": 2, "review": 5, "tests": 8, "no_progress": 3})

    def test_invalid_values_fail_instead_of_silently_reducing_budget(self):
        for value in (True, False, -1, 1.5, "5", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "nonnegative integer"):
                limits({"repair_limits": {"tests": value}})
        for value in (False, [], "none", {"norml": 5}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "table"):
                limits({"repair_limits": value})

    def test_all_four_layers_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = root / "defaults.toml"
            user = root / "user.toml"
            project = root / ext.PROJECT_CONFIG
            local = root / ext.LOCAL_CONFIG
            defaults.write_text("[repair_limits]\nspec=2\nreview=5\ntests=10\nno_progress=3\n")
            user.write_text("[repair_limits]\ntests=4\n")
            project.write_text("[repair_limits]\ntests=5\n")
            local.write_text("[repair_limits]\ntests=7\n")
            with patch.object(ext, "DEFAULTS", str(defaults)), patch.dict(os.environ, {"AUTO_BMAD_CONFIG": str(user)}):
                cfg, _, _ = ext.load(tmp, strict=True)
                self.assertEqual(limits(cfg), {"spec": 2, "review": 5, "tests": 7, "no_progress": 3})
                local.write_text("[repair_limits]\ntests=true\n")
                with self.assertRaisesRegex(ValueError, "repair_limits.tests"):
                    ext.load(tmp, strict=True)

    def test_progress_requires_a_pass_or_strictly_fewer_known_failures(self):
        before = {"verdict": "problem", "tail": "FAILED tests/a.py::test_a - wrong\nFAILED tests/b.py::test_b - wrong"}
        self.assertTrue(test_progress(before, {"verdict": "pass"}))
        self.assertTrue(test_progress(before, {"verdict": "problem", "tail": "FAILED tests/b.py::test_b - changed message"}))
        self.assertFalse(test_progress(before, {"verdict": "problem", "tail": "FAILED tests/a.py::test_a - new\nFAILED tests/b.py::test_b - new"}))
        self.assertFalse(test_progress(before, {"verdict": "problem", "tail": "FAILED tests/c.py::test_c"}))
        self.assertFalse(test_progress(before, {"verdict": "problem", "tail": "changed error text"}))
        with self.assertRaisesRegex(ValueError, "positive"):
            limits({"repair_limits": {"no_progress": 0}})
