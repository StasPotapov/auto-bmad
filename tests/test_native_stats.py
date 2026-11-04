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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import native_stats
import stats

ROOT = '11111111-1111-1111-1111-111111111111'
TURN = '22222222-2222-2222-2222-222222222222'
CHILD = '33333333-3333-3333-3333-333333333333'
OTHER = '44444444-4444-4444-4444-444444444444'


class NativeStatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'; self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        self.home = Path(self.tmp.name) / 'codex'; (self.home / 'sessions').mkdir(parents=True)
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(self.home)})
        self.env.start(); self.addCleanup(self.env.stop)
        self.session = self.repo / '.git/auto-bmad-native/fixture/session.json'
        self.session.parent.mkdir(parents=True)
        self.data = {'transport': 'native-subagents', 'repo': str(self.repo), 'status': 'completed',
            'created': '2026-01-01T00:00:00Z', 'plan': {'epic': 1, 'level': 'normal'},
            'roles': {'implementer': {'model': 'fixture-model', 'effort': 'high'}},
            'events': [{'event': 'bind', 'story': s, 'at': '2026-01-01T00:00:00Z'} for s in ['1-1', '1-2']],
            'stories': {s: {'status': 'completed', 'completed': '2026-01-01T01:00:00Z', 'agents': {}}
                        for s in ['1-1', '1-2']}}
        self.data['stories']['1-1']['agents']['/root/dev'] = {'role': 'implementer', 'status': 'completed'}
        self.session.write_text(json.dumps(self.data))
        self.rollout(ROOT, [{'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': TURN}}])
        native_stats.bind(self.repo, str(self.session), ROOT, TURN)

    def usage(self, thread, response, input=100, cached=80, output=7, turn=TURN, **extra):
        return {'type': 'token_usage_record', 'timestamp': '2026-01-01T00:01:00Z', 'payload': {
            'thread_id': thread, 'session_id': ROOT, 'root_turn_id': turn, 'turn_id': TURN if thread == ROOT else thread,
            'response_id': response, 'usage': {'input_tokens': input, 'cached_input_tokens': cached,
            'output_tokens': output, 'reasoning_output_tokens': output, 'total_tokens': input + output},
            'thread_token_usage': {'input_tokens': 99999999}, **extra}}

    def rollout(self, thread, events, parent=None, agent_path=None, suffix=''):
        meta = {'id': thread, 'cwd': str(self.repo), 'base_instructions': 'PRIVATE PROMPT',
                'source': {'subagent': {'thread_spawn': {'parent_thread_id': parent, 'agent_path': agent_path}}} if parent else 'vscode'}
        path = self.home / 'sessions' / f'rollout-2026-01-01-{thread}{suffix}.jsonl'
        rows = [{'type': 'session_meta', 'payload': meta}, *events,
                {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': TURN if thread == ROOT else thread}}]
        path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        return path

    def test_exact_response_dedup_compaction_root_and_children_and_wrong_turn(self):
        r = self.usage(ROOT, 'root-r')
        self.rollout(ROOT, [r, r, {'type': 'compacted', 'payload': {'latest_token_usage_record': r}},
                            {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': 99999999}}}}])
        c = self.usage(CHILD, 'child-r', input=40, cached=10, output=3)
        self.rollout(CHILD, [c, self.usage(CHILD, 'other-turn', turn=OTHER)], ROOT, '/root/dev')
        self.rollout(CHILD, [c], ROOT, '/root/dev', suffix='-copy')
        self.rollout(OTHER, [self.usage(OTHER, 'unrelated')])
        for _ in range(2): self.assertEqual(native_stats.publish(self.repo)['recorded'], 3)
        rows = stats.load(str(self.repo)); summary = stats.summarize(rows)
        self.assertEqual(summary['tokens']['input_exact'], 40)
        self.assertEqual(summary['tokens_with_orchestrator']['input_exact'], 140)
        self.assertEqual(summary['tokens_with_orchestrator']['out_exact'], 10)
        self.assertEqual(summary['tokens_with_orchestrator']['cache_read'], 90)
        self.assertEqual(summary['minutes_total'], 120)
        self.assertEqual(summary['run_minutes_total'], 60)
        body = (self.repo / stats.STATS).read_text()
        self.assertNotIn('PRIVATE PROMPT', body); self.assertNotIn(str(self.home), body)
        self.assertIn('Including main chat, measured input=140', stats.table(rows, summary, calls=True))

    def test_missing_usage_and_incomplete_records_are_visible_not_zero(self):
        rows = native_stats.collect_session(self.session)
        summary = stats.summarize(rows)
        self.assertEqual(summary['tokens']['usage_unavailable'], 1)
        self.assertIn('output=— unavailable', stats.table(rows, summary, calls=True))
        text = stats.table(rows, summary)
        self.assertIn('orchestrator, total output: —', text)
        self.assertIn('measured input=—, output=—, cached=—', text)
        self.assertIn('implementer —', text)
        self.assertIn('fixture-model —', text)
        self.rollout(ROOT, [self.usage(ROOT, 'r', cached=None)])
        row = native_stats.collect_session(self.session)[0]
        self.assertEqual(row['calls'][0]['usage_status'], 'partial')
        self.assertEqual(row['calls'][0]['usage']['input_tokens'], 100)

    def test_failed_unregistered_descendant_is_accounted_without_inventing_model(self):
        self.rollout(ROOT, [self.usage(ROOT, 'r')])
        self.rollout(CHILD, [self.usage(CHILD, 'c')], ROOT, '/root/dev')
        self.rollout(OTHER, [self.usage(OTHER, 'eye')], CHILD, '/root/dev/eyes')
        rows = native_stats.collect_session(self.session)
        story = next(r for r in rows if r['story'] == '1-1')
        self.assertEqual(story['tokens']['total']['input_exact'], 200)
        self.assertEqual(story['tokens']['by_role']['unattributed']['input_exact'], 100)
        self.assertEqual(next(c for c in story['calls'] if c['role'] == 'unattributed')['model_requested'], '?')

    def test_bind_is_idempotent_and_cannot_assign_same_turn_to_other_run(self):
        native_stats.bind(self.repo, str(self.session), ROOT, TURN)
        self.assertEqual(len(json.loads((self.session.parent / 'accounting.json').read_text())['codex']), 1)
        other = self.session.parent.parent / 'other/session.json'; other.parent.mkdir()
        other.write_text(self.session.read_text())
        with self.assertRaisesRegex(ValueError, 'already assigned'):
            native_stats.bind(self.repo, str(other), ROOT, TURN)
        with self.assertRaises(ValueError): native_stats.bind(self.repo, str(self.session), ROOT, None)
        with self.assertRaisesRegex(ValueError, 'not present'):
            native_stats.bind(self.repo, str(self.session), ROOT, OTHER)

    def test_cli_record_and_show_refresh_native_session(self):
        self.rollout(ROOT, [self.usage(ROOT, 'r')])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = stats.main(['record', '--repo', str(self.repo), '--session', str(self.session),
                               '--codex-thread', ROOT, '--codex-turn', TURN])
        self.assertEqual(code, 0, output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(stats.main(['show', '--repo', str(self.repo), '--last', '1', '--json']), 0)

    def test_unknown_subagent_metadata_does_not_break_accounting(self):
        self.rollout(ROOT, [self.usage(ROOT, 'r')])
        path = self.home / 'sessions/rollout-old.jsonl'
        path.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': OTHER,
                         'source': {'subagent': 'review'}}}) + '\n')
        rows = native_stats.collect_session(self.session)
        self.assertEqual(rows[0]['tokens']['total']['input_exact'], 100)

    def test_resumed_agent_without_new_usage_is_partial(self):
        self.rollout(ROOT, [self.usage(ROOT, 'r')])
        self.rollout(CHILD, [self.usage(CHILD, 'r'),
            {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': OTHER, 'root_turn_id': TURN}}],
            ROOT, '/root/dev')
        rows = native_stats.collect_session(self.session)
        self.assertEqual(rows[1]['calls'][0]['usage_status'], 'partial')
        self.assertEqual(rows[1]['calls'][0]['usage']['input_tokens'], 100)

    def test_cancel_time_includes_work_after_last_completed_story(self):
        self.data['status'] = 'cancelled'
        self.data['stories']['1-2'].pop('completed')
        self.data['stories']['1-2']['status'] = 'running'
        self.data['events'].append({'event': 'cancel', 'at': '2026-01-01T02:00:00Z'})
        self.session.write_text(json.dumps(self.data))
        rows = native_stats.collect_session(self.session)
        self.assertEqual(stats.summarize(rows)['run_minutes_total'], 120)


if __name__ == '__main__': unittest.main()
