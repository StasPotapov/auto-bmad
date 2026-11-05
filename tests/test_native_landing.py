"""Existing land candidate pipeline must run the native gate before touching main."""
from unittest.mock import patch
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import land
import native_session as native
import native_verification
from test_land import RunWorktreeBase, write, commit, sh


class NativeLandingTest(RunWorktreeBase):
    def setUp(self):
        super().setUp()
        self.wt = self.start()['path']
        write(self.wt, 'feature.py', 'value = 1\n')
        commit(self.wt, 'feature')
        self.before = sh(self.repo, 'git', 'rev-parse', 'HEAD').strip()
        self.data = {'orchestration_policy': 'thin-root-v1', 'verification_policy': 'integration-full-v1'}
        self.session = str(Path(self.repo) / '.git/session-fixture.json')
        self.reader = patch.object(native, 'read_session', return_value=(None, self.data, None, None))
        self.reader.start()
        self.addCleanup(self.reader.stop)

    def gate(self, session, stories, candidate):
        self.assertEqual(sh(self.repo, 'git', 'rev-parse', 'HEAD').strip(), self.before)
        self.assertNotEqual(candidate, self.repo)
        self.assertTrue(os.path.isfile(os.path.join(candidate, 'feature.py')))
        self.data['integration_gate'] = {'verdict': 'pass', 'stories': stories,
            'git_tree': sh(candidate, 'git', 'rev-parse', 'HEAD^{tree}').strip()}
        return self.data['integration_gate']

    def test_combined_stories_share_one_pre_main_gate_and_keep_journal_worktrees(self):
        with patch.object(native_verification, 'integration', side_effect=self.gate) as gate:
            result, code = land.land(self.repo, 'bmad/epic-1', native_session=self.session,
                                     stories=['1-1', '1-2'])
        self.assertEqual(code, 0, result)
        self.assertTrue(result['merged'])
        self.assertEqual(gate.call_count, 1)
        self.assertTrue(os.path.isdir(self.wt))
        with patch.object(native_verification, 'integration', side_effect=AssertionError('already landed')):
            repeated, code = land.land(self.repo, 'bmad/epic-1', native_session=self.session, stories=['1-1', '1-2'])
        self.assertEqual(code, 0, repeated)
        self.assertTrue(os.path.isdir(self.wt))
        self.assertTrue(sh(self.repo, 'git', 'branch', '--list', 'bmad/epic-1').strip())

    def test_failed_gate_preserves_main_and_candidate_for_focused_repair(self):
        with patch.object(native_verification, 'integration', return_value={'verdict': 'problem'}):
            result, code = land.land(self.repo, 'bmad/epic-1', native_session=self.session, stories=['1-1'])
        self.assertEqual(code, 2, result)
        self.assertEqual(sh(self.repo, 'git', 'rev-parse', 'HEAD').strip(), self.before)
        self.assertTrue(os.path.isdir(result['tests']['worktree']))

    def test_target_change_while_gate_runs_requires_new_candidate(self):
        def changing_gate(*args):
            result = self.gate(*args)
            write(self.repo, 'concurrent.py', 'change = 1\n')
            commit(self.repo, 'concurrent main change')
            return result
        with patch.object(native_verification, 'integration', side_effect=changing_gate):
            result, code = land.land(self.repo, 'bmad/epic-1', native_session=self.session, stories=['1-1'])
        self.assertEqual(code, 2, result)
        self.assertIn('target changed', result['error'])
        self.assertFalse(os.path.isfile(os.path.join(self.repo, 'feature.py')))

    def test_no_tests_cannot_bypass_new_native_landing_policy(self):
        result, code = land.land(self.repo, 'bmad/epic-1', with_tests=False,
                                 native_session=self.session, stories=['1-1'])
        self.assertEqual(code, 2, result)
        self.assertEqual(sh(self.repo, 'git', 'rev-parse', 'HEAD').strip(), self.before)
