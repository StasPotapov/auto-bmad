import copy
import hashlib
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
            'roles': {'story-runner': {}, 'implementer': {}, 'reviewer': {}, 'verifier': {}}}
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
            'delegation': {'transport': 'native-subagents'}, 'review_layers': ['blind'],
            'workflow': str(workflow), 'profile': str(profile),
            'workflow_hash': hashlib.sha256(workflow.read_bytes()).hexdigest(),
            'profile_hash': hashlib.sha256(profile.read_bytes()).hexdigest(),
            'snapshot_hashes': {'workflow.md': hashlib.sha256(workflow.read_bytes()).hexdigest()},
            'review_condition_expressions': {'blind': 'Story changes public API'}}))
        self.record('bind', worktree=str(self.root), baseline=self.base, manifest=str(self.manifest))

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True, check=True)

    def record(self, event, **values):
        return native.record(self.session, {'event': event, 'story': '1-1', **values})

    def review(self):
        self.record('agent', role='reviewer', agent_id='reviewer-1', status='completed')
        report = Path(self.tmp.name) / 'review.txt'
        report.write_text('Independent review: no findings.\n')
        self.record('review', layer='blind', agent_id='reviewer-1', report=str(report),
                    verdict='pass', reviewed_tree=native.code_tree(self.root))
        return report

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
        values = {'layer': 'blind', 'condition': 'Story changes public API', 'condition_result': False,
                  'evaluated_by': 'main-chat', 'reviewed_tree': native.code_tree(self.root), 'evidence': str(evidence)}
        with self.assertRaisesRegex(ValueError, 'exact prepared condition'):
            self.record('review-not-applicable', **{**values, 'condition': 'Anything'})
        with self.assertRaisesRegex(ValueError, 'conditional review layer'):
            self.record('review-not-applicable', **{**values, 'layer': 'unknown'})
        self.record('review-not-applicable', **values)
        self.checked()
        spec = self.spec()
        result = self.record('complete', spec=str(spec))
        self.assertEqual(result['stories']['1-1']['reviews']['blind']['verdict'], 'not_applicable')
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
