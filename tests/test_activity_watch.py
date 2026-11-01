import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from activity_watch import InactivityWatch


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.watch = InactivityWatch(10, clock=lambda: self.now)

    def test_stall_requires_warning_and_a_further_unchanged_interval(self):
        self.now = 9
        self.watch.observe()
        self.assertEqual(self.watch.evidence["state"], "active")
        for self.now in (10, 19):
            self.assertFalse(self.watch.observe())
            self.assertEqual(self.watch.evidence["state"], "suspected_stall")
            self.assertEqual(self.watch.evidence["action"], "keep_running")
        self.now = 20
        self.assertTrue(self.watch.observe())
        self.assertEqual(self.watch.evidence["state"], "stalled")
        self.assertEqual(self.watch.evidence["action"], "stop")

    def test_progress_clears_the_suspicion(self):
        self.now = 10
        self.watch.observe()
        self.watch.progress()
        self.now = 15
        self.watch.observe()
        self.assertEqual(self.watch.evidence["state"], "active")
        self.now = 20
        self.assertFalse(self.watch.observe())
        self.assertEqual(self.watch.evidence["state"], "suspected_stall")
        self.now = 30
        self.assertTrue(self.watch.observe())

    def test_supervised_child_work_is_not_idle(self):
        self.now = 100
        self.watch.observe(paused=True)
        self.assertEqual(self.watch.evidence["state"], "waiting_for_supervised_work")
        self.now = 105
        self.watch.observe()
        self.assertEqual(self.watch.evidence["state"], "active")
        self.now = 110
        self.watch.observe()
        self.assertEqual(self.watch.evidence["state"], "suspected_stall")

    def test_warning_is_not_skipped_when_monitoring_resumes_late(self):
        self.now = 10000
        self.assertFalse(self.watch.observe())
        self.now += 10
        self.assertTrue(self.watch.observe())

    def test_confirmation_is_capped_at_two_minutes(self):
        watch = InactivityWatch(3600, clock=lambda: self.now)
        self.now = 3600
        self.assertFalse(watch.observe())
        self.now = 3719
        self.assertFalse(watch.observe())
        self.now = 3720
        self.assertTrue(watch.observe())
