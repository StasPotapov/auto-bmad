"""Review and finish evidence cannot be lost between a receipt and root dispatch."""
import copy
import json
from pathlib import Path
import unittest

import test_bounded_checkpoints
import native_session as native
import native_tasks as tasks


class ReceiptCompletionTest(unittest.TestCase):
    def setUp(self):
        test_bounded_checkpoints.BoundedTaskTest.setUp(self)
        (self.root / '.auto-bmad/tests').mkdir(parents=True, exist_ok=True)
    ref = test_bounded_checkpoints.BoundedTaskTest.ref
    prepare = test_bounded_checkpoints.BoundedTaskTest.prepare

    def reviewer(self):
        p = Path(self.prepare('blind-hunter', {'diff': self.ref('code.diff')})['task_file'])
        tasks.start(p, 'reviewer')
        report = self.ref('report.md', 'F1: incorrect value')
        decision = {'state': 'ready', 'next': 'triage', 'actions': [], 'blocker': None,
                    'artifact_paths': [report['path']],
                    'review': {'verdict': 'problem', 'report': report['path']}}
        return p, decision

    def test_review_registration_is_atomic_and_preserves_original_for_repairs(self):
        p, decision = self.reviewer()
        before = Path(self.session).read_bytes()
        tasks.write_receipt(p, decision)
        self.assertEqual(Path(self.session).read_bytes(), before)  # preflight is read-only
        with self.assertRaisesRegex(ValueError, 'terminal completion'):
            tasks.result(p, 'reviewer')
        tasks.result(p, 'reviewer', True)
        data = native.status(self.session)
        saved = copy.deepcopy(data['stories']['1-1']['reviews']['blind-hunter'])
        self.assertEqual(saved['verdict'], 'problem')
        self.assertEqual(saved['agent_id'], 'reviewer')
        self.assertEqual(data['events'][-1]['event'], 'review')
        self.assertEqual(data['events'][-2]['event'], 'task-result')
        row = data['stories']['1-1']; row['reviews'].pop('other')
        native.begin_repair(data, row, self.root, {'kind': 'review', 'reason': 'Fix F1'})
        self.assertEqual(row['review_candidates']['blind-hunter'], saved)
        self.assertEqual(row['reviews'], {})

    def test_missing_verdict_unhashed_report_or_stale_tree_cannot_finish_review(self):
        p, decision = self.reviewer()
        for review in (None, {'verdict': 'pass', 'report': '/unissued.md'},
                       {'verdict': 'unknown', 'report': decision['review']['report']}):
            with self.subTest(review=review), self.assertRaises(ValueError):
                tasks.write_receipt(p, {**decision, 'review': review})
        (self.root / 'code.py').write_text('value = 5\n')
        with self.assertRaisesRegex(ValueError, 'tree changed'):
            tasks.write_receipt(p, decision)
        self.assertEqual(native.status(self.session)['tasks'][p.parent.name]['status'], 'running')

    def test_report_tampering_and_cancel_cannot_register_review(self):
        p, decision = self.reviewer(); tasks.write_receipt(p, decision)
        report = Path(decision['review']['report']); original = report.read_text()
        report.write_text('No findings')
        with self.assertRaisesRegex(ValueError, 'artifact missing or changed'):
            tasks.result(p, 'reviewer', True)
        report.write_text(original)
        tasks.stop(p, 'reviewer', 'stopped', 'Host observed cancellation', True)
        native.control(self.session, 'cancel')
        with self.assertRaises(ValueError):
            tasks.result(p, 'reviewer', True)
        self.assertNotIn('blind-hunter', native.status(self.session)['stories']['1-1']['reviews'])

    def test_review_targets_verified_integration_candidate_not_story_tree(self):
        git = self.fixture.fixture.git
        data = native.status(self.session)
        data['stories']['1-1']['commit'] = git('rev-parse', 'HEAD').stdout.strip()
        native.atomic_json(Path(self.session), data)
        candidate = self.root.parent / 'review-candidate'
        git('worktree', 'add', '-q', '-b', 'review-candidate', str(candidate), 'HEAD')
        (candidate / 'code.py').write_text('value = 9\n')
        native.git(str(candidate), 'add', 'code.py')
        native.git(str(candidate), 'commit', '-qm', 'integration change')
        candidate_tree = native.code_tree(candidate)
        self.assertNotEqual(candidate_tree, native.code_tree(self.root))
        inp = self.ref('candidate-input.json', json.dumps({'diff': self.ref('candidate.diff')}))
        p = Path(tasks.prepare(session=self.session, story='1-1', role='blind-hunter', checkpoint='review',
                               input_path=inp['path'], review_worktree=str(candidate))['task_file'])
        spec = json.loads(p.read_text())
        self.assertEqual(spec['story_state']['worktree'], str(candidate.resolve()))
        self.assertEqual(spec['review_tree'], candidate_tree)
        tasks.start(p, 'candidate-reviewer')
        report = self.ref('candidate-report.md', 'Reviewed the integration delta')
        decision = {'state': 'ready', 'next': 'triage', 'actions': [], 'blocker': None,
            'artifact_paths': [report['path']], 'review': {'verdict': 'pass', 'report': report['path']}}
        (candidate / 'code.py').write_text('value = 10\n')
        with self.assertRaisesRegex(ValueError, 'tree changed'):
            tasks.write_receipt(p, decision)
        (candidate / 'code.py').write_text('value = 9\n')
        tasks.write_receipt(p, decision)
        tasks.result(p, 'candidate-reviewer', True)
        saved = native.status(self.session)['stories']['1-1']['reviews']['blind-hunter']
        self.assertEqual(saved['tree'], candidate_tree)
        self.assertNotEqual(saved['tree'], native.code_tree(self.root))

    def batch_task(self):
        p = Path(tasks.prepare(session=self.session, story='1-1', role='story-runner',
                               checkpoint='finalization')['task_file'])
        tasks.start(p, 'finisher')
        batch = self.ref('finish-batch.json', json.dumps({'batch_id': 'finish-fixture',
            'events': [{'event': 'phase', 'story': '1-1', 'phase': 'finalization'}]}))
        decision = {'state': 'ready', 'next': 'integration', 'actions': [], 'blocker': None,
                    'artifact_paths': [batch['path']]}
        tasks.write_receipt(p, decision, record_batch=batch['path'])
        return p, batch

    def test_receipt_carries_batch_without_root_repeating_the_path(self):
        p, batch = self.batch_task()
        self.assertNotIn('finish-fixture', native.status(self.session).get('batches', {}))
        saved = json.loads(p.with_name('result.json').read_text())
        self.assertEqual(saved['acceptance_batch'], {**batch, 'path': str(Path(batch['path']).resolve())})
        result = tasks.result(p, 'finisher', True)
        self.assertTrue(result['batch_applied'])
        self.assertEqual(native.status(self.session)['stories']['1-1']['phase'], 'finalization')

    def test_batch_tampering_and_explicit_substitution_are_rejected(self):
        p, batch = self.batch_task()
        other = self.ref('other.json', Path(batch['path']).read_text())
        with self.assertRaisesRegex(ValueError, 'differs'):
            tasks.result(p, 'finisher', True, record_batch=other['path'])
        Path(batch['path']).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            tasks.result(p, 'finisher', True)
        self.assertEqual(native.status(self.session)['tasks'][p.parent.name]['status'], 'running')

    def test_failed_batch_keeps_honest_completion_without_partial_events(self):
        p, batch = self.batch_task()
        data = native.status(self.session)
        data['batches'] = {'finish-fixture': {'digest': 'conflicting digest'}}
        native.atomic_json(Path(self.session), data)
        result = tasks.result(p, 'finisher', True)
        self.assertTrue(result['receipt_accepted']); self.assertFalse(result['batch_applied'])
        self.assertEqual(result['state'], 'blocked')
        data = native.status(self.session)
        self.assertEqual(data['tasks'][p.parent.name]['status'], 'completed')
        self.assertNotEqual(data['stories']['1-1']['phase'], 'finalization')


