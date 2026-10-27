"""Tests for write_profile.py: the level profile the engine reads.
python3 -m unittest discover tests"""
import os
import re
import sys
import tomllib
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import write_profile as wp  # noqa: E402

HEADS = {
    "A": "Follow-up review policy",
    "B": "Triage screening policy",
    "C": "Repair loop limit",
    "D": "Blind Hunter launch policy",
    "E": "Model policy",
    "F": "Subagent execution in this host is asynchronous",
    "G": "Context-compilation policy",
    "H": "Context economy",
}


class ProfileTest(unittest.TestCase):
    def facts(self, level):
        return tomllib.loads(wp.build(level))["workflow"]["persistent_facts"]

    def test_every_level_parses_and_has_its_facts(self):
        for level in wp.DISABLED:
            facts = self.facts(level)
            want = [k for k in HEADS if not (k == "G" and level == "deep")]
            found = [k for k in HEADS if any(f.startswith(HEADS[k]) for f in facts)]
            self.assertEqual(found, want, level)
            self.assertEqual(len(facts), len(want), level)

    def test_level_values_reach_the_text(self):
        for level, n in wp.REPAIR_LIMIT.items():
            text = wp.build(level)
            self.assertIn(f"loopback limit in step-04 Classify step 5 is {n}, not 5", text)
            self.assertIn(wp.REVIEWER_ROUTING[level], text)

    def test_disabled_layers_are_empty_entries(self):
        for level, layers in wp.DISABLED.items():
            entries = tomllib.loads(wp.build(level))["workflow"].get("review_layers", [])
            self.assertEqual([(e["id"], e["instruction"]) for e in entries], [(x, "") for x in layers])

    def test_facts_leave_engine_placeholders_alone(self):
        # The engine substitutes {name} placeholders when it renders; a fact must not carry one.
        for level in wp.DISABLED:
            for fact in self.facts(level):
                self.assertIsNone(re.search(r"\{[a-z_]+\}", fact), fact[:60])

    def test_context_economy_keeps_the_checks(self):
        h = wp.FACT_H
        self.assertIn("the review layers read that file themselves", h)
        self.assertIn("git status --porcelain", h)                 # new untracked files are seen
        self.assertIn("There is no limit on such targeted reads", h)
        self.assertIn("still re-reads the spec file from disk", h)


if __name__ == "__main__":
    unittest.main()
