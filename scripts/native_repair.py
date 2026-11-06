"""Bounded local observations and durable repair decisions, never self-acceptance."""
from pathlib import Path
import json
import uuid

import native_policy as policy
import native_session as native
import native_tasks as tasks
import native_verification as verification
import native_check_lock as check_lock
import project_tests
import testrun
from repair_policy import environment_failure, failed_tests

LOCAL_LIMIT = 3


def actor(data, story, roles, task_path=None, terminal=False):
    if not policy.enabled(data):
        raise ValueError('bounded checkpoints require a new versioned session')
    candidates = [(tid, item) for tid, item in data.get('tasks', {}).items()
        if item.get('story') == story and item.get('role') in roles
        and item.get('status') == ('completed' if terminal else 'running')]
    if task_path:
        path, spec, _ = tasks.read_task(task_path)
        candidates = [(tid, item) for tid, item in candidates if tid == spec['task_id']]
    if len(candidates) != 1:
        raise ValueError('operation requires one registered matching task producer')
    tid, item = candidates[0]
    path = Path(data['session']).parent / 'tasks' / tid / 'task.json'
    _, spec, _ = tasks.read_task(path)
    tasks.validate(path, spec, data)
    agent = data['stories'][story].get('agents', {}).get(item.get('agent_id'), {})
    if agent.get('role') != item['role'] or agent.get('status') != ('completed' if terminal else 'running'):
        raise ValueError('producer must match the registered host agent')
    return tid, spec, item


def trusted_decision(data, story, request):
    tid, spec, item = actor(data, story, {'triager'}, request['task'], terminal=True)
    ref = policy.reference(request['decision'])
    receipt = Path(item['receipt'])
    accepted = json.loads(receipt.read_text())
    if (tasks.file_hash(receipt) != item['receipt_hash'] or ref not in accepted['artifacts']
            or accepted.get('state') not in ('ready', 'done')):
        raise ValueError('decision must be a hashed artifact of the completed triager')
    decision = json.loads(Path(ref['path']).read_text())
    if decision.get('story') != story or decision.get('tree') != native.code_tree(data['stories'][story]['worktree']):
        raise ValueError('decision story/tree is stale')
    return decision, ref, tid


def strings(value, label, nonempty=True):
    if (not isinstance(value, list) or (nonempty and not value) or len(set(value)) != len(value)
            or not all(isinstance(x, str) and x.strip() for x in value)):
        raise ValueError(label + ' must be a unique string list')
    return value


def admit(data, story, request, common):
    row = data['stories'][story]
    decision, ref, producer = trusted_decision(data, story, request)
    identity = decision.get('batch_id')
    if not isinstance(identity, str) or not identity or len(identity) > 100:
        raise ValueError('repair requires a stable bounded batch_id')
    batches = row.setdefault('repair_batches', {})
    if identity in batches:
        if batches[identity]['decision'] != ref:
            raise ValueError('repair batch identity cannot be reused')
        return
    if row.get('active_repair_batch'):
        raise ValueError('close the existing repair batch before admitting another')
    findings = strings(decision.get('finding_ids'), 'finding_ids')
    failures = strings(decision.get('failure_ids', []), 'failure_ids', False)
    scope = strings(decision.get('scope'), 'scope')
    for rel in scope:
        if Path(rel).is_absolute() or '..' in Path(rel).parts or rel.startswith('.git/'):
            raise ValueError('repair scope needs concrete repository-relative paths')
    refs = [policy.reference(r) for r in decision.get('requirements', [])]
    reports = [policy.reference(r) for r in decision.get('reports', [])]
    if not refs or not reports:
        raise ValueError('repair decision requires requirements and original reports')
    cfg, _ = native.config(row['worktree'])
    plan = decision['plan']
    verification.development_plan(row['worktree'], cfg, plan)
    native.begin_repair(data, row, row['worktree'], {'kind': decision['kind'], 'reason': decision['reason']})
    snapshot = Path(data['session']).parent / 'repair-evidence' / (native.digest([story, identity]) + '.json')
    snapshot.parent.mkdir(exist_ok=True)
    native.atomic_json(snapshot, file_state(row['worktree']))
    batch = {'decision': ref, 'producer': producer, 'source_tree': decision['tree'],
        'finding_ids': findings, 'failure_ids': failures, 'scope': scope, 'requirements': refs,
        'reports': reports, 'plan': plan, 'plan_hash': native.digest(plan), 'kind': decision['kind'],
        'attempts': 0, 'diagnostics': 0, 'no_progress': 0, 'state': 'open',
        'admitted_at': native.now(), 'last_decision_at': native.now(),
        'snapshot': {'path': str(snapshot), 'sha256': tasks.file_hash(snapshot)}}
    batches[identity] = batch
    row['active_repair_batch'] = identity
    request['reason'] = str(decision['reason'])[:320]
    request['kind'] = decision['kind']


