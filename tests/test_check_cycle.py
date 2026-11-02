"""Development selectors cannot replace the final gate; host receipts survive story boundaries."""
import contextlib
import json
import os
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import project_tests
import test_bridge
from execution_state import lease, current_lease_fd
from story_broker import Broker
import test_run_story


class CheckCycleTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_run_story.StoryTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.counter = self.root.parent / 'check-count'
        (self.root / 'backend/tests').mkdir(parents=True)
        (self.root / 'backend/tests/test_example.py').write_text('pass\n')
        self.fixture.fixture.git(self.root, 'add', 'backend')
        script = "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.write_text(p.read_text()+'x' if p.exists() else 'x'); print(sys.argv[2:])"
        self.command = shlex.join([sys.executable, '-c', script, str(self.counter)])
        config = (self.root / '.auto-bmad.toml').read_text().replace('command="true"', 'command=' + json.dumps(self.command))
        config += '\n[project_tests.development.backend]\ncommand=' + json.dumps(self.command) + '\ntargets=["backend/tests/test_*.py"]\n'
        self.fixture.save_config(config)
        self.fixture.prepare()

    @contextlib.contextmanager
    def broker(self):
        with lease(self.root):
            b = Broker(self.root, self.fixture.manifest, '1-3', self.fixture.base, current_lease_fd())
            try:
                yield b
            finally:
                b.close('completed')

    def test_targeted_host_test_does_not_satisfy_full_gate(self):
        with self.broker() as b:
            result = test_bridge.request(self.root, b.session_path, 'dev/backend',
                                         targets=['backend/tests/test_example.py::test_one[param with spaces]'])
            self.assertTrue(result['development'])
            self.assertIn('test_one[param with spaces]', result['tail'])
            self.assertEqual(self.counter.read_text(), 'x')
            final = b.project_tests()
            self.assertFalse(final['reused'])
            self.assertEqual(self.counter.read_text(), 'xx')
            self.assertTrue(b.project_tests()['reused'])
            self.assertIn('controller checkpoint', b.development_policy())

    def test_checkpoint_rechecks_pending_failed_gate_after_targeted_repair(self):
        with self.broker() as b:
            b.require_implementer = False
            b.manifest["review_layers"] = []
            failure = b.tests("test -f fixed.py", 10)
            b.begin_test_repair(failure['failure_id'])
            (self.root / 'fixed.py').write_text('fixed = True\n')
            test_bridge.request(self.root, b.session_path, 'dev/backend',
                                targets=['backend/tests/test_example.py'])
            self.assertIsNotNone(b.pending_test_repair)
            result = b.handle({'action': 'checkpoint', 'payload': None})
            self.assertEqual(result['code_tree'], b.tree())
            self.assertIsNone(b.pending_test_repair)
            self.assertEqual(b.repair_counts['tests'], 1)
            self.assertEqual(self.counter.read_text(), 'xx')  # dev plus final, never just dev

    def test_checkpoint_rejects_unresolved_original_check_despite_green_dev(self):
        with self.broker() as b:
            b.require_implementer = False
            b.manifest["review_layers"] = []
            failure = b.tests('false', 10)
            b.begin_test_repair(failure['failure_id'])
            test_bridge.request(self.root, b.session_path, 'dev/backend',
                                targets=['backend/tests/test_example.py'])
            with self.assertRaisesRegex(ValueError, 'repaired checks must pass'):
                b.handle({'action': 'checkpoint', 'payload': None})
            self.assertEqual(b.checkpoints, [])
            self.assertEqual(b.test_no_progress, 1)

    def test_explicit_fallback_sticks_and_rechecks_after_new_product_change(self):
        config = (self.root / '.auto-bmad.toml').read_text()
        config += ('\n[project_tests.scopes.frontend]\npaths=["app.py"]\ncommand="true"\n'
                   '[project_tests.fallback]\ncommand=' + json.dumps(self.command) + '\n'
                   '[project_tests]\nbaseline=false\n')
        self.fixture.save_config(config)
        self.fixture.prepare()
        with self.broker() as b:
            first = test_bridge.request(self.root, b.session_path, 'project-tests/@all')
            self.assertEqual(first['verdict'], 'pass')
            self.assertTrue(b.session['full_project_tests'])
            self.assertEqual(b.project_tests()['scopes'], ['@all'])
            self.assertEqual(self.counter.read_text(), 'x')
            (self.root / 'app.py').write_text('new_product = True\n')
            self.assertFalse(b.project_tests()['reused'])
            self.assertEqual(self.counter.read_text(), 'xx')

    def test_receipt_reused_between_stories_but_invalidated_by_product_changes(self):
        with self.broker() as b:
            b.project_tests()
        (self.root / '_bmad-output/implementation-artifacts/sprint-status.yaml').write_text('tracking changed\n')
        with self.broker() as b:
            self.assertTrue(b.project_tests()['reused'])
            self.assertEqual(self.counter.read_text(), 'x')
            (self.root / 'app.py').write_text('answer = 77\n')
            self.assertFalse(b.project_tests()['reused'])
            self.assertEqual(self.counter.read_text(), 'xx')

    def test_wave_number_does_not_invalidate_but_test_environment_does(self):
        with patch.dict(os.environ, {'AUTO_BMAD_WAVE': '1'}), self.broker() as b:
            b.project_tests()
        with patch.dict(os.environ, {'AUTO_BMAD_WAVE': '2'}), self.broker() as b:
            self.assertTrue(b.project_tests()['reused'])
        with patch.dict(os.environ, {'PYTEST_ADDOPTS': '--durations=10'}), self.broker() as b:
            self.assertFalse(b.project_tests()['reused'])
        self.assertEqual(self.counter.read_text(), 'xx')

    def test_explicit_rerun_invalidates_host_receipts(self):
        with self.broker() as b:
            b.project_tests()
        with self.broker() as b:
            result = test_bridge.request(self.root, b.session_path, 'project-tests', rerun=True)
            self.assertFalse(result['reused'])
            self.assertEqual(self.counter.read_text(), 'xx')

    def test_missing_targets_and_targets_on_full_gate_are_rejected(self):
        with self.broker() as b:
            self.assertIn('error', test_bridge.request(self.root, b.session_path, 'dev/backend'))
            self.assertIn('error', test_bridge.request(self.root, b.session_path, 'project-tests',
                                                     targets=['backend/tests/test_example.py']))
            self.assertFalse(self.counter.exists())

    def test_selectors_cannot_inject_options_shell_commands_or_escape_project(self):
        item = {'command': 'fixed-command', 'targets': ['backend/tests/test_*.py']}
        outside = self.root.parent / 'test_outside.py'
        outside.write_text('pass\n')
        (self.root / 'backend/tests/test_link.py').symlink_to(outside)
        for target in ['--override-ini=x', '../test_outside.py', '/tmp/test.py',
                       'backend/tests/../test_x.py', 'backend/tests/test_link.py',
                       'backend/tests/test_example.py\n;touch /tmp/injected']:
            with self.subTest(target=target), self.assertRaises(ValueError):
                project_tests.development_command(self.root, item, [target])
        selector = 'backend/tests/test_example.py::test_value[$(touch /tmp/injected)]'
        command = project_tests.development_command(self.root, item, [selector])
        self.assertEqual(shlex.split(command), ['fixed-command', selector])

    def test_failed_checks_are_not_shared_with_next_story(self):
        with self.broker() as b:
            self.assertEqual(b.tests('false', 10)['verdict'], 'problem')
        with self.broker() as b:
            self.assertFalse(b.tests('false', 10)['reused'])

    def test_source_mutation_during_tests_is_not_cached(self):
        command = shlex.join([sys.executable, '-c', "from pathlib import Path; p=Path('app.py'); p.write_text(p.read_text()+'# edit\\n')"])
        with self.broker() as b:
            b.tests(command, 10)
            self.assertFalse(b.shared_test_cache.get(b.tree(), command, 10))


if __name__ == '__main__':
    unittest.main()
