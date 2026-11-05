"""File-backed checkpoints stay compact and preserve journal provenance."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import agent_config
import native_session as native
import native_tasks as tasks
import test_native_session


class NativeTaskTest(unittest.TestCase):
    def setUp(self):
        fixture = test_native_session.NativeSessionTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root, self.session = fixture.root, fixture.session
        self.fixture = fixture
        data = native.status(self.session)
        data['orchestration_policy'] = 'thin-root-v1'
        data['roles'] = agent_config.resolve(native.config(self.root)[0])['roles']
        native.atomic_json(Path(self.session), data)

    def prepare(self, checkpoint='triage', role='triager'):
        return tasks.prepare(session=self.session, story='1-1', role=role, checkpoint=checkpoint)

    def running(self):
        envelope = self.prepare()
        path = envelope['task_file']
        binding = tasks.start(path, 'host-fresh-1')
        spec = json.loads(Path(path).read_text())
        report = Path(path).parent / 'full-report.md'
        report.write_text('FULL_FINDING ' * 100000)
        receipt = {**spec['receipt_template'], 'agent_id': binding['agent_id'],
                   'task_hash': binding['task_hash'], 'tree': native.code_tree(self.root),
                   'artifacts': [{'path': str(report), 'sha256': tasks.file_hash(report)}]}
        native.atomic_json(Path(spec['result_file']), receipt)
        return path, spec, receipt

    def accept(self, path):
        return tasks.result(path, 'host-fresh-1', True)

    def test_clean_bounded_envelope_uses_configured_model_and_pinned_prompt(self):
        data = native.status(self.session)
        data['stories']['1-1']['long_history'] = 'large finding ' * 10000
        native.atomic_json(Path(self.session), data)
        envelope = self.prepare()
        self.assertLessEqual(len(json.dumps(envelope).encode()), tasks.MAX_OUTPUT)
        self.assertEqual(envelope['spawn']['fork_turns'], 'none')
        self.assertEqual(envelope['spawn']['model'], data['roles']['triager']['model'])
        self.assertEqual(envelope['spawn']['reasoning_effort'], data['roles']['triager']['effort'])
        self.assertNotIn('large finding', json.dumps(envelope))
        spec = json.loads(Path(envelope['task_file']).read_text())
        self.assertEqual(tasks.file_hash(spec['prompt']), tasks.file_hash(spec['prompt_source']))
        self.assertIn('long_history', spec['story_state'])

    def test_large_report_stays_on_disk_and_result_registers_completion(self):
        path, spec, receipt = self.running()
        compact = self.accept(path)
        self.assertLessEqual(len(json.dumps(compact).encode()), tasks.MAX_OUTPUT)
        self.assertNotIn('FULL_FINDING', json.dumps(compact))
        data = native.status(self.session)
        self.assertEqual(data['stories']['1-1']['agents']['host-fresh-1']['status'], 'completed')
        self.assertEqual(data['tasks'][spec['task_id']]['receipt_hash'], tasks.file_hash(spec['result_file']))
        self.assertEqual(data['events'][-1]['event'], 'task-result')
        self.assertEqual(data['stories']['1-1']['status'], 'running')
        with self.assertRaisesRegex(ValueError, 'not running'):
            self.accept(path)

    def test_role_story_and_profile_names_preserve_identity_and_retry_uniqueness(self):
        self.assertEqual(tasks.task_names('13-6', 'implementer', 'implementation',
                         {'model': 'gpt-6.1-sol', 'effort': 'high'}),
                         ('13.6 Impl [Sol·h]', '13_6_impl_sol_h'))
        data = native.status(self.session)
        names = set()
        for role in data['roles']:
            for checkpoint in ('review', 'revalidation'):
                for _ in range(2):
                    envelope = self.prepare(checkpoint, role)
                    spec = json.loads(Path(envelope['task_file']).read_text())
                    profile = data['roles'][role]
                    self.assertTrue(envelope['display_name'].startswith(f"1.1 {tasks.ROLE_LABELS[role]} ["))
                    self.assertEqual(spec['display_name'], envelope['display_name'])
                    self.assertEqual(spec['profile'], profile)
                    name = envelope['spawn']['task_name']
                    self.assertRegex(name, '^1_1_' + tasks.ROLE_LABELS[role].lower() + '_[a-z0-9_]+$')
                    self.assertNotIn(spec['task_id'][:12], name)
                    self.assertEqual(spec['task_name'], name)
                    self.assertNotIn(name, names)
                    names.add(name)
                    self.assertNotIn('display_name', envelope['spawn'])
                    self.assertEqual(Path(envelope['task_file']).parent.name, spec['task_id'])
                    saved = native.status(self.session)['tasks'][spec['task_id']]
                    self.assertEqual(saved['task_hash'], native.digest(spec))

    def test_compact_titles_keep_actual_model_effort_and_distinct_review_roles(self):
        for model, effort, label in [('gpt-6.1-sol', 'medium', 'Sol·m'),
                ('gpt-6.1-terra', 'xhigh', 'Terra·xh'), ('gpt-6-luna', 'low', 'Luna·l'),
                ('gpt-6-astra', 'high', 'Astra·h'), ('gpt-6-sol', 'max', 'Sol6·max'),
                ('gpt-6.2-sol', 'ultra', 'Sol6.2·ultra'),
                ('custom-model', 'custom-effort', 'custom-model·custom-effort')]:
            with self.subTest(model=model, effort=effort):
                display, _ = tasks.task_names('13-6', 'implementer', 'implementation',
                                             {'model': model, 'effort': effort})
                self.assertEqual(display, f'13.6 Impl [{label}]')
        labels = {'story-runner': 'Runner', 'context-compiler': 'Context', 'blind-hunter': 'Blind',
                  'edge-case-hunter': 'Edge', 'intent-alignment': 'Intent', 'verification-gap': 'Gap',
                  'triager': 'Triager', 'verifier': 'Verify', 'custom-role': 'custom-role'}
        for role, label in labels.items():
            display, _ = tasks.task_names('13-6', role, 'review',
                                         {'model': 'gpt-6.1-sol', 'effort': 'medium'})
            self.assertEqual(display, f'13.6 {label} [Sol·m]')

    def test_names_reserve_retries_across_checkpoints_and_concurrent_prepares(self):
        first = self.prepare('review', 'implementer')
        base = first['spawn']['task_name']
        self.assertEqual(base, '1_1_impl_sol_h')
        with ThreadPoolExecutor(max_workers=4) as pool:
            envelopes = list(pool.map(lambda _: self.prepare('revalidation', 'implementer'), range(4)))
        self.assertEqual({item['spawn']['task_name'] for item in envelopes},
                         {f'{base}_{attempt}' for attempt in range(2, 6)})
        self.assertEqual(native.status(self.session)['task_name_counts'][base], 5)
        for envelope in [first, *envelopes]:
            spec = json.loads(Path(envelope['task_file']).read_text())
            self.assertFalse(any('set its title' in item for item in spec['instructions']))
        self.assertEqual(self.prepare('checks', 'implementer')['spawn']['task_name'], base + '_6')

    def test_names_skip_legacy_host_names_without_changing_old_tasks(self):
        data = native.status(self.session)
        old = {'task_hash': 'unchanged', 'agent_id': '/root/1_1_impl_sol_h',
               'status': 'completed'}
        data['tasks'] = {'legacy': old, 'old-long-name': {
            'agent_id': '/root/1_1_implementer_gpt_6_1_sol_medium_abcdef012345',
            'status': 'completed'}}
        data['stories']['1-1']['agents']['/root/1_1_impl_sol_h_2'] = {'status': 'completed'}
        native.atomic_json(Path(self.session), data)
        envelope = self.prepare('implementation', 'implementer')
        self.assertEqual(envelope['spawn']['task_name'], '1_1_impl_sol_h_3')
        self.assertEqual(native.status(self.session)['tasks']['legacy'], old)
        self.assertEqual(self.prepare('review', 'implementer')['spawn']['task_name'], '1_1_impl_sol_h_4')

    def test_two_sessions_in_same_repo_reserve_distinct_host_names(self):
        first = self.prepare('implementation', 'implementer')
        first_id = '/root/' + first['spawn']['task_name']
        tasks.start(first['task_file'], first_id)
        tasks.stop(first['task_file'], first_id, 'stopped', 'Fixture host joined', True)
        native.control(self.session, 'cancel')
        old_bytes = Path(self.session).read_bytes()
        second_data = native.init(self.root, self.fixture.prepared)
        second_session = second_data['session']
        second_data['roles'] = agent_config.resolve(native.config(self.root)[0])['roles']
        native.atomic_json(Path(second_session), second_data)
        second = tasks.prepare(session=second_session, story='1-1', role='implementer',
                               checkpoint='implementation')
        second_id = '/root/' + second['spawn']['task_name']
        self.assertEqual(first_id, '/root/1_1_impl_sol_h')
        self.assertEqual(second_id, '/root/1_1_impl_sol_h_2')
        binding = tasks.start(second['task_file'], second_id)
        self.assertEqual(binding['agent_id'], second_id)
        self.assertEqual(Path(self.session).read_bytes(), old_bytes)

    def test_wrong_binding_or_missing_host_observation_is_rejected(self):
        path, spec, receipt = self.running()
        for field, value in [('story', '9-9'), ('agent_id', 'other'), ('task_hash', 'old'), ('session', None)]:
            with self.subTest(field=field):
                native.atomic_json(Path(spec['result_file']), {**receipt, field: value})
                with self.assertRaisesRegex(ValueError, 'binding'):
                    self.accept(path)
        native.atomic_json(Path(spec['result_file']), receipt)
        with self.assertRaisesRegex(ValueError, 'confirm-completed'):
            tasks.result(path, 'host-fresh-1')
        self.assertEqual(native.status(self.session)['tasks'][spec['task_id']]['status'], 'running')

    def test_task_prompt_artifact_and_current_tree_tampering_rejected(self):
        path, spec, receipt = self.running()
        original = Path(path).read_bytes()
        native.atomic_json(Path(path), {**spec, 'checkpoint': 'finalization'})
        with self.assertRaisesRegex(ValueError, 'changed or was not issued'):
            self.accept(path)
        Path(path).write_bytes(original)
        prompt = Path(spec['prompt'])
        saved = prompt.read_bytes()
        prompt.write_text('altered role')
        with self.assertRaisesRegex(ValueError, 'prompt changed'):
            self.accept(path)
        prompt.write_bytes(saved)
        artifact = Path(receipt['artifacts'][0]['path'])
        artifact.write_text('tampered evidence')
        with self.assertRaisesRegex(ValueError, 'artifact missing or changed'):
            self.accept(path)
        receipt['artifacts'][0]['sha256'] = tasks.file_hash(artifact)
        native.atomic_json(Path(spec['result_file']), receipt)
        (self.root / 'code.py').write_text('value = 2\n')
        with self.assertRaisesRegex(ValueError, 'tree is stale'):
            self.accept(path)

    def test_fresh_identity_and_supersession(self):
        first = self.prepare()
        second = self.prepare()
        with self.assertRaisesRegex(ValueError, 'superseded'):
            tasks.start(first['task_file'], 'host-fresh-1')
        tasks.start(second['task_file'], 'host-fresh-1')
        with self.assertRaisesRegex(ValueError, 'already has a running'):
            self.prepare()
        other = self.prepare('checks', 'verifier')
        with self.assertRaisesRegex(ValueError, 'already used'):
            tasks.start(other['task_file'], 'host-fresh-1')
        with self.assertRaisesRegex(ValueError, 'already started'):
            tasks.start(second['task_file'], 'host-fresh-2')

    def test_oversized_report_inline_and_unknown_fields_rejected(self):
        path, spec, receipt = self.running()
        native.atomic_json(Path(spec['result_file']), {**receipt, 'findings': 'report'})
        with self.assertRaisesRegex(ValueError, 'fields'):
            self.accept(path)
        native.atomic_json(Path(spec['result_file']), {**receipt, 'actions': ['x' * 200]})
        with self.assertRaisesRegex(ValueError, 'short decisions'):
            self.accept(path)
        Path(spec['result_file']).write_text('x' * (tasks.MAX_RECEIPT + 1))
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            self.accept(path)

    def test_bootstrap_uses_role_config_without_plan_and_binds_created_session(self):
        self.fixture.plan_patch.stop()
        with patch.object(native, 'plan', side_effect=AssertionError('root must not plan')):
            envelope = tasks.prepare(repo=self.root, arg='1-1 --deep', host_limit=4, accounting_unavailable_reason='Synthetic host exposes no root UUIDs')
        spec = json.loads(Path(envelope['task_file']).read_text())
        self.assertEqual(spec['level'], 'deep')
        self.assertEqual(spec['role'], 'story-runner')
        self.assertTrue(envelope['display_name'].startswith('bootstrap Runner ['))
        self.assertRegex(envelope['spawn']['task_name'], '^bootstrap_runner_[a-z0-9_]+$')
        binding = tasks.start(envelope['task_file'], 'bootstrap-worker')
        report = Path(spec['result_file']).parent / 'bootstrap.md'
        report.write_text('Prepared session and schedule evidence.')
        receipt = {**spec['receipt_template'], 'task_hash': binding['task_hash'],
            'agent_id': 'bootstrap-worker', 'created_session': self.session,
            'artifacts': [{'path': str(report), 'sha256': tasks.file_hash(report)}]}
        native.atomic_json(Path(spec['result_file']), {**receipt, 'created_session': None})
        with self.assertRaisesRegex(ValueError, 'needs its created_session'):
            tasks.result(envelope['task_file'], 'bootstrap-worker', True)
        native.atomic_json(Path(spec['result_file']), receipt)
        self.assertEqual(tasks.result(envelope['task_file'], 'bootstrap-worker', True)['created_session'], self.session)

    def test_long_bootstrap_request_never_enters_envelope(self):
        request = '1-1 ' + ('LONG_USER_SCOPE ' * 10000)
        envelope = tasks.prepare(repo=self.root, arg=request, host_limit=4, accounting_unavailable_reason='Synthetic host exposes no root UUIDs')
        self.assertLessEqual(len(json.dumps(envelope).encode()), tasks.MAX_OUTPUT)
        self.assertNotIn('LONG_USER_SCOPE', json.dumps(envelope))
        self.assertEqual(json.loads(Path(envelope['task_file']).read_text())['request'], request)

    def test_bootstrap_names_use_actual_profile_and_reserve_retries(self):
        options = dict(repo=self.root, arg='1-1', host_limit=4,
                       accounting_unavailable_reason='Synthetic host exposes no root UUIDs')
        first = tasks.prepare(**options)
        second = tasks.prepare(**options)
        self.assertEqual(first['spawn']['task_name'], 'bootstrap_runner_sol_m')
        self.assertEqual(second['spawn']['task_name'], 'bootstrap_runner_sol_m_2')
        spec = json.loads(Path(first['task_file']).read_text())
        self.assertIsNone(spec['story'])
        self.assertEqual(first['spawn']['model'], spec['profile']['model'])
        self.assertEqual(first['spawn']['reasoning_effort'], spec['profile']['effort'])
        # A host can disambiguate a name from another journal; binding keeps its real ID.
        binding = tasks.start(second['task_file'], '/root/bootstrap_runner_sol_m_9')
        self.assertEqual(binding['agent_id'], '/root/bootstrap_runner_sol_m_9')
        self.assertEqual(binding['task_hash'], native.digest(json.loads(Path(second['task_file']).read_text())))

    def test_concurrent_starts_have_one_winner_and_invalid_result_is_atomic(self):
        envelope = self.prepare()
        def attempt(identity):
            try:
                return tasks.start(envelope['task_file'], identity)
            except ValueError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, ('host-one', 'host-two')))
        self.assertEqual(sum(isinstance(value, dict) for value in outcomes), 1)
        self.assertEqual(sum('already started' in value for value in outcomes if isinstance(value, str)), 1)
        spec = json.loads(Path(envelope['task_file']).read_text())
        binding = next(value for value in outcomes if isinstance(value, dict))
        receipt = {**spec['receipt_template'], 'task_hash': binding['task_hash'],
                   'agent_id': binding['agent_id'], 'artifacts': []}
        native.atomic_json(Path(spec['result_file']), receipt)
        before = Path(self.session).read_bytes()
        with self.assertRaisesRegex(ValueError, 'evidence artifacts'):
            tasks.result(envelope['task_file'], binding['agent_id'], True)
        self.assertEqual(Path(self.session).read_bytes(), before)

    def test_planning_only_bootstrap_needs_no_session(self):
        envelope = tasks.prepare(repo=self.root, arg='1-1', planning_only=True, host_limit=4, accounting_unavailable_reason='Synthetic host exposes no root UUIDs')
        spec = json.loads(Path(envelope['task_file']).read_text())
        binding = tasks.start(envelope['task_file'], 'planning-worker')
        plan = Path(spec['result_file']).parent / 'plan.json'
        plan.write_text('{"planned": true}')
        receipt = {**spec['receipt_template'], 'task_hash': binding['task_hash'],
                   'agent_id': 'planning-worker', 'next': 'none',
                   'artifacts': [{'path': str(plan), 'sha256': tasks.file_hash(plan)}]}
        native.atomic_json(Path(spec['result_file']), receipt)
        self.assertIsNone(tasks.result(envelope['task_file'], 'planning-worker', True)['created_session'])
        self.assertIn('Do not initialize a journal', spec['instructions'][0])

    def test_receipt_changed_during_validation_does_not_commit(self):
        path, spec, receipt = self.running()
        before = Path(self.session).read_bytes()
        real_hash = tasks.file_hash
        def changed(target):
            return '0' * 64 if str(target) == spec['result_file'] else real_hash(target)
        with patch.object(tasks, 'file_hash', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed during validation'):
                self.accept(path)
        self.assertEqual(Path(self.session).read_bytes(), before)

    def test_bootstrap_public_levels_match_configured_role_and_defaults(self):
        config = self.root / '.auto-bmad.toml'
        with config.open('a') as stream:
            stream.write('[run]\nlevel="deep"\n')
            for level, effort in [('fast', 'low'), ('normal', 'medium'), ('deep', 'high')]:
                stream.write(f'[executors.codex.levels.{level}.roles.story-runner]\n'
                             f'model="fixture-{level}"\neffort="{effort}"\n')
        for argument, level in [('1-1 --fast', 'fast'), ('1-1 --normal', 'normal'),
                                ('1-1 --deep', 'deep'), ('1-1', 'deep')]:
            with self.subTest(argument=argument):
                envelope = tasks.prepare(repo=self.root, arg=argument, host_limit=4,
                    accounting_unavailable_reason='Host does not expose root UUIDs')
                profile = agent_config.resolve(native.config(self.root)[0], level)['roles']['story-runner']
                self.assertEqual(envelope['spawn']['model'], profile['model'])
                self.assertEqual(envelope['spawn']['reasoning_effort'], profile['effort'])
                self.assertEqual(json.loads(Path(envelope['task_file']).read_text())['level'], level)
        with self.assertRaisesRegex(ValueError, 'two different levels'):
            tasks.prepare(repo=self.root, arg='1-1 --fast --deep', host_limit=4,
                          accounting_unavailable_reason='No root UUIDs')

    def test_bootstrap_requires_real_host_metadata_or_explicit_unknown_accounting(self):
        thread = '00000000-0000-0000-0000-000000000001'
        turn = '00000000-0000-0000-0000-000000000002'
        for kwargs, error in [({}, 'host-limit'), ({'host_limit': 1}, 'host-limit'),
                ({'host_limit': 4}, 'accounting-unavailable-reason'),
                ({'host_limit': 4, 'root_thread_id': thread}, 'provided together'),
                ({'host_limit': 4, 'root_thread_id': 'guessed', 'root_turn_id': turn}, 'exact UUIDs')]:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, error):
                tasks.prepare(repo=self.root, **kwargs)
        envelope = tasks.prepare(repo=self.root, host_limit=4, root_thread_id=thread, root_turn_id=turn)
        metadata = json.loads(Path(envelope['task_file']).read_text())['host_metadata']
        self.assertEqual(metadata['host_limit'], 4)
        self.assertEqual((metadata['root_thread_id'], metadata['root_turn_id']), (thread, turn))
        self.assertIsNone(metadata['accounting_unavailable_reason'])

    def test_receiptless_stop_requires_terminal_observation_and_fresh_producer(self):
        envelope = self.prepare()
        path = envelope['task_file']
        tasks.start(path, 'crashed-worker')
        before = Path(self.session).read_bytes()
        with self.assertRaisesRegex(ValueError, 'confirm-terminal'):
            tasks.stop(path, 'crashed-worker', 'failed', 'Host crash')
        with self.assertRaisesRegex(ValueError, 'this producer'):
            tasks.stop(path, 'another-worker', 'failed', 'Host crash', True)
        self.assertEqual(Path(self.session).read_bytes(), before)
        result = tasks.stop(path, 'crashed-worker', 'failed', 'Host terminal crash observed', True)
        self.assertIsNone(result['receipt'])
        self.assertEqual(native.status(self.session)['stories']['1-1']['agents']['crashed-worker']['status'], 'failed')
        fresh = self.prepare()
        with self.assertRaisesRegex(ValueError, 'already used'):
            tasks.start(fresh['task_file'], 'crashed-worker')
        tasks.start(fresh['task_file'], 'fresh-worker')
        self.assertEqual(native.status(self.session)['stories']['1-1']['agents']['fresh-worker']['status'], 'running')

    def test_receiptless_stop_recovers_after_cancel_and_authorized_resume(self):
        envelope = self.prepare()
        path = envelope['task_file']
        tasks.start(path, 'stopped-worker')
        self.fixture.record('agent', role='triager', agent_id='stopped-worker', status='stopped')
        native.control(self.session, 'cancel')
        tasks.stop(path, 'stopped-worker', 'stopped', 'Host confirmed stopped', True)
        with self.assertRaisesRegex(ValueError, 'not running'):
            self.prepare()
        with self.assertRaisesRegex(ValueError, 'explicit user authorization'):
            native.control(self.session, 'resume')
        native.control(self.session, 'resume', confirm_cancelled=True)
        fresh = self.prepare()
        tasks.start(fresh['task_file'], 'resumed-fresh-worker')

    def test_completed_host_with_missing_or_invalid_receipt_can_retry_without_evidence_acceptance(self):
        for index, content in enumerate((None, '{invalid receipt')):
            with self.subTest(content=content):
                envelope = self.prepare()
                path = envelope['task_file']
                task = json.loads(Path(path).read_text())
                identity = f'completed-invalid-{index}'
                tasks.start(path, identity)
                if content:
                    Path(task['result_file']).write_text(content)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    tasks.result(path, identity, True)
                with self.assertRaisesRegex(ValueError, 'may differ only'):
                    tasks.stop(path, identity, 'stopped', 'Invalid receipt', True, 'completed')
                tasks.stop(path, identity, 'failed', 'Host completed but receipt is missing or invalid', True, 'completed')
                data = native.status(self.session)
                self.assertEqual(data['stories']['1-1']['agents'][identity]['status'], 'completed')
                failed = data['tasks'][task['task_id']]
                self.assertEqual(failed['status'], 'failed')
                self.assertNotIn('receipt_hash', failed)
                self.assertEqual(bool(failed['terminal_observation']['unaccepted_receipt']), bool(content))
                if content:
                    self.assertEqual(Path(task['result_file']).read_text(), content)
                self.assertEqual(data['stories']['1-1']['reviews'], {})
                self.assertEqual(data['stories']['1-1']['checks'], {})
        fresh = self.prepare()
        tasks.start(fresh['task_file'], 'after-malformed-fresh')

    def test_finalizer_stages_batch_then_terminal_result_allows_completion_gates(self):
        fixture = self.fixture
        spec_path = fixture.spec()
        tracking = self.root / test_native_session.SPRINT_REL
        tracking.parent.mkdir(parents=True, exist_ok=True)
        tracking.write_text('development_status:\n  epic-1: in-progress\n  1-1-fixture: done\n')
        fixture.git('add', '.')
        fixture.git('commit', '-qm', 'tracking')
        fixture.review()
        fixture.checked()
        envelope = self.prepare('finalization', 'story-runner')
        path = envelope['task_file']
        task = json.loads(Path(path).read_text())
        binding = tasks.start(path, 'finalizer-fresh')
        finish = Path(path).parent / 'finish.json'
        native.atomic_json(finish, {'ok': True, 'steps': [{'step': 'sync', 'ok': True}]})
        batch = {'batch_id': 'finish-1-1', 'events': [
            {'event': 'complete', 'story': '1-1', 'spec': str(spec_path)},
            {'event': 'finalize', 'story': '1-1', 'repo': str(self.root), 'finish_report': str(finish)}]}
        batch_path = Path(path).parent / 'finalization-batch.json'
        native.atomic_json(batch_path, batch)
        before = Path(self.session).read_bytes()
        with self.assertRaisesRegex(ValueError, 'join all story agents'):
            native.record_batch(self.session, batch)
        self.assertEqual(Path(self.session).read_bytes(), before)
        receipt = {**task['receipt_template'], 'task_hash': binding['task_hash'], 'agent_id': 'finalizer-fresh',
                   'next': 'none', 'tree': native.code_tree(self.root),
                   'actions': ['record saved finalization-batch.json with native record-batch'],
                   'artifacts': [{'path': str(batch_path), 'sha256': tasks.file_hash(batch_path)}]}
        native.atomic_json(Path(task['result_file']), receipt)
        self.assertTrue(tasks.result(path, 'finalizer-fresh', preflight=True, record_batch=batch_path)['valid'])
        self.assertEqual(Path(self.session).read_bytes(), before)
        accepted = tasks.result(path, 'finalizer-fresh', True)
        self.assertEqual(accepted['state'], 'ready')
        self.assertEqual(native.status(self.session)['stories']['1-1']['status'], 'running')
        native.record_batch(self.session, json.loads(batch_path.read_text()))
        completed = native.status(self.session)
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['stories']['1-1']['status'], 'completed')
        self.assertEqual(completed['stories']['1-1']['agents']['finalizer-fresh']['status'], 'completed')

    def receipt_request(self, receipt):
        return {**{key: receipt[key] for key in ('state', 'next', 'actions', 'blocker')},
                'artifact_paths': [item['path'] for item in receipt['artifacts']]}

    def batch_artifact(self, path, spec, receipt, events):
        batch_path = Path(path).parent / 'batch.json'
        native.atomic_json(batch_path, {'batch_id': 'fixture-batch', 'events': events})
        receipt['artifacts'].append({'path': str(batch_path), 'sha256': tasks.file_hash(batch_path)})
        native.atomic_json(Path(spec['result_file']), receipt)
        return batch_path

    def test_generated_receipt_binds_hashes_and_tree_without_terminal_transition(self):
        path, spec, receipt = self.running()
        before = Path(self.session).read_bytes()
        generated = tasks.write_receipt(path, self.receipt_request(receipt))
        self.assertTrue(generated['valid'])
        self.assertEqual(json.loads(Path(spec['result_file']).read_text()), receipt)
        self.assertEqual(Path(self.session).read_bytes(), before)
        self.assertEqual(tasks.result(path, 'host-fresh-1', preflight=True)['valid'], True)
        self.assertEqual(Path(self.session).read_bytes(), before)
        self.accept(path)

    def test_pilot_malformed_decisions_fail_locally_preserving_previous_receipt(self):
        path, spec, receipt = self.running()
        before, saved = Path(self.session).read_bytes(), Path(spec['result_file']).read_bytes()
        request = self.receipt_request(receipt)
        for field, value, error in [('next', 'complete', 'next checkpoint'),
                ('next', 'review-revalidate', 'next checkpoint'),
                ('artifact_paths', request['artifact_paths'] * 9, 'eight evidence'),
                ('actions', ['one'] * 5, 'four short decisions'),
                ('actions', ['x' * 161], 'four short decisions'),
                ('actions', 'run checks', 'four short decisions')]:
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, error):
                tasks.write_receipt(path, {**request, field: value})
            self.assertEqual(Path(spec['result_file']).read_bytes(), saved)
            self.assertEqual(Path(self.session).read_bytes(), before)
        self.assertFalse(list(Path(path).parent.glob('receipt-draft-*')))

    def test_preflight_retains_stale_artifact_and_tree_guards(self):
        path, spec, receipt = self.running()
        before = Path(self.session).read_bytes()
        (self.root / 'code.py').write_text('value = 3\n')
        with self.assertRaisesRegex(ValueError, 'tree is stale'):
            tasks.result(path, 'host-fresh-1', preflight=True)
        (self.root / 'code.py').write_text('value = 1\n')
        Path(receipt['artifacts'][0]['path']).write_text('changed report')
        with self.assertRaisesRegex(ValueError, 'artifact missing or changed'):
            tasks.result(path, 'host-fresh-1', preflight=True)
        self.assertEqual(Path(self.session).read_bytes(), before)

    def test_binding_wait_joins_start_without_message_and_stops_on_timeout_or_cancel(self):
        path = self.prepare()['task_file']
        with self.assertRaisesRegex(ValueError, 'timed out'):
            tasks.binding(path)
        for timeout in (-1, 61, float('nan')):
            with self.assertRaisesRegex(ValueError, 'between 0 and 60'):
                tasks.binding(path, timeout)
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiter = pool.submit(tasks.binding, path, 2)
            expected = tasks.start(path, 'bound-without-message')
            self.assertEqual(waiter.result(timeout=3), expected)
        tasks.stop(path, 'bound-without-message', 'stopped', 'Host observed cancellation', True)
        with self.assertRaisesRegex(ValueError, 'terminal'):
            tasks.binding(path, 1)
        native.control(self.session, 'cancel')
        with self.assertRaisesRegex(ValueError, 'session is not running'):
            tasks.binding(path, 1)

    def test_binding_deadline_includes_real_journal_lock_contention(self):
        path = self.prepare()['task_file']
        _, _, common = tasks.read_task(path)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with native.locked(common):
                started = time.monotonic()
                waiter = pool.submit(tasks.binding, path, 0.1)
                with self.assertRaisesRegex(ValueError, 'timed out'):
                    waiter.result(timeout=0.7)
                self.assertLess(time.monotonic() - started, 0.7)
            # Cancellation becomes visible as soon as the contended lock is available.
            with native.locked(common):
                waiter = pool.submit(tasks.binding, path, 2)
                saved = native.status(self.session)
                saved['status'] = 'cancelled'
                native.atomic_json(Path(self.session), saved)
            with self.assertRaisesRegex(ValueError, 'session is not running'):
                waiter.result(timeout=1)

    def test_combined_acceptance_requires_observed_completion_and_hashed_batch(self):
        path, spec, receipt = self.running()
        batch = self.batch_artifact(path, spec, receipt, [{'story': '1-1', 'event': 'phase', 'phase': 'review'}])
        before = Path(self.session).read_bytes()
        with self.assertRaisesRegex(ValueError, 'confirm-completed'):
            tasks.accept_batch(path, 'host-fresh-1', batch)
        self.assertEqual(Path(self.session).read_bytes(), before)
        compact = tasks.accept_batch(path, 'host-fresh-1', batch, True)
        self.assertTrue(compact['batch_applied'])
        self.assertTrue(compact['receipt_accepted'])
        data = native.status(self.session)
        self.assertEqual(data['stories']['1-1']['phase'], 'review')
        self.assertEqual(data['stories']['1-1']['agents']['host-fresh-1']['status'], 'completed')
        self.assertTrue(native.record_batch(self.session, json.loads(batch.read_text()))['replayed'])

    def test_batch_cannot_change_host_liveness_or_escape_story_or_omit_hash(self):
        path, spec, receipt = self.running()
        before = Path(self.session).read_bytes()
        for event in [{'story': '1-1', 'event': 'agent', 'status': 'completed', 'agent_id': 'other'},
                      {'story': '2-2', 'event': 'phase', 'phase': 'review'}]:
            batch = self.batch_artifact(path, spec, receipt, [event])
            with self.assertRaisesRegex(ValueError, 'same-story evidence'):
                tasks.accept_batch(path, 'host-fresh-1', batch, True)
            receipt['artifacts'].pop()
            self.assertEqual(Path(self.session).read_bytes(), before)
        batch.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'unchanged receipt artifact'):
            tasks.accept_batch(path, 'host-fresh-1', batch, True)
        self.assertEqual(Path(self.session).read_bytes(), before)

    def test_preflight_catches_missing_completion_gate_and_batch_failure_is_atomic(self):
        path, spec, receipt = self.running()
        batch = self.batch_artifact(path, spec, receipt, [
            {'story': '1-1', 'event': 'phase', 'phase': 'finalization'},
            {'story': '1-1', 'event': 'complete', 'spec': '/missing/spec.md'}])
        before = Path(self.session).read_bytes()
        with self.assertRaisesRegex(ValueError, 'missing/current review'):
            tasks.result(path, 'host-fresh-1', preflight=True, record_batch=batch)
        self.assertEqual(Path(self.session).read_bytes(), before)
        compact = tasks.accept_batch(path, 'host-fresh-1', batch, True)
        self.assertTrue(compact['receipt_accepted'])
        self.assertFalse(compact['batch_applied'])
        data = native.status(self.session)
        self.assertEqual(data['stories']['1-1']['phase'], 'preflight')
        self.assertEqual(data['stories']['1-1']['status'], 'running')
        self.assertNotIn('fixture-batch', data.get('batches', {}))
        self.assertEqual(data['tasks'][spec['task_id']]['status'], 'completed')

    def test_revalidation_preflight_checks_changes_and_simulates_only_own_completion(self):
        self.fixture.review('problem')
        tree = native.code_tree(self.root)
        path, spec, receipt = self.running()
        values = self.fixture.revalidation(tree, story='1-1', layer='blind-hunter',
                                           evaluated_by='host-fresh-1', checked_changes='')
        values['evaluated_by'] = 'host-fresh-1'
        batch = self.batch_artifact(path, spec, receipt, [{'story': '1-1', 'event': 'review-revalidate', **values}])
        before = Path(self.session).read_bytes()
        with self.assertRaisesRegex(ValueError, 'checked_changes'):
            tasks.result(path, 'host-fresh-1', preflight=True, record_batch=batch)
        self.assertEqual(Path(self.session).read_bytes(), before)
        evidence = Path(values['evidence'])
        payload = json.loads(evidence.read_text())
        payload['checked_changes'] = 'Inspected cumulative code.py diff; only the reviewed constant.'
        native.atomic_json(evidence, payload)
        self.assertTrue(tasks.result(path, 'host-fresh-1', preflight=True, record_batch=batch)['valid'])
        self.assertEqual(Path(self.session).read_bytes(), before)
        self.assertTrue(tasks.accept_batch(path, 'host-fresh-1', batch, True)['batch_applied'])

    def test_legacy_session_rejected_without_mutation(self):
        data = native.status(self.session)
        data.pop('orchestration_policy')
        native.atomic_json(Path(self.session), data)
        before = Path(self.session).read_bytes()
        with self.assertRaisesRegex(ValueError, 'legacy sessions remain unchanged'):
            self.prepare()
        self.assertEqual(Path(self.session).read_bytes(), before)

    def test_failed_worker_is_not_recorded_completed(self):
        path, spec, receipt = self.running()
        native.atomic_json(Path(spec['result_file']), {**receipt, 'state': 'failed', 'blocker': 'Check crashed'})
        self.accept(path)
        self.assertEqual(native.status(self.session)['stories']['1-1']['agents']['host-fresh-1']['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