def file_state(root):
    root = Path(root)
    proc = native.git(str(root), 'ls-files', '--cached', '--others', '--exclude-standard', '-z')
    if proc.returncode:
        raise ValueError('cannot fingerprint repair scope')
    result = {}
    for rel in set(filter(None, proc.stdout.split('\0'))):
        if rel.startswith('.auto-bmad/'):
            continue
        p = root / rel
        if p.is_symlink():
            result[rel] = 'link:' + str(p.readlink())
        elif p.is_file():
            result[rel] = str(p.stat().st_mode) + ':' + tasks.file_hash(p)
        elif not p.exists():
            result[rel] = 'deleted'
        else:
            raise ValueError('unsupported repair input: ' + rel)
    return result


def validate_batch(row, batch):
    policy.reference(batch['decision'])
    for ref in batch['requirements'] + batch['reports']:
        policy.reference(ref)
    original = json.loads(Path(policy.reference(batch['snapshot'])['path']).read_text())
    current = file_state(row['worktree'])
    changes = {p for p in original.keys() | current.keys() if original.get(p) != current.get(p)}
    if changes - set(batch['scope']):
        raise ValueError('repair changed files outside the admitted scope; triage required')
    if native.digest(batch['plan']) != batch['plan_hash']:
        raise ValueError('repair plan changed')


def changed_tests(row, batch):
    original = json.loads(Path(batch['snapshot']['path']).read_text())
    current = file_state(row['worktree'])
    strategy = project_tests.settings(native.config(row['worktree'])[0])
    patterns = [p for item in strategy.get('development', {}).values() for p in item['targets']]
    return {p for p in original.keys() | current.keys()
            if original.get(p) != current.get(p) and (project_tests.matches(p, patterns)
                or 'tests' in Path(p).parts or Path(p).name.startswith('test_'))}


def test_review(row, batch, decision):
    changed = changed_tests(row, batch)
    reviewed = decision.get('test_review', [])
    refs = {}
    for item in reviewed:
        if not item.get('reason') or item.get('requirement') not in batch['requirements']:
            raise ValueError('test-oracle review requires authoritative requirement evidence')
        ref = policy.reference(item['artifact'])
        rel = str(Path(ref['path']).relative_to(Path(row['worktree'])))
        refs[rel] = ref
    if set(refs) != changed:
        raise ValueError('changed tests require independent triager oracle review')
    return refs


def local_plan(root, request):
    cfg, _ = native.config(root)
    strategy = project_tests.settings(cfg)
    if set(request) - {'checks', 'builds'}:
        raise ValueError('local diagnostics accept only registered checks/builds, never full_risk')
    commands = []
    for row in request.get('checks', []):
        if set(row) != {'name', 'targets'} or row['name'] not in strategy.get('development', {}):
            raise ValueError('local check requires a registered development target')
        commands.append(verification.command(root, 'dev/' + row['name'],
            strategy['development'][row['name']], row['targets']))
    for name in request.get('builds', []):
        if name not in strategy.get('build', {}):
            raise ValueError('local build is not registered')
        commands.append(verification.command(root, 'build/' + name, strategy['build'][name]))
    if not commands or len({c['name'] for c in commands}) != len(commands):
        raise ValueError('local checks need a nonempty unique plan')
    return commands


