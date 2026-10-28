"""Unit tests for plan_run.py: story titles and goals, waits, run defaults, language.
python3 -m unittest discover tests"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import plan_run as p  # noqa: E402

EPICS = """# Epics
## Epic 16: Fixes from real use

### Story 16.1: Keyboard does not cover input fields

As a user,
I want, the field to stay visible above the keyboard,
So that typing is easy.

### Story 16.2: No want line

The first line of text.
"""

STATUS = [("epic-16", "in-progress"),
          ("16-1-keyboard-insets-forms", "backlog"),
          ("16-2-no-want", "done"),
          ("16-3-not-in-epics", "backlog")]


class PlanRunTitlesTest(unittest.TestCase):
    def test_epic_head(self):
        epics, stories = p.parse_epics(EPICS)
        self.assertEqual(epics, {16: "Fixes from real use"})
        self.assertEqual(stories[(16, "1")][0], "Keyboard does not cover input fields")

    def test_bmad_grammar_english_keywords_any_title(self):
        """Same grammar as BMad's sprint_plan.py: English keywords, the title in any language."""
        text = ("# Epic 3: Importación\n#### Story 3.1 Cargar CSV\n```\n## Epic 9: in a code block\n```\n"
                "### Story 3.2a: split story\n")
        epics, stories = p.parse_epics(text)
        self.assertEqual(epics, {3: "Importación"})
        self.assertEqual(list(stories), [(3, "1"), (3, "2a")])
        self.assertEqual(stories[(3, "1")][0], "Cargar CSV")
        self.assertEqual(stories[(3, "2a")][0], "split story")

    def test_heading_in_another_language_is_warned_not_read(self):
        text = "## Épica 3: Importación\n### Story 3.1: Cargar CSV\n## Overview\n"
        epics, stories = p.parse_epics(text)
        self.assertEqual(epics, {})
        self.assertEqual(list(stories), [(3, "1")])
        warnings = p.heading_warnings(text)
        self.assertEqual(len(warnings), 1)
        self.assertIn("line 1", warnings[0])
        self.assertEqual(p.heading_warnings("## Epic 1: A\n### Story 1.1: B\n## Overview\n"), [])

    def test_goal_from_want_line(self):
        _, stories = p.parse_epics(EPICS)
        self.assertEqual(p.story_goal(stories[(16, "1")][1]),
                         "the field to stay visible above the keyboard")

    def test_goal_falls_back_to_first_line(self):
        _, stories = p.parse_epics(EPICS)
        self.assertEqual(p.story_goal(stories[(16, "2")][1]), "The first line of text")

    def test_goal_truncated(self):
        goal = p.story_goal("I want " + "a" * 300)
        self.assertEqual(len(goal), p.GOAL_MAX)
        self.assertTrue(goal.endswith("…"))

    def test_goal_markdown_want_variants(self):
        self.assertEqual(p.story_goal("As a user,\n**I want** to export data"), "export data")
        self.assertEqual(p.story_goal("- I want: see the list"), "see the list")

    def test_goal_skips_user_story_boilerplate(self):
        self.assertEqual(p.story_goal("As a user,\nSo that it is easy.\nA short description."),
                         "A short description")
        self.assertIsNone(p.story_goal("As a user,\nSo that x."))

    def test_pipe_does_not_break_table(self):
        self.assertEqual(p.story_goal("I want CSV | JSON"), "CSV / JSON")

    def test_load_epics_missing_and_tag_stripped(self):
        with tempfile.TemporaryDirectory() as repo:
            self.assertEqual(p.load_epics(repo), ({}, {}, None))
            os.makedirs(os.path.join(repo, p.PLANNING))
            path = os.path.join(repo, p.PLANNING, "epics.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("## Epic 5: Import (CSV) [deferred 2026-10-05]\n")
            epics, _, warning = p.load_epics(repo)
            self.assertEqual(epics, {5: "Import (CSV)"})
            self.assertIsNone(warning)
            with open(path, "wb") as f:
                f.write(b"\xff\xfe\x00broken")
            self.assertEqual(p.load_epics(repo)[:2], ({}, {}))
            self.assertIn("is not readable", p.load_epics(repo)[2])


    def test_collect_uses_epics_and_falls_back_to_slug(self):
        _, stories = p.parse_epics(EPICS)
        out = p.collect(STATUS, 16, story_text=stories)
        self.assertEqual([s["id"] for s in out], ["16-1", "16-3"])
        self.assertEqual(out[0]["title"], "Keyboard does not cover input fields")
        self.assertEqual(out[1]["title"], "not in epics")
        self.assertIsNone(out[1]["goal"])

    def test_review_stories_go_first(self):
        status = [("epic-5", "in-progress"), ("5-1-a", "done"), ("5-2-b", "backlog"),
                  ("5-3-c", "review"), ("5-4-d", "ready-for-dev"), ("5-10-e", "review")]
        self.assertEqual([s["id"] for s in p.collect(status, 5)], ["5-3", "5-10", "5-2", "5-4"])

    def test_default_story_takes_review_before_ready_for_dev(self):
        status = [("epic-5", "in-progress"), ("5-1-a", "ready-for-dev"), ("5-2-b", "review")]
        self.assertEqual(p.default_story(status)[0]["story"], "2")
        status.append(("5-3-c", "in-progress"))
        self.assertEqual(p.default_story(status)[0]["story"], "3")


WAITS_EPICS = """# Epics
## Epic List

### Epic 4: Autofill
**Waits:** 4.13 — story 7.6; 4.14 — story 4.13 and 19.1.

### Epic 8: Passkeys [deferred 2026-10-05]
**Waits:** epic 7 (key transport).

### Epic 21: System transfer [deferred 2026-10-14]
**Waits:** the app is published on Google Play.

### Epic 22: Transfer to Mac
**Waits:** epic 14 (build; the vault holds 100+ items), epic 20 (protocol).

## Epic 22: Transfer to Mac

**Waits:** epic 14 (build; the vault holds 100+ items), epic 20 (protocol).

### Story 22.1: Android → Mac
"""

WAITS_STATUS = [("epic-4", "in-progress"),
                ("4-12-x", "done"), ("4-13-x", "backlog"), ("4-14-x", "backlog"),
                ("epic-7", "backlog"), ("7-6-x", "backlog"),
                ("epic-8", "backlog"), ("8-1-x", "backlog"),
                ("epic-14", "done"), ("epic-19", "done"), ("19-1-x", "done"),
                ("epic-20", "in-progress"), ("20-5-x", "backlog"),
                ("epic-21", "backlog"), ("21-1-x", "backlog"),
                ("epic-22", "backlog"), ("22-1-x", "backlog"), ("22-2-x", "backlog")]


def clauses(epic):
    return [c for line in p.parse_waits(WAITS_EPICS).get(epic, []) for c in p.parse_wait_clauses(line)]


class PlanRunWaitsTest(unittest.TestCase):
    def test_lines_from_list_and_section_without_duplicates(self):
        waits = p.parse_waits(WAITS_EPICS)
        self.assertEqual(sorted(waits), [4, 8, 21, 22])
        self.assertEqual(len(waits[22]), 1)

    def test_scoped_and_whole_epic_clauses(self):
        c4 = clauses(4)
        self.assertEqual([c["stories"] for c in c4], [[(4, "13", "13")], [(4, "14", "14")]])
        self.assertEqual(c4[0]["story_refs"], [(7, "6")])
        self.assertEqual(c4[1]["story_refs"], [(4, "13"), (19, "1")])
        self.assertEqual(clauses(8)[0]["epics"], [7])
        self.assertIsNone(clauses(8)[0]["stories"])

    def test_semicolon_inside_parentheses_does_not_split(self):
        c22 = clauses(22)
        self.assertEqual(len(c22), 1)
        self.assertEqual(c22[0]["epics"], [14, 20])
        self.assertIsNone(c22[0]["free"])

    def test_free_text_condition_cannot_be_checked(self):
        c = clauses(21)[0]
        self.assertEqual(c["free"], "the app is published on Google Play")
        self.assertIn("cannot check", p.waits_for([c], dict(WAITS_STATUS), 21)[0])

    def test_range_and_list_of_stories(self):
        c = p.parse_wait_clauses("18.1–18.2, 18.5 — epics 14 and 17")[0]
        self.assertEqual(c["stories"], [(18, "1", "2"), (18, "5", "5")])
        self.assertEqual(c["epics"], [14, 17])

    def test_whole_epic_wait_is_error(self):
        status = dict(WAITS_STATUS)
        result = {"stories": p.collect(WAITS_STATUS, 22)}
        p.check_waits(result, clauses(22), status, 22)
        self.assertIn("epic 20 (in-progress)", result["error"])
        self.assertEqual(result["waiting"], ["epic 20 (in-progress)"])

    def test_story_wait_cuts_queue_before_story(self):
        status = dict(WAITS_STATUS, **{"7-6-x": "done"})
        entries = list(status.items())
        result = {"stories": p.collect(entries, 4)}
        p.check_waits(result, clauses(4), status, 4)
        self.assertNotIn("error", result)
        self.assertEqual([s["id"] for s in result["stories"]], ["4-13", "4-14"])
        status["7-6-x"] = "backlog"
        result = {"stories": p.collect(entries, 4)}
        p.check_waits(result, clauses(4), status, 4)
        self.assertEqual(result["stories"], [])
        self.assertIn("story 4-13 waits for", result["error"])

    def test_cut_keeps_earlier_stories_in_note(self):
        entries = WAITS_STATUS + [("4-11-x", "backlog")]
        result = {"stories": p.collect(entries, 4)}
        p.check_waits(result, clauses(4), dict(entries), 4)
        self.assertEqual([s["id"] for s in result["stories"]], ["4-11"])
        self.assertIn("before story 4-13", result["note"])

    def test_own_epic_refs_are_not_checked(self):
        # 4.14 waits for 4.13: in an epic run 4.13 is done first, so no cut.
        status = dict(WAITS_STATUS, **{"7-6-x": "done"})
        self.assertEqual(p.waits_for(clauses(4), status, 4, "14"), [])

    def test_single_story_checks_own_epic_refs(self):
        # A single 4.14 run: 4.13 will not come first, so its status is checked.
        status = dict(WAITS_STATUS, **{"7-6-x": "done"})
        result = {"stories": p.collect(list(status.items()), 4, only_story="14")}
        p.check_waits(result, clauses(4), status, 4, own=True)
        self.assertIn("story 4.13 (backlog)", result["error"])

    def test_default_story_skips_waiting_backlog(self):
        waits = {n: clauses(n) for n in (4, 8, 21, 22)}
        target, err = p.default_story(WAITS_STATUS, waits)
        self.assertIsNone(err)
        self.assertEqual((target["epic"], target["story"]), (20, "5"))
        self.assertIn("4-13 waits for", target["note"])

    def test_no_epics_file_means_no_waits(self):
        with tempfile.TemporaryDirectory() as repo:
            self.assertEqual(p.load_waits(repo), {})


class RunDefaultsTest(unittest.TestCase):
    def test_flags_override_config_defaults(self):
        d = {"level": "deep", "parallel": "off", "width": 2}
        self.assertEqual(p.parse_flags("epic-1", d)[:3], ("deep", "off", 2))
        self.assertEqual(p.parse_flags("epic-1 --fast --width 4", d)[:3], ("fast", "off", 4))
        self.assertEqual(p.parse_flags("epic-1")[:3], ("normal", "conservative", 3))

    def test_run_section_read_from_project_config(self):
        with tempfile.TemporaryDirectory() as repo:
            with open(os.path.join(repo, ".auto-bmad.toml"), "w") as fh:
                fh.write('[run]\nlevel = "fast"\nparallel = "nonsense"\nwidth = 2\n')
            os.environ["AUTO_BMAD_CONFIG"] = os.path.join(repo, "absent.toml")
            try:
                self.assertEqual(p.run_defaults(repo), {"level": "fast", "width": 2})
            finally:
                del os.environ["AUTO_BMAD_CONFIG"]


class EnglishWaitsTest(unittest.TestCase):
    def test_english_waits_line(self):
        text = "## Epic 3: Sync\n**Waits for:** epic 2; 3.2 — story 1.4.\n"
        cs = [c for line in p.parse_waits(text)[3] for c in p.parse_wait_clauses(line)]
        self.assertEqual(cs[0]["epics"], [2])
        self.assertEqual((cs[1]["stories"], cs[1]["story_refs"]), ([(3, "2", "2")], [(1, "4")]))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class LanguageTest(unittest.TestCase):
    def test_none_without_bmad_config(self):
        with tempfile.TemporaryDirectory() as repo:
            self.assertIsNone(p.bmad_language(repo))

    def test_user_toml_wins_over_team_toml(self):
        with tempfile.TemporaryDirectory() as repo:
            write(os.path.join(repo, "_bmad", "config.toml"),
                  '[core]\ncommunication_language = "English"\n')
            self.assertEqual(p.bmad_language(repo), "English")
            write(os.path.join(repo, "_bmad", "config.user.toml"),
                  '[core]\ncommunication_language = "Russian"\n')
            self.assertEqual(p.bmad_language(repo), "Russian")
            write(os.path.join(repo, "_bmad", "custom", "config.user.toml"),
                  '[core]\ncommunication_language = "German"\n')
            self.assertEqual(p.bmad_language(repo), "German")

    def test_custom_team_toml_wins_over_installer_user_toml(self):
        """Same order as BMad's load_central_config: custom/ overrides the installer files."""
        with tempfile.TemporaryDirectory() as repo:
            write(os.path.join(repo, "_bmad", "config.user.toml"),
                  '[core]\ncommunication_language = "Russian"\n')
            write(os.path.join(repo, "_bmad", "custom", "config.toml"),
                  '[core]\ncommunication_language = "English"\n')
            self.assertEqual(p.bmad_language(repo), "English")

    def test_yaml_fallback_and_empty_value_skipped(self):
        with tempfile.TemporaryDirectory() as repo:
            write(os.path.join(repo, "_bmad", "config.toml"), '[core]\ncommunication_language = ""\n')
            write(os.path.join(repo, "_bmad", "core", "config.yaml"),
                  "user_name: X\ncommunication_language: 'Spanish'  # comment\n")
            self.assertEqual(p.bmad_language(repo), "Spanish")

    def test_broken_toml_is_skipped(self):
        with tempfile.TemporaryDirectory() as repo:
            write(os.path.join(repo, "_bmad", "config.user.toml"), "[core\n")
            write(os.path.join(repo, "_bmad", "bmm", "config.yaml"), "communication_language: French\n")
            self.assertEqual(p.bmad_language(repo), "French")


class HeadingsAndScopeTest(unittest.TestCase):
    def test_stray_numbered_heading_is_not_an_epic(self):
        text = ("## Epic 1: One\n### Story 1.1: A\n## Epic 2: Real\n### Story 2.1: B\n"
                "## Milestone 2: Beta\n**Waits:** the app is published.\n")
        epics, stories = p.parse_epics(text)
        self.assertEqual(epics, {1: "One", 2: "Real"})
        self.assertEqual(p.parse_waits(text), {})

    def test_epic_heading_with_dot_separator_keeps_its_waits(self):
        text = "## Epic 2. Base\n## Epic 3. Sync\n**Waits:** epic 2.\n"
        self.assertEqual(p.parse_waits(text), {3: ["epic 2."]})

    def test_scope_forms(self):
        for arg, epic in (("epic-7", 7), ("epic 7", 7), ("Épica 7", 7), ("7", 7)):
            self.assertEqual(p.parse_scope(arg, [])[0], {"mode": "epic", "epic": epic, "story": None}, arg)
        self.assertEqual(p.parse_scope("3-7", [])[0]["mode"], "story")
        for arg in ("story 7", "fix bug 12", "--resume 2", "epic 1 2"):
            target, err = p.parse_scope(arg, [])
            self.assertIsNone(target, arg)
            self.assertIn("cannot parse", err)


class SplitStoryTest(unittest.TestCase):
    """BMad split stories: key "2-6a-<slug>", heading "### Story 2.6a: …"."""
    ENTRIES = [("epic-2", "in-progress"), ("2-5-x", "done"), ("2-6-base", "backlog"),
               ("2-6b-second-half", "backlog"), ("2-6a-first-half", "backlog"), ("2-7-next", "backlog"),
               ("2-10-late", "backlog"), ("epic-2-retrospective", "optional")]

    def test_queue_order_and_ids(self):
        out = p.collect(self.ENTRIES, 2)
        self.assertEqual([s["id"] for s in out], ["2-6", "2-6a", "2-6b", "2-7", "2-10"])
        self.assertEqual(out[1]["slug"], "first-half")

    def test_scope_picks_a_split_story(self):
        for arg in ("2-6a", "2.6A", "story 2-6a"):
            self.assertEqual(p.parse_scope(arg, self.ENTRIES)[0],
                             {"mode": "story", "epic": 2, "story": "6a"}, arg)
        self.assertEqual(p.parse_scope("2-6", self.ENTRIES)[0]["story"], "6")
        self.assertIsNone(p.parse_scope("2-6ab", self.ENTRIES)[0])
        self.assertEqual([s["id"] for s in p.collect(self.ENTRIES, 2, only_story="6a")], ["2-6a"])

    def test_waits_reference_a_split_story(self):
        c = p.parse_wait_clauses("2.7 — story 2.6a and 1.3")[0]
        self.assertEqual((c["stories"], c["story_refs"], c["free"]), ([(2, "7", "7")], [(2, "6a"), (1, "3")], None))
        status = dict(self.ENTRIES)
        self.assertEqual(p.unmet(c, status, 2, own=True), ["story 2.6a (backlog)", "story 1.3 (not in sprint-status)"])
        self.assertEqual(p.story_items("2.6a, 2.8–2.9"), [(2, "6a", "6a"), (2, "8", "9")])

    def test_ranges_cover_split_stories(self):
        items = p.story_items("2.5–2.7, 3.6a–3.6c, 4.5–4.6a")
        self.assertTrue(all(p.covers(items, 2, n) for n in ("5", "6", "6a", "6b", "7")))
        self.assertFalse(p.covers(items, 2, "7a"))
        self.assertEqual([n for n in ("6", "6a", "6b", "6c", "6d") if p.covers(items, 3, n)], ["6a", "6b", "6c"])
        self.assertEqual([n for n in ("5", "6", "6a", "6b") if p.covers(items, 4, n)], ["5", "6", "6a"])
        self.assertFalse(p.covers(p.story_items("2.6"), 2, "6a"))
        c = p.parse_wait_clauses("2.5–2.6a — epic 3")[0]
        self.assertEqual((c["stories"], c["epics"], c["free"]), ([(2, "5", "6a")], [3], None))
        status = dict(self.ENTRIES, **{"epic-3": "backlog"})
        self.assertEqual(p.waits_for([c], status, 2, "6a"), ["epic 3 (backlog)"])
        self.assertEqual(p.waits_for([c], status, 2, "7"), [])

    def test_key_numbers_are_normalized(self):
        entries = [("epic-2", "in-progress"), ("2-06-padded", "in-progress"), ("2-6B-upper", "backlog")]
        self.assertEqual(p.default_story(entries)[0]["story"], "6")
        self.assertEqual([s["id"] for s in p.collect(entries, 2)], ["2-6", "2-6b"])
        self.assertEqual(p.parse_scope("2-6", entries)[0]["story"], "6")


class QuestionsFileTest(unittest.TestCase):
    def test_fixed_english_name(self):
        self.assertEqual(p.questions_file(4),
                         os.path.join("_bmad-output", "implementation-artifacts", "epic-4-open-questions.md"))


if __name__ == "__main__":
    unittest.main()
