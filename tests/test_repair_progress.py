"""Regressions for spec-budget exhaustion, test-oracle progress and root visibility."""
import copy
import json
from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import native_repair as repair
import native_repair_progress as progress
import native_session as native
import native_tasks as tasks
import native_verification as verification
from native_progress import snapshot
from repair_policy import failed_tests, complete_failure_ids
import test_bounded_checkpoints as fixtures


class ProgressComparisonTest(unittest.TestCase):
    def receipt(self, backend, browser):
        def item(status, ids):
            return {'transport_code': 2 if status == 'not-run' else 0,
                    'result': {'verdict': status,
                'reason': 'depends on an earlier failed command' if status == 'not-run' else None,
                'failure_ids': ids, 'failure_ids_complete': ids is not None}}
        return {'commands': [{'name': 'backend'}, {'name': 'browser'}],
                'results': {'backend': item(*backend), 'browser': item(*browser)}}

    def test_newly_reached_browser_failure_does_not_erase_backend_progress(self):
        before = self.receipt(('problem', ['auth']), ('not-run', None))
        after = self.receipt(('pass', []), ('problem', ['selector']))
        self.assertTrue(progress.advanced(before, after))
        self.assertFalse(progress.advanced(after, after))
        self.assertFalse(progress.advanced(after, self.receipt(('problem', ['auth']), ('pass', []))))

    def test_real_execute_dependency_receipts_progress_without_granting_acceptance(self):
        fixture = fixtures.test_native_verification.StagedVerificationTest()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        commands = [{'name': name, 'command': name, 'timeout': 2} for name in ('backend', 'browser')]
        states = {'backend': ['a', 'b'], 'browser': ['selector']}
        def run(repo, command, timeout, **kwargs):
            key = verification.testrun.key_of(repo, command, cache_context=kwargs['cache_context'])
            return {'verdict': 'problem' if states[command] else 'pass',
                'code': 1 if states[command] else 0, 'key': key, 'source_key': key,
                'tree_changed': False, 'failure_ids': states[command][:], 'failure_ids_complete': True}, 0
        fixture.mock_run.side_effect = run
        first = verification.execute(fixture.root, commands, collect_independent=True)
        self.assertEqual(first['results']['browser']['transport_code'], 2)
        states['backend'] = ['b']
        second = verification.execute(fixture.root, commands, collect_independent=True)
        self.assertTrue(progress.advanced(first, second))
        states['backend'] = []
        third = verification.execute(fixture.root, commands, collect_independent=True)
        self.assertTrue(progress.advanced(second, third))
        self.assertEqual(third['verdict'], 'problem')
        second['results']['browser']['result']['reason'] = 'execution, environment or preparation failed'
        self.assertFalse(progress.advanced(first, second))

    def test_unknown_partial_environment_and_weaker_plans_do_not_prove_progress(self):
        before = self.receipt(('problem', ['a', 'b']), ('pass', []))
        after = self.receipt(('problem', ['b']), ('pass', []))
        self.assertTrue(progress.advanced(before, after))
        for mutator in (
            lambda r: r['results']['backend']['result'].update(failure_ids_complete=False),
            lambda r: r['results']['backend']['result'].update(failure_ids=['new']),
            lambda r: r['results']['browser'].update(transport_code=1),
            lambda r: r['results']['browser']['result'].update(code=127),
            lambda r: r['results'].pop('browser'),
            lambda r: r['commands'].pop(),
        ):
            changed = copy.deepcopy(after); mutator(changed)
            self.assertFalse(progress.advanced(before, changed))

    def test_playwright_ids_survive_line_changes_but_require_complete_summary(self):
        log = '\x1b[31m  1) [chromium] › e2e/ads.spec.ts:1087:5 › товары без рекламы ───\x1b[0m\n  1 failed\n  38 passed (28.1s)\n'
        ids = failed_tests({'tail': log}, complete=True)
        self.assertEqual(ids, {'[chromium] › e2e/ads.spec.ts › товары без рекламы'})
        self.assertEqual(ids, failed_tests({'tail': log.replace('1087:5', '1092:7')}, complete=True))
        self.assertTrue(complete_failure_ids(log, ids))
        self.assertFalse(complete_failure_ids(log.replace('1 failed', '2 failed'), ids))
        self.assertFalse(complete_failure_ids(log.replace('  1 failed\n', ''), ids))
        self.assertEqual(failed_tests({'tail': log, 'tail_truncated': True}), set())