def local_check(task_path, request):
    path, spec, common = tasks.read_task(task_path)
    story = spec['story']
    _, data, _, _ = native.read_session(spec['session'])
    _, root = native.bound(data, story, common)
    if (not {'batch_id', 'mode', 'plan'} <= set(request) or set(request) - {'batch_id', 'mode', 'plan', 'environment'}
            or request['mode'] not in ('diagnostic', 'attempt')):
        raise ValueError('local check needs batch_id, mode diagnostic/attempt, and plan')
    if request.get('environment') is not None:
        policy.reference(request['environment'])
    if request['batch_id'] is None:
        return task_diagnostic(task_path, request)
    with check_lock.worktree_lock(common, root):
        with native.locked(common):
            _, data, _, _ = native.read_session(spec['session'])
            if data['status'] != 'running':
                raise ValueError('session is not running')
            tid, _, producer = actor(data, story, {'implementer', 'triager', 'verifier'}, path)
            waiter = producer['role'] == 'verifier' and spec['checkpoint'] == 'test-wait'
            if producer['role'] == 'verifier' and not waiter:
                raise ValueError('only a test-wait verifier may join a local observation')
            if request['mode'] == 'attempt' and producer['role'] != 'implementer' and not waiter:
                raise ValueError('only implementer may spend a local repair attempt')
            row, _ = native.bound(data, story, common)
            identity = request['batch_id']
            batch = row.get('repair_batches', {}).get(identity)
            if batch is None or row.get('active_repair_batch') != identity or batch['state'] != 'open':
                raise ValueError('local check needs the active admitted repair batch')
            validate_batch(row, batch)
            commands = local_plan(root, request['plan'])
            allowed = verification.development_plan(root, native.config(root)[0], batch['plan'])
            if any(c not in allowed for c in commands):
                raise ValueError('diagnostic plan must be a subset of the admitted mandatory plan')
            if request['mode'] == 'attempt' and commands != allowed:
                raise ValueError('repair progress requires the complete admitted mandatory plan')
            tree = native.code_tree(root)
            signature = native.digest([identity, request, tree, native.config(root)[1]])
            observations = row.setdefault('local_observations', {})
            prior = observations.get(signature)
            if waiter and (not prior or prior.get('verdict') != 'running'):
                raise ValueError('local waiter may only join an already paid running execution')
            if prior and prior.get('verdict') != 'running':
                if not request.get('environment'):
                    raise ValueError('completed observation has unknown environment freshness; triage before reuse')
                policy.reference(prior['evidence'])
                cached = json.loads(Path(prior['evidence']['path']).read_text())
                if not verification.evidence_valid(cached):
                    raise ValueError('local check log changed')
                return {**cached, 'reused': True}
            running = [r for r in observations.values() if r.get('verdict') == 'running']
            if running and prior not in running:
                raise ValueError('join the saved local check before a different attempt')
            if not prior:
                if batch['no_progress'] >= data['repair_limits']['no_progress']:
                    raise ValueError('local no-progress budget exhausted')
                field = 'attempts' if request['mode'] == 'attempt' else 'diagnostics'
                if batch[field] >= LOCAL_LIMIT:
                    raise ValueError('local batch budget exhausted')
                if field == 'attempts' and batch[field]:
                    kind = batch['kind']
                    if row['repair_counts'][kind] >= data['repair_limits'][kind]:
                        raise ValueError('story repair budget exhausted')
                    row['repair_counts'][kind] += 1
                batch[field] += 1
                prior = {'verdict': 'running', 'execution_id': uuid.uuid4().hex,
                    'producer_task': tid, 'agent_id': producer['agent_id'], 'role': producer['role']}
                observations[signature] = prior
                data['events'].append({'event': 'local-check-start', 'story': story,
                    'batch_id': identity, 'mode': request['mode'], 'task_id': tid,
                    'execution_id': prior['execution_id'], 'at': native.now()})
                native.atomic_json(Path(spec['session']), data)
            expected = check_lock.snapshot(data, [story])
            cfg_hash = native.config(root)[1]
            checkpoint = Path(spec['session']).parent / 'local-checks' / (prior['execution_id'] + '.json')
            checkpoint.parent.mkdir(exist_ok=True)
        def valid():
            _, live, _, _ = native.read_session(spec['session'])
            check_lock.validate(live, [story], expected, root, tree, cfg_hash)
            actor(live, story, {'implementer', 'triager', 'verifier'}, path)
            if request.get('environment') is not None:
                policy.reference(request['environment'])
        receipt = verification.execute(root, commands, checkpoint=checkpoint,
                                       collect_independent=True, still_valid=valid,
                                       environment=request.get('environment'))
        verification.save_logs(receipt, checkpoint.with_suffix(''))
        if not verification.complete_logs(receipt):
            raise ValueError('local observation requires every executed command log')
        with native.locked(common):
            _, current, _, _ = native.read_session(spec['session'])
            check_lock.validate(current, [story], expected, root, tree, cfg_hash)
            actor(current, story, {'implementer', 'triager', 'verifier'}, path)
            row = current['stories'][story]; batch = row['repair_batches'][identity]
            validate_batch(row, batch)
            # A local receipt can never be read as checks/development_check/integration_gate.
            receipt.update(kind='local-observation', batch_id=identity, story=story,
                session=spec['session'], task_id=prior['producer_task'], agent_id=prior['agent_id'],
                role=prior['role'], mode=request['mode'], checkpoint_policy=policy.POLICY)
            if waiter:
                receipt['joined_by'] = {'task_id': tid, 'agent_id': producer['agent_id']}
            output = checkpoint.with_name(checkpoint.stem + '-evidence.json')
            native.atomic_json(output, receipt)
            row['local_observations'][signature] = {**prior, 'verdict': receipt['verdict'],
                'evidence': {'path': str(output), 'sha256': tasks.file_hash(output)}}
            if receipt['verdict'] != 'running':
                failed, complete = failures(receipt)
                if request['mode'] == 'attempt':
                    old = set(batch.get('last_failure_ids', batch['failure_ids']))
                    progress = not changed_tests(row, batch) and (receipt['verdict'] == 'pass'
                        or (complete and old and failed and failed < old))
                    batch['no_progress'] = 0 if progress else batch['no_progress'] + 1
                    batch['last_failure_ids'] = sorted(failed) if complete else []
                current['events'].append({'event': 'local-check-result', 'story': story,
                    'batch_id': identity, 'execution_id': prior['execution_id'],
                    'verdict': receipt['verdict'], 'seconds': sum(r['result'].get('seconds', 0)
                        for r in receipt['results'].values() if not r['result'].get('reused')),
                    'at': native.now()})
            native.atomic_json(Path(spec['session']), current)
        return receipt


