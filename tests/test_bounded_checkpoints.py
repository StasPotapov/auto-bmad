"""Versioned inputs cannot leak another layer's context or grant acceptance."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import native_policy as policy
import native_session as native
import native_tasks as tasks
import test_native_tasks


class BoundedTaskTest(unittest.TestCase):
    def setUp(self):
        fixture = test_native_tasks.NativeTaskTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture, self.root, self.session = fixture, fixture.root, fixture.session
        data = native.status(self.session)
        data['checkpoint_policy'] = policy.POLICY
        data['stories']['1-1'].update(title='SECRET_CLAIM', reviews={'other': 'SECRET_REVIEW'},
            checks={'unit': 'SECRET_CHECK'}, agents={}, long_history='SECRET_HISTORY')
        native.atomic_json(Path(self.session), data)

    def ref(self, name, text='diff content'):
        p = self.root / '.auto-bmad' / name
        p.parent.mkdir(exist_ok=True)
        p.write_text(text)
        return {'path': str(p), 'sha256': tasks.file_hash(p)}

    def prepare(self, role, payload):
        p = self.root / '.auto-bmad/input.json'
        p.parent.mkdir(exist_ok=True)
        native.atomic_json(p, payload)
        return tasks.prepare(session=self.session, story='1-1', role=role,
                             checkpoint='review', input_path=p)

    def test_blind_router_projection_and_real_lifecycle(self):
        ref = self.ref('review.diff')
        router = {'spec': 'SECRET_SPEC', 'narrative': 'SECRET_NARRATIVE', 'roles': [
            {'role': 'blind-hunter', 'inputs': {'diff': ref}, 'payload': 'SECRET_PAYLOAD'},
            {'role': 'edge-case-hunter', 'inputs': {'claims': 'SECRET_CLAIMS'}}]}
        envelope = self.prepare('blind-hunter', router)
        p = Path(envelope['task_file']); spec = json.loads(p.read_text())
        exposed = p.read_text() + p.with_name('input.json').read_text() + json.dumps(envelope)
        self.assertNotIn('SECRET_', exposed)
        self.assertIsNone(spec['request'])
        self.assertEqual(spec['runtime_references'], {})
        self.assertNotIn('manifest', spec['story_state'])
        self.assertEqual(json.loads(p.with_name('input.json').read_text()), {'diff': policy.reference(ref)})
        self.assertEqual(spec['transport']['binding'][-4:], ['--task', str(p), '--wait-seconds', '60'])
        tasks.start(p, 'blind-fixture')
        self.assertEqual(tasks.binding(p)['agent_id'], 'blind-fixture')
        report = self.ref('findings.txt', 'No findings')
        tasks.write_receipt(p, {'state': 'ready', 'next': 'triage', 'actions': [],
            'blocker': None, 'artifact_paths': [report['path']]})
        tasks.result(p, 'blind-fixture', True)
        self.assertEqual(native.status(self.session)['stories']['1-1']['reviews'], {'other': 'SECRET_REVIEW'})

    def test_rejects_nested_extra_claims_and_changed_artifact(self):
        ref = self.ref('review.diff')
        with self.assertRaisesRegex(ValueError, 'fields must be exactly'):
            self.prepare('blind-hunter', {'diff': ref, 'claims': ref})
        with self.assertRaisesRegex(ValueError, 'absolute path'):
            self.prepare('blind-hunter', {'diff': {**ref, 'claims': 'leak'}})
        Path(ref['path']).write_text('changed')
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            self.prepare('blind-hunter', {'diff': ref})

    def test_old_task_keeps_old_contract_and_policy_cannot_change(self):
        data = native.status(self.session); data.pop('checkpoint_policy')
        native.atomic_json(Path(self.session), data)
        envelope = self.prepare('blind-hunter', {'legacy_input': 'kept'})
        spec = json.loads(Path(envelope['task_file']).read_text())
        self.assertEqual(spec['story_state']['title'], 'SECRET_CLAIM')
        data = native.status(self.session); data['checkpoint_policy'] = policy.POLICY
        native.atomic_json(Path(self.session), data)
        with self.assertRaisesRegex(ValueError, 'policy changed'):
            tasks.start(envelope['task_file'], 'new-identity')


if __name__ == '__main__':
    unittest.main()

import agent_config
import native_repair as repair
import native_verification as verification
import test_native_verification
from unittest.mock import patch


class LocalRepairTest(unittest.TestCase):
    def setUp(self):
        fixture = test_native_verification.StagedVerificationTest()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture, self.root, self.session = fixture, fixture.root, fixture.session
        cfg = self.root / '.auto-bmad.toml'
        cfg.write_text(cfg.read_text().replace('command="compile-check"', 'command="compile-check"\nindependent=true'))
        data = native.status(self.session)
        data['checkpoint_policy'] = policy.POLICY
        data['roles'] = agent_config.resolve(native.config(self.root)[0])['roles']
        data['config_hash'] = native.config(self.root)[1]
        data['stories']['1-1']['config_hash'] = data['config_hash']
        native.atomic_json(Path(self.session), data)
        self.plan = fixture.request
        self.serial = 0
        self.verdict = 'pass'
        self.calls = []
        def run(repo, command, timeout, **kwargs):
            self.calls.append(command)
            key = verification.testrun.key_of(repo, command, cache_context=kwargs.get('cache_context'))
            log = self.root / '.auto-bmad' / (key + '.log'); log.parent.mkdir(exist_ok=True)
            log.write_text('FAILED test_code.py::test_code\n' if self.verdict == 'problem' else 'passed\n')
            return {'verdict': self.verdict, 'code': 1 if self.verdict == 'problem' else 0,
                'command': command, 'key': key, 'source_key': key, 'tree_changed': False,
                'failure_ids': ['test_code.py::test_code'] if self.verdict == 'problem' else [],
                'failure_ids_complete': True,
                'log': str(log), 'seconds': 1}, 0
        fixture.mock_run.side_effect = run
        self.live = patch.object(verification.testrun, 'live_runs', return_value={})
        self.live.start(); self.addCleanup(self.live.stop)
        self.requirement = self.ref('spec.md', 'Keep value valid')
        self.report = self.ref('findings.md', 'Fix value')

    def ref(self, name, content):
        p = self.root / '.auto-bmad' / name; p.parent.mkdir(exist_ok=True); p.write_text(content)
        return {'path': str(p), 'sha256': tasks.file_hash(p)}

    def start(self, role, checkpoint):
        self.serial += 1
        envelope = tasks.prepare(session=self.session, story='1-1', role=role, checkpoint=checkpoint)
        p = envelope['task_file']; tasks.start(p, 'agent-' + str(self.serial)); return p

    def finish(self, p, artifacts):
        binding = tasks.binding(p)
        spec = json.loads(Path(p).read_text())
        pending = native.status(self.session)['tasks'][spec['task_id']].get('pending_verification')
        if pending:
            artifacts = [*artifacts, pending['path']]
        tasks.write_receipt(p, {'state': 'ready', 'next': 'checks', 'actions': [],
                               'blocker': None, 'artifact_paths': artifacts})
        tasks.result(p, binding['agent_id'], True)

    def admit(self):
        p = self.start('triager', 'triage')
        decision = {'story': '1-1', 'tree': native.code_tree(self.root), 'batch_id': 'repair-1',
            'finding_ids': ['F1'], 'failure_ids': ['test_code.py::test_code'],
            'scope': ['code.py'], 'requirements': [self.requirement], 'reports': [self.report],
            'kind': 'review', 'reason': 'Concrete requirement deviation', 'plan': self.plan}
        ref = self.ref('decision.json', json.dumps(decision)); self.finish(p, [ref['path']])
        native.record(self.session, {'event': 'repair-batch', 'story': '1-1', 'task': p, 'decision': ref})
        return p, ref

    def check(self, p, mode='attempt'):
        return repair.local_check(p, {'batch_id': 'repair-1', 'mode': mode, 'plan': self.plan})

    def test_red_fix_green_one_task_is_not_independent_acceptance(self):
        self.admit(); p = self.start('implementer', 'implementation')
        self.verdict = 'problem'; self.assertEqual(self.check(p, 'diagnostic')['verdict'], 'problem')
        (self.root / 'code.py').write_text('value = 2\n')
        self.verdict = 'pass'; self.assertEqual(self.check(p)['verdict'], 'pass')
        data = native.status(self.session); row = data['stories']['1-1']
        self.assertEqual(row['repair_batches']['repair-1']['attempts'], 1)
        self.assertEqual(row['checks'], {})
        self.assertNotIn('development_check', row)
        with self.assertRaisesRegex(ValueError, 'matching task producer'):
            verification.development(self.session, '1-1', self.plan, task=p)
        with self.assertRaisesRegex(ValueError, 'independent producer'):
            verification.require_development(data, '1-1', self.root)
        with self.assertRaisesRegex(ValueError, 'closure'):
            native.complete(data, '1-1', row, self.root)
        self.finish(p, [self.report['path']])
        verifier = self.start('verifier', 'checks')
        receipt = verification.development(self.session, '1-1', self.plan, task=verifier)
        self.assertEqual(receipt['kind'], 'independent-verification')
        self.finish(verifier, [self.report['path']])
        self.assertEqual(repair.route(native.status(self.session), '1-1', self.root)['next'], 'revalidation')

    def test_scope_requirements_and_new_batch_cannot_reset_limits(self):
        triager, ref = self.admit()
        p = self.start('implementer', 'implementation')
        (self.root / 'test_code.py').write_text('def test_code(): assert True\n')
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.check(p)
        (self.root / 'test_code.py').write_text('def test_code(): pass\n')
        Path(self.requirement['path']).write_text('weakened spec')
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            self.check(p)

    def test_local_budget_survives_new_implementer_and_resume(self):
        self.admit(); self.verdict = 'problem'
        for n in range(3):
            p = self.start('implementer', 'implementation')
            (self.root / 'code.py').write_text(f'value = {n+2}\n')
            self.assertEqual(self.check(p)['verdict'], 'problem')
            self.finish(p, [self.report['path']])
        (self.root / 'code.py').write_text('value = 9\n')
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            self.start('implementer', 'implementation')
        row = native.status(self.session)['stories']['1-1']
        self.assertEqual(row['repair_batches']['repair-1']['attempts'], 3)
        self.assertEqual(row['repair_counts']['review'], 3)

    def test_matching_failure_routes_direct_unknown_failure_does_not(self):
        self.admit(); p = self.start('verifier', 'checks'); self.verdict = 'problem'
        verification.development(self.session, '1-1', self.plan, task=p)
        self.finish(p, [self.report['path']])
        data = native.status(self.session)
        self.assertEqual(repair.route(data, '1-1', self.root)['next'], 'implementation')
        data['stories']['1-1']['development_check']['results']['dev/unit']['result']['failure_ids'] = ['unknown']
        self.assertEqual(repair.route(data, '1-1', self.root)['next'], 'triage')

import native_context as context
import native_stats
import os
from concurrent.futures import ThreadPoolExecutor


class ContextCacheTest(unittest.TestCase):
    setUp = BoundedTaskTest.setUp
    def compiler(self):
        source = self.root / '.auto-bmad/source.md'; source.parent.mkdir(exist_ok=True)
        if not source.exists(): source.write_text('authoritative source')
        p = self.root / '.auto-bmad/context-input.json'
        contract = self.root / '.auto-bmad/compile.md'; contract.write_text('Extract authoritative context')
        workflow = self.root / '.auto-bmad/workflow.md'; workflow.write_text('Preparation workflow v1')
        native.atomic_json(p, {'context': {'epic': '1', 'sources': ['.auto-bmad/source.md'],
            'contract': {'path': str(contract), 'sha256': tasks.file_hash(contract)},
            'options': {'language': 'en', 'workflow': {'path': str(workflow), 'sha256': tasks.file_hash(workflow)}}}})
        return tasks.prepare(session=self.session, story='1-1', role='context-compiler',
                             checkpoint='preparation', input_path=p)

    def test_one_compiler_concurrent_miss_publish_and_cached_hit(self):
        # Create the identical request first; concurrent prepares only read it.
        first = self.compiler()
        p = Path(first['task_file']); task = json.loads(p.read_text())
        input_path = task['input']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: tasks.prepare(session=self.session, story='1-1',
                role='context-compiler', checkpoint='preparation', input_path=input_path), range(2)))
        self.assertTrue(all(r['status'] == 'waiting' and r['spawn'] is None for r in results))
        tasks.start(p, 'compiler-owner')
        inp = json.loads(Path(input_path).read_text())
        out = Path(inp['context_reservation']['output']); out.write_text('compiled content')
        tasks.write_receipt(p, {'state':'ready','next':'preparation','actions':[], 'blocker':None,
                               'artifact_paths':[str(out)]})
        ref = {'path':str(out),'sha256':tasks.file_hash(out)}
        with self.assertRaisesRegex(ValueError, 'matching task producer'):
            context.publish(p, ref)
        tasks.result(p, 'compiler-owner', True)
        artifact = context.publish(p, ref)
        self.assertEqual(self.compiler()['artifact'], artifact)
        Path(artifact['path']).write_text('corrupted')
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            self.compiler()

    def test_source_content_not_mtime_and_failed_owner_retry(self):
        first = self.compiler(); p = first['task_file']
        tasks.start(p, 'first-compiler')
        tasks.stop(p, 'first-compiler', 'failed', 'Fixture failure', True)
        second = self.compiler()
        self.assertIn('spawn', second); self.assertIsNotNone(second['spawn'])
        source = self.root / '.auto-bmad/source.md'; old = source.stat()
        source.write_text('changed source'); os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
        third = self.compiler()
        second_input = json.loads(Path(json.loads(Path(second['task_file']).read_text())['input']).read_text())
        third_input = json.loads(Path(json.loads(Path(third['task_file']).read_text())['input']).read_text())
        self.assertNotEqual(second_input['context_reservation']['key'], third_input['context_reservation']['key'])


class MeasurementTest(unittest.TestCase):
    def test_parallel_agent_time_is_not_wall_time_or_token_savings(self):
        data = {'tasks':{'a':{'role':'verifier'},'b':{'role':'triager'}},'events':[
            {'event':'task-start','task_id':'a'}, {'event':'task-start','task_id':'b'},
            {'event':'agent','agent_id':'a','role':'verifier','status':'running','at':'2026-01-01T00:00:00+00:00'},
            {'event':'agent','agent_id':'b','role':'triager','status':'running','at':'2026-01-01T00:00:10+00:00'},
            {'event':'agent','agent_id':'a','role':'verifier','status':'completed','at':'2026-01-01T00:00:30+00:00'},
            {'event':'agent','agent_id':'b','role':'triager','status':'completed','at':'2026-01-01T00:00:40+00:00'}]}
        r = native_stats.checkpoint_metrics(data)
        self.assertEqual(r['completed_agent_seconds'],60)
        self.assertEqual(r['completed_agent_wall_seconds'],40)
        self.assertIsNone(r['wait_seconds']); self.assertIsNone(r['measured_command_seconds'])

class CollectionTest(unittest.TestCase):
    def test_independent_failures_collected_dependent_skipped_and_environment_stops(self):
        fixture = test_native_verification.StagedVerificationTest(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        cfg = fixture.root
        commands = [{'name':'first','command':'first','timeout':2},
                    {'name':'dependent','command':'dependent','timeout':2},
                    {'name':'independent','command':'independent','timeout':2,'independent':True}]
        calls = []
        def failing(repo, command, timeout, **kw):
            calls.append(command); key = verification.testrun.key_of(repo, command, cache_context=kw['cache_context'])
            return {'verdict':'problem','code':1,'key':key,'source_key':key,'tree_changed':False,
                    'failure_ids':[command]}, 0
        fixture.mock_run.side_effect = failing
        receipt = verification.execute(cfg, commands, collect_independent=True)
        self.assertEqual(calls, ['first','independent'])
        self.assertEqual(receipt['results']['dependent']['result']['verdict'], 'not-run')
        self.assertEqual(receipt['verdict'], 'problem')
        calls.clear()
        def unavailable(*args, **kw):
            result, code = failing(*args, **kw); result['code'] = 127; return result, code
        fixture.mock_run.side_effect = unavailable
        receipt = verification.execute(cfg, commands, collect_independent=True)
        self.assertEqual(calls, ['first'])
        self.assertEqual(receipt['results']['independent']['result']['verdict'], 'not-run')

class RepairRegressionTest(unittest.TestCase):
    setUp = LocalRepairTest.setUp
    ref = LocalRepairTest.ref
    start = LocalRepairTest.start
    finish = LocalRepairTest.finish
    admit = LocalRepairTest.admit
    check = LocalRepairTest.check

    def test_changed_environment_cannot_reuse_prior_pass(self):
        env_a = self.ref('env-a.json', 'A')
        env_b = self.ref('env-b.json', 'B')
        first = self.start('verifier', 'checks')
        verification.development(self.session, '1-1', {**self.plan,'environment':env_a}, task=first)
        self.assertNotIn('development_check', native.status(self.session)['stories']['1-1'])
        self.finish(first, [self.report['path']])
        count = len(self.calls)
        second = self.start('verifier', 'checks')
        result = verification.development(self.session, '1-1', {**self.plan,'environment':env_b}, task=second)
        self.assertFalse(result['reused']); self.assertGreater(len(self.calls), count)
        self.finish(second, [self.report['path']])

    def test_closure_rejects_short_plan_and_live_or_missing_producer(self):
        (self.root/'test_other.py').write_text('def test_other(): pass\n')
        self.plan = {'checks':[{'name':'unit','targets':['test_code.py','test_other.py']}], 'builds':['compile']}
        self.admit()
        verifier = self.start('verifier','checks')
        short = {'checks':[{'name':'unit','targets':['test_code.py']}], 'builds':['compile']}
        result = verification.development(self.session,'1-1',short,task=verifier)
        with self.assertRaisesRegex(ValueError,'independent producer'):
            verification.require_development(native.status(self.session),'1-1',self.root)
        self.finish(verifier,[self.report['path']])
        triager = self.start('triager','revalidation')
        decision={'story':'1-1','tree':native.code_tree(self.root),'batch_id':'repair-1',
                  'findings':[{'id':'F1','disposition':'fixed','evidence':'code.py verified'}]}
        ref=self.ref('closure.json',json.dumps(decision));self.finish(triager,[ref['path']])
        with self.assertRaisesRegex(ValueError,'complete admitted'):
            native.record(self.session,{'event':'repair-close','story':'1-1','task':triager,'decision':ref})

    def test_unknown_complete_flag_and_dispatch_drift_require_triage(self):
        self.admit(); self.verdict='problem'
        p=self.start('verifier','checks');verification.development(self.session,'1-1',self.plan,task=p)
        self.finish(p,[self.report['path']])
        envelope=tasks.prepare(session=self.session,story='1-1',role='implementer',checkpoint='implementation')
        data=native.status(self.session)
        data['stories']['1-1']['development_check']['results']['dev/unit']['result']['failure_ids_complete']=False
        native.atomic_json(Path(self.session),data)
        self.assertEqual(repair.route(data,'1-1',self.root)['next'],'triage')
        with self.assertRaisesRegex(ValueError,'fresh triage'):
            tasks.start(envelope['task_file'],'stale-dispatch')

    def test_pre_admission_diagnostics_and_real_cancel_resume_preserve_budget(self):
        p=self.start('triager','triage')
        result=repair.local_check(p,{'batch_id':None,'mode':'diagnostic','plan':self.plan})
        self.assertEqual(result['kind'],'diagnostic-observation')
        self.assertEqual(native.status(self.session)['stories']['1-1']['checks'],{})
        self.finish(p,[self.report['path']])
        native.control(self.session,'cancel');native.control(self.session,'resume',True)
        self.assertEqual(native.status(self.session)['stories']['1-1']['diagnostic_state']['count'],1)
        self.admit(); p=self.start('implementer','implementation')
        self.verdict='problem';self.check(p);self.finish(p,[self.report['path']])
        native.control(self.session,'cancel');native.control(self.session,'resume',True)
        self.assertEqual(native.status(self.session)['stories']['1-1']['repair_batches']['repair-1']['attempts'],1)

    def test_partial_local_plan_is_not_progress_and_new_batch_cannot_reset(self):
        _, decision_ref=self.admit();p=self.start('implementer','implementation')
        with self.assertRaisesRegex(ValueError,'complete admitted'):
            repair.local_check(p,{'batch_id':'repair-1','mode':'attempt',
                                 'plan':{'checks':self.plan['checks'],'builds':[]}})
        self.finish(p,[self.report['path']])
        q=self.start('triager','triage');decision=json.loads(Path(decision_ref['path']).read_text())
        decision.update(batch_id='new-name',tree=native.code_tree(self.root))
        ref=self.ref('new-decision.json',json.dumps(decision));self.finish(q,[ref['path']])
        with self.assertRaisesRegex(ValueError,'existing repair batch'):
            native.record(self.session,{'event':'repair-batch','story':'1-1','task':q,'decision':ref})

    def test_running_local_check_joins_without_spending_another_attempt(self):
        self.admit();p=self.start('implementer','implementation')
        original=self.fixture.mock_run.side_effect; once=[True]
        def running(*a,**kw):
            result,code=original(*a,**kw)
            if once[0]:once[0]=False;return {**result,'verdict':'running'},3
            return result,code
        self.fixture.mock_run.side_effect=running
        first=self.check(p);second=self.check(p)
        self.assertEqual(first['verdict'],'running');self.assertEqual(second['verdict'],'pass')
        self.assertEqual(first['execution_id'],second['execution_id'])
        self.assertEqual(native.status(self.session)['stories']['1-1']['repair_batches']['repair-1']['attempts'],1)

    def test_zero_story_budget_and_unreviewed_oracle_within_scope_are_rejected(self):
        data=native.status(self.session);data['repair_limits']['review']=0
        native.atomic_json(Path(self.session),data)
        with self.assertRaisesRegex(ValueError,'repair budget exhausted'):self.admit()
        data=native.status(self.session);data['repair_limits']['review']=5
        native.atomic_json(Path(self.session),data)
        p=self.start('triager','triage')
        d={'story':'1-1','tree':native.code_tree(self.root),'batch_id':'repair-1','finding_ids':['F1'],
           'failure_ids':[],'scope':['code.py','test_code.py'],'requirements':[self.requirement],
           'reports':[self.report],'kind':'review','reason':'Fix approved case','plan':self.plan}
        ref=self.ref('oracle-decision.json',json.dumps(d));self.finish(p,[ref['path']])
        native.record(self.session,{'event':'repair-batch','story':'1-1','task':p,'decision':ref})
        (self.root/'test_code.py').write_text('def test_code(): assert True\n')
        row=native.status(self.session)['stories']['1-1']
        with self.assertRaisesRegex(ValueError,'oracle review'):
            repair.test_review(row,row['repair_batches']['repair-1'],{'test_review':[]})

class IntegrationAcceptanceTest(unittest.TestCase):
    setUp = LocalRepairTest.setUp
    ref = LocalRepairTest.ref
    start = LocalRepairTest.start
    finish = LocalRepairTest.finish

    def test_full_gate_published_only_after_terminal_receipt_and_reused_for_same_candidate(self):
        data=native.status(self.session)
        data['stories']['1-1'].update(status='verified',commit=self.fixture.fixture.git('rev-parse','HEAD').stdout.strip())
        native.atomic_json(Path(self.session),data)
        p=self.start('story-runner','integration')
        result=verification.integration(self.session,['1-1'],self.root,task=p)
        self.assertFalse(result['accepted'])
        self.assertNotIn('integration_gate',native.status(self.session))
        self.finish(p,[self.report['path']])
        data=native.status(self.session)
        verification.require_integration(data,'1-1',self.root)
        count=len(self.calls)
        second=self.start('story-runner','integration')
        result=verification.integration(self.session,['1-1'],self.root,task=second)
        self.assertTrue(result['accepted']);self.assertEqual(len(self.calls),count)


class ContextRecoveryTest(unittest.TestCase):
    setUp = BoundedTaskTest.setUp
    compiler = ContextCacheTest.compiler

    def test_superseded_prepared_owner_is_replaced_with_bounded_recovery(self):
        first=self.compiler()
        source=self.root/'.auto-bmad/source.md';source.write_text('B')
        self.compiler()
        source.write_text('authoritative source')
        third=self.compiler()
        self.assertIsNotNone(third['spawn'])
        self.assertNotEqual(first['task_file'],third['task_file'])
        self.assertEqual(native.status(self.session)['stories']['1-1']['technical_retries'],1)

    def test_same_sources_in_two_worktrees_share_key_and_consumer_rechecks_bytes(self):
        first=self.compiler();p=Path(first['task_file']);spec=json.loads(p.read_text())
        request=json.loads(Path(spec['input']).read_text())['context']
        _,_,_,common=native.read_session(self.session)
        other=self.root.parent/'other-worktree'
        self.fixture.fixture.git('worktree','add','-q','-b','context-fixture',str(other),'HEAD')
        import shutil
        shutil.copy2(self.root/'.auto-bmad.toml',other/'.auto-bmad.toml')
        (other/'.auto-bmad').mkdir(exist_ok=True)
        for name in ('source.md','compile.md','workflow.md'):
            shutil.copy2(self.root/'.auto-bmad'/name,other/'.auto-bmad'/name)
        clone=json.loads(json.dumps(request))
        for ref in (clone['contract'],clone['options']['workflow']):
            ref['path']=str(other/'.auto-bmad'/Path(ref['path']).name)
        self.assertEqual(context.description(self.root.resolve(),common,spec['profile'],request),
                         context.description(other.resolve(),common,spec['profile'],clone))
        (other/'.auto-bmad/source.md').write_text('different source')
        self.assertNotEqual(context.description(self.root.resolve(),common,spec['profile'],request),
                            context.description(other.resolve(),common,spec['profile'],clone))

class RoutingExperimentTest(unittest.TestCase):
    def test_same_known_local_error_uses_fewer_real_checkpoint_launches(self):
        measurements = {}
        for bounded in (False, True):
            f=LocalRepairTest();f.setUp()
            try:
                if not bounded:
                    data=native.status(f.session);data.pop('checkpoint_policy')
                    native.atomic_json(Path(f.session),data)
                f.verdict='problem'
                implementer=f.start('implementer','implementation')
                if bounded:
                    repair.local_check(implementer,{'batch_id':None,'mode':'diagnostic','plan':f.plan})
                    (f.root/'code.py').write_text('value = 2\n');f.verdict='pass'
                    repair.local_check(implementer,{'batch_id':None,'mode':'diagnostic','plan':f.plan})
                    f.finish(implementer,[f.report['path']])
                else:
                    f.finish(implementer,[f.report['path']])
                    verifier=f.start('verifier','checks')
                    verification.development(f.session,'1-1',f.plan)
                    f.finish(verifier,[f.report['path']])
                    triager=f.start('triager','triage');f.finish(triager,[f.report['path']])
                    native.record(f.session,{'event':'repair','story':'1-1','kind':'tests','reason':'known local defect'})
                    implementer=f.start('implementer','implementation')
                    (f.root/'code.py').write_text('value = 2\n');f.verdict='pass'
                    f.finish(implementer,[f.report['path']])
                verifier=f.start('verifier','checks')
                verification.development(f.session,'1-1',f.plan,task=verifier if bounded else None)
                f.finish(verifier,[f.report['path']])
                data=native.status(f.session)
                measurements['bounded' if bounded else 'legacy'] = {
                    'launches':native_stats.checkpoint_metrics(data)['launches_by_role'],
                    'task_input_bytes':sum(p.stat().st_size for p in Path(f.session).parent.glob('tasks/*/task.json')),
                    'command_invocations':len(f.calls)}
                self.assertEqual((f.root/'code.py').read_text(),'value = 2\n')
                self.assertEqual(data['stories']['1-1']['development_check']['verdict'],'pass')
                self.assertNotEqual(data['stories']['1-1']['status'],'completed')
            finally:f.doCleanups()
        self.assertEqual(sum(measurements['legacy']['launches'].values()),5)
        self.assertEqual(sum(measurements['bounded']['launches'].values()),2)
        print('BOUNDED_ROUTE_FIXTURE '+json.dumps(measurements,sort_keys=True))

class SecondReviewRegressionTest(unittest.TestCase):
    setUp = LocalRepairTest.setUp
    ref = LocalRepairTest.ref
    start = LocalRepairTest.start
    finish = LocalRepairTest.finish
    admit = LocalRepairTest.admit
    check = LocalRepairTest.check

    def test_public_legacy_repair_cannot_bypass_admission(self):
        with self.assertRaisesRegex(ValueError,'triager repair-batch'):
            native.record(self.session,{'event':'repair','story':'1-1','kind':'review','reason':'bypass'})
        p=self.start('implementer','implementation');self.finish(p,[self.report['path']])
        with self.assertRaisesRegex(ValueError,'admitted repair batch'):
            self.start('implementer','implementation')

    def test_changed_environment_cannot_join_live_old_environment(self):
        a=self.ref('environment-a','A');b=self.ref('environment-b','B')
        p=self.start('verifier','checks');original=self.fixture.mock_run.side_effect
        def running(*args,**kw):
            result,code=original(*args,**kw);return {**result,'verdict':'running'},3
        self.fixture.mock_run.side_effect=running
        verification.development(self.session,'1-1',{**self.plan,'environment':a},task=p)
        self.fixture.mock_run.side_effect=original
        before=len(self.calls)
        with patch.object(verification.testrun,'live_runs',return_value={'existing':{}}):
            with self.assertRaisesRegex(ValueError,'previous verification is still running'):
                verification.development(self.session,'1-1',{**self.plan,'environment':b},task=p)
        self.assertEqual(len(self.calls),before)

    def test_verifier_waiter_joins_last_paid_local_attempt_without_writing(self):
        self.admit();p=self.start('implementer','implementation')
        data=native.status(self.session);batch=data['stories']['1-1']['repair_batches']['repair-1']
        batch['attempts']=2;data['stories']['1-1']['repair_counts']['review']=2
        native.atomic_json(Path(self.session),data)
        original=self.fixture.mock_run.side_effect;once=[True]
        def running(*args,**kw):
            result,code=original(*args,**kw)
            if once[0]:once[0]=False;return {**result,'verdict':'running'},3
            return result,code
        self.fixture.mock_run.side_effect=running
        first=self.check(p);self.assertEqual(first['verdict'],'running')
        self.finish(p,[self.report['path']])
        with patch.object(verification.testrun,'live_runs',return_value={'existing':{}}):
            waiter=self.start('verifier','test-wait')
        second=self.check(waiter)
        self.assertEqual(second['verdict'],'pass');self.assertEqual(first['execution_id'],second['execution_id'])
        self.assertEqual(native.status(self.session)['stories']['1-1']['repair_batches']['repair-1']['attempts'],3)
        self.assertNotIn('development_check',native.status(self.session)['stories']['1-1'])

    def test_two_phase_land_preserves_main_until_terminal_gate_acceptance(self):
        import land, shutil
        git=self.fixture.fixture.git
        (self.root/'.gitignore').write_text('.auto-bmad/\n')
        git('add','.');git('commit','-qm','fixture candidate base')
        baseline=git('rev-parse','HEAD').stdout.strip();other=self.root.parent/'story-worktree'
        git('worktree','add','-q','-b','story-fixture',str(other),'HEAD')
        shutil.copytree(self.root/'_bmad', other/'_bmad', dirs_exist_ok=True)
        (other/'code.py').write_text('value = 2\n')
        native.git(str(other),'add','code.py');native.git(str(other),'commit','-qm','fixture story')
        data=native.status(self.session);row=data['stories']['1-1']
        manifest=json.loads(Path(row['manifest']).read_text())
        manifest=json.loads(json.dumps(manifest).replace(str(self.root.resolve()),str(other.resolve())).replace(str(self.root),str(other)))
        manifest_path=self.root.parent/'candidate-manifest.json';native.atomic_json(manifest_path,manifest)
        row.update(worktree=str(other.resolve()),branch='refs/heads/story-fixture',baseline=baseline,
            manifest=str(manifest_path),manifest_hash=native.digest(manifest),status='verified',
            commit=native.git(str(other),'rev-parse','HEAD').stdout.strip())
        native.atomic_json(Path(self.session),data)
        first=self.start('story-runner','integration')
        outcome,code=land.land(str(self.root),'story-fixture',native_session=self.session,stories=['1-1'],native_task=first)
        self.assertEqual(code,0,outcome);self.assertFalse(outcome['merged'])
        self.assertEqual(git('rev-parse','HEAD').stdout.strip(),baseline)
        self.finish(first,[self.report['path']]);count=len(self.calls)
        second=self.start('story-runner','integration')
        outcome,code=land.land(str(self.root),'story-fixture',native_session=self.session,stories=['1-1'],native_task=second)
        self.assertEqual(code,0,outcome);self.assertTrue(outcome['merged'])
        self.assertNotEqual(git('rev-parse','HEAD').stdout.strip(),baseline)
        self.assertEqual(len(self.calls),count)


class ContextPublicationRegressionTest(unittest.TestCase):
    setUp = BoundedTaskTest.setUp
    compiler = ContextCacheTest.compiler

    def test_unbound_story_is_rejected_before_reservation(self):
        data=native.status(self.session);data['stories']['1-1'].pop('worktree')
        native.atomic_json(Path(self.session),data)
        with self.assertRaisesRegex(ValueError,'bind the story'):
            self.compiler()
        self.assertFalse((Path(self.session).parent.parent/'context-cache').exists())

    def test_blocked_compiler_cannot_publish_partial_output(self):
        envelope=self.compiler();p=Path(envelope['task_file']);spec=json.loads(p.read_text())
        tasks.start(p,'blocked-compiler')
        inp=json.loads(Path(spec['input']).read_text());out=Path(inp['context_reservation']['output'])
        out.write_text('partial context')
        tasks.write_receipt(p,{'state':'blocked','next':'decision','actions':[],'blocker':'Source could not be parsed',
                               'artifact_paths':[str(out)]})
        tasks.result(p,'blocked-compiler',True)
        with self.assertRaisesRegex(ValueError,'completed compiler receipt'):
            context.publish(p,{'path':str(out),'sha256':tasks.file_hash(out)})

class FinalBoundaryRegressionTest(unittest.TestCase):
    setUp = LocalRepairTest.setUp
    ref = LocalRepairTest.ref
    start = LocalRepairTest.start
    finish = LocalRepairTest.finish
    admit = LocalRepairTest.admit

    def test_failed_receipt_can_retry_only_after_technical_budget_event(self):
        p=self.start('implementer','implementation')
        tasks.write_receipt(p,{'state':'failed','next':'decision','actions':[],
            'blocker':'Tool transport failed','artifact_paths':[self.report['path']]})
        tasks.result(p,tasks.binding(p)['agent_id'],True)
        with self.assertRaisesRegex(ValueError,'budgeted technical retry'):
            self.start('implementer','implementation')
        native.record(self.session,{'event':'retry','story':'1-1','reason':'Confirmed tool failure'})
        q=self.start('implementer','implementation')
        self.assertEqual(tasks.binding(q)['status'],'running')
        self.assertEqual(native.status(self.session)['stories']['1-1']['repair_counts']['review'],0)

    def test_compiler_gets_no_story_repair_context_and_metrics_keep_reason(self):
        self.admit()
        data=native.status(self.session)
        metrics=native_stats.checkpoint_metrics(data)
        self.assertIn('Concrete requirement deviation',[r['reason'] for r in metrics['retry_reasons']])
        source=self.root/'.auto-bmad/source.md';source.write_text('common source')
        contract=self.ref('compile.md','Extract only common source')
        workflow=self.ref('workflow.md','Fixture preparation')
        p=self.root/'.auto-bmad/compiler-input.json'
        native.atomic_json(p,{'context':{'epic':'1','sources':['.auto-bmad/source.md'],
            'contract':contract,'options':{'language':'en','workflow':workflow}}})
        envelope=tasks.prepare(session=self.session,story='1-1',role='context-compiler',checkpoint='preparation',input_path=p)
        spec=json.loads(Path(envelope['task_file']).read_text())
        self.assertEqual(set(spec['story_state']),{'worktree'})
        self.assertIsNone(spec['request'])
        exposed=json.dumps(spec)+Path(spec['input']).read_text()
        self.assertNotIn('Concrete requirement deviation',exposed)
        self.assertNotIn(self.report['path'],exposed)
        self.assertNotIn('repair-1',exposed)
