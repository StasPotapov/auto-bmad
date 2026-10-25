#!/usr/bin/env python3
"""Tests for window.py — does one more story fit into the work window.

The script runs as a subprocess: the contract matters here — JSON in stdout,
the reason in stderr, exit code 0/2. No network, no model.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "window.py")
NOW = 1_800_000_000          # fixed "now", so the tests do not depend on the clock


def run(args=(), env=None):
    """(exit code, JSON, stderr) of one script call."""
    e = dict(os.environ)
    # Variables of a real window must not leak into the test.
    e.pop("AUTO_BMAD_DEADLINE", None)
    e.pop("AUTO_BMAD_RESERVE_MINUTES", None)
    e.pop("AUTO_BMAD_LIMITS_FILE", None)
    e.pop("AUTO_BMAD_STOP_AT_FIVE_HOUR_PCT", None)
    e.pop("AUTO_BMAD_STOP_AT_SEVEN_DAY_PCT", None)
    e.pop("AUTO_BMAD_STOP_FILE", None)
    e.pop("AUTO_BMAD_LIVE_FILE", None)
    e.update(env or {})
    p = subprocess.run([sys.executable, SCRIPT, "--now", str(NOW), *args],
                       capture_output=True, text=True, env=e, timeout=30)
    return p.returncode, json.loads(p.stdout), p.stderr


def at(minutes):
    """Deadline this many minutes after the fixed "now", as a string."""
    return str(NOW + minutes * 60)


class Window(unittest.TestCase):

    def test_no_window_means_no_time_limit(self):
        """A manual run from a terminal: no variable, and time decides nothing."""
        code, out, _ = run()
        self.assertEqual(code, 0)
        self.assertTrue(out["take_next"])
        self.assertFalse(out["window"])
        self.assertIsNone(out["deadline"])

    def test_plenty_of_time_takes_next(self):
        code, out, _ = run(env={"AUTO_BMAD_DEADLINE": at(180),
                                "AUTO_BMAD_RESERVE_MINUTES": "60"})
        self.assertEqual(code, 0)
        self.assertTrue(out["take_next"])
        self.assertEqual(out["left_minutes"], 180)

    def test_less_than_reserve_does_not_take(self):
        code, out, err = run(env={"AUTO_BMAD_DEADLINE": at(30),
                                  "AUTO_BMAD_RESERVE_MINUTES": "60"})
        self.assertEqual(code, 2)
        self.assertFalse(out["take_next"])
        self.assertIn("not taking the next", out["reason"])
        self.assertIn("not taking the next", err, "the reason must be repeated in stderr")

    def test_exactly_the_reserve_still_takes(self):
        """Exactly the reserve still fits: otherwise the reserve would be a minute stricter than set."""
        code, out, _ = run(env={"AUTO_BMAD_DEADLINE": at(60),
                                "AUTO_BMAD_RESERVE_MINUTES": "60"})
        self.assertEqual(code, 0)
        self.assertTrue(out["take_next"])

    def test_window_already_closed(self):
        code, out, _ = run(env={"AUTO_BMAD_DEADLINE": at(-40),
                                "AUTO_BMAD_RESERVE_MINUTES": "60"})
        self.assertEqual(code, 2)
        self.assertFalse(out["take_next"])
        self.assertIn("closed", out["reason"])

    def test_wave_needs_more_reserve_than_story(self):
        """A wave ends with worktree merges — it must not be cut off midway."""
        env = {"AUTO_BMAD_DEADLINE": at(70), "AUTO_BMAD_RESERVE_MINUTES": "60"}
        story_code, story, _ = run(env=env)
        wave_code, wave, _ = run(["--stage", "next-wave"], env=env)
        self.assertEqual(story_code, 0, "70 minutes are enough for a story")
        self.assertEqual(wave_code, 2, "not for a wave")
        self.assertGreater(wave["needed_minutes"], story["needed_minutes"])

    def test_garbage_in_variable_does_not_break_run(self):
        """A broken deadline means no window: failing an epic over garbage is worse."""
        code, out, err = run(env={"AUTO_BMAD_DEADLINE": "tomorrow morning"})
        self.assertEqual(code, 0)
        self.assertTrue(out["take_next"])
        self.assertTrue(out["warnings"])
        self.assertIn("not a number", err)

    def test_reserve_without_value_uses_default(self):
        code, out, _ = run(env={"AUTO_BMAD_DEADLINE": at(300)})
        self.assertEqual(code, 0)
        self.assertEqual(out["reserve_minutes"], 60)

    def test_argument_beats_variable(self):
        """This is how the script is checked by hand without touching the session environment."""
        code, out, _ = run(["--deadline", at(300)],
                           env={"AUTO_BMAD_DEADLINE": at(5)})
        self.assertEqual(code, 0)
        self.assertEqual(out["left_minutes"], 300)

    def test_json_printed_on_any_outcome(self):
        for env in ({}, {"AUTO_BMAD_DEADLINE": at(5)}, {"AUTO_BMAD_DEADLINE": "garbage"}):
            with self.subTest(env=env):
                _, out, _ = run(env=env)
                self.assertIn("take_next", out)
                self.assertIn("reason", out)


class SubscriptionThreshold(unittest.TestCase):
    """The subscription limit stops the run where time does: between stories.

    Without this, the threshold was checked only between runs, and one wave took
    the five-hour window from 7% to 99% and stopped to wait for the reset.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "limits.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def snap(self, five=None, seven=None, updated=None, raw=None):
        """Write a windows snapshot and return its path."""
        if raw is not None:
            with open(self.path, "w") as fh:
                fh.write(raw)
            return self.path
        d = {"updated_at": NOW if updated is None else updated}
        if five is not None:
            util, resets = five
            d["five_hour"] = {"utilization": util, "resets_at": resets}
        if seven is not None:
            util, resets = seven
            d["seven_day"] = {"utilization": util, "resets_at": resets}
        with open(self.path, "w") as fh:
            json.dump(d, fh)
        return self.path

    def ask(self, *extra, **kw):
        args = ["--deadline", at(kw.pop("left", 300)),
                "--reserve-min", "60", "--limits-file", self.path, *extra]
        return run(args, kw.pop("env", None))

    def test_above_threshold_does_not_take(self):
        self.snap(five=(0.72, NOW + 7200))
        code, out, err = self.ask("--stop-at-five-hour-pct", "70")
        self.assertEqual(code, 2)
        self.assertFalse(out["take_next"])
        self.assertIn("72%", out["reason"])
        self.assertIn("five-hour", out["reason"])
        self.assertIn("72%", err)

    def test_exactly_at_threshold_is_enough(self):
        self.snap(five=(0.70, NOW + 7200))
        self.assertEqual(self.ask("--stop-at-five-hour-pct", "70")[0], 2)

    def test_below_threshold_takes(self):
        self.snap(five=(0.69, NOW + 7200))
        self.assertEqual(self.ask("--stop-at-five-hour-pct", "70")[0], 0)

    def test_zero_threshold_means_no_limit(self):
        self.snap(five=(0.99, NOW + 7200))
        self.assertEqual(self.ask("--stop-at-five-hour-pct", "0")[0], 0)

    def test_no_threshold_means_no_limit(self):
        self.snap(five=(0.99, NOW + 7200))
        self.assertEqual(self.ask()[0], 0)

    def test_seven_day_window_also_stops(self):
        self.snap(seven=(0.85, NOW + 200000))
        code, out, _ = self.ask("--stop-at-seven-day-pct", "80")
        self.assertEqual(code, 2)
        self.assertIn("seven-day", out["reason"])

    def test_reset_in_the_past_means_window_is_free(self):
        self.snap(five=(0.99, NOW - 60))
        self.assertEqual(self.ask("--stop-at-five-hour-pct", "70")[0], 0)

    def test_snapshot_from_past_run_is_ignored(self):
        self.snap(five=(0.99, NOW + 7200), updated=NOW - 20000)
        code, _, err = self.ask("--stop-at-five-hour-pct", "70")
        self.assertEqual(code, 0)
        self.assertIn("past run", err)

    def test_broken_snapshot_does_not_break_run(self):
        self.snap(raw="{ garbage")
        code, out, err = self.ask("--stop-at-five-hour-pct", "70")
        self.assertEqual(code, 0)
        self.assertTrue(out["warnings"])
        self.assertIn("unreadable", err)

    def test_no_snapshot_at_all(self):
        code, out, _ = run(["--deadline", at(300), "--limits-file",
                            os.path.join(self.tmp, "missing.json"),
                            "--stop-at-five-hour-pct", "70"])
        self.assertEqual(code, 0)
        self.assertEqual(out["limits"], {})

    def test_time_beats_limit(self):
        # Both reasons apply — the report gets the more precise one: time.
        self.snap(five=(0.99, NOW + 7200))
        code, out, _ = self.ask("--stop-at-five-hour-pct", "70", left=10)
        self.assertEqual(code, 2)
        self.assertIn("until the window end", out["reason"])

    def test_numbers_visible_even_when_taking(self):
        self.snap(five=(0.20, NOW + 7200))
        _, out, _ = self.ask("--stop-at-five-hour-pct", "70")
        self.assertEqual(out["limits"]["five_hour"]["used_pct"], 20)
        self.assertEqual(out["limits"]["five_hour"]["threshold_pct"], 70)

    def test_environment_instead_of_arguments(self):
        self.snap(five=(0.72, NOW + 7200))
        code, _, _ = run(["--deadline", at(300)],
                         {"AUTO_BMAD_LIMITS_FILE": self.path,
                          "AUTO_BMAD_STOP_AT_FIVE_HOUR_PCT": "70"})
        self.assertEqual(code, 2)

    def test_wave_also_hits_threshold(self):
        self.snap(five=(0.72, NOW + 7200))
        _, out, _ = self.ask("--stop-at-five-hour-pct", "70", "--stage", "next-wave")
        self.assertIn("wave", out["reason"])