class RepairBudgetTest(unittest.TestCase):
    setUp = fixtures.LocalRepairTest.setUp
    ref = fixtures.LocalRepairTest.ref
    start = fixtures.LocalRepairTest.start
    finish = fixtures.LocalRepairTest.finish
    check = fixtures.LocalRepairTest.check

    def admit_spec(self):
        # One earlier legitimate spec correction already consumed one of two slots.
        data = native.status(self.session)
        data['stories']['1-1']['repair_counts']['spec'] = 1
        native.atomic_json(Path(self.session), data)
        p = self.start('triager', 'triage')
        decision = {'story': '1-1', 'tree': native.code_tree(self.root), 'batch_id': 'repair-1',
            'finding_ids': ['snapshot'], 'failure_ids': ['auth'],
            'scope': ['code.py', 'test_code.py'], 'requirements': [self.requirement],
            'reports': [self.report], 'kind': 'spec', 'reason': 'Correct generated technical plan', 'plan': self.plan}
        ref = self.ref('decision.json', json.dumps(decision)); self.finish(p, [ref['path']])
        native.record(self.session, {'event': 'repair-batch', 'story': '1-1', 'task': p, 'decision': ref})
        return decision

    def test_exhausted_spec_still_allows_fixture_repair_with_test_budget_and_oracle_review(self):
        decision = self.admit_spec()
        p = self.start('implementer', 'implementation')
        self.verdict = 'problem'; self.check(p); self.finish(p, [self.report['path']])
        q = self.start('implementer', 'implementation')
        (self.root / 'test_code.py').write_text('def test_code(): assert 1 == 1\n')
        self.verdict = 'pass'; self.check(q); self.finish(q, [self.report['path']])
        row = native.status(self.session)['stories']['1-1']; batch = row['repair_batches']['repair-1']
        self.assertEqual(row['repair_counts'], {'spec': 2, 'review': 0, 'tests': 1})
        self.assertEqual(batch['no_progress'], 2)  # local test edits alone prove nothing
        self.assertNotIn('development_check', row)
        triager = self.start('triager', 'triage')
        decision.update(tree=native.code_tree(self.root), test_review=[{
            'artifact': {'path': str(self.root / 'test_code.py'), 'sha256': tasks.file_hash(self.root / 'test_code.py')},
            'requirement': self.requirement, 'reason': 'Assertion retains original requirement'}])
        ref = self.ref('amend.json', json.dumps(decision)); self.finish(triager, [ref['path']])
        native.record(self.session, {'event': 'repair-amend', 'story': '1-1', 'task': triager, 'decision': ref})
        row = native.status(self.session)['stories']['1-1']; batch = row['repair_batches']['repair-1']
        self.assertEqual(batch['no_progress'], 0)
        self.assertEqual(batch['attempts'], 2)
        self.assertEqual(batch['finding_ids'], ['snapshot'])
        self.assertEqual(batch['state'], 'open')
        self.assertNotIn('development_check', row)
        # Replayed progress cannot clear a later no-progress counter.
        batch['no_progress'] = 1; repair.credit_progress(row, batch)
        self.assertEqual(batch['no_progress'], 1)
        with self.assertRaisesRegex(ValueError, 'closure'):
            native.complete(native.status(self.session), '1-1', row, self.root)
        # Final acceptance still requires a fresh independent verifier AND closure.
        verifier = self.start('verifier', 'checks')
        verification.development(self.session, '1-1', self.plan, task=verifier)
        self.finish(verifier, [self.report['path']])
        self.assertEqual(native.status(self.session)['stories']['1-1']['development_check']['verdict'], 'pass')

    def test_four_progressing_attempts_use_tests_budget_not_fixed_three_cap(self):
        self.admit_spec(); original = self.fixture.mock_run.side_effect
        remaining = [5]
        def run(*args, **kwargs):
            result, code = original(*args, **kwargs)
            result.update(failure_ids=[str(i) for i in range(remaining[0])], failure_ids_complete=True)
            return result, code
        self.fixture.mock_run.side_effect = run; self.verdict = 'problem'
        for count in (5, 4, 3, 2):
            remaining[0] = count
            p = self.start('implementer', 'implementation')
            (self.root / 'code.py').write_text(f'value = {count}\n')
            self.check(p); self.finish(p, [self.report['path']])
        row = native.status(self.session)['stories']['1-1']
        self.assertEqual(row['repair_counts'], {'spec': 2, 'review': 0, 'tests': 3})
        self.assertEqual(row['repair_batches']['repair-1']['attempts'], 4)
        self.assertEqual(row['repair_batches']['repair-1']['no_progress'], 0)
        data = native.status(self.session); data['repair_limits']['tests'] = 3
        native.atomic_json(Path(self.session), data)
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            self.start('implementer', 'implementation')

    def test_unreviewed_green_tests_cannot_reset_no_progress(self):
        self.admit_spec()
        for n in range(3):
            p = self.start('implementer', 'implementation')
            (self.root / 'test_code.py').write_text(f'def test_code(): assert {n+1}\n')
            self.check(p); self.finish(p, [self.report['path']])
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            self.start('implementer', 'implementation')


