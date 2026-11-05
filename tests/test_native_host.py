import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import native_host as host
import native_session as native


class NativeHostTest(unittest.TestCase):
    def setUp(self):
        self.thread = str(uuid.uuid4())
        self.turn = str(uuid.uuid4())
        self.data = {'session': '/fixture/session.json', 'status': 'running',
                     'technical_limit': 2, 'roles': {}, 'stories': {
                         '1-1': {'status': 'running', 'phase': 'verification'},
                         '1-2': {'status': 'pending', 'phase': 'pending'}}}
        self.binding = {'thread_id': self.thread, 'automation_id': 'host-automation-1'}
        with patch.object(host, 'runtime', return_value='/fixture/runtime'):
            self.state = host.bind(self.data, None, self.binding)
        runtime_patch = patch.object(host, 'runtime', return_value='/fixture/runtime')
        self.real_runtime = host.runtime
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)

    def request(self, **changes):
        return {**self.binding, 'turn_id': self.turn, 'turn_status': 'completed',
                'cause': 'premature-final', **changes}

    def test_pending_epic_resumes_after_premature_final_without_changing_story_state(self):
        before = copy.deepcopy(self.data)
        result = host.decide(self.data, self.state, self.request())
        self.assertEqual(result['action'], 'continue')
        self.assertEqual(result['runtime'], '/fixture/runtime')
        self.assertFalse(result['model_started'])
        self.assertEqual(self.data, before)

    def test_interruption_stops_even_with_a_claim_or_a_fake_technical_cause(self):
        host.decide(self.data, self.state, self.request())
        result = host.decide(self.data, self.state, self.request(turn_status='interrupted', cause='transport'))
        self.assertEqual(result['action'], 'stop')
        self.assertFalse(self.state['armed'])
        # A later successful heartbeat cannot hide the original stop.
        result = host.decide(self.data, self.state, self.request(turn_id=str(uuid.uuid4())))
        self.assertEqual(result['action'], 'stop')

    def test_no_recovery_while_busy(self):
        result = host.decide(self.data, self.state, self.request(turn_status='active'))
        self.assertEqual(result['action'], 'wait')
        self.assertEqual(self.state['attempts'], [])

    def test_explicit_stop_overrides_active_or_claimed_turn(self):
        host.decide(self.data, self.state, self.request())
        for status in ('active', 'completed'):
            state = copy.deepcopy(self.state)
            self.assertEqual(host.decide(self.data, state,
                self.request(turn_status=status, stop_requested=True))['action'], 'stop')
            self.assertFalse(state['armed'])

    def test_terminal_session_input_approval_and_unknown_state_disarm(self):
        for status in ('completed', 'cancelled', 'blocked'):
            with self.subTest(session=status):
                data = {**self.data, 'status': status}
                self.assertEqual(host.decide(data, copy.deepcopy(self.state), self.request())['action'], 'stop')
        for status in ('waiting-user', 'waiting-approval', 'unknown'):
            with self.subTest(host=status):
                self.assertEqual(host.decide(self.data, copy.deepcopy(self.state),
                                            self.request(turn_status=status))['action'], 'stop')

    def test_blocked_story_cannot_be_resumed_by_running_session(self):
        self.data['stories']['1-1']['phase'] = 'blocked'
        self.assertEqual(host.decide(self.data, self.state, self.request())['action'], 'stop')

    def test_only_confirmed_technical_failures_are_retried(self):
        for cause in ('transport', 'host-exit'):
            self.assertEqual(host.decide(self.data, copy.deepcopy(self.state),
                self.request(turn_status='failed', cause=cause))['action'], 'continue')
        for cause in (None, 'auth', 'budget', 'permission', 'transport'):
            status = 'completed' if cause == 'transport' else 'failed'
            self.assertEqual(host.decide(self.data, copy.deepcopy(self.state),
                self.request(turn_status=status, cause=cause))['action'], 'stop')

    def test_duplicate_delivery_is_claimed_once_and_budget_survives_new_turns(self):
        first = host.decide(self.data, self.state, self.request())
        self.assertEqual(first['action'], 'continue')
        self.assertEqual(host.decide(self.data, self.state, self.request())['action'], 'already-claimed')
        self.assertEqual(len(self.state['attempts']), 1)
        self.assertEqual(host.decide(self.data, self.state,
                         self.request(turn_id=str(uuid.uuid4())))['action'], 'continue')
        self.assertEqual(host.decide(self.data, self.state,
                         self.request(turn_id=str(uuid.uuid4())))['action'], 'stop')

    def test_only_finalized_progress_resets_host_budget(self):
        self.data['technical_limit'] = 1
        host.decide(self.data, self.state, self.request())
        self.data['stories']['1-1']['status'] = 'completed'
        result = host.decide(self.data, self.state, self.request(turn_id=str(uuid.uuid4())))
        self.assertEqual(result['action'], 'continue')
        self.assertEqual(len(self.state['attempts']), 2)

    def test_wrong_host_and_invalid_ids_do_not_mutate_state(self):
        before = copy.deepcopy(self.state)
        for change in ({'thread_id': str(uuid.uuid4())}, {'automation_id': 'another'},
                       {'turn_id': 'invented'}, {'turn_status': 'made-up'}):
            with self.assertRaises(ValueError):
                host.decide(self.data, self.state, self.request(**change))
            self.assertEqual(self.state, before)

    def test_registration_retry_never_rearms_and_duplicate_binding_is_rejected(self):
        self.state['armed'] = False
        with patch.object(host, 'runtime', return_value='/fixture/runtime'):
            self.assertFalse(host.bind(self.data, self.state, self.binding)['armed'])
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                host.bind(self.data, self.state, {**self.binding, 'automation_id': 'other'})

    def test_runtime_is_original_package_not_current_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            (package / 'scripts').mkdir()
            (package / 'scripts/native_session.py').touch()
            self.data['roles'] = {'verifier': {'prompt': str(package / 'prompts/roles/verifier.md')}}
            self.assertEqual(self.real_runtime(self.data), str(package.resolve()))
            self.data['roles']['other'] = {'prompt': '/other/prompts/roles/role.md'}
            with self.assertRaises(ValueError):
                self.real_runtime(self.data)

    def test_explicit_rearm_preserves_budget_and_cannot_replay_authorization(self):
        host.decide(self.data, self.state, self.request())
        host.decide(self.data, self.state, self.request(turn_status='interrupted'))
        fresh = str(uuid.uuid4())
        bound = host.bind(self.data, self.state, {**self.binding, 'resume_authorization_turn': fresh})
        self.assertTrue(bound['armed'])
        self.assertEqual(len(bound['attempts']), 1)
        with self.assertRaises(ValueError):
            host.bind(self.data, self.state, {**self.binding, 'resume_authorization_turn': fresh})

    def test_old_authorization_cannot_cross_two_later_stop_cycles(self):
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        for authorization in (first, second):
            host.decide(self.data, self.state,
                        self.request(turn_status='interrupted', turn_id=str(uuid.uuid4())))
            host.bind(self.data, self.state, {**self.binding, 'resume_authorization_turn': authorization})
        host.decide(self.data, self.state,
                    self.request(turn_status='interrupted', turn_id=str(uuid.uuid4())))
        before = copy.deepcopy(self.state)
        with self.assertRaises(ValueError):
            host.bind(self.data, self.state, {**self.binding, 'resume_authorization_turn': first})
        self.assertEqual(self.state, before)
        self.assertFalse(self.state['armed'])

    def test_rearm_retains_legacy_authorization_when_starting_the_history(self):
        old = str(uuid.uuid4())
        self.state.update(armed=False, resume_authorization_turn=old)
        host.bind(self.data, self.state,
                  {**self.binding, 'resume_authorization_turn': str(uuid.uuid4())})
        self.state['armed'] = False
        with self.assertRaises(ValueError):
            host.bind(self.data, self.state, {**self.binding, 'resume_authorization_turn': old})

    def test_cli_persists_claim_without_touching_canonical_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            common = Path(directory)
            folder = common / 'auto-bmad-native' / 'fixture'
            folder.mkdir(parents=True)
            session = folder / 'session.json'
            self.data['session'] = str(session)
            session.write_text(json.dumps(self.data))
            original = session.read_bytes()
            request = common / 'request.json'
            with patch.object(native, 'read_session', side_effect=lambda _: (
                    session, json.loads(session.read_text()), common, common)), \
                    patch.object(host, 'runtime', return_value='/fixture/runtime'):
                host.run(session, 'host-bind', self.binding)
                request.write_text(json.dumps(self.request()))
                with patch('sys.stdout'):
                    self.assertEqual(native.main(['host-recover', '--session', str(session),
                                                  '--request', str(request)]), 0)
                result = host.run(session, 'host-recover', self.request())
                self.assertEqual(result['action'], 'already-claimed')
                self.assertEqual(session.read_bytes(), original)
                self.assertEqual(len(json.loads((folder / 'host-continuation.json').read_text())['attempts']), 1)


if __name__ == '__main__':
    unittest.main()
