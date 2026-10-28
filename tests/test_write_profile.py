"""Tests for write_profile.py: the level profile the engine reads.
python3 -m unittest discover tests"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

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
        self.assertIn("Under 30000 characters, read it whole", h)    # a small diff is read whole
        self.assertIn("wc -m", h)                                     # characters, not bytes
        self.assertIn("is not evidence", h)                           # a rejection names what was read
        self.assertIn("auto-bmad evidence --input", h)                # one call for the whole pass
        self.assertIn("with the Write tool (no heredoc)", h)


class TriageSubagentTest(unittest.TestCase):
    def test_off_is_the_same_profile_byte_for_byte(self):
        args = {"triager": {"effort": "max"}, "implementer": {"model": "sonnet"}}
        for level in wp.DISABLED:
            self.assertEqual(wp.build(level, args, False), wp.build(level, args))
            self.assertNotIn("bmad-triager", wp.build(level, args))

    def test_on_adds_fact_i_last_on_every_level(self):
        for level in wp.DISABLED:
            facts = tomllib.loads(wp.build(level, triage_subagent=True))["workflow"]["persistent_facts"]
            self.assertTrue(facts[-1].startswith("Triage delegation"), level)
            off = tomllib.loads(wp.build(level))["workflow"]["persistent_facts"]
            self.assertEqual([f for f in facts[:-1] if not f.startswith(HEADS["H"])],
                             [f for f in off if not f.startswith(HEADS["H"])])

    def test_on_gives_the_evidence_to_the_triager_only(self):
        h_on = next(f for f in tomllib.loads(wp.build("normal", triage_subagent=True))["workflow"]
                    ["persistent_facts"] if f.startswith(HEADS["H"]))
        self.assertIn(wp.H_TRIAGE_DELEGATED, h_on)
        self.assertIn("this session collects no evidence", h_on)
        self.assertEqual(h_on.replace(wp.H_TRIAGE_DELEGATED, wp.H_TRIAGE).strip(), wp.FACT_H)
        self.assertNotIn(wp.H_TRIAGE_DELEGATED, wp.build("normal"))
        self.assertEqual(wp.FACT_H.count(wp.H_TRIAGE), 1)

    def test_fact_i_keeps_the_session_work_and_a_fallback(self):
        i = wp.FACT_I
        self.assertIn('`subagent_type: "auto-bmad:bmad-triager"`', i)
        self.assertIn("steps 1–3", i)
        self.assertIn("continue Classify from step 4", i)          # patches stay in the session
        self.assertIn("It reads code and changes nothing", i)
        self.assertIn("the only file it writes is its evidence input", i)
        self.assertIn("do not halt over it", i)

    def test_triager_override_follows_its_agent_type(self):
        facts = tomllib.loads(wp.build("normal", {"triager": {"model": "sonnet"}}, True))
        i = facts["workflow"]["persistent_facts"][-1]
        self.assertIn('`subagent_type: "auto-bmad:bmad-triager"` with Agent parameters `model: "sonnet"`', i)
        self.assertIn(wp.ARGS_RULE, i)


class TriageConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        os.makedirs(os.path.join(self.repo, "_bmad", "custom"))
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.env = mock.patch.dict(os.environ, {"AUTO_BMAD_CONFIG": os.path.join(self.repo, "user.toml")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def profile(self, config=None):
        if config is not None:
            with open(os.path.join(self.repo, ".auto-bmad.toml"), "w", encoding="utf-8") as fh:
                fh.write(config)
        out = io.StringIO()
        argv = ["write_profile.py", "--level", "normal", "--repo", self.repo]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(wp.main(), 0)
        with open(os.path.join(self.repo, "_bmad", "custom", "bmad-build-auto.user.toml"), encoding="utf-8") as fh:
            return json.loads(out.getvalue()), fh.read()

    def test_default_is_off(self):
        res, text = self.profile()
        self.assertFalse(res["triage_subagent"])
        self.assertEqual(text, wp.build("normal"))

    def test_flag_on(self):
        res, text = self.profile("[run]\ntriage_subagent = true\n")
        self.assertTrue(res["triage_subagent"])
        self.assertIn("Triage delegation", text)

    def test_broken_config_is_a_warning(self):
        res, text = self.profile("[run\ntriage_subagent = true\n")
        self.assertFalse(res["triage_subagent"])
        self.assertNotIn("Triage delegation", text)
        self.assertTrue(any("unreadable" in w for w in res["warnings"]), res["warnings"])

    def test_flag_false_and_bad_value(self):
        res, text = self.profile("[run]\ntriage_subagent = false\n")
        self.assertEqual(text, wp.build("normal"))
        res, text = self.profile('[run]\ntriage_subagent = "yes"\n')
        self.assertFalse(res["triage_subagent"])
        self.assertNotIn("Triage delegation", text)
        self.assertTrue(any("triage_subagent" in w for w in res["warnings"]))


if __name__ == "__main__":
    unittest.main()