def failures(receipt):
    result, complete = set(), receipt.get('tree') is not None
    if len(receipt.get('results', {})) != len(receipt.get('commands', [])):
        complete = False
    for item in receipt.get('results', {}).values():
        r = item['result']
        if r.get('verdict') == 'pass':
            continue
        ids = failed_tests(r)
        if (not ids or item['transport_code'] or environment_failure(r)
                or r.get('verdict') != 'problem' or r.get('failure_ids_complete') is not True
                or not isinstance(r.get('failure_ids'), list)):
            complete = False
        result |= ids
    return result, bool(complete)


def route(data, story, root):
    if data.get('status') != 'running' or not policy.enabled(data):
        raise ValueError('routing requires a running bounded session')
    row = data['stories'][story]
    identity = row.get('active_repair_batch')
    batch = row.get('repair_batches', {}).get(identity)
    if not batch:
        try:
            verification.require_development(data, story, root)
            return {'next': 'review', 'reason': 'initial independent checks accepted'}
        except ValueError:
            pass
        return {'next': 'triage', 'reason': 'no admitted repair decision'}
    validate_batch(row, batch)
    if changed_tests(row, batch):
        return {'next': 'triage', 'reason': 'changed test oracle requires independent review'}
    receipt = row.get('development_check', {})
    if (receipt.get('tree') != native.code_tree(root) or receipt.get('request_hash') != batch['plan_hash']
            or receipt.get('config_hash') != native.config(root)[1]
            or receipt.get('commands_hash') != native.digest(verification.development_plan(
                root, native.config(root)[0], batch['plan']))
            or receipt.get('kind') != 'independent-verification' or not verification.evidence_valid(receipt)):
        return {'next': 'triage', 'reason': 'changed or incomplete independent evidence'}
    ids, complete = failures(receipt)
    if receipt.get('verdict') == 'pass':
        return {'next': 'revalidation', 'batch_id': identity}
    if (complete and ids and ids <= set(batch['failure_ids']) and batch['attempts'] < LOCAL_LIMIT
            and batch['no_progress'] < data['repair_limits']['no_progress']
            and row['repair_counts'][batch['kind']] < data['repair_limits'][batch['kind']]):
        return {'next': 'implementation', 'batch_id': identity, 'finding_ids': batch['finding_ids'],
                'decision': batch['decision']}
    return {'next': 'triage', 'reason': 'unknown failures, incomplete evidence or exhausted budget'}


