"""Bootstrap -> diagnosis -> bootstrap without invented sessions or duplicate workers."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import native_tasks as tasks
import native_session as native
import native_bootstrap as bootstrap
import agent_config
import test_native_tasks as fixtures


class BootstrapDiagnosisTest(unittest.TestCase):
    setUp = fixtures.NativeTaskTest.setUp

    def blocked(self, planning=False, next_step='triage', arg='epic 1 --deep'):
        envelope = tasks.prepare(repo=self.root, arg=arg, planning_only=planning,
            host_limit=4, accounting_unavailable_reason='Synthetic host lacks accounting IDs')
        task = envelope['task_file']; tasks.start(task, 'bootstrap')
        report = Path(task).parent / 'preflight.json'; report.write_text('{"dirty_files":["tooling/"]}')
        tasks.write_receipt(task, {'state':'blocked','next':next_step,'actions':['Diagnose saved preflight evidence'],
            'blocker':'Untracked tooling needs provenance checks','artifact_paths':[str(report)]})
        return task, report

    def finish_diagnosis(self, envelope, *, next_step='bootstrap', state='ready'):
        task = envelope['task_file']; tasks.start(task, 'diagnostic')
        report = Path(task).parent / 'diagnosis.md'; report.write_text('Concrete source-backed remedy; preserve user work')
        tasks.write_receipt(task, {'state':state,'next':next_step,'actions':['Recheck preflight with diagnosis evidence'],
            'blocker':None if state=='ready' else 'Missing user intent', 'artifact_paths':[str(report)]})
        return tasks.result(task, 'diagnostic', True)

    def test_direct_diagnosis_uses_configured_role_and_preserves_request_evidence(self):
        original, report = self.blocked()
        result = tasks.result(original, 'bootstrap', True)
        self.assertEqual(result['next_prepare'][-3:], ['task-diagnose','--task',original])
        before = Path(self.session).read_bytes()
        with patch.object(native, 'init', side_effect=AssertionError('diagnosis cannot initialize')):
            envelope = bootstrap.diagnose(original)
            spec = json.loads(Path(envelope['task_file']).read_text())
            self.assertEqual(spec['role'], 'triager'); self.assertIsNone(spec['session']); self.assertIsNone(spec['story'])
            self.assertEqual(spec['profile'], agent_config.resolve(native.config(self.root)[0], 'deep')['roles']['triager'])
            self.assertEqual(spec['request'], 'epic 1 --deep')
            self.assertEqual(spec['host_metadata']['host_limit'], 4)
            payload = json.loads(Path(spec['input']).read_text())
            self.assertEqual(payload['bootstrap_receipt']['sha256'], tasks.file_hash(Path(original).with_name('result.json')))
            result = self.finish_diagnosis(envelope)
        self.assertEqual(Path(self.session).read_bytes(), before)
        self.assertIsNone(result['created_session'])
        self.assertEqual(result['next_prepare'][4], 'task-retry-bootstrap')
        argv = result['next_prepare']
        # Execute the exact generated command contract through the public CLI parser.
        with patch.object(native, 'init', side_effect=AssertionError('preparation must not execute')):
            self.assertEqual(native.main(argv[4:]), 0)
        with self.assertRaisesRegex(ValueError, 'superseded'):
            bootstrap.diagnose(original)

    def test_no_diagnosis_before_terminal_acceptance_and_no_duplicate_after(self):
        original, _ = self.blocked()
        with self.assertRaisesRegex(ValueError, 'observe and accept'):
            bootstrap.diagnose(original)
        tasks.result(original, 'bootstrap', True)
        envelope = bootstrap.diagnose(original)
        with self.assertRaisesRegex(ValueError, 'already issued'):
            bootstrap.diagnose(original)
        tasks.start(envelope['task_file'], 'diagnostic')
        with self.assertRaisesRegex(ValueError, 'pre-session task is still running'):
            tasks.prepare(repo=self.root, arg='epic 1', host_limit=4, accounting_unavailable_reason='unknown IDs')

    def test_modified_source_artifact_refuses_dispatch(self):
        original, report = self.blocked(); tasks.result(original, 'bootstrap', True)
        envelope = bootstrap.diagnose(original)
        report.write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            tasks.start(envelope['task_file'], 'diagnostic')

    def test_diagnosis_cannot_claim_session_or_story_acceptance(self):
        original, _ = self.blocked(); tasks.result(original, 'bootstrap', True)
        envelope = bootstrap.diagnose(original); task = envelope['task_file'];tasks.start(task, 'diagnostic')
        report = Path(task).parent / 'report';report.write_text('diagnosis')
        request = {'state':'ready','next':'bootstrap','actions':[],'blocker':None,'artifact_paths':[str(report)]}
        for extra in ({'created_session':self.session}, {'next':'implementation'}):
            with self.assertRaisesRegex(ValueError, 'diagnosis'):
                tasks.write_receipt(task, {**request, **extra})
        self.assertEqual(tasks.binding(task)['status'],'running')

    def test_planning_only_survives_diagnosis_and_real_user_decision_has_no_route(self):
        original, _ = self.blocked(planning=True);tasks.result(original, 'bootstrap', True)
        envelope = bootstrap.diagnose(original)
        self.assertTrue(json.loads(Path(envelope['task_file']).read_text())['planning_only'])
        result = self.finish_diagnosis(envelope)
        retried = bootstrap.retry(envelope['task_file'])
        self.assertTrue(json.loads(Path(retried['task_file']).read_text())['planning_only'])

    def test_real_user_decision_and_failed_diagnosis_do_not_loop(self):
        original, _ = self.blocked(next_step='decision')
        result=tasks.result(original, 'bootstrap', True)
        self.assertNotIn('next_prepare',result)
        with self.assertRaisesRegex(ValueError, 'technical triage'):
            bootstrap.diagnose(original)
        # A new blocked bootstrap may be diagnosed once, but a blocked diagnosis stops.
        envelope=tasks.prepare(repo=self.root,arg='epic 1',host_limit=4,accounting_unavailable_reason='unknown')
        task=envelope['task_file'];tasks.start(task,'bootstrap-2')
        report=Path(task).parent/'preflight';report.write_text('unknown files')
        tasks.write_receipt(task,{'state':'blocked','next':'triage','actions':[],'blocker':'unknown files','artifact_paths':[str(report)]})
        tasks.result(task,'bootstrap-2',True)
        diagnosis=bootstrap.diagnose(task)
        result=self.finish_diagnosis(diagnosis,next_step='decision',state='blocked')
        self.assertNotIn('next_prepare',result)
        with self.assertRaisesRegex(ValueError,'newly issued pre-session bootstrap'):
            bootstrap.diagnose(diagnosis['task_file'])


    def test_compact_public_retry_preserves_flag_only_request(self):
        original, _ = self.blocked(arg='--deep')
        result = tasks.result(original, 'bootstrap', True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(native.main(result['next_prepare'][4:]), 0)
        envelope = json.loads(out.getvalue())
        result = self.finish_diagnosis(envelope)
        self.assertLess(len(json.dumps(result).encode()), tasks.MAX_OUTPUT)
        self.assertNotIn('--deep', json.dumps(result))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(native.main(result['next_prepare'][4:]), 0)
        retried = json.loads(out.getvalue())
        spec = json.loads(Path(retried['task_file']).read_text())
        self.assertEqual(spec['request'], '--deep')
        self.assertEqual(spec['input_hash'], tasks.file_hash(spec['input']))
        with self.assertRaisesRegex(ValueError, 'already issued'):
            bootstrap.retry(envelope['task_file'])
        # Source validation must survive supersession of the original bootstrap.
        tasks.start(retried['task_file'], 'retry-bootstrap')
        tasks.stop(retried['task_file'], 'retry-bootstrap', 'stopped', 'Fixture finished', True)

    def test_large_request_roundtrip(self):
        original, _ = self.blocked(arg='epic 1 '+('context '*600))
        result=tasks.result(original,'bootstrap',True)
        envelope=bootstrap.diagnose(original)
        result=self.finish_diagnosis(envelope)
        self.assertLess(len(json.dumps(result).encode()),tasks.MAX_OUTPUT)
        retried=bootstrap.retry(envelope['task_file'])
        self.assertEqual(json.loads(Path(retried['task_file']).read_text())['request'], 'epic 1 '+('context '*600))


if __name__ == '__main__':
    unittest.main()