class VisibleProgressTest(unittest.TestCase):
    def test_wall_clock_story_finish_parallel_tasks_and_blocker(self):
        data = {'created': '2026-01-01T00:00:00+00:00', 'status': 'running',
                'stories': {'1-1': {'status': 'completed'}, '1-2': {'status': 'running'}},
                'tasks': {'a': {'story': '1-2', 'role': 'verifier', 'checkpoint': 'checks', 'status': 'running'},
                          'b': {'story': '1-2', 'role': 'triager', 'checkpoint': 'triage', 'status': 'completed',
                                'result_state': 'blocked', 'blocker': 'tests exhausted', 'next': 'decision'}},
                'events': [
                    {'story': '1-1', 'event': 'bind', 'at': '2026-01-01T00:10:00+00:00'},
                    {'story': '1-1', 'event': 'finalize', 'at': '2026-01-01T01:10:00+00:00'},
                    {'story': '1-2', 'event': 'bind', 'at': '2026-01-01T01:10:00+00:00'},
                    {'story': '1-2', 'event': 'task-result', 'task_id': 'b', 'at': '2026-01-01T01:25:00+00:00'},
                    {'story': '1-2', 'event': 'task-start', 'task_id': 'a', 'at': '2026-01-01T01:30:00+00:00'}]}
        now = datetime(2026, 1, 1, 2, tzinfo=timezone.utc)
        self.assertEqual(snapshot(data, now=now)['elapsed_seconds'], 7200)
        self.assertEqual(snapshot(data, '1-1', now)['elapsed_seconds'], 3600)
        active = snapshot(data, '1-2', now)
        self.assertEqual(active['elapsed_seconds'], 3000)
        self.assertEqual(active['active_tasks'][0]['elapsed_seconds'], 1800)
        self.assertEqual(active['last_result']['blocker'], 'tests exhausted')
        data['status'] = 'cancelled'
        self.assertEqual(snapshot(data, now=now)['elapsed_seconds'], 5400)
        data['created'] = 'unknown'
        self.assertIsNone(snapshot(data, now=now)['elapsed_seconds'])


if __name__ == '__main__':
    unittest.main()