def close(data, story, request):
    row = data['stories'][story]
    decision, ref, _ = trusted_decision(data, story, request)
    identity = row.get('active_repair_batch')
    batch = row.get('repair_batches', {}).get(identity)
    if not batch or decision.get('batch_id') != identity:
        raise ValueError('closure must cover the active batch')
    validate_batch(row, batch)
    dispositions = decision.get('findings', [])
    if (len(dispositions) != len(batch['finding_ids'])
            or {x.get('id') for x in dispositions} != set(batch['finding_ids'])
            or any(x.get('disposition') != 'fixed' or not x.get('evidence') for x in dispositions)):
        raise ValueError('every admitted mandatory finding requires concrete fixed evidence')
    verification.require_development(data, story, row['worktree'])
    reviewed_tests = test_review(row, batch, decision)
    receipt = row['development_check']
    if (receipt.get('request_hash') != batch['plan_hash']
            or receipt.get('commands_hash') != native.digest(verification.development_plan(
                row['worktree'], native.config(row['worktree'])[0], batch['plan']))):
        raise ValueError('closure requires the complete admitted mandatory plan')
    batch.update(state='closed', closure=ref, reviewed_tests=reviewed_tests)
    row.pop('active_repair_batch')


def amend(data, story, request):
    """A fresh triage decision can expand a batch, never erase its history/budgets."""
    row = data['stories'][story]
    decision, ref, producer = trusted_decision(data, story, request)
    identity = row.get('active_repair_batch')
    batch = row.get('repair_batches', {}).get(identity)
    if not batch or decision.get('batch_id') != identity:
        raise ValueError('amendment must retain the active batch identity')
    finding_ids = strings(decision.get('finding_ids'), 'finding_ids')
    scope = strings(decision.get('scope'), 'scope')
    if not set(batch['finding_ids']) <= set(finding_ids) or not set(batch['scope']) <= set(scope):
        raise ValueError('amendment cannot drop findings or original scope')
    if any(Path(p).is_absolute() or '..' in Path(p).parts or p.startswith('.git/') for p in scope):
        raise ValueError('invalid amended scope')
    # Requirement changes need a separate spec repair, not laundering old approvals.
    if ([policy.reference(r) for r in decision.get('requirements', [])] != batch['requirements']
            or decision.get('kind') != batch['kind']):
        raise ValueError('amendment cannot change requirements or budget kind')
    reports = [policy.reference(r) for r in decision.get('reports', [])]
    if any(r not in reports for r in batch['reports']):
        raise ValueError('amendment must preserve original reports')
    plan = decision['plan']
    updated = verification.development_plan(row['worktree'], native.config(row['worktree'])[0], plan)
    original = verification.development_plan(row['worktree'], native.config(row['worktree'])[0], batch['plan'])
    if any(command not in updated for command in original):
        raise ValueError('amendment cannot reduce the mandatory plan')
    batch.setdefault('decision_history', []).append(batch['decision'])
    batch.update(decision=ref, producer=producer, finding_ids=finding_ids, scope=scope,
        last_decision_at=native.now(),
        reports=reports, plan=plan, plan_hash=native.digest(plan),
        failure_ids=strings(decision.get('failure_ids', []), 'failure_ids', False))


