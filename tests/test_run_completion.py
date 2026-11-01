import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_completion as completion
from execution_state import lease, revision


class CompletionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.main = Path(self.tmp.name).resolve() / 'main'
        self.main.mkdir()
        self.git(self.main, 'init', '-b', 'main')
        self.git(self.main, 'config', 'user.email', 'test@example.invalid')
        self.git(self.main, 'config', 'user.name', 'Test')
        self.git(self.main, 'config', 'commit.gpgsign', 'false')
        self.sprint = '_bmad-output/implementation-artifacts/sprint-status.yaml'
        path = self.main / self.sprint
        path.parent.mkdir(parents=True)
        path.write_text('development_status:\n  epic-1: in-progress\n  1-1-example: backlog\n')
        (self.main / 'code.py').write_text('answer = 0\n')
        self.commit(self.main)
        self.snapshot = completion.target_snapshot(self.main)
        self.run = Path(self.tmp.name).resolve() / 'run'
        self.git(self.main, 'worktree', 'add', '-b', 'epic-1', str(self.run))
        (self.run / self.sprint).write_text('development_status:\n  epic-1: done\n  1-1-example: done\n')
        (self.run / 'code.py').write_text('answer = 42\n')
        self.commit(self.run)
        self.out = {'mode': 'epic', 'epic': 1, 'merge_policy': 'auto-main', 'execution_status': 'completed',
                    'run_completed': True, 'remaining': [], 'head_commit': revision(self.run), 'base_commit': self.snapshot['head'],
                    'stories': [{'story': '1-1', 'story_completed': True,
                                 'verification': {'status': 'pass', 'checks': {'project-tests': 'pass'}},
                                 'finish': {'ok': True}, 'questions': 'Editorial choice for later'}],
                    'done': 1, 'left': 0, 'hooks': [], 'session': 'fixture/session.json'}

    def git(self, root, *args):
        return subprocess.run(['git', '-C', str(root), *args], text=True, capture_output=True, check=True)

    def commit(self, root):
        self.git(root, 'add', '-A')
        self.git(root, 'commit', '-qm', 'fixture')

    def finalize(self):
        with lease(self.main):
            completion.finalize(self.main, self.run, self.snapshot, self.out)

    def assert_preserved(self):
        self.assertEqual(revision(self.main), self.snapshot['head'])
        self.assertTrue(self.run.exists())

    def test_epic_with_editorial_questions_lands_without_asking(self):
        self.finalize()
        self.assertEqual(self.out['merge']['status'], 'merged')
        self.assertEqual(revision(self.main), self.out['head_commit'])
        self.assertIn('Editorial choice', completion.report(self.out))

    def test_story_and_manual_runs_never_land(self):
        for key, value in [('mode', 'story'), ('merge_policy', 'manual')]:
            with self.subTest(key=key), patch.dict(self.out, {key: value}):
                self.finalize()
                self.assertEqual(self.out['merge']['status'], 'not_requested')
                self.assert_preserved()

    def test_failed_and_partial_runs_preserve_main(self):
        for status in ['blocked', 'timed_out', 'stopped', 'cancelled', 'needs_attention']:
            with self.subTest(status=status), patch.dict(self.out, {'execution_status': status, 'run_completed': False}):
                self.finalize()
                self.assertEqual(self.out['merge']['status'], 'not_merged')
                self.assert_preserved()

    def test_skipped_failed_and_missing_checks_refuse_merge(self):
        for checks in [{}, {'project-tests': 'skipped'}, {'project-tests': 'problem'}]:
            with self.subTest(checks=checks):
                self.out.update(run_completed=True, execution_status='completed')
                self.out['stories'][0]['verification']['checks'] = checks
                self.finalize()
                self.assertEqual(self.out['execution_status'], 'needs_attention')
                self.assert_preserved()

    def test_dirty_main_and_dirty_run_preserve_files(self):
        for root in (self.main, self.run):
            with self.subTest(root=root):
                self.out.update(run_completed=True, execution_status='completed')
                new = root / 'personal.txt'
                new.write_text('untouched')
                self.finalize()
                self.assertEqual(self.out['execution_status'], 'needs_attention')
                self.assertEqual(new.read_text(), 'untouched')
                self.assert_preserved()
                new.unlink()

    def test_changed_main_refuses_without_resetting_it(self):
        (self.main / 'other.txt').write_text('new work')
        self.commit(self.main)
        head = revision(self.main)
        self.finalize()
        self.assertEqual(self.out['execution_status'], 'needs_attention')
        self.assertEqual(revision(self.main), head)
        self.assertIn('integration checks are required', self.out['error'])

    def test_diverged_main_is_integrated_and_checked_before_landing(self):
        (self.main / 'other.py').write_text('other = 1')
        self.commit(self.main)
        previous = revision(self.main)
        checks = []
        def verify(root, base):
            checks.append((root, base))
            self.assertEqual(revision(self.main), previous)
            self.assertEqual((root / 'other.py').read_text(), 'other = 1')
            return {'verdict': 'pass'}
        with lease(self.main):
            completion.finalize(self.main, self.run, self.snapshot, self.out, verify)
        self.assertEqual(len(checks), 1)
        self.assertEqual(self.out['merge']['status'], 'merged')
        self.assertEqual((self.main / 'code.py').read_text(), 'answer = 42\n')
        self.assertEqual((self.main / 'other.py').read_text(), 'other = 1')

    def test_integration_failure_and_conflict_preserve_main(self):
        (self.main / 'other.py').write_text('other = 1')
        self.commit(self.main)
        head = revision(self.main)
        with lease(self.main):
            completion.finalize(self.main, self.run, self.snapshot, self.out, lambda *_: {'verdict': 'problem'})
        self.assertEqual(revision(self.main), head)
        self.assertEqual(self.out['merge']['status'], 'not_merged')
        self.assertIn('integration checks', self.out['error'])

    def test_conflict_does_not_leave_main_in_merge_state(self):
        (self.main / 'code.py').write_text('answer = 123\n')
        self.commit(self.main)
        head = revision(self.main)
        self.finalize()
        self.assertEqual(revision(self.main), head)
        self.assertEqual(self.out['merge']['status'], 'not_merged')
        self.assertIn('conflict', self.out['error'])
        self.assertTrue(completion.clean(self.main))
        self.assertTrue(completion.clean(self.run))

    def test_mixed_integration_checks_preserve_main(self):
        (self.main / 'other.py').write_text('other = 1')
        self.commit(self.main)
        head = revision(self.main)
        checked = {'verdict': 'pass', 'checks': {'ui': {'verdict': 'pass'}, 'backend': {'verdict': 'skipped'}},
                   'skipped': [{'scope': 'backend', 'reason': 'same failure on the exact pre-story baseline'}]}
        with lease(self.main):
            completion.finalize(self.main, self.run, self.snapshot, self.out, lambda *_: checked)
        self.assertEqual(revision(self.main), head)
        self.assertEqual(self.out['merge']['status'], 'not_merged')
        self.assertIn('integration checks', self.out['error'])

    def test_mixed_wave_checks_preserve_main(self):
        self.out['waves'] = [{'stories': ['1-1', '1-2'], 'verification': {
            'verdict': 'pass', 'skipped': [{'scope': 'backend', 'reason': 'preexisting failure'}]}}]
        self.finalize()
        self.assert_preserved()
        self.assertEqual(self.out['merge']['status'], 'not_merged')
        self.assertIn('wave', self.out['error'])

    def test_cancel_before_landing_preserves_main(self):
        with lease(self.main):
            completion.finalize(self.main, self.run, self.snapshot, self.out, cancelled=lambda: True)
        self.assertIn('cancelled', self.out['error'])
        self.assert_preserved()

    def test_token_rows_aggregate_roles_and_keep_missing_effort_explicit(self):
        private = Path(self.tmp.name).resolve() / 'sessions'
        child = private / 'child'
        child.mkdir(parents=True)
        (child / 'manifest.json').write_text(json.dumps({'roles': {
            'reviewer-mid': {'profile_id': 'r', 'effort': 'high'},
            'reviewer-lite': {'profile_id': 'r', 'effort': 'high'}}}))
        calls = [{'id': str(i), 'role': role, 'profile_id': 'r', 'model_requested': 'gpt-6-astra',
                  'usage_status': 'complete', 'usage': {'input_tokens': 100, 'output_tokens': 20,
                                                       'cached_input_tokens': 80}}
                 for i, role in enumerate(['reviewer-mid', 'reviewer-lite'])]
        rows = [{'queue_id': 'queue', 'session': 'cli:child', 'calls': calls + [calls[0]]},
                {'queue_id': 'old', 'calls': [dict(calls[0], id='old')]}]
        with patch('stats.load', return_value=rows):
            result = completion.token_summary(self.main, private / 'queue/session.json')
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]['role'], result[0]['effort'], result[0]['total'], result[0]['cached']),
                         ('Reviewer', 'high', 240, 160))
        self.assertIn('Reviewer (GPT-6 Astra, high)', completion.token_table(result))
        calls[0]['usage_status'] = 'unavailable'
        calls[0]['usage'] = {}
        calls[0]['profile_id'] = 'mismatch'
        with patch('stats.load', return_value=rows):
            result = completion.token_summary(self.main, private / 'queue/session.json')
        self.assertIn('unavailable', completion.token_table(result))

    def test_russian_report_uses_approved_compact_role_table(self):
        self.out.update(language='Russian', token_summary=[{
            'role': 'StoryRunner', 'model': 'gpt-6.1-sol', 'effort': 'high',
            'total': 44576433, 'cached': 44168576, 'incomplete': 0, 'measured': 1, 'cache_measured': 1}])
        text = completion.report(self.out)
        self.assertIn('Эпик 1: завершён', text)
        self.assertIn('Роль (модель, effort)', text)
        self.assertIn('StoryRunner (GPT-6.1 Sol, high)', text)
        self.assertIn('44,58 млн', text)
        self.assertNotIn('44.58M', text)

    def test_changed_run_head_refuses(self):
        (self.run / 'other.txt').write_text('unverified')
        self.commit(self.run)
        self.finalize()
        self.assertEqual(self.out['execution_status'], 'needs_attention')
        self.assert_preserved()

    def test_active_target_is_not_taken_over(self):
        # Model a run launched from another linked source, with main busy elsewhere.
        with lease(self.main):
            completion.finalize(self.run, self.run, self.snapshot, self.out)
        self.assertEqual(self.out['execution_status'], 'needs_attention')
        self.assertIn('active execution', self.out['error'])
        self.assert_preserved()

    def test_unfinished_sprint_and_unverified_wave_refuse(self):
        self.out['waves'] = [{'stories': ['1-1', '1-2'], 'verification': {'verdict': 'skipped'}}]
        self.finalize()
        self.assert_preserved()
        self.out.update(waves=[], run_completed=True, execution_status='completed')
        (self.run / self.sprint).write_text('development_status:\n  1-1-example: backlog\n')
        self.commit(self.run)
        self.out['head_commit'] = revision(self.run)
        self.finalize()
        self.assertIn('sprint', self.out['error'])
        self.assert_preserved()

    def test_hook_questions_are_committed_without_overwriting_story_sections(self):
        path = self.run / completion.questions_file(1)
        path.write_text('# Questions\n<!-- auto-bmad:open-questions epic=1 -->\n\nHuman notes\n')
        self.commit(self.run)
        questions = [{'hook': 'planner', 'question': 'Choose wording later?', 'options': [{'id': 'a'}]}]
        for _ in range(2):
            completion.save_questions(self.run, 1, 'fixture', questions)
        self.assertEqual(path.read_text().count('Choose wording later?'), 1)
        self.assertIn('Human notes', path.read_text())
        self.assertTrue(completion.clean(self.run))

    def test_foreign_questions_file_is_preserved(self):
        path = self.run / completion.questions_file(1)
        path.write_text('Human-owned')
        self.commit(self.run)
        with self.assertRaisesRegex(ValueError, 'human-owned'):
            completion.save_questions(self.run, 1, 'fixture', [{'question': 'Later?'}])
        self.assertEqual(path.read_text(), 'Human-owned')

    def test_final_notification_has_merge_result_and_delivery_failure_is_reported(self):
        self.finalize()
        private = Path(self.tmp.name) / 'session'
        private.mkdir()
        cfg = {'hook': [{'name': 'notify', 'events': ['run-result'], 'command': 'false'}]}
        with patch.object(completion.ext, 'run_hook', return_value={'name': 'notify', 'ok': False, 'error': 'offline'}) as hook, \
             patch.object(completion.ext, 'log_event'):
            completion.publish(private, self.out, cfg, self.run)
        self.assertEqual(hook.call_args.args[1]['data']['merge']['status'], 'merged')
        self.assertIn('offline', (private / 'report.md').read_text())
        self.assertEqual(self.out['merge']['status'], 'merged')


if __name__ == '__main__':
    unittest.main()
