import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cli_waves


class WaveTest(unittest.TestCase):
    def test_finishing_budget_covers_every_story_hook_and_one_wave_hook(self):
        cfg = {"hook": [{"events": ["story-done"], "timeout": 120},
                        {"events": ["verify-done"], "timeout": 20},
                        {"events": ["wave-merged"], "timeout": 45}]}
        self.assertGreaterEqual(cli_waves.finish_timeout(cfg, 3), 3 * (120 + 20) + 45)

    def test_preexisting_failure_ignores_summary_duration_but_keeps_failure_details(self):
        def signature(text, command="pytest"):
            return cli_waves.failure_signature({"command": command, "code": 1, "tail": text})
        self.assertEqual(signature("AssertionError: expected 42\n1 failed in 0.13s"),
                         signature("AssertionError: expected 42\n1 failed in 0.14s"))
        self.assertEqual(signature("Ran 2 tests in 0.13s\nFAILED (failures=1)"),
                         signature("Ran 2 tests in 0.14s\nFAILED (failures=1)"))
        self.assertNotEqual(signature("AssertionError: expected 42\n1 failed in 0.13s"),
                            signature("AssertionError: expected 43\n1 failed in 0.14s"))
        self.assertNotEqual(signature("1 failed in 0.13s"), signature("2 failed in 0.14s"))
        self.assertNotEqual(signature("1 failed in 0.13s"), signature("1 failed in 0.14s", command="other"))


if __name__ == "__main__":
    unittest.main()