def implementation_guard(data, story, root):
    row = data['stories'][story]
    identity = row.get('active_repair_batch')
    if not identity:
        previous = [(tid, task) for tid, task in data.get('tasks', {}).items()
            if task.get('story') == story and task.get('role') == 'implementer'
            and task.get('status') in ('completed', 'failed', 'stopped')]
        failed = set()
        for tid, task in previous:
            state = task.get('result_state')
            if state is None and task.get('receipt'):
                receipt = Path(task['receipt'])
                if tasks.file_hash(receipt) != task['receipt_hash']:
                    raise ValueError('previous implementation receipt changed')
                state = json.loads(receipt.read_text())['state']
            if task['status'] == 'completed' and state != 'failed':
                raise ValueError('a new implementation after completion requires an admitted repair batch')
            failed.add(tid)
        if failed:
            last = max((e['at'] for e in data['events'] if e.get('task_id') in failed
                        and e['event'] in ('task-result', 'task-stop')), default='')
            if not any(e['event'] == 'retry' and e.get('story') == story and e['at'] > last for e in data['events']):
                raise ValueError('record a budgeted technical retry before restarting failed implementation')
        return None
    batch = row['repair_batches'][identity]
    validate_batch(row, batch)
    if (batch['attempts'] >= LOCAL_LIMIT or batch['no_progress'] >= data['repair_limits']['no_progress']
            or (batch['attempts'] and row['repair_counts'][batch['kind']] >= data['repair_limits'][batch['kind']])):
        raise ValueError('repair budget exhausted before dispatch')
    check = row.get('development_check', {})
    if check.get('at', '') > batch['last_decision_at'] and route(data, story, root).get('next') != 'implementation':
        raise ValueError('independent failures require fresh triage or closure before implementation')
    return native.digest({'batch': identity, 'decision': batch['decision'], 'plan': batch['plan_hash'],
        'tree': native.code_tree(root), 'attempts': batch['attempts'], 'no_progress': batch['no_progress'],
        'counts': row['repair_counts'], 'check': check})


