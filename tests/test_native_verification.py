"""Focused development does not repeatedly execute the landing suite."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import native_session as native
import native_verification as verification
import test_native_session


class StagedVerificationTest(unittest.TestCase):
    def setUp(self):
        fixture = test_native_session.NativeSessionTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture, self.root, self.session = fixture, fixture.root, fixture.session
        cfg = self.root / '.auto-bmad.toml'
        cfg.write_text(cfg.read_text().replace('command="true"', 'command="full-suite"') +
            '\n[project_tests.development.unit]\ncommand="focused-tests"\ntargets=["test_*.py"]\n'
            '\n[project_tests.build.compile]\ncommand="compile-check"\n')
        (self.root / 'test_code.py').write_text('def test_code(): pass\n')
        fixture.git('add', '.')
        fixture.git('commit', '-qm', 'registered test plan')
        data = native.status(self.session)
        data['orchestration_policy'] = 'thin-root-v1'
        data['verification_policy'] = verification.POLICY
        data['config_hash'] = native.config(self.root)[1]
        data['stories']['1-1']['config_hash'] = data['config_hash']
        native.atomic_json(Path(self.session), data)
        self.request = {'checks': [{'name': 'unit', 'targets': ['test_code.py']}], 'builds': ['compile']}
        self.calls = []
        def run(repo, command, timeout, **kwargs):
            self.calls.append(command)
            key = verification.testrun.key_of(repo, command, cache_context=kwargs.get('cache_context'))
            return {'verdict': 'pass', 'code': 0, 'command': command, 'key': key, 'source_key': key, 'tree_changed': False}, 0
        self.successful_run = run
        self.real_run = verification.testrun.run
        self.runner = patch.object(verification.testrun, 'run', side_effect=run)
        self.mock_run = self.runner.start()
        self.addCleanup(self.runner.stop)

    def verified(self):
        data = native.status(self.session)
        data['stories']['1-1'].update(status='verified', commit=self.fixture.git('rev-parse', 'HEAD').stdout.strip())
        native.atomic_json(Path(self.session), data)

    def test_development_requires_registered_focused_plan_and_build_without_full_fallback(self):
        for request in (None, {}, {'checks': self.request['checks']},
                        {'checks': [{'name': 'unknown', 'targets': ['test_code.py']}], 'builds': ['compile']}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                native.check(self.session, '1-1', request=request)
        self.assertEqual(self.calls, [])
        native.check(self.session, '1-1', request=self.request)
        native.check(self.session, '1-1', request=self.request)
        self.assertEqual(self.calls, ['focused-tests test_code.py', 'compile-check'])
        (self.root / 'code.py').write_text('value = 3\n')
        native.check(self.session, '1-1', request=self.request)
        self.assertEqual(self.calls, ['focused-tests test_code.py', 'compile-check'] * 2)
        self.assertNotIn('full-suite', self.calls)

    def test_development_complete_requires_current_tests_but_defers_full_to_landing(self):
        self.fixture.review()
        native.check(self.session, '1-1', request=self.request)
        data = native.status(self.session)
        native.complete(data, '1-1', data['stories']['1-1'], self.root)
        self.assertNotIn('full-suite', self.calls)
        (self.root / 'code.py').write_text('value = 4\n')
        with self.assertRaisesRegex(ValueError, 'current focused'):
            native.complete(data, '1-1', data['stories']['1-1'], self.root)

    def test_early_full_requires_specific_risk_reason_and_never_runs_baseline_suite(self):
        with self.assertRaisesRegex(ValueError, 'broad-risk'):
            native.check(self.session, '1-1', request={**self.request, 'full_risk': 'habit'})
        native.check(self.session, '1-1', request={**self.request,
            'full_risk': 'Shared persistence contract changed; focused tests cannot cover migration compatibility.'})
        self.assertEqual(self.calls.count('full-suite'), 1)
        self.assertEqual(len(self.calls), 3)

    def test_combined_exact_tree_gate_reuses_once_and_code_or_commands_invalidate(self):
        self.verified()
        data = native.status(self.session)
        data['stories']['1-2'] = {**data['stories']['1-1'], 'title': 'second included story'}
        native.atomic_json(Path(self.session), data)
        first = verification.integration(self.session, ['1-1', '1-2'], self.root)
        second = verification.integration(self.session, ['1-1', '1-2'], self.root)
        self.assertEqual(first['verdict'], 'pass')
        self.assertTrue(second['reused'])
        self.assertEqual(self.calls, ['full-suite', 'compile-check'])
        verification.require_integration(native.status(self.session), '1-2', self.root)
        (self.root / 'code.py').write_text('value = 5\n')
        with self.assertRaisesRegex(ValueError, 'exact integration'):
            verification.require_integration(native.status(self.session), '1-1', self.root)
        self.fixture.git('add', 'code.py')
        self.fixture.git('commit', '-qm', 'merge resolution changes code')
        verification.integration(self.session, ['1-1', '1-2'], self.root)
        self.assertEqual(self.calls.count('full-suite'), 2)
        cfg = self.root / '.auto-bmad.toml'
        cfg.write_text(cfg.read_text().replace('full-suite', 'different-full-suite'))
        with self.assertRaisesRegex(ValueError, 'configuration differs'):
            verification.integration(self.session, ['1-1', '1-2'], self.root)

    def test_failed_full_requires_focused_repairs_before_next_full(self):
        self.verified()
        self.mock_run.side_effect = lambda repo, cmd, timeout, **kwargs: ({'verdict': 'problem', 'code': 1}, 0)
        result = verification.integration(self.session, ['1-1'], self.root)
        self.assertEqual(result['verdict'], 'problem')
        with self.assertRaisesRegex(ValueError, 'focused regressions'):
            verification.integration(self.session, ['1-1'], self.root)
        self.mock_run.side_effect = self.successful_run
        native.check(self.session, '1-1', request=self.request)
        self.assertEqual(verification.integration(self.session, ['1-1'], self.root)['verdict'], 'pass')

    def test_finalization_rejects_development_only_and_does_not_reexecute_full(self):
        self.verified()
        self.fixture.review()
        native.check(self.session, '1-1', request=self.request)
        data = native.status(self.session)
        with self.assertRaisesRegex(ValueError, 'full gate'):
            native.complete(data, '1-1', data['stories']['1-1'], self.root, final=True)
        verification.integration(self.session, ['1-1'], self.root)
        data = native.status(self.session)
        native.complete(data, '1-1', data['stories']['1-1'], self.root, final=True)
        self.assertEqual(self.calls.count('full-suite'), 1)

    def test_tree_changed_and_foreign_run_origin_cannot_certify_current_code(self):
        for field, value in [('tree_changed', True), ('key', 'old-run'), ('source_key', 'old-tree')]:
            def stale(repo, cmd, timeout, **kwargs):
                result, code = self.successful_run(repo, cmd, timeout, **kwargs)
                return {**result, field: value}, code
            self.mock_run.side_effect = stale
            receipt = native.check(self.session, '1-1', request=self.request)
            self.assertEqual(receipt['verdict'], 'problem')

    def test_policy_cache_miss_cannot_reuse_lower_cache_after_timeout_or_evidence_change(self):
        self.mock_run.side_effect = self.real_run
        commands = [{'name': 'fixture', 'command': 'printf x >> .auto-bmad/counter', 'timeout': 1800}]
        first = verification.execute(self.root, commands)
        self.assertEqual(first['verdict'], 'pass')
        verification.save_logs(first, Path(self.session).parent / 'copied-logs')
        self.assertTrue(verification.execute(self.root, commands, first)['reused'])
        evidence = Path(first['evidence'][0]['path'])
        evidence.write_text('changed saved evidence')
        second = verification.execute(self.root, commands, first)
        self.assertEqual(second['verdict'], 'pass')
        self.assertNotEqual(first['execution_id'], second['execution_id'])
        third = verification.execute(self.root, [{**commands[0], 'timeout': 1}], second)
        self.assertEqual(third['verdict'], 'pass')
        self.assertNotEqual(second['execution_id'], third['execution_id'])
        self.assertEqual((self.root / '.auto-bmad/counter').read_text(), 'xxx')

    def test_failed_full_blocks_full_risk_before_any_repeat_full_launch(self):
        self.verified()
        self.mock_run.side_effect = lambda repo, cmd, timeout, **kwargs: ({'verdict': 'problem', 'code': 1}, 0)
        verification.integration(self.session, ['1-1'], self.root)
        self.mock_run.reset_mock()
        for checks in ([], self.request['checks']):
            with self.assertRaisesRegex(ValueError, 'full_risk cannot launch'):
                native.check(self.session, '1-1', request={'checks': checks, 'builds': ['compile'],
                    'full_risk': 'Shared architecture changed and broad tests are necessary.'})
        self.mock_run.assert_not_called()

    def test_environment_repair_refreshes_focused_receipt_older_than_failed_full(self):
        self.verified()
        first = native.check(self.session, '1-1', request=self.request)
        self.mock_run.side_effect = lambda repo, cmd, timeout, **kwargs: ({'verdict': 'problem', 'code': 1}, 0)
        verification.integration(self.session, ['1-1'], self.root)
        self.mock_run.side_effect = self.successful_run
        self.mock_run.reset_mock()
        repaired = native.check(self.session, '1-1', request=self.request)
        self.assertFalse(repaired['reused'])
        self.assertNotEqual(first['execution_id'], repaired['execution_id'])
        self.assertEqual(self.mock_run.call_count, 2)
        self.assertEqual(verification.integration(self.session, ['1-1'], self.root)['verdict'], 'pass')

    def test_build_gap_is_explicit_for_projects_without_registered_builds(self):
        cfg = {'project_tests': {'development': {'unit': {'command': 'test', 'targets': ['test_*.py']}}}}
        request = {'checks': self.request['checks']}
        with self.assertRaisesRegex(ValueError, 'build coverage gap'):
            verification.development_plan(self.root, cfg, request)
        commands = verification.development_plan(self.root, cfg, {**request,
            'build_not_applicable': 'Interpreted fixture project has no build step.'})
        self.assertEqual([row['name'] for row in commands], ['dev/unit'])


if __name__ == '__main__':
    unittest.main()
