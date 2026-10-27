import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import stats  # noqa: E402

SPEC = """# spec
## Review Triage Log

### 2026-10-15 — Review pass
- verdicts: 3 findings — high 1, medium 0, low 1, false 1
- findings:
  - `[high]` `[patch]` (edge) secret finding text
  - `[low]` `[reject]` (blind) another secret
  - `[false]` `[reject]` (blind) third

## Design Notes
"""


def msg(mid, model, content, usage=None, ts="2026-10-15T01:00:00Z"):
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": mid, "model": model, "content": content,
                        "usage": usage or {"input_tokens": 10, "output_tokens": 1,
                                           "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 100}}}


class Collect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.spec = os.path.join(self.repo, "spec-3-2-x.md")
        with open(self.spec, "w") as fh:
            fh.write(SPEC)
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp.name, "claude")
        pdir = os.path.join(stats.projects_dir(), stats.project_key(self.repo))
        sub = os.path.join(pdir, "S1", "subagents")
        os.makedirs(sub)
        prompt = "Run…\n\nStory: 3.2 — Secret title\nRun level: deep\nSecret task text"
        self.write(os.path.join(pdir, "S1.jsonl"), [
            msg("m0", "claude-opus-5-5", [{"type": "tool_use", "id": "t-run", "name": "Agent",
                                          "input": {"subagent_type": "auto-bmad:bmad-story-runner", "prompt": prompt}}])])
        handback = f"STATUS: done\nSPEC: {self.spec}\nCOMMIT: abcdef1234567890\nFILES: 4\nPASSES: 1 of 3\nFOLLOWUP_OPEN: no\nDEFERRED: 2\n\n### What was done\n…"
        self.agent(sub, "a-run", "auto-bmad:bmad-story-runner", "t-run", 1, [
            msg("r1", "claude-opus-5-5", [{"type": "tool_use", "id": "t-impl", "name": "Agent", "input": {}}],
                ts="2026-10-15T01:00:00Z"),
            msg("r1", "claude-opus-5-5", [{"type": "text", "text": "x" * 35}], ts="2026-10-15T01:01:00Z"),
            msg("r2", "claude-opus-5-5", [{"type": "tool_use", "id": "t-hb", "name": "SubagentHandback",
                                          "input": {"message": handback}}], ts="2026-10-15T01:10:00Z"),
            msg("r3", "claude-opus-5-5", [{"type": "text", "text": "A background command finished."}],
                ts="2026-10-15T02:00:00Z")])
        self.agent(sub, "a-impl", "auto-bmad:bmad-implementer", "t-impl", 2, [
            msg("i1", "claude-opus-5-5", [{"type": "tool_use", "id": "t-b", "name": "Bash", "input": {"command": "ls"}}],
                ts="2026-10-15T01:20:00Z")])

    def tearDown(self):
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.tmp.cleanup()

    def write(self, path, rows):
        with open(path, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    def agent(self, sub, aid, typ, parent, depth, rows):
        with open(os.path.join(sub, aid + ".meta.json"), "w") as fh:
            json.dump({"agentType": typ, "toolUseId": parent, "spawnDepth": depth}, fh)
        self.write(os.path.join(sub, aid + ".jsonl"), rows)

    def test_story_record(self):
        recs = stats.collect(stats.find_session(self.repo, "S1"))
        orch, story = recs
        self.assertEqual(orch["kind"], "orchestrator")
        self.assertEqual((story["story"], story["epic"], story["level"], story["status"]), ("3-2", 3, "deep", "done"))
        self.assertEqual((story["files"], story["review_passes_used"], story["deferred"]), (4, 1, 2))
        self.assertEqual(story["agents"], {"story-runner": 1, "implementer": 1})
        self.assertEqual(story["minutes"], 10.0)               # woken after the handback: not counted
        self.assertEqual(story["tokens"]["total"]["cache_read"], 4000)   # r1 counted once
        self.assertEqual(story["tools"]["Bash"], 1)
        self.assertEqual(story["review"], {"passes": 1, "findings": 3,
                                           "by_verdict": {"high": 1, "medium": 0, "low": 1, "false": 1},
                                           "by_action": {"patch": 1, "reject": 2},
                                           "by_layer": {"edge": 1, "blind": 2}})

    def test_fix_run_and_verifier_join_the_story(self):
        pdir = os.path.join(stats.projects_dir(), stats.project_key(self.repo))
        sub = os.path.join(pdir, "S1", "subagents")
        prompt = "Story: 3.2 — Secret title\nRun level: deep"
        rows = [json.loads(l) for l in open(os.path.join(pdir, "S1.jsonl"))]
        rows.append(msg("m1", "claude-opus-5-5", [
            {"type": "tool_use", "id": "t-ver", "name": "Agent", "input": {"prompt": "Check\n" + prompt}},
            {"type": "tool_use", "id": "t-fix", "name": "Agent", "input": {"prompt": prompt}}]))
        self.write(os.path.join(pdir, "S1.jsonl"), rows)
        self.agent(sub, "a-ver", "auto-bmad:bmad-verifier", "t-ver", 1, [
            msg("v1", "claude-sonnet-5-5", [{"type": "text", "text": "VERDICT: problem\nPROBLEMS:\n1. x"}],
                ts="2026-10-15T01:30:00Z")])
        self.agent(sub, "a-fix", "auto-bmad:bmad-story-runner", "t-fix", 1, [
            msg("f1", "claude-opus-5-5", [{"type": "text", "text": "STATUS: done\nCOMMIT: ffff"}],
                ts="2026-10-15T01:40:00Z")])
        recs = [r for r in stats.collect(stats.find_session(self.repo, "S1")) if r["kind"] == "story"]
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual((r["fix_runs"], r["verify"], r["commit"]), (1, ["problem"], "ffff"))
        self.assertEqual(r["agents"]["verifier"], 1)
        self.assertEqual(r["files"], 4)                 # from the last main run
        self.assertEqual(r["minutes"], 10.0)            # the check and the fix are one message each
        self.assertEqual(r["ended"], "2026-10-15T01:40:00Z")

    def test_summary_shows_triage_shares(self):
        rows = [{"kind": "story", "level": "normal", "tokens": {"total": dict.fromkeys(stats.ZERO, 0)},
                 "review": {"by_action": {"patch": 1, "reject": 3, "blind": 5},
                            "by_verdict": {"low": 2, "false": 1, "high": 1}}},
                {"kind": "story", "level": "normal", "tokens": {"total": dict.fromkeys(stats.ZERO, 0)},
                 "review": {"by_action": {"patch": 1, "defer": 1, "reject": 2, "bad_spec": 1}}}]
        summary = stats.summarize(rows)
        t = summary["triage"]
        # an unknown label ("blind") stays out of the shares; 12.5 rounds up
        self.assertEqual((t["routed"], t["patch_pct"], t["defer_pct"], t["reject_pct"], t["spec_pct"]),
                         (9, 22, 11, 56, 11))
        self.assertEqual((t["graded"], t["low_pct"], t["false_pct"]), (4, 50, 25))
        self.assertEqual(summary["by_level"]["normal"]["triage"], t)
        self.assertIn("Triage of 9 findings: patch 22%, defer 11%, reject 56%, to the spec 11%"
                      " · verdicts of 4: low 50%, false 25%", stats.table(rows, summary))
        self.assertEqual(stats.pct(1, 8), 13)
        self.assertIsNone(stats.summarize([])["triage"]["patch_pct"])

    def test_collect_and_summary_show_the_models_of_each_role(self):
        r = [r for r in stats.collect(stats.find_session(self.repo, "S1")) if r["kind"] == "story"][0]
        self.assertEqual(set(r["tokens"]["by_role_model"]), set(r["tokens"]["by_role"]))
        for role, models in r["tokens"]["by_role_model"].items():
            self.assertEqual(stats.total(models), r["tokens"]["by_role"][role], role)
        zero = dict.fromkeys(stats.ZERO, 0)
        rows = [{"kind": "story", "tokens": {"total": zero, "by_role": {"implementer": dict(zero, out_est=30)},
                                             "by_role_model": {"implementer": {
                                                 "opus-5-5": dict(zero, out_est=10),
                                                 "sonnet-5-5": dict(zero, out_est=20)}}}},
                {"kind": "story", "tokens": {"total": zero, "by_role": {"verifier": dict(zero, out_est=5)}}}]
        summary = stats.summarize(rows)
        self.assertEqual(summary["role_models"], {"implementer": ["sonnet-5-5", "opus-5-5"]})
        self.assertIn("Output by role: implementer 30 (sonnet-5-5, opus-5-5), verifier 5", stats.table(rows, summary))

    def test_rerun_before_the_check_is_not_a_fix(self):
        pdir = os.path.join(stats.projects_dir(), stats.project_key(self.repo))
        sub = os.path.join(pdir, "S1", "subagents")
        rows = [json.loads(l) for l in open(os.path.join(pdir, "S1.jsonl"))]
        rows.insert(0, msg("m-1", "claude-opus-5-5", [{"type": "tool_use", "id": "t-early", "name": "Agent",
                                                      "input": {"prompt": "Story: 3.2 — X\nRun level: deep"}}]))
        self.write(os.path.join(pdir, "S1.jsonl"), rows)
        self.agent(sub, "a-early", "auto-bmad:bmad-story-runner", "t-early", 1, [
            msg("e1", "claude-opus-5-5", [{"type": "text", "text": "STATUS: blocked\nCOMMIT: none\nFILES: 0"}],
                ts="2026-10-15T00:50:00Z")])
        r = [r for r in stats.collect(stats.find_session(self.repo, "S1")) if r["kind"] == "story"][0]
        self.assertEqual((r["fix_runs"], r["files"], r["status"]), (0, 4, "done"))
        self.assertEqual(r["minutes"], 10.0)                # the pause before the rerun is not counted
        self.assertEqual(r["started"], "2026-10-15T00:50:00Z")

    def test_busy_minutes(self):
        t = lambda m: f"2026-10-15T01:{m:02d}:00Z"
        self.assertEqual(stats.busy_minutes([(t(0), t(10)), (t(5), t(15)), (t(30), t(40)), (t(32), t(35))]), 25.0)
        self.assertIsNone(stats.busy_minutes([(t(0), None)]))
        self.assertIsNone(stats.busy_minutes([]))
        self.assertIsNone(stats.busy_minutes([(t(10), t(0))]))              # end before start is dropped
        self.assertEqual(stats.busy_minutes([(t(0), t(10)), (t(10), t(20))]), 20.0)
        self.assertEqual(stats.busy_minutes([("2026-10-15T01:00:00.500Z", "2026-10-15T01:01:00+00:00"),
                                             ("2026-10-15T01:00:00Z", "2026-10-15T01:00:30Z")]), 1.0)
        self.assertEqual(stats.busy_minutes([(f"2026-10-15T01:00:{i:02d}Z", f"2026-10-15T01:00:{i:02d}.900Z")
                                             for i in range(0, 60, 2)]), 0.4)

    def test_text_after_the_handback_changes_neither_status_nor_end(self):
        path = os.path.join(stats.projects_dir(), stats.project_key(self.repo), "S1", "subagents", "a-run.jsonl")
        rows = [json.loads(l) for l in open(path)]
        rows[-1]["message"]["content"][0]["text"] = "STATUS: blocked\nCOMMIT: none"
        self.write(path, rows)
        story = stats.collect(stats.find_session(self.repo, "S1"))[1]
        self.assertEqual((story["status"], story["minutes"]), ("done", 10.0))

    def test_check_without_handback_ends_at_its_verdict(self):
        t = os.path.join(self.tmp.name, "v.jsonl")
        self.write(t, [msg("v1", "m", [{"type": "text", "text": "VERDICT: pass"}], ts="2026-10-15T01:30:00Z"),
                       msg("v2", "m", [{"type": "text", "text": "A background command finished."}],
                           ts="2026-10-15T02:30:00Z")])
        self.assertEqual(stats.Transcript(t).reported, "2026-10-15T01:30:00Z")

    def test_review_layers_as_bmad_writes_them(self):
        with open(self.spec, "w") as fh:
            fh.write(SPEC.replace("(edge) secret", "Edge: secret").replace("`[false]` `[reject]` (blind) third",
                                                                           "`false` `reject` third")
                     .replace("`[low]` `[reject]` (blind)", "`[low]` (blind, claim)"))
        rv = stats.review(self.spec)
        self.assertEqual((rv["by_action"], rv["by_layer"]), ({"patch": 1, "reject": 1}, {"edge": 1, "blind": 1}))
        for row, layer in (("Edge (claim): x", "edge"), ("Intent D1: x", "intent"), ("`code`: x", None),
                           ("Tab is not trimmed", None), ("Note: fix this", None), ("Race (two writers): x", None),
                           ("Blind Hunter: x", "blind")):
            m = stats.FINDING_RE.match(f"  - `[low]` `[reject]` {row}")
            self.assertEqual(m.group(5).lower() if m.group(5) else None, layer, row)
        self.assertEqual(stats.FINDING_RE.match("  - `[critical]` `[fix]` x").group(1, 3), ("critical", "fix"))
        self.assertIsNone(stats.FINDING_RE.match("  - `low` `selectPalette` x").group(4))

    def test_spec_of_a_removed_worktree_is_read_from_the_repo(self):
        art = os.path.join(self.repo, "_bmad-output", "implementation-artifacts")
        os.makedirs(art)
        os.rename(self.spec, os.path.join(art, "spec-3-2-x.md"))
        self.assertIsNone(stats.review(self.spec))
        self.assertEqual(stats.review(self.spec, self.repo)["findings"], 3)

    def test_nothing_private_is_stored(self):
        stats.save(self.repo, stats.collect(stats.find_session(self.repo, "S1")))
        with open(os.path.join(self.repo, stats.STATS)) as fh:
            text = fh.read()
        for secret in ("Secret", "secret", self.spec, "What was done"):
            self.assertNotIn(secret, text)
        status = subprocess.run(["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertNotIn(".auto-bmad", status)

    def rewrite_run(self, prompt, handback):
        pdir = os.path.join(stats.projects_dir(), stats.project_key(self.repo))
        rows = [json.loads(l) for l in open(os.path.join(pdir, "S1.jsonl"))]
        rows[0]["message"]["content"][0]["input"]["prompt"] = prompt
        self.write(os.path.join(pdir, "S1.jsonl"), rows)
        path = os.path.join(pdir, "S1", "subagents", "a-run.jsonl")
        rows = [json.loads(l) for l in open(path)]
        rows[-2]["message"]["content"][0]["input"]["message"] = handback
        self.write(path, rows)

    def test_task_mode_uses_spec_slug(self):
        self.rewrite_run("Task: #12 — Fix login\nSpec slug: issue-12\nRun level: normal",
                         "STATUS: done\nCOMMIT: none\nFILES: 1\nPASSES: 1 of 2\nFOLLOWUP_OPEN: yes — risk")
        story = stats.collect(stats.find_session(self.repo, "S1"))[1]
        self.assertEqual((story["kind"], story["story"], story["epic"], story["level"]),
                         ("task", "issue-12", None, "normal"))
        self.assertEqual((story["commit"], story["followup_open"]), (None, True))

    def test_task_check_prompt_maps_to_the_task(self):
        prompt = "Check the story by the instructions.\n\nStory: issue-12 — Fix login\nCheck: adbm"
        self.assertEqual(stats.task_id(prompt), "issue-12")
        self.assertIsNone(stats.task_id("Story: 1.2 — Login"))

    def test_record_twice_does_not_duplicate(self):
        for _ in range(2):
            stats.save(self.repo, stats.collect(stats.find_session(self.repo, "S1")))
        self.assertEqual(len(stats.load(self.repo)), 2)


    def test_backfill_keeps_recorded_sessions(self):
        stats.save(self.repo, stats.collect(stats.find_session(self.repo, "S1")))
        rows = stats.load(self.repo)
        rows[0]["level"] = "recorded-earlier"
        stats.save(self.repo, rows)
        with mock.patch("sys.stdout", io.StringIO()):
            code = stats.main(["backfill", "--repo", self.repo])
        self.assertEqual(code, 2)
        self.assertIn("recorded-earlier", [r.get("level") for r in stats.load(self.repo)])

    def test_followup_open_compares_the_first_word(self):
        self.rewrite_run("Story: 3.2 — X\nRun level: deep",
                         "STATUS: done\nCOMMIT: none\nFILES: 1\nPASSES: 1 of 2\nFOLLOWUP_OPEN: not verified — risk")
        story = stats.collect(stats.find_session(self.repo, "S1"))[1]
        self.assertTrue(story["followup_open"])

if __name__ == "__main__":
    unittest.main()