def task_diagnostic(task_path, request):
    """Finite pre-admission measurements for first implementation or uncertain triage."""
    path, spec, common = tasks.read_task(task_path)
    if request['mode'] != 'diagnostic':
        raise ValueError('before admission only diagnostic observations are allowed')
    _, initial, _, _ = native.read_session(spec['session'])
    _, root = native.bound(initial, spec['story'], common)
    with check_lock.worktree_lock(common, root):
        with native.locked(common):
            _, data, _, _ = native.read_session(spec['session'])
            if data['status'] != 'running':
                raise ValueError('session is not running')
            tid, _, producer = actor(data, spec['story'], {'implementer', 'triager', 'verifier'}, path)
            waiter = producer['role'] == 'verifier' and spec['checkpoint'] == 'test-wait'
            if producer['role'] == 'verifier' and not waiter:
                raise ValueError('only a test-wait verifier may join diagnostics')
            row = data['stories'][spec['story']]
            if row.get('active_repair_batch'):
                raise ValueError('use the active batch; pre-admission cannot bypass its limits')
            commands = local_plan(root, request['plan'])
            tree, cfg_hash = native.code_tree(root), native.config(root)[1]
            state = row.setdefault('diagnostic_state', {'count': 0, 'no_progress': 0})
            signature = native.digest([tree, commands, request.get('environment')])
            pending = state.get('pending')
            if waiter and not pending:
                raise ValueError('diagnostic waiter cannot start a new execution')
            if pending and pending['signature'] != signature:
                raise ValueError('join the pre-admission diagnostic before changing code or plan')
            if not pending:
                if state['count'] >= LOCAL_LIMIT or state['no_progress'] >= data['repair_limits']['no_progress']:
                    raise ValueError('pre-admission diagnostic budget exhausted')
                if state.get('last_verdict') == 'problem' and state.get('last_tree') != tree:
                    if row['repair_counts']['tests'] >= data['repair_limits']['tests']:
                        raise ValueError('story tests repair budget exhausted')
                    row['repair_counts']['tests'] += 1
                state['count'] += 1
                pending = {'signature': signature, 'execution_id': uuid.uuid4().hex,
                           'task_id': tid, 'role': producer['role'], 'agent_id': producer['agent_id']}
                state['pending'] = pending
                data['events'].append({'event': 'diagnostic-check-start', 'story': spec['story'],
                    'task_id': tid, 'execution_id': pending['execution_id'], 'at': native.now()})
                native.atomic_json(Path(spec['session']), data)
            expected = check_lock.snapshot(data, [spec['story']])
            checkpoint = Path(spec['session']).parent / 'local-checks' / (pending['execution_id'] + '.json')
            checkpoint.parent.mkdir(exist_ok=True)
        def valid():
            _, live, _, _ = native.read_session(spec['session'])
            check_lock.validate(live, [spec['story']], expected, root, tree, cfg_hash)
            actor(live, spec['story'], {'implementer', 'triager', 'verifier'}, path)
            if request.get('environment'):
                policy.reference(request['environment'])
        receipt = verification.execute(root, commands, checkpoint=checkpoint,
            collect_independent=True, still_valid=valid, environment=request.get('environment'))
        verification.save_logs(receipt, checkpoint.with_suffix(''))
        if not verification.complete_logs(receipt):
            raise ValueError('diagnostic observation requires every executed command log')
        with native.locked(common):
            _, data, _, _ = native.read_session(spec['session']); valid()
            row = data['stories'][spec['story']]; state = row['diagnostic_state']
            receipt.update(kind='diagnostic-observation', task_id=tid, story=spec['story'],
                batch_id=None, agent_id=producer['agent_id'], role=producer['role'],
                checkpoint_policy=policy.POLICY, session=spec['session'])
            output = checkpoint.with_name(checkpoint.stem + '-diagnostic.json')
            native.atomic_json(output, receipt)
            row.setdefault('diagnostic_observations', []).append(
                {'path': str(output), 'sha256': tasks.file_hash(output)})
            if receipt['verdict'] != 'running':
                state.pop('pending')
                state['no_progress'] = 0 if receipt['verdict'] == 'pass' else state['no_progress'] + 1
                state.update(last_verdict=receipt['verdict'], last_tree=tree)
                data['events'].append({'event': 'diagnostic-check-result', 'story': spec['story'],
                    'task_id': tid, 'execution_id': pending['execution_id'],
                    'seconds': sum(r['result'].get('seconds', 0) for r in receipt['results'].values()
                                   if not r['result'].get('reused')), 'at': native.now()})
            native.atomic_json(Path(spec['session']), data)
        return receipt
