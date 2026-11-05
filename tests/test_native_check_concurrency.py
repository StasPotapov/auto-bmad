"""Long checks release the journal and publish only into their current generation."""
import copy
import fcntl
import json
from pathlib import Path
import shutil
import shlex
import sys
import threading
import unittest

import test_native_verification as fixtures

native = fixtures.native
verification = fixtures.verification


class CheckConcurrencyTest(unittest.TestCase):
    setUp = fixtures.StagedVerificationTest.setUp
    verified = fixtures.StagedVerificationTest.verified

    def assert_journal_available(self):
        with (Path(self.session).parent.parent / 'journal.lock').open('a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.fail('test execution still holds the journal lock')

    def check(self):
        return native.check(self.session, '1-1', request=self.request)

    def during_first_command(self, action):
        first = True
        def run(*args, **kwargs):
            nonlocal first
            self.assert_journal_available()
            if first:
                first = False
                action()
            return self.successful_run(*args, **kwargs)
        self.mock_run.side_effect = run

    def concurrent_update(self):
        self.fixture.review()
        self.fixture.record('agent', role='intent-alignment', agent_id='new-reviewer', status='running')
        self.fixture.record('phase', phase='blocked', reason='Independent requirement question')

    def assert_updates_preserved(self):
        row = native.status(self.session)['stories']['1-1']
        self.assertIn('blind-hunter', row['reviews'])
        self.assertEqual(row['agents']['new-reviewer']['status'], 'running')
        self.assertEqual(row['phase'], 'blocked')
        self.assertEqual(row['blocker'], 'Independent requirement question')

    def test_development_allows_agent_and_review_writes_without_losing_them(self):
        self.during_first_command(self.concurrent_update)
        self.assertEqual(self.check()['verdict'], 'pass')
        self.assert_updates_preserved()

    def test_integration_allows_agent_and_review_writes_without_losing_them(self):
        self.verified()
        self.during_first_command(self.concurrent_update)
        self.assertEqual(verification.integration(self.session, ['1-1'], self.root)['verdict'], 'pass')
        self.assert_updates_preserved()

    def test_cancel_then_resume_cannot_accept_an_old_result(self):
        def cancel_resume():
            native.control(self.session, 'cancel')
            native.control(self.session, 'resume', confirm_cancelled=True)
        self.during_first_command(cancel_resume)
        with self.assertRaisesRegex(ValueError, 'state changed'):
            self.check()
        data = native.status(self.session)
        self.assertEqual(data['status'], 'running')
        self.assertNotIn('development_check', data['stories']['1-1'])
        self.assertEqual([e['event'] for e in data['events']][-2:], ['cancel', 'resume'])

    def test_repair_during_checks_is_preserved_and_rejects_old_result(self):
        self.during_first_command(lambda: self.fixture.record('repair', kind='review', reason='Fix accepted finding'))
        with self.assertRaisesRegex(ValueError, 'state changed'):
            self.check()
        row = native.status(self.session)['stories']['1-1']
        self.assertEqual(row['repair_counts']['review'], 1)
        self.assertEqual(row['phase'], 'repair')
        self.assertEqual(row['checks'], {})

    def test_cancel_during_integration_cannot_publish_gate(self):
        self.verified()
        self.during_first_command(lambda: native.control(self.session, 'cancel'))
        with self.assertRaisesRegex(ValueError, 'state changed'):
            verification.integration(self.session, ['1-1'], self.root)
        data = native.status(self.session)
        self.assertEqual(data['status'], 'cancelled')
        self.assertNotIn('integration_gate', data)

    def test_code_change_after_execution_before_publish_is_rejected(self):
        real_save = verification.save_logs
        def change_after_execution(receipt, directory):
            real_save(receipt, directory)
            (self.root / 'code.py').write_text('value = 99\n')
        with fixtures.patch.object(verification, 'save_logs', side_effect=change_after_execution):
            with self.assertRaisesRegex(ValueError, 'code/config changed'):
                self.check()
        self.assertNotIn('development_check', native.status(self.session)['stories']['1-1'])

    def test_check_exception_releases_locks_and_does_not_publish_partial_result(self):
        self.mock_run.side_effect = RuntimeError('fixture runner failure')
        with self.assertRaisesRegex(RuntimeError, 'runner failure'):
            self.check()
        self.assert_journal_available()
        self.assertNotIn('development_check', native.status(self.session)['stories']['1-1'])
        self.mock_run.side_effect = self.successful_run
        self.assertEqual(self.check()['verdict'], 'pass')

    def test_running_check_resumes_same_execution_after_releasing_lock(self):
        self.mock_run.side_effect = lambda *args, **kwargs: ({'verdict': 'running'}, 3)
        running = self.check()
        self.assertEqual(running['verdict'], 'running')
        self.assert_journal_available()
        self.fixture.record('agent', role='intent-alignment', agent_id='new-reviewer', status='running')
        self.mock_run.side_effect = self.successful_run
        complete = self.check()
        self.assertEqual(complete['execution_id'], running['execution_id'])
        self.assertEqual(complete['verdict'], 'pass')

    def test_rejected_running_receipt_retains_execution_for_next_authorized_check(self):
        contexts = []
        def running(*args, **kwargs):
            self.assert_journal_available()
            contexts.append(kwargs['cache_context'])
            native.control(self.session, 'cancel')
            native.control(self.session, 'resume', confirm_cancelled=True)
            return {'verdict': 'running'}, 3
        self.mock_run.side_effect = running
        with self.assertRaisesRegex(ValueError, 'state changed'):
            self.check()
        self.assertNotIn('development_check', native.status(self.session)['stories']['1-1'])
        def resume(*args, **kwargs):
            contexts.append(kwargs['cache_context'])
            return self.successful_run(*args, **kwargs)
        self.mock_run.side_effect = resume
        self.assertEqual(self.check()['verdict'], 'pass')
        self.assertEqual(len(set(contexts)), 1)

    def test_integration_rejected_running_receipt_retains_execution(self):
        self.verified()
        contexts = []
        def running(*args, **kwargs):
            contexts.append(kwargs['cache_context'])
            native.control(self.session, 'cancel')
            return {'verdict': 'running'}, 3
        self.mock_run.side_effect = running
        with self.assertRaisesRegex(ValueError, 'state changed'):
            verification.integration(self.session, ['1-1'], self.root)
        native.control(self.session, 'resume', confirm_cancelled=True)
        def resume(*args, **kwargs):
            contexts.append(kwargs['cache_context'])
            return self.successful_run(*args, **kwargs)
        self.mock_run.side_effect = resume
        self.assertEqual(verification.integration(self.session, ['1-1'], self.root)['verdict'], 'pass')
        self.assertEqual(len(set(contexts)), 1)

    def test_different_check_cannot_replace_a_live_execution_checkpoint(self):
        self.mock_run.side_effect = lambda *args, **kwargs: ({'verdict': 'running'}, 3)
        self.check()
        (self.root / 'code.py').write_text('value = 2\n')
        self.mock_run.reset_mock()
        with fixtures.patch.object(verification.testrun, 'live_runs', return_value={'fixture': {'pid': 123}}):
            with self.assertRaisesRegex(ValueError, 'previous verification is still running'):
                self.check()
        self.mock_run.assert_not_called()

    def test_failure_before_receipt_retains_execution_id(self):
        contexts = []
        def fail(*args, **kwargs):
            contexts.append(kwargs['cache_context'])
            raise RuntimeError('caller failed after starting managed worker')
        self.mock_run.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, 'caller failed'):
            self.check()
        def resume(*args, **kwargs):
            contexts.append(kwargs['cache_context'])
            return self.successful_run(*args, **kwargs)
        self.mock_run.side_effect = resume
        self.assertEqual(self.check()['verdict'], 'pass')
        self.assertEqual(len(set(contexts)), 1)

    def test_real_managed_worker_is_joined_after_cancel_resume_not_launched_twice(self):
        release = self.root / '.auto-bmad/release'
        self.addCleanup(lambda: release.touch() if release.parent.exists() else None)
        script = ("from pathlib import Path\nimport time\n"
                  "deadline = time.monotonic() + 6\n"
                  "while not Path('.auto-bmad/release').exists() and time.monotonic() < deadline:\n"
                  "    time.sleep(0.01)\n"
                  "with Path('.auto-bmad/counter').open('a') as f: f.write('x')\n")
        commands = [{'name': 'fixture', 'command': shlex.quote(sys.executable) + ' -c ' + shlex.quote(script),
                     'timeout': 10}]
        attempts = []
        def run(repo, command, timeout, **kwargs):
            result = self.real_run(repo, command, timeout, wait=3 if release.exists() else 0.05, **kwargs)
            attempts.append(result)
            if len(attempts) == 1:
                self.assertEqual(result[0]['verdict'], 'running')
                native.control(self.session, 'cancel')
                native.control(self.session, 'resume', confirm_cancelled=True)
            return result
        self.mock_run.side_effect = run
        with fixtures.patch.object(verification, 'development_plan', return_value=commands):
            with self.assertRaisesRegex(ValueError, 'state changed'):
                self.check()
            self.assertEqual(self.check()['verdict'], 'running')
            self.assertEqual(attempts[0][0]['key'], attempts[1][0]['key'])
            self.assertEqual(len(verification.testrun.live_runs(str(self.root))), 1)
            release.touch()
            self.assertEqual(self.check()['verdict'], 'pass')
        self.assertEqual((self.root / '.auto-bmad/counter').read_text(), 'x')

    def second_worktree(self):
        root = Path(self.fixture.tmp.name) / 'second'
        self.fixture.git('worktree', 'add', '-qb', 'second', str(root))
        shutil.copytree(self.root / '_bmad', root / '_bmad')
        manifest = json.loads(self.fixture.manifest.read_text())
        for field in ('workflow', 'profile'):
            manifest[field] = str(root / Path(manifest[field]).relative_to(self.root))
        manifest['repo'] = str(root)
        path = Path(self.fixture.tmp.name) / 'second-manifest.json'
        path.write_text(json.dumps(manifest))
        data = native.status(self.session)
        row = copy.deepcopy(data['stories']['1-1'])
        row.update(worktree=str(root), branch='refs/heads/second', manifest=str(path),
                   manifest_hash=native.digest(manifest))
        data['stories']['1-2'] = row
        native.atomic_json(Path(self.session), data)
        return root

    def threads(self, *calls):
        results, errors = [], []
        def call(fn):
            try:
                results.append(fn())
            except BaseException as error:
                errors.append(error)
        workers = [threading.Thread(target=call, args=(fn,), daemon=True) for fn in calls]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(15)
        self.assertFalse(any(worker.is_alive() for worker in workers), 'concurrent check deadlocked')
        if errors:
            raise errors[0]
        return results

    def test_checks_in_separate_worktrees_overlap_and_both_results_survive(self):
        self.second_worktree()
        barrier = threading.Barrier(2, timeout=8)
        def run(*args, **kwargs):
            barrier.wait()
            return self.successful_run(*args, **kwargs)
        self.mock_run.side_effect = run
        results = self.threads(self.check, lambda: native.check(self.session, '1-2', request=self.request))
        self.assertEqual([result['verdict'] for result in results], ['pass', 'pass'])
        for row in native.status(self.session)['stories'].values():
            self.assertEqual(row['development_check']['verdict'], 'pass')

    def test_duplicate_check_waits_without_holding_journal_then_reuses_result(self):
        entered, release = threading.Event(), threading.Event()
        first = True
        def run(*args, **kwargs):
            nonlocal first
            self.assert_journal_available()
            if first:
                first = False
                entered.set()
                self.assertTrue(release.wait(8))
            return self.successful_run(*args, **kwargs)
        self.mock_run.side_effect = run
        def second():
            self.assertTrue(entered.wait(8))
            self.assert_journal_available()
            release.set()
            return self.check()
        results = self.threads(self.check, second)
        self.assertEqual(sorted(r['reused'] for r in results), [False, True])
        self.assertEqual(len(self.calls), 2)

    def test_legacy_check_also_releases_journal_and_preserves_new_events(self):
        data = native.status(self.session)
        data.pop('verification_policy')
        native.atomic_json(Path(self.session), data)
        def run(*args):
            self.assert_journal_available()
            self.concurrent_update()
            return {'verdict': 'pass', 'code': 0}, 0
        with fixtures.patch.object(native.verify, 'cmd_run', side_effect=run):
            result = native.check(self.session, '1-1')
        self.assertEqual(result['checks']['project-tests']['result']['verdict'], 'pass')
        self.assert_updates_preserved()


if __name__ == '__main__':
    unittest.main()