class StopFile(unittest.TestCase):
    """A clean stop asked by the runner through a file."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.flag = os.path.join(self.dir, "stop-soft")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_no_file_takes_next(self):
        code, out, _ = run(env={"AUTO_BMAD_STOP_FILE": self.flag})
        self.assertEqual(code, 0)
        self.assertFalse(out["stop_requested"])

    def test_file_stops_between_stories(self):
        open(self.flag, "w").close()
        code, out, err = run(env={"AUTO_BMAD_STOP_FILE": self.flag, "AUTO_BMAD_DEADLINE": at(600)})
        self.assertEqual(code, 2)
        self.assertTrue(out["stop_requested"])
        self.assertIn("stop was requested", out["reason"])
        self.assertIn("stop was requested", err)

    def test_argument_wins_and_names_the_wave(self):
        open(self.flag, "w").close()
        code, out, _ = run(["--stop-file", self.flag, "--stage", "next-wave"])
        self.assertEqual(code, 2)
        self.assertIn("next wave", out["reason"])


class LiveFile(unittest.TestCase):
    """Values changed by the runner during the run win over the environment."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.live = os.path.join(self.dir, "live.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, data):
        with open(self.live, "w") as f:
            json.dump(data, f)

    def test_live_deadline_wins(self):
        self.write({"deadline": int(at(10)), "reserve_minutes": 30})
        code, out, _ = run(env={"AUTO_BMAD_LIVE_FILE": self.live, "AUTO_BMAD_DEADLINE": at(600)})
        self.assertEqual(code, 2)
        self.assertEqual(out["deadline"], int(at(10)))

    def test_live_threshold_wins(self):
        limits = os.path.join(self.dir, "limits.json")
        with open(limits, "w") as f:
            json.dump({"updated_at": NOW, "five_hour": {"utilization": 0.8, "resets_at": NOW + 3600}}, f)
        self.write({"stop_at_five_hour_pct": 97})
        code, _, _ = run(env={"AUTO_BMAD_LIVE_FILE": self.live, "AUTO_BMAD_LIMITS_FILE": limits,
                              "AUTO_BMAD_STOP_AT_FIVE_HOUR_PCT": "70"})
        self.assertEqual(code, 0, "97% из файла главнее 70% из окружения")

    def test_missing_file_falls_back(self):
        code, out, _ = run(env={"AUTO_BMAD_LIVE_FILE": self.live, "AUTO_BMAD_DEADLINE": at(5)})
        self.assertEqual(code, 2)
        self.assertEqual(out["deadline"], int(at(5)))

    def test_broken_file_warns(self):
        with open(self.live, "w") as f:
            f.write("{nope")
        code, out, _ = run(env={"AUTO_BMAD_LIVE_FILE": self.live, "AUTO_BMAD_DEADLINE": at(600)})
        self.assertEqual(code, 0)
        self.assertTrue(any("live file" in w for w in out["warnings"]))

if __name__ == "__main__":
    unittest.main(verbosity=1)
