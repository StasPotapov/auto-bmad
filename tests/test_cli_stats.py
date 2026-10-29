import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_adapters
import agent_runtime
import cli_stats
import stats


class CliStatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.common = self.root / ".git"
        self.private = self.common / "auto-bmad-sessions"

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def session(self, sid="a" * 32, story="1-1", queue=None):
        root = self.private / sid
        self.put(root / "session.json", {"repo": str(self.root), "story": story, "status": "completed", "queue_id": queue})
        self.put(root / "result.json", {"story_completed": True, "execution_status": "completed"})
        self.put(root / "manifest.json", {"level": "normal", "roles": {
            "story-runner": {"adapter": "codex", "model": "test-main"},
            "implementer": {"adapter": "codex", "model": "test-dev"}}})
        return root

    def process(self, folder, usage=None, state="completed", raw=None, **metadata):
        metrics = {"turns": [usage] if usage is not None else [], "tools": {"command_execution": 1}, "unfinished_turn": False}
        data = {"execution_status": state, "seconds": 2, "started": "2026-10-30T00:00:00+00:00",
                "ended": "2026-10-30T00:00:02+00:00", "call": metadata}
        if raw is None:
            data["metrics"] = metrics
        self.put(folder / "status.json", data)
        if raw is not None:
            (folder / "stdout.jsonl").write_text("\n".join(json.dumps(v) for v in raw))

    def test_all_views_count_calls_once_and_cache_is_a_subset(self):
        root = self.session()
        self.process(root / "controller-1", {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 7})
        leaf = root / "attempts" / ("f" * 32)
        self.put(leaf / "request.json", {"role": "implementer", "prompt": "SECRET PROMPT", "code": "SECRET SOURCE CODE"})
        self.process(leaf / "process", {"input_tokens": 40, "cached_input_tokens": 10, "output_tokens": 3})
        for _ in range(2):
            self.assertEqual(cli_stats.record(str(self.root))["recorded"], 1)
        rows = stats.load(str(self.root))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        t = row["tokens"]["total"]
        self.assertEqual((t["input_exact"], t["in"], t["cache_read"], t["out_exact"], t["out_est"]), (140, 50, 90, 10, 0))
        self.assertEqual((t["calls"], t["usage_complete"]), (2, 2))
        self.assertEqual(set(row["tokens"]["by_model"]), {"test-main", "test-dev"})
        self.assertEqual(stats.total(row["tokens"]["by_role_model"]["implementer"]), row["tokens"]["by_role"]["implementer"])
        summary = stats.summarize(rows)
        self.assertEqual(summary["by_epic"]["1"]["tokens"], t)
        self.assertEqual(summary["by_role"]["implementer"]["out_exact"], 3)
        self.assertEqual(summary["tokens_out_avg"], 10)
        public = (self.root / stats.STATS).read_text()
        self.assertNotIn("SECRET PROMPT", public)
        self.assertNotIn(str(self.root), public)
        self.assertNotIn("SECRET SOURCE CODE", public)
        self.assertEqual(subprocess.run(["git", "-C", str(self.root), "status", "--porcelain"],
                                       capture_output=True, text=True).stdout, "")
        text = stats.table(rows, summary, calls=True)
        self.assertIn("input=40 cached=10 output=3 complete", text)
        self.assertIn("Output by role: story-runner 7 (test-main), implementer 3 (test-dev)", text)

    def test_missing_usage_is_distinct_from_reported_zero(self):
        root = self.session()
        self.process(root / "controller-1")
        row = cli_stats.collect_session(root / "session.json")[0]
        call = row["calls"][0]
        self.assertEqual(call["usage_status"], "unavailable")
        self.assertIsNone(call["usage"]["output_tokens"])
        self.assertIn("output=— unavailable", stats.table([row], stats.summarize([row]), calls=True))
        self.process(root / "controller-1", {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0})
        row = cli_stats.collect_session(root / "session.json")[0]
        self.assertEqual(row["calls"][0]["usage_status"], "complete")
        self.assertEqual(row["calls"][0]["usage"]["output_tokens"], 0)

    def test_partial_invalid_and_negative_values_are_never_fabricated(self):
        for raw in ({"output_tokens": 12}, {"input_tokens": True, "output_tokens": 3},
                    {"input_tokens": 5, "cached_input_tokens": 10, "output_tokens": 2},
                    {"input_tokens": -2, "output_tokens": 2}):
            usage, acc, status = cli_stats.counters({"turns": [raw]})
            self.assertEqual(status, "partial")
            self.assertGreaterEqual(acc["in"], 0)
            self.assertIsNone(usage["uncached_input_tokens"])

    def test_multiple_identical_turns_sum_but_duplicate_completion_does_not(self):
        parser = agent_adapters.CodexResult()
        event = {"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 70, "output_tokens": 5}}
        for _ in range(2):
            parser.consume({"type": "turn.started"})
            parser.consume(event)
            parser.consume(event)
        usage, acc, status = cli_stats.counters(parser.snapshot())
        self.assertEqual((usage["input_tokens"], usage["output_tokens"], acc["in"], status), (200, 10, 60, "complete"))
        parser.consume({"type": "turn.started"})
        self.assertEqual(cli_stats.counters(parser.snapshot())[2], "partial")

    def test_tool_started_and_completed_are_not_double_counted(self):
        parser = agent_adapters.CodexResult()
        for kind in ("item.started", "item.completed", "item.completed"):
            parser.consume({"type": kind, "item": {"id": "x", "type": "command_execution", "command": "SECRET"}})
        self.assertEqual(parser.snapshot()["tools"], {"command_execution": 1})
        self.assertNotIn("SECRET", json.dumps(parser.snapshot()))

    def test_old_stream_backfill_ignores_other_usage_events(self):
        root = self.session()
        self.process(root / "controller-1", raw=[
            {"type": "turn.started"},
            {"type": "event_msg", "usage": {"input_tokens": 99999}},
            {"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 3, "output_tokens": 4}}])
        row = cli_stats.collect_session(root / "session.json")[0]
        self.assertEqual(row["tokens"]["total"]["input_exact"], 10)

    def test_interrupted_call_keeps_reported_subtotal_and_unknown_tail(self):
        root = self.session()
        self.process(root / "controller-1", state="running", raw=[
            {"type": "turn.started"},
            {"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 3, "output_tokens": 4}},
            {"type": "turn.started"}])
        (root / "result.json").unlink()
        self.put(root / "session.json", {"repo": str(self.root), "story": "1-1", "status": "running"})
        row = cli_stats.collect_session(root / "session.json")[0]
        self.assertEqual(row["execution_status"], "interrupted")
        self.assertEqual(row["calls"][0]["usage_status"], "partial")
        self.assertEqual(row["tokens"]["total"]["out_exact"], 4)

    def test_stale_collector_cannot_overwrite_newer_result(self):
        root = self.session()
        self.process(root / "controller-1", {"input_tokens": 10, "cached_input_tokens": 3, "output_tokens": 4})
        old = cli_stats.collect_session(root / "session.json")
        newer = copy.deepcopy(old)
        newer[0]["revision"] += 100
        newer[0]["status"] = "completed-newer"
        stats.save(str(self.root), newer)
        stats.save(str(self.root), old)
        self.assertEqual(stats.load(str(self.root))[0]["status"], "completed-newer")

    def test_queue_record_and_last_filter_keep_whole_epic_without_duplicates(self):
        queue = self.private / ("c" * 32)
        self.put(queue / "session.json", {"kind": "queue", "repo": str(self.root), "stories": []})
        for sid, story in (("a" * 32, "2-1"), ("b" * 32, "2-2")):
            root = self.session(sid, story, queue=queue.name)
            self.process(root / "controller-1", {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 3})
        self.assertEqual(cli_stats.record(str(self.root), str(queue / "session.json"))["recorded"], 2)
        proc = subprocess.run([sys.executable, stats.__file__, "show", "--repo", str(self.root),
                               "--epic", "2", "--last", "1", "--json"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(len(data["rows"]), 2)
        self.assertEqual(data["summary"]["by_epic"]["2"]["tokens"]["out_exact"], 6)

    def test_standalone_role_is_not_claimed_to_be_a_completed_story(self):
        attempt = self.root / ".auto-bmad/agents" / ("d" * 32)
        self.put(attempt / "request.json", {"role": "implementer", "task_id": "3-1"})
        self.process(attempt / "process", {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 3},
                     role="implementer", model_requested="test-dev", adapter="codex")
        row = cli_stats.collect_attempt(attempt)[0]
        self.assertEqual(row["kind"], "task")
        self.assertFalse(row["story_completed"])
        self.assertNotEqual(row["status"], "done")
        self.assertEqual(cli_stats.publish_attempt(self.root, attempt)["recorded"], 1)
        self.assertEqual(cli_stats.record(str(self.root))["recorded"], 1)
        self.assertEqual(len(stats.load(str(self.root))), 1)

    def test_summary_keeps_legacy_estimates_separate_from_cli_exact_output(self):
        root = self.session()
        self.process(root / "controller-1", {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 3})
        rows = cli_stats.collect_session(root / "session.json")
        legacy = {"id": "old", "session": "old", "kind": "story", "tokens": {
            "total": dict.fromkeys(stats.ZERO, 0) | {"out_est": 5},
            "by_model": {"opus": dict.fromkeys(stats.ZERO, 0) | {"out_est": 5}}}}
        stats.save(str(self.root), [legacy])
        cli_stats.record(str(self.root))
        self.assertEqual(len(stats.load(str(self.root))), 2)
        summary = stats.summarize([legacy, *rows])
        self.assertEqual(summary["tokens_out_avg"], 4)
        self.assertEqual((summary["tokens"]["out_est"], summary["tokens"]["out_exact"]), (5, 3))

    def test_statistics_directory_cannot_escape_and_failure_does_not_raise(self):
        root = self.session()
        self.process(root / "controller-1", {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1})
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.root / ".auto-bmad").symlink_to(outside, target_is_directory=True)
        self.assertIn("error", cli_stats.publish(self.root, root / "session.json"))
        self.assertEqual(list(outside.iterdir()), [])
        proc = subprocess.run([sys.executable, stats.__file__, "record", "--repo", str(self.root),
                               "--session", str(root / "session.json")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error", json.loads(proc.stdout))

    def test_runtime_persists_usage_snapshot_on_failed_protocol(self):
        folder = Path(self.tmp.name) / "process"
        parser = agent_adapters.CodexResult()
        event = json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 3}})
        result = agent_runtime.execute([sys.executable, "-c", "print(" + repr(event) + ")"],
                    cwd=str(self.root), env=dict(os.environ), stdin="", directory=folder, timeout=5,
                    consume=parser.consume, finish=parser.finish, snapshot=parser.snapshot,
                    metadata={"role": "implementer", "model_requested": "test-dev"})
        self.assertEqual(result["execution_status"], "failed")
        state = cli_stats.read(folder / "status.json")
        self.assertEqual(state["metrics"]["turns"][0]["output_tokens"], 3)
        self.assertEqual(state["call"]["role"], "implementer")

    def test_review_snapshot_survives_deleted_worktree_and_spec(self):
        root = self.session()
        self.process(root / "controller-1", {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1})
        spec = Path(self.tmp.name) / "removed-worktree" / "spec.md"
        spec.parent.mkdir()
        spec.write_text("## Review Triage Log\n\n### Review pass\n- verdicts: 0 findings\n")
        self.put(root / "result.json", {"story_completed": True, "execution_status": "completed", "spec": str(spec)})
        self.assertEqual(cli_stats.record(str(self.root))["recorded"], 1)
        original = stats.load(str(self.root))[0]["review"]
        self.assertIsNotNone(original)
        spec.unlink()
        spec.parent.rmdir()
        cli_stats.record(str(self.root))
        self.assertEqual(stats.load(str(self.root))[0]["review"], original)

    def test_running_snapshot_mtime_is_not_an_end_timestamp(self):
        root = self.session()
        folder = root / "controller-1"
        self.put(folder / "status.json", {"execution_status": "running", "started": "2026-10-30T00:00:00Z"})
        data = cli_stats.call(folder, "interrupted", {"role": "story-runner"})
        self.assertIsNone(data["ended"])
        self.assertIsNone(data["seconds"])

    def test_old_interrupted_stream_keeps_tools_before_first_usage(self):
        root = self.session()
        folder = root / "controller-1"
        self.process(folder, state="running", raw=[{"type": "turn.started"},
                     {"type": "item.completed", "item": {"id": "cmd", "type": "command_execution"}}])
        data = cli_stats.call(folder, "interrupted", {"role": "story-runner"})
        self.assertEqual(data["tools"], {"command_execution": 1})
        self.assertEqual(data["usage_status"], "unavailable")

    def test_empty_show_reports_a_collection_error_instead_of_no_statistics(self):
        stdout = io.StringIO()
        with patch.object(cli_stats, "publish", return_value={"recorded": 0, "error": "cannot read usage"}), \
                patch.object(stats, "load", return_value=[]), contextlib.redirect_stdout(stdout):
            code = stats.main(["show", "--repo", str(self.root), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["error"], "cannot read usage")

    def test_lock_symlink_cannot_truncate_a_project_file(self):
        root = self.session()
        self.process(root / "controller-1", {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1})
        target = self.root / "app.py"
        target.write_text("keep this code\n")
        lock = self.root / (stats.STATS + ".lock")
        lock.parent.mkdir(parents=True)
        lock.symlink_to(target)
        self.assertIn("error", cli_stats.publish(self.root, root / "session.json"))
        self.assertEqual(target.read_text(), "keep this code\n")

    def test_freeform_task_identifier_is_not_exported_as_a_private_path(self):
        attempt = self.root / ".auto-bmad/agents" / ("d" * 32)
        self.put(attempt / "request.json", {"role": "implementer", "task_id": "/Users/private/secret-project"})
        self.process(attempt / "process", {"output_tokens": 3}, role="implementer", model_requested="test-dev")
        self.assertEqual(cli_stats.publish_attempt(self.root, attempt)["recorded"], 1)
        public = (self.root / stats.STATS).read_text()
        self.assertNotIn("/Users/private", public)
        self.assertTrue(stats.load(str(self.root))[0]["story"].startswith("task-"))
