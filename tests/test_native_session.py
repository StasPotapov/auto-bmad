import copy
import hashlib
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
import native_session as native
from common import ARTIFACTS, SPRINT_REL


class NativeSessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.test')
        (self.root / '.auto-bmad.toml').write_text('[execution]\nbackend="native"\n'
            '[[verify]]\nname="project-tests"\ncommand="true"\n')
        (self.root / 'code.py').write_text('value = 1\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD').stdout.strip()
        self.env = patch.dict(os.environ, {'AUTO_BMAD_CONFIG': str(self.root / 'absent'), 'AUTO_BMAD_EXECUTOR': 'codex'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.prepared = {'backend': 'native', 'request': '1-1', 'base_commit': self.base,
            'plan': {'level': 'normal', 'stories': [{'id': '1-1', 'title': 'Fixture'}]},
            'roles': {name: {} for name in ('story-runner', 'implementer', 'blind-hunter', 'intent-alignment', 'verifier')}}
        self.real_plan = native.plan
        self.plan_patch = patch.object(native, 'plan', return_value=copy.deepcopy(self.prepared))
        self.plan_patch.start()
        self.addCleanup(self.plan_patch.stop)
        self.data = native.init(self.root, self.prepared)
        self.session = self.data['session']
        self.manifest = Path(self.tmp.name) / 'manifest.json'
        workflow = self.root / '_bmad/render/native-fixture/workflow.md'
        workflow.parent.mkdir(parents=True)
        workflow.write_text('Native workflow fixture.\n')
        profile = self.root / '_bmad/custom/bmad-build-auto.user.toml'
        profile.parent.mkdir(parents=True)
        profile.write_text('Native profile fixture.\n')
        self.git('config', 'core.excludesFile', str(Path(self.tmp.name) / 'ignored'))
        (Path(self.tmp.name) / 'ignored').write_text('_bmad/render/\n_bmad/custom/bmad-build-auto.user.toml\n')
        self.manifest.write_text(json.dumps({'repo': str(self.root), 'config_hash': native.config(self.root)[1],
            'delegation': {'transport': 'native-subagents'}, 'review_layers': ['blind-hunter'],
            'workflow': str(workflow), 'profile': str(profile),
            'workflow_hash': hashlib.sha256(workflow.read_bytes()).hexdigest(),
            'profile_hash': hashlib.sha256(profile.read_bytes()).hexdigest(),
            'snapshot_hashes': {'workflow.md': hashlib.sha256(workflow.read_bytes()).hexdigest()},
            'review_condition_expressions': {'blind-hunter': 'Story changes public API'}}))
        self.record('bind', worktree=str(self.root), baseline=self.base, manifest=str(self.manifest))

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True, check=True)

    def record(self, event, **values):
        return native.record(self.session, {'event': event, 'story': '1-1', **values})

    def review(self, verdict='pass'):
        self.record('agent', role='blind-hunter', agent_id='reviewer-1', status='completed')
        report = Path(self.tmp.name) / 'review.txt'
        report.write_text('Independent review: ' + ('no findings.' if verdict == 'pass' else 'F1: wrong value.') + '\n')
        self.record('review', layer='blind-hunter', agent_id='reviewer-1', report=str(report),
                    verdict=verdict, reviewed_tree=native.code_tree(self.root))
        return report

    def revalidation(self, original_tree, **overrides):
        target = native.code_tree(self.root)
        evidence = Path(self.tmp.name) / 'revalidation.json'
        evidence.write_text(json.dumps({'kind': 'targeted-fixes', 'evaluated_by': 'main-chat',
            'source_tree': original_tree, 'target_tree': target, 'scope_reason': 'Only corrected the known constant.',
            'all_findings_addressed': True, 'findings': [{'id': 'F1', 'status': 'fixed',
                'evidence': 'code.py now has the required value; regression passed.'}],
            'checked_changes': 'Inspected cumulative delta from original review: only code.py value.', **overrides}))
        return {'layer': 'blind-hunter', 'source_tree': original_tree, 'reviewed_tree': target, 'evidence': str(evidence)}

    def add_review_layer(self, layer):
        manifest = json.loads(self.manifest.read_text())
        manifest['review_layers'].append(layer)
        self.manifest.write_text(json.dumps(manifest))
        data = native.status(self.session)
        row = data['stories']['1-1']
        row['required_reviews'].append(layer)
        row['manifest_hash'] = native.digest(manifest)
        native.atomic_json(Path(self.session), data)

    def checked(self, verdict='pass'):
        result = {'verdict': verdict, 'code': 0 if verdict == 'pass' else 1, 'failure_ids': ['test_x']}
        with patch.object(native.verify, 'cmd_run', return_value=(result, 0)):
            return native.check(self.session, '1-1')

    def spec(self):
        path = self.root / ARTIFACTS / 'spec-1-1-fixture.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'---\nstatus: done\nbaseline_revision: {self.base}\n---\nVerified fixture.\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'story')
        return path

    def test_batch_is_atomic_and_retry_is_idempotent(self):
        request = {'batch_id': 'repair-1', 'events': [
            {'event': 'repair', 'story': '1-1', 'kind': 'review', 'reason': 'Fix F1'},
            {'event': 'phase', 'story': '1-1', 'phase': 'implementation'}]}
        before = Path(self.session).read_bytes()
        invalid = copy.deepcopy(request)
        invalid['events'][1]['phase'] = 'invented'
        with self.assertRaisesRegex(ValueError, 'unknown story phase'):
            native.record_batch(self.session, invalid)
        self.assertEqual(Path(self.session).read_bytes(), before)
        with patch.object(native, 'atomic_json', wraps=native.atomic_json) as write:
            receipt = native.record_batch(self.session, request)
            self.assertEqual(write.call_count, 1)
        saved = Path(self.session).read_bytes()
        again = native.record_batch(self.session, request)
        self.assertTrue(again['replayed'])
        self.assertEqual(again['event_end'], receipt['event_end'])
        self.assertEqual(receipt['event_end'] - receipt['event_start'], 2)
        self.assertEqual(Path(self.session).read_bytes(), saved)
        self.assertEqual(native.status(self.session)['stories']['1-1']['repair_counts']['review'], 1)
        changed = copy.deepcopy(request)
        changed['events'][0]['reason'] = 'Different work'
        with self.assertRaisesRegex(ValueError, 'different events'):
            native.record_batch(self.session, changed)
        self.assertEqual(Path(self.session).read_bytes(), saved)

    def test_batch_replay_after_cancel_returns_original_receipt(self):
        request = {'batch_id': 'retry-1', 'events': [
            {'event': 'retry', 'story': '1-1', 'reason': 'Malformed result'}]}
        receipt = native.record_batch(self.session, request)
        native.control(self.session, 'cancel')
        replay = native.record_batch(self.session, request)
        self.assertEqual(replay, {**receipt, 'replayed': True})
        self.assertEqual(native.status(self.session)['status'], 'cancelled')
        with self.assertRaisesRegex(ValueError, 'not running'):
            native.record_batch(self.session, {**request, 'batch_id': 'retry-2'})

    def test_batch_validation_preserves_review_gates_and_limits(self):
        before = Path(self.session).read_bytes()
        with self.assertRaisesRegex(ValueError, 'review'):
            native.record_batch(self.session, {'batch_id': 'missing-evidence', 'events': [
                {'event': 'phase', 'story': '1-1', 'phase': 'verification'},
                {'event': 'complete', 'story': '1-1', 'spec': 'missing'}]})
        self.assertEqual(Path(self.session).read_bytes(), before)
        limit = native.status(self.session)['technical_limit']
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            native.record_batch(self.session, {'batch_id': 'too-many', 'events': [
                {'event': 'retry', 'story': '1-1', 'reason': 'Failure'}] * (limit + 1)})
        self.assertEqual(Path(self.session).read_bytes(), before)

    def test_batch_obeys_slot_order_and_independent_review_evidence(self):
        self.record('schedule', host_limit=4, waves=[{'stories': ['1-1'], 'reason': 'Single story'}])
        self.record('agent', role='story-runner', agent_id='controller', status='running')
        done = {'event': 'agent', 'story': '1-1', 'role': 'story-runner',
                'agent_id': 'controller', 'status': 'completed'}
        start = {'event': 'agent', 'story': '1-1', 'role': 'blind-hunter',
                 'agent_id': 'reviewer', 'status': 'running'}
        before = Path(self.session).read_bytes()
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            native.record_batch(self.session, {'batch_id': 'roles', 'events': [start, done]})
        self.assertEqual(Path(self.session).read_bytes(), before)
        native.record_batch(self.session, {'batch_id': 'roles', 'events': [done, start]})
        report = Path(self.tmp.name) / 'batch-review.txt'
        report.write_text('No findings')
        review = {'event': 'review', 'story': '1-1', 'layer': 'blind-hunter',
                  'agent_id': 'reviewer', 'report': str(report), 'verdict': 'pass',
                  'reviewed_tree': native.code_tree(self.root)}
        terminal = {**start, 'status': 'completed'}
        native.record_batch(self.session, {'batch_id': 'review', 'events': [terminal, review]})
        saved = native.status(self.session)['stories']['1-1']['reviews']['blind-hunter']
        self.assertEqual(saved['report_hash'], hashlib.sha256(report.read_bytes()).hexdigest())

    def test_summary_is_navigation_and_preserves_failure_and_staleness_signals(self):
        self.review(verdict='problem')
        self.record('phase', phase='blocked', reason='Decision needed')
        self.record('agent', role='implementer', agent_id='writer', status='waiting')
        data = native.status(self.session)
        row = data['stories']['1-1']
        row['checks']['test'] = {'tree': native.code_tree(self.root), 'result': {
            'verdict': 'problem', 'code': 1, 'log': '/private/test.log',
            'tail': 'very long output\n' * 10000, 'failure_ids': ['F1']}}
        native.atomic_json(Path(self.session), data)
        (self.root / 'code.py').write_text('value = 2\n')
        with patch.object(native, 'code_tree', side_effect=AssertionError('overview must not hash')):
            overview = native.summary(self.session)
        self.assertIsNone(overview['stories']['1-1']['reviews']['blind-hunter']['matches_current_tree'])
        self.assertNotIn('report', overview['stories']['1-1']['reviews']['blind-hunter'])
        self.assertEqual(overview['stories']['1-1']['checks']['test']['verdict'], 'problem')
        summary = native.summary(self.session, '1-1')
        compact = summary['stories']['1-1']
        self.assertFalse(compact['reviews']['blind-hunter']['matches_current_tree'])
        self.assertEqual(compact['checks']['test']['verdict'], 'problem')
        self.assertEqual(compact['checks']['test']['log'], '/private/test.log')
        self.assertTrue(compact['reviews']['blind-hunter']['report'].endswith('review.txt'))
        self.assertEqual(compact['blocker'], 'Decision needed')
        self.assertEqual(compact['agent_counts'], {'launched': 2, 'active': 1, 'terminal': 1})
        self.assertEqual(set(compact['active_agents']), {'writer'})
        self.assertNotIn('events', summary)
        self.assertNotIn('tail', compact['checks']['test'])
        self.assertLess(len(json.dumps(summary)), len(json.dumps(data)) / 10)
        self.assertIn('not performed', summary['evidence_validation'])
        self.record('phase', phase='implementation')
        self.assertNotIn('blocker', native.summary(self.session, '1-1')['stories']['1-1'])
        with self.assertRaisesRegex(ValueError, 'outside'):
            native.summary(self.session, '9-9')

    def test_summary_reports_missing_worktree_without_losing_run_state(self):
        with patch.object(native, 'code_tree', side_effect=ValueError('worktree unavailable')):
            result = native.summary(self.session, '1-1')
        self.assertEqual(result['stories']['1-1']['fingerprint_error'], 'worktree unavailable')
        self.assertEqual(result['status'], 'running')

    def test_cli_batch_and_summary_and_legacy_output(self):
        request = Path(self.tmp.name) / 'batch.json'
        request.write_text(json.dumps({'batch_id': 'cli', 'events': [
            {'event': 'phase', 'story': '1-1', 'phase': 'planning'}]}))
        for command, options in [('record-batch', ['--request', str(request)]),
                                 ('summary', ['--story', '1-1']), ('status', [])]:
            with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(native.main([command, '--session', self.session, *options]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual('events' in result, command == 'status')
        request.write_text('{"batch_id":"empty","events":[]}')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(native.main(['record-batch', '--session', self.session,
                                          '--request', str(request)]), 2)
        self.assertIn('nonempty', json.loads(output.getvalue())['error'])

    def test_completion_needs_actual_checks_and_current_independent_review(self):
        spec = self.spec()
        with self.assertRaisesRegex(ValueError, 'review'):
            self.record('complete', spec=str(spec))
        self.review()
        with self.assertRaisesRegex(ValueError, 'check'):
            self.record('complete', spec=str(spec))
        self.checked()
        result = self.record('complete', spec=str(spec))
        self.assertEqual(result['stories']['1-1']['status'], 'verified')
        self.assertEqual(result['status'], 'running')

    def test_cancelled_session_cannot_resume_over_another_active_run(self):
        native.control(self.session, 'cancel')
        other = native.init(self.root, self.prepared)
        with self.assertRaisesRegex(ValueError, 'another unfinished native session'):
            native.control(self.session, 'resume', confirm_cancelled=True)
        self.assertEqual(native.status(self.session)['status'], 'cancelled')
        self.assertEqual(native.status(other['session'])['status'], 'running')
        native.control(other['session'], 'cancel')
        self.assertEqual(native.control(self.session, 'resume', confirm_cancelled=True)['status'], 'running')

    def test_schedule_is_saved_and_required_before_native_dispatch(self):
        data = json.loads(Path(self.session).read_text())
        data['schedule_required'] = True
        native.atomic_json(Path(self.session), data)
        with self.assertRaisesRegex(ValueError, 'schedule'):
            self.record('agent', role='story-runner', agent_id='controller', status='running')
        result = native.record(self.session, {'event': 'schedule', 'host_limit': 4,
            'waves': [{'stories': ['1-1'], 'reason': 'Single selected story.'}]})
        self.assertEqual(result['schedule']['capacity'], 3)
        self.record('agent', role='story-runner', agent_id='controller', status='running')
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            self.record('agent', role='implementer', agent_id='dev', status='running')
        self.record('agent', role='story-runner', agent_id='controller', status='completed')
        result = self.record('agent', role='implementer', agent_id='dev', status='running')
        self.assertEqual(result['stories']['1-1']['agents']['dev']['status'], 'running')

    def test_explicit_note_policy_preserves_failure_without_claiming_a_pass(self):
        spec = self.spec()
        self.review()
        self.checked('problem')
        with self.assertRaisesRegex(ValueError, 'successful check'):
            self.record('complete', spec=str(spec))
        selected = [{'name': 'project-tests', 'kind': 'command', 'on_fail': 'note'}]
        with patch.object(native, 'required_checks', return_value=selected):
            data = self.record('complete', spec=str(spec))
        self.assertEqual(data['stories']['1-1']['status'], 'verified')
        self.assertEqual(data['stories']['1-1']['verification_notes'][0]['verdict'], 'problem')

    def test_stale_review_and_changed_report_cannot_complete(self):
        report = self.review()
        self.checked()
        (self.root / 'code.py').write_text('value = 2\n')
        spec = self.spec()
        with self.assertRaisesRegex(ValueError, 'review'):
            self.record('complete', spec=str(spec))
        self.review()
        self.checked()
        report.write_text('modified after attestation')
        with self.assertRaisesRegex(ValueError, 'report changed'):
            self.record('complete', spec=str(spec))

    def test_cancel_requires_explicit_resume_and_preserves_budget(self):
        self.record('repair', kind='review', reason='verified defect')
        native.control(self.session, 'cancel')
        with self.assertRaisesRegex(ValueError, 'explicit user'):
            native.control(self.session, 'resume')
        result = native.control(self.session, 'resume', True)
        self.assertEqual(result['stories']['1-1']['repair_counts']['review'], 1)

    def test_targeted_fixes_complete_without_second_independent_review(self):
        report = self.review('problem')
        source = native.code_tree(self.root)
        self.record('repair', kind='review', reason='Fix all known findings together')
        (self.root / 'code.py').write_text('value = 2\n')
        spec = self.spec()
        with self.assertRaisesRegex(ValueError, 'review'):
            self.record('complete', spec=str(spec))
        result = self.record('review-revalidate', **self.revalidation(source))
        current = result['stories']['1-1']['reviews']['blind-hunter']
        self.assertEqual(current['method'], 'targeted-fixes')
        self.assertEqual(current['evaluated_by'], 'main-chat')
        self.assertEqual(current['original_review']['tree'], source)
        self.assertEqual(current['original_review']['verdict'], 'problem')
        self.assertEqual(current['original_review']['report'], str(report.resolve()))
        with self.assertRaisesRegex(ValueError, 'successful check'):
            self.record('complete', spec=str(spec))
        self.checked()
        result = self.record('complete', spec=str(spec))
        self.assertEqual(result['stories']['1-1']['status'], 'verified')
        self.assertEqual(sum(e['event'] == 'review' for e in result['events']), 1)

    def test_revalidation_rejects_missing_wrong_or_broad_evidence(self):
        source = native.code_tree(self.root)
        with self.assertRaisesRegex(ValueError, 'saved completed independent review'):
            self.record('review-revalidate', **self.revalidation(source))
        self.review('problem')
        self.record('repair', kind='review', reason='known findings')
        (self.root / 'code.py').write_text('value = 2\n')
        for override in ({'kind': 'broad'}, {'evaluated_by': 'implementer'},
                         {'source_tree': 'wrong'}, {'target_tree': 'wrong'},
                         {'all_findings_addressed': False}, {'scope_reason': ''},
                         {'checked_changes': ''}, {'findings': []},
                         {'findings': [{'id': 'F1', 'status': 'deferred', 'evidence': 'later'}]},
                         {'findings': [{'id': 'F1', 'status': 'fixed', 'evidence': ''}]}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.record('review-revalidate', **self.revalidation(source, **override))
        values = self.revalidation(source)
        with self.assertRaisesRegex(ValueError, 'original review tree'):
            self.record('review-revalidate', **{**values, 'source_tree': 'wrong'})
        with self.assertRaisesRegex(ValueError, 'required independent review layers'):
            self.record('review-revalidate', **{**values, 'layer': 'verify:device'})
        Path(values['evidence']).unlink()
        with self.assertRaises(FileNotFoundError):
            self.record('review-revalidate', **values)

    def test_revalidation_checks_original_report_and_evidence_integrity(self):
        report = self.review('problem')
        source = native.code_tree(self.root)
        self.record('repair', kind='review', reason='known finding')
        (self.root / 'code.py').write_text('value = 2\n')
        spec = self.spec()
        values = self.revalidation(source)
        original = report.read_bytes()
        report.write_text('rewritten original')
        with self.assertRaisesRegex(ValueError, 'review report changed'):
            self.record('review-revalidate', **values)
        report.write_bytes(original)
        self.record('review-revalidate', **values)
        self.checked()
        evidence = Path(values['evidence'])
        original_evidence = evidence.read_bytes()
        evidence.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'revalidation evidence changed'):
            self.record('complete', spec=str(spec))
        evidence.write_bytes(original_evidence)
        report.write_text('rewritten original')
        with self.assertRaisesRegex(ValueError, 'review report changed'):
            self.record('complete', spec=str(spec))

    def test_revalidation_preserves_original_snapshot_across_repairs_and_resume(self):
        self.review()
        source = native.code_tree(self.root)
        self.record('repair', kind='review', reason='first targeted fix')
        (self.root / 'code.py').write_text('value = 2\n')
        intermediate = native.code_tree(self.root)
        self.record('review-revalidate', **self.revalidation(source, findings=[]))
        self.record('repair', kind='review', reason='second targeted fix')
        native.control(self.session, 'cancel')
        native.control(self.session, 'resume', confirm_cancelled=True)
        (self.root / 'code.py').write_text('value = 3\n')
        with self.assertRaisesRegex(ValueError, 'original review tree'):
            self.record('review-revalidate', **self.revalidation(intermediate))
        result = self.record('review-revalidate', **self.revalidation(source, findings=[]))
        self.assertEqual(result['stories']['1-1']['reviews']['blind-hunter']['original_review']['tree'], source)
        self.assertEqual(result['stories']['1-1']['repair_counts']['review'], 2)

    def test_new_independent_report_invalidates_older_candidate(self):
        self.review()
        source = native.code_tree(self.root)
        self.record('repair', kind='review', reason='change')
        (self.root / 'code.py').write_text('value = 2\n')
        self.review('problem')
        with self.assertRaisesRegex(ValueError, 'original review tree'):
            self.record('review-revalidate', **self.revalidation(source))

    def test_rejected_findings_need_no_fake_repair_or_second_review(self):
        self.review('problem')
        source = native.code_tree(self.root)
        spec = self.spec()
        finding = {'id': 'F1', 'status': 'rejected', 'evidence': 'Existing value matches the authoritative requirement.'}
        self.record('review-revalidate', **self.revalidation(source, findings=[finding],
            scope_reason='No implementation changes.', checked_changes='Checked original report against unchanged code.'))
        self.checked()
        result = self.record('complete', spec=str(spec))
        self.assertEqual(result['stories']['1-1']['repair_counts']['review'], 0)
        self.assertEqual(sum(e['event'] == 'review' for e in result['events']), 1)

    def test_targeted_integration_can_revalidate_current_review_without_repair(self):
        spec = self.spec()
        self.review()
        source = native.code_tree(self.root)
        self.checked()
        self.record('complete', spec=str(spec))
        (self.root / 'code.py').write_text('value = 2\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'targeted integration correction')
        result = self.record('review-revalidate', worktree=str(self.root), **self.revalidation(source))
        self.assertEqual(result['stories']['1-1']['reviews']['blind-hunter']['original_review']['tree'], source)
        self.assertEqual(result['stories']['1-1']['repair_counts']['review'], 0)
        self.checked()
        self.record('complete', spec=str(spec))

    def test_independent_review_cannot_reuse_another_layers_candidate_agent(self):
        self.add_review_layer('intent-alignment')
        self.review()
        self.record('agent', role='intent-alignment', agent_id='reviewer-2', status='completed')
        report = Path(self.tmp.name) / 'intent.txt'
        report.write_text('Independent intent review: no findings.')
        self.record('review', layer='intent-alignment', agent_id='reviewer-2', report=str(report),
                    verdict='pass', reviewed_tree=native.code_tree(self.root))
        self.record('repair', kind='review', reason='targeted corrections')
        with self.assertRaisesRegex(ValueError, 'matching independent'):
            self.record('review', layer='blind-hunter', agent_id='reviewer-2', report=str(report),
                        verdict='pass', reviewed_tree=native.code_tree(self.root))

    def test_revalidation_checks_agent_independence_against_current_and_candidates(self):
        self.add_review_layer('intent-alignment')
        self.review()
        source = native.code_tree(self.root)
        self.record('repair', kind='review', reason='targeted correction')
        data = native.status(self.session)
        original = copy.deepcopy(data['stories']['1-1']['review_candidates']['blind-hunter'])
        for collection in ('reviews', 'review_candidates'):
            with self.subTest(collection=collection):
                conflicting = copy.deepcopy(data)
                conflicting['stories']['1-1'][collection]['intent-alignment'] = original
                native.atomic_json(Path(self.session), conflicting)
                with self.assertRaisesRegex(ValueError, 'separate native agents'):
                    self.record('review-revalidate', **self.revalidation(source))

    def test_nonblocking_deferral_is_explicit_and_tracking_remains_required(self):
        self.review('problem')
        source = native.code_tree(self.root)
        tracking = Path(self.tmp.name) / 'open-questions.md'
        tracking.write_text('F1: optional terminology choice needs a human decision; mandatory behaviour is correct.')
        finding = {'id': 'F1', 'status': 'deferred', 'evidence': 'No mandatory acceptance criterion is unmet.',
                   'mandatory_defect': False, 'blocking': False, 'reason': 'Optional wording choice.',
                   'tracking': str(tracking.resolve())}
        values = self.revalidation(source, findings=[finding])
        result = self.record('review-revalidate', **values)
        self.assertEqual(result['stories']['1-1']['reviews']['blind-hunter']['deferred_findings'], [finding])
        self.checked()
        spec = self.spec()
        self.record('complete', spec=str(spec))
        tracking.unlink()
        with self.assertRaisesRegex(ValueError, 'deferral tracking'):
            self.record('complete', spec=str(spec))

    def test_deferral_cannot_hide_a_mandatory_or_blocking_finding(self):
        self.review('problem')
        source = native.code_tree(self.root)
        tracking = Path(self.tmp.name) / 'open-questions.md'
        tracking.write_text('Tracked optional wording choice.')
        valid = {'id': 'F1', 'status': 'deferred', 'evidence': 'Requirement allows both words.',
                 'mandatory_defect': False, 'blocking': False, 'reason': 'Optional choice.',
                 'tracking': str(tracking.resolve())}
        for changes in ({'mandatory_defect': True}, {'mandatory_defect': None}, {'blocking': True},
                        {'blocking': None}, {'reason': ''}, {'tracking': ''},
                        {'tracking': str(tracking.parent / 'absent.md')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.record('review-revalidate', **self.revalidation(source, findings=[{**valid, **changes}]))
        tracking.write_text('')
        with self.assertRaisesRegex(ValueError, 'deferral tracking'):
            self.record('review-revalidate', **self.revalidation(source, findings=[valid]))

    def test_no_duplicate_unfinished_run_or_unknown_story(self):
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            native.init(self.root, self.prepared)
        with self.assertRaisesRegex(ValueError, 'outside'):
            native.record(self.session, {'event': 'phase', 'story': '9-9', 'phase': 'planning'})

    def test_no_progress_bounded_and_failed_checks_not_completion(self):
        self.checked('problem')
        for _ in range(3):
            self.record('repair', kind='tests', reason='fix test_x')
            self.checked('problem')
        with self.assertRaisesRegex(ValueError, 'no-progress'):
            self.record('repair', kind='tests', reason='still failing')
        self.assertEqual(native.status(self.session)['stories']['1-1']['repair_counts']['tests'], 3)

    def test_finalization_requires_tracking_and_verified_commit(self):
        spec = self.spec()
        self.review()
        self.checked()
        self.record('complete', spec=str(spec))
        report = Path(self.tmp.name) / 'finish.json'
        report.write_text(json.dumps({'ok': True, 'steps': [{'step': 'sync', 'ok': True}]}))
        with self.assertRaisesRegex(ValueError, 'tracking'):
            self.record('finalize', repo=str(self.root), finish_report=str(report))
        status = self.root / SPRINT_REL
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text('development_status:\n  epic-1: in-progress\n  1-1-fixture: done\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'tracking')
        result = self.record('finalize', repo=str(self.root), finish_report=str(report))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['stories']['1-1']['final_commit'], self.git('rev-parse', 'HEAD').stdout.strip())

    def test_technical_retries_are_bounded_and_cancel_waits_for_agents(self):
        for _ in range(3):
            self.record('retry', reason='malformed agent response')
        with self.assertRaisesRegex(ValueError, 'technical retry budget'):
            self.record('retry', reason='fourth failed response')
        self.record('agent', role='implementer', agent_id='writer', status='running')
        with self.assertRaisesRegex(ValueError, 'stop/join'):
            native.control(self.session, 'cancel')
        self.record('agent', role='implementer', agent_id='writer', status='stopped')
        native.control(self.session, 'cancel')

    def test_real_plan_does_not_start_models_and_surfaces_native_profiles(self):
        status = self.root / SPRINT_REL
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text('development_status:\n  epic-1: in-progress\n  1-1-fixture: backlog\n')
        result = self.real_plan(self.root, '1-1')
        self.assertFalse(result['model_started'])
        self.assertEqual(result['backend'], 'native')
        self.assertTrue(result['wave_plan_required'])
        self.assertEqual(result['plan']['stories'][0]['id'], '1-1')
        self.assertIn('model', result['roles']['story-runner'])

    def test_optional_verifier_skips_are_preserved_without_fabricated_pass(self):
        selected = {'verifiers': [{'name': 'project-tests', 'kind': 'command'}],
                    'skipped': [{'name': 'device', 'reason': 'no skill adbm', 'install_hint': 'install adbm'}],
                    'warnings': []}
        with patch.object(native.verify, 'cmd_plan', return_value=(selected, 0)):
            result = self.checked()
            self.assertEqual(result['skipped'], selected['skipped'])
            self.assertNotIn('device', result['checks'])
            saved = native.status(self.session)['stories']['1-1']['verification_plan']
            self.assertEqual(saved['skipped'], selected['skipped'])

    def test_failed_detector_still_blocks_instead_of_silently_skipping(self):
        selected = {'verifiers': [], 'skipped': [], 'warnings': ['device: detect failed — timed out']}
        with patch.object(native.verify, 'cmd_plan', return_value=(selected, 2)), \
             self.assertRaisesRegex(ValueError, 'verification plan needs resolution'):
            native.check(self.session, '1-1')

    def test_conditional_review_can_be_not_applicable_with_current_false_evidence(self):
        evidence = Path(self.tmp.name) / 'condition.txt'
        evidence.write_text('Main chat inspected diff: only private implementation changed, public API unchanged.\n')
        values = {'layer': 'blind-hunter', 'condition': 'Story changes public API', 'condition_result': False,
                  'evaluated_by': 'main-chat', 'reviewed_tree': native.code_tree(self.root), 'evidence': str(evidence)}
        with self.assertRaisesRegex(ValueError, 'exact prepared condition'):
            self.record('review-not-applicable', **{**values, 'condition': 'Anything'})
        with self.assertRaisesRegex(ValueError, 'conditional review layer'):
            self.record('review-not-applicable', **{**values, 'layer': 'unknown'})
        self.record('review-not-applicable', **values)
        self.checked()
        spec = self.spec()
        result = self.record('complete', spec=str(spec))
        self.assertEqual(result['stories']['1-1']['reviews']['blind-hunter']['verdict'], 'not_applicable')
        self.assertEqual(result['stories']['1-1']['status'], 'verified')
        (self.root / 'code.py').write_text('value = 3\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'new change')
        with self.assertRaisesRegex(ValueError, 'review'):
            self.record('complete', spec=str(spec))

    def test_changed_rendered_instructions_and_branch_block_resume(self):
        manifest = json.loads(self.manifest.read_text())
        workflow = Path(manifest['workflow'])
        original = workflow.read_text()
        workflow.write_text('changed instruction')
        with self.assertRaisesRegex(ValueError, 'workflow/profile changed'):
            native.control(self.session, 'resume')
        workflow.write_text(original)
        self.git('switch', '-qc', 'other-branch')
        with self.assertRaisesRegex(ValueError, 'branch changed'):
            native.control(self.session, 'resume')

    def test_agent_verification_is_mandatory(self):
        selected = [{'name': 'device', 'kind': 'agent'}]
        self.review()
        spec = self.spec()
        with patch.object(native, 'required_checks', return_value=selected), \
             self.assertRaisesRegex(ValueError, 'verify:device'):
            self.record('complete', spec=str(spec))


if __name__ == '__main__':
    unittest.main()