class CompactFinishTest(unittest.TestCase):
    setUp = test_bounded_checkpoints.LocalRepairTest.setUp
    ref = test_bounded_checkpoints.LocalRepairTest.ref
    start = test_bounded_checkpoints.LocalRepairTest.start
    finish = test_bounded_checkpoints.LocalRepairTest.finish

    def test_three_finish_assignments_preserve_terminal_gates_and_finalize(self):
        import shutil
        import land, story_finish
        from unittest.mock import patch
        import native_verification as verification
        git = self.fixture.fixture.git
        (self.root / '.gitignore').write_text('.auto-bmad/\n')
        git('add', '.'); git('commit', '-qm', 'candidate base')
        baseline = git('rev-parse', 'HEAD').stdout.strip()
        other = self.root.parent / 'story-worktree'
        git('worktree', 'add', '-q', '-b', 'story-fixture', str(other), 'HEAD')
        shutil.copytree(self.root / '_bmad', other / '_bmad', dirs_exist_ok=True)
        (other / 'code.py').write_text('value = 2\n')
        spec = other / '_bmad-output/implementation-artifacts/spec-1-1-fixture.md'
        spec.parent.mkdir(parents=True)
        spec.write_text(f'---\nstatus: done\nbaseline_revision: {baseline}\n---\nDone fixture\n')
        (spec.parent / 'sprint-status.yaml').write_text('development_status:\n  epic-1: in-progress\n  1-1-fixture: review\n')
        native.git(str(other), 'add', '.'); native.git(str(other), 'commit', '-qm', 'story and tracking')
        finish_response = story_finish.finish({'epic': 1, 'stories': [{'story': '1-1', 'status': 'done',
            'spec': str(spec), 'commit': native.revision(other), 'questions': ''}]}, str(other))
        self.assertTrue(finish_response['ok'], finish_response)
        self.assertIn('1-1-fixture: done', (spec.parent / 'sprint-status.yaml').read_text())
        data = native.status(self.session); row = data['stories']['1-1']
        manifest = json.loads(Path(row['manifest']).read_text())
        manifest = json.loads(json.dumps(manifest).replace(str(self.root.resolve()), str(other.resolve()))
                              .replace(str(self.root), str(other)))
        manifest_path = self.root.parent / 'story-manifest.json'; native.atomic_json(manifest_path, manifest)
        row.update(worktree=str(other.resolve()), branch='refs/heads/story-fixture', baseline=baseline,
                   manifest=str(manifest_path), manifest_hash=native.digest(manifest), status='running')
        native.atomic_json(Path(self.session), data)
        # Real independent review and focused acceptance precede the finish sequence.
        inp = self.ref('review-input.json', json.dumps({'diff': self.ref('story.diff', 'value = 2')}))
        review = tasks.prepare(session=self.session, story='1-1', role='blind-hunter',
                               checkpoint='review', input_path=inp['path'])['task_file']
        tasks.start(review, 'blind')
        tasks.write_receipt(review, {'state': 'ready', 'next': 'triage', 'actions': [], 'blocker': None,
            'artifact_paths': [self.report['path']], 'review': {'verdict': 'pass', 'report': self.report['path']}})
        tasks.result(review, 'blind', True)
        verifier = self.start('verifier', 'checks')
        verification.development(self.session, '1-1', self.plan, task=verifier)
        self.finish(verifier, [self.report['path']])

        def save_batch(task, batch_id, events, artifacts=()):
            batch = self.ref(batch_id + '.json', json.dumps({'batch_id': batch_id, 'events': events}))
            task_spec = json.loads(Path(task).read_text())
            pending = native.status(self.session)['tasks'][task_spec['task_id']].get('pending_verification')
            paths = [batch['path'], *artifacts, *([pending['path']] if pending else [])]
            tasks.write_receipt(task, {'state': 'ready', 'next': 'integration', 'actions': [], 'blocker': None,
                                      'artifact_paths': paths}, record_batch=batch['path'])

        complete = {'event': 'complete', 'story': '1-1', 'spec': str(spec.resolve())}
        # Assignment 1: prepare and complete; live self-completion remains forbidden.
        first = self.start('story-runner', 'finalization')
        intact = native.status(self.session)
        broken = copy.deepcopy(intact); broken['stories']['1-1']['reviews'] = {}
        native.atomic_json(Path(self.session), broken)
        with self.assertRaisesRegex(ValueError, 'missing/current review'):
            save_batch(first, 'missing-review', [complete])
        native.atomic_json(Path(self.session), intact)
        save_batch(first, 'initial-complete', [complete])
        self.assertNotEqual(native.status(self.session)['stories']['1-1']['status'], 'verified')
        self.assertTrue(tasks.result(first, tasks.binding(first)['agent_id'], True)['batch_applied'])
        self.assertEqual(native.status(self.session)['stories']['1-1']['status'], 'verified')

        # Exercise repeat complete after a full repair: only accepted full evidence clears pending.
        data = native.status(self.session)
        data['stories']['1-1']['pending_test_repair'] = {'project-tests': {'result': {'verdict': 'problem'}}}
        native.atomic_json(Path(self.session), data)
        second = self.start('story-runner', 'integration')
        original_run = self.fixture.mock_run.side_effect
        contexts = []
        def running_once(*args, **kwargs):
            result, code = original_run(*args, **kwargs)
            contexts.append(kwargs['cache_context'])
            return ({**result, 'verdict': 'running'}, 3) if len(contexts) == 1 else (result, code)
        with patch.object(verification.testrun, 'run', side_effect=running_once):
            outcome, code = land.land(str(self.root), 'story-fixture', native_session=self.session,
                                      stories=['1-1'], native_task=second, check_only=True)
            self.assertEqual(code, 0, outcome); self.assertFalse(outcome['merged'])
            self.assertEqual(outcome['tests']['verdict'], 'running')
            candidate = outcome['tests']['worktree']
            resumed = verification.integration(self.session, ['1-1'], candidate, task=second)
        self.assertEqual(resumed['verdict'], 'pass')
        self.assertEqual(resumed['execution_id'], outcome['tests']['execution_id'])
        self.assertEqual(contexts[0], contexts[1])
        self.assertEqual(git('rev-parse', 'HEAD').stdout.strip(), baseline)
        save_batch(second, 'repeat-complete', [complete])
        self.assertNotIn('integration_gate', native.status(self.session))
        self.assertTrue(tasks.result(second, tasks.binding(second)['agent_id'], True)['batch_applied'])
        data = native.status(self.session)
        self.assertNotIn('pending_test_repair', data['stories']['1-1'])
        self.assertEqual(data['integration_gate']['verdict'], 'pass')
        count = len(self.calls)

        # Assignment 3: an accepted cached pass in check-only still cannot move main.
        third = self.start('story-runner', 'integration')
        outcome, code = land.land(str(self.root), 'story-fixture', native_session=self.session,
                                  stories=['1-1'], native_task=third, check_only=True)
        self.assertEqual(code, 0, outcome); self.assertFalse(outcome['merged'])
        self.assertEqual(git('rev-parse', 'HEAD').stdout.strip(), baseline)
        outcome, code = land.land(str(self.root), 'story-fixture', native_session=self.session,
                                  stories=['1-1'], native_task=third)
        self.assertEqual(code, 0, outcome); self.assertTrue(outcome['merged'])
        self.assertEqual(len(self.calls), count)
        finish = self.ref('finish.json', json.dumps(finish_response))
        final_event = {'event': 'finalize', 'story': '1-1', 'repo': str(self.root),
                       'finish_report': finish['path']}
        # Neither a failed finish helper nor missing full evidence can close the story.
        broken_report = self.ref('failed-finish.json', json.dumps({'ok': False, 'steps': [{'ok': False}]}))
        with self.assertRaisesRegex(ValueError, 'story-finish'):
            save_batch(third, 'bad-finish', [{**final_event, 'finish_report': broken_report['path']}], [broken_report['path']])
        intact = native.status(self.session)
        broken = copy.deepcopy(intact); broken.pop('integration_gate')
        native.atomic_json(Path(self.session), broken)
        with self.assertRaisesRegex(ValueError, 'full gate'):
            save_batch(third, 'missing-full', [final_event], [finish['path']])
        native.atomic_json(Path(self.session), intact)
        save_batch(third, 'finalize', [{'event': 'finalize', 'story': '1-1', 'repo': str(self.root),
                                       'finish_report': finish['path']}], [finish['path']])
        self.assertNotEqual(native.status(self.session)['status'], 'completed')
        self.assertTrue(tasks.result(third, tasks.binding(third)['agent_id'], True)['batch_applied'])
        self.assertEqual(native.status(self.session)['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
