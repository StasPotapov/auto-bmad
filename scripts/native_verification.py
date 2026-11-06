"""Staged native verification: focused development, one exact-candidate landing gate."""
from pathlib import Path
import hashlib
import json
import shutil
import uuid

import native_session as native
import native_check_lock as check_lock
import project_tests
import testrun
import verify
import native_policy
from repair_policy import environment_failure

POLICY = 'integration-full-v1'


def enabled(data):
    return native.thin_root(data) and data.get('verification_policy') == POLICY


def command(root, name, item, targets=None):
    value = project_tests.development_command(root, item, targets) if targets is not None else item['command']
    result = {'name': name, 'command': value, 'timeout': item.get('timeout', 1800)}
    if item.get('independent') is True:
        result['independent'] = True
    return result


def development_plan(root, cfg, request):
    if not isinstance(request, dict) or set(request) - {'checks', 'builds', 'build_not_applicable', 'full_risk', 'environment'}:
        raise ValueError('development request accepts checks, builds, build_not_applicable and full_risk')
    if request.get('environment') is not None:
        native_policy.reference(request['environment'])
    strategy = project_tests.settings(cfg)
    rows = request.get('checks', [])
    if not isinstance(rows, list):
        raise ValueError('development checks must be a list of registered names and targets')
    selected = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'name', 'targets'}:
            raise ValueError('each focused check needs name and targets')
        item = strategy.get('development', {}).get(row['name'])
        if not item:
            raise ValueError('focused check is not registered: ' + str(row['name']))
        selected.append(command(root, 'dev/' + row['name'], item, row['targets']))
    risk = request.get('full_risk')
    if risk is not None:
        if not isinstance(risk, str) or len(risk.strip()) < 20:
            raise ValueError('early full gate requires a concrete broad-risk/architecture necessity (full_risk)')
        value, timeout = verify.command_check(str(root), 'project-tests')
        if not value:
            raise ValueError('early full gate needs a registered project-tests command')
        selected.append({'name': 'project-tests', 'command': value, 'timeout': timeout or 1800})
    if not selected:
        raise ValueError('focused test coverage gap: register development commands and select targets; no automatic full fallback')
    builds = request.get('builds', [])
    if not isinstance(builds, list) or not all(isinstance(name, str) for name in builds):
        raise ValueError('builds must list registered build names')
    configured = strategy.get('build', {})
    if configured and set(builds) != set(configured):
        raise ValueError('development requires all registered compile/build checks')
    if not configured:
        reason = request.get('build_not_applicable')
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('compile/build coverage gap: register build commands or document build_not_applicable')
    elif request.get('build_not_applicable'):
        raise ValueError('registered build checks cannot be declared not applicable')
    for name in builds:
        if name not in configured:
            raise ValueError('build check is not registered: ' + name)
        selected.append(command(root, 'build/' + name, configured[name]))
    if len({item['name'] for item in selected}) != len(selected):
        raise ValueError('combine targets for each development check; duplicate names are invalid')
    return selected


def evidence_valid(receipt):
    return all(Path(item['path']).is_file() and hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() == item['sha256']
               for item in receipt.get('evidence', []))


def complete_logs(receipt):
    paths = {item['path'] for item in receipt.get('evidence', [])}
    return evidence_valid(receipt) and all(
        row['result'].get('verdict') in ('running', 'not-run')
        or row['result'].get('log') in paths for row in receipt.get('results', {}).values())


def save_logs(receipt, directory):
    directory.mkdir(parents=True, exist_ok=True)
    evidence = []
    for name, row in receipt['results'].items():
        source = row['result'].get('log')
        if not source:
            continue
        source = Path(source)
        if not source.is_file():
            if row['result'].get('verdict') == 'running':
                continue
            raise ValueError('test evidence log is missing: ' + str(source))
        target = directory / (native.digest(name)[:16] + '.log')
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        row['result']['log'] = str(target)
        evidence.append({'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    receipt['evidence'] = evidence


def stage(data, path, producer, stories, root, receipt, snapshot, phase):
    """Persist observations; only a terminal task receipt can publish the gate."""
    import native_tasks
    if not complete_logs(receipt):
        raise ValueError('every executed check needs an intact saved log')
    target = path.parent / 'pending-verification' / (producer + '.json')
    target.parent.mkdir(exist_ok=True)
    owner = data['tasks'][producer]
    receipt.update(task_hash=owner['task_hash'], agent_id=owner['agent_id'], role=owner['role'],
                   batch_ids={s: data['stories'][s].get('active_repair_batch') for s in stories})
    envelope = {'producer': producer, 'stories': stories, 'root': str(root),
                'snapshot': snapshot, 'phase': phase, 'receipt': receipt}
    native.atomic_json(target, envelope)
    ref = {'path': str(target), 'sha256': native_tasks.file_hash(target)}
    data['tasks'][producer]['pending_verification'] = ref
    native.atomic_json(path, data)
    return {**receipt, 'accepted': False, 'pending_evidence': ref,
            'next': 'include pending_evidence in the task receipt; root accepts after actual completion'}


def accept_produced(data, spec, payload):
    """Called under journal lock after observed task completion (or dry-run preflight)."""
    import native_tasks
    task = data['tasks'][spec['task_id']]
    ref = task.get('pending_verification')
    if not ref or payload['state'] not in ('ready', 'done'):
        return
    native_policy.reference(ref)
    if ref not in payload['artifacts']:
        raise ValueError('verifier receipt must include its staged evidence')
    saved = json.loads(Path(ref['path']).read_text())
    receipt = saved['receipt']; stories = saved['stories']; root = Path(saved['root'])
    if (saved['producer'] != spec['task_id'] or receipt.get('producer_task') != spec['task_id']
            or receipt.get('task_hash') != task['task_hash'] or receipt.get('agent_id') != task['agent_id']
            or receipt.get('role') != task['role']
            or spec['story'] not in stories or task['status'] != 'completed'
            or receipt['verdict'] == 'running' or not receipt.get('evidence') or not complete_logs(receipt)):
        raise ValueError('staged verification has invalid producer, logs or incomplete execution')
    check_lock.validate(data, stories, saved['snapshot'], root, receipt['tree'], receipt['config_hash'])
    if receipt['kind'] == 'independent-verification':
        if spec['role'] != 'verifier' or stories != [spec['story']]:
            raise ValueError('development evidence needs its verifier producer')
        request = receipt['request']
        commands = development_plan(root, native.config(root)[0], request)
        if native.digest(commands) != receipt['commands_hash'] or native.digest(request) != receipt['request_hash']:
            raise ValueError('staged development plan changed')
        row = data['stories'][spec['story']]
        record_checks(row, receipt); row['development_check'] = receipt
        data['focused_repair'] = receipt; check_lock.set_phase(row, saved['phase'])
    elif receipt['kind'] == 'independent-integration':
        if (spec['role'] not in ('verifier', 'story-runner') or spec['checkpoint'] != 'integration'
                or receipt.get('git_tree') != native.git(str(root), 'rev-parse', 'HEAD^{tree}').stdout.strip()
                or native.digest(integration_plan(data, stories, root)) != receipt['commands_hash']):
            raise ValueError('staged integration candidate changed')
        for story in stories:
            record_checks(data['stories'][story], receipt)
        data['integration_gate'] = receipt
    else:
        raise ValueError('local observations cannot be accepted as verification')
    task.pop('pending_verification')
    data['events'].append({'event': 'independent-check-result', 'story': spec['story'],
        'task_id': spec['task_id'], 'execution_id': receipt['execution_id'],
        'seconds': sum(r['result'].get('seconds', 0) for r in receipt['results'].values()
                       if not r['result'].get('reused')), 'at': native.now()})


def record_checks(row, receipt):
    observed = set()
    for name, saved in receipt['results'].items():
        result = saved['result']
        row.setdefault('checks', {})[name] = {'tree': receipt['tree'], 'result': result, 'at': receipt['at']}
        if saved['transport_code'] == 0 and receipt['tree'] is not None:
            observed.add(name)
    pending = row.get('pending_test_repair', {})
    if pending and set(pending) <= observed:
        progress = all(native.test_progress(old['result'], row['checks'][name]['result']) for name, old in pending.items())
        row['test_no_progress'] = 0 if progress else row['test_no_progress'] + 1
        row.pop('pending_test_repair', None)


def execute(root, commands, previous=None, checkpoint=None, collect_independent=False, still_valid=None,
            environment=None):
    """Only exact code/config/command matches may reuse a successful recorded result."""
    cfg_hash = native.config(root)[1]
    tree = native.code_tree(root)
    signature = native.digest(commands)
    environment_hash = native.digest(environment) if environment is not None else None
    pending = json.loads(checkpoint.read_text()) if checkpoint and checkpoint.exists() else None
    if pending and pending.get('verdict') == 'running':
        if (pending.get('tree') == tree and pending.get('config_hash') == cfg_hash
                and pending.get('commands_hash') == signature and pending.get('environment_hash') == environment_hash):
            previous = pending
        elif testrun.live_runs(str(root)):
            raise ValueError('previous verification is still running in this worktree; wait for it before changing the check')
    if (previous and previous.get('tree') == tree and previous.get('config_hash') == cfg_hash
            and previous.get('commands_hash') == signature and previous.get('verdict') == 'pass'
            and previous.get('environment_hash') == environment_hash
            and evidence_valid(previous)):
        return {**previous, 'reused': True}
    resume = (previous and previous.get('verdict') == 'running' and previous.get('tree') == tree
              and previous.get('config_hash') == cfg_hash and previous.get('commands_hash') == signature
              and previous.get('environment_hash') == environment_hash)
    execution_id = previous['execution_id'] if resume else uuid.uuid4().hex
    context = native.digest([POLICY, cfg_hash, signature, execution_id]
                            + ([environment_hash] if environment_hash is not None else []))
    if checkpoint:
        # Persist before spawning: journal publication can be rejected, or this
        # caller can die, while the managed test worker continues independently.
        native.atomic_json(checkpoint, {'tree': tree, 'config_hash': cfg_hash,
            'commands_hash': signature, 'execution_id': execution_id, 'verdict': 'running',
            'environment_hash': environment_hash})
    results = {}
    stopped = None
    failed = False
    for item in commands:
        if stopped or (failed and not item.get('independent')):
            if collect_independent:
                results[item['name']] = {'result': {'verdict': 'not-run',
                    'reason': stopped or 'depends on an earlier failed command'}, 'transport_code': 2}
                continue
            break
        if still_valid:
            still_valid()
        expected = testrun.key_of(str(root), item['command'], cache_context=context)
        outcome, code = testrun.run(str(root), item['command'], item['timeout'], cache_context=context)
        if code == 0 and (outcome.get('tree_changed') is not False or outcome.get('key') != expected
                          or outcome.get('source_key') != expected):
            outcome = {**outcome, 'verdict': 'problem', 'error': 'test origin/tree changed; current code is unverified'}
            code = 1
        results[item['name']] = {'result': outcome, 'transport_code': code}
        if code or outcome.get('verdict') != 'pass':
            if not collect_independent:
                break
            failed = True
            if (code or outcome.get('verdict') != 'problem' or environment_failure(outcome)
                    or outcome.get('tree_changed') is not False or type(outcome.get('code')) is not int
                    or outcome['code'] != 1):
                stopped = 'execution, environment or preparation failed'
        if native.code_tree(root) != tree or native.config(root)[1] != cfg_hash:
            stopped = 'code/config changed during checks'
    fresh = native.code_tree(root) == tree and native.config(root)[1] == cfg_hash
    passed = fresh and len(results) == len(commands) and all(
        row['transport_code'] == 0 and row['result'].get('verdict') == 'pass' for row in results.values())
    receipt = {'tree': tree if fresh else None, 'config_hash': cfg_hash, 'commands_hash': signature,
            'environment_hash': environment_hash,
            'commands': commands, 'execution_id': execution_id, 'results': results, 'verdict': ('pass' if passed else 'running' if any(
                row['transport_code'] == 3 or row['result'].get('verdict') == 'running'
                for row in results.values()) else 'problem'),
            'reused': False, 'at': native.now()}
    if checkpoint:
        native.atomic_json(checkpoint, receipt)
    return receipt


def development(session, story, request, repo=None, task=None):
    path, initial, _, common = native.read_session(session)
    _, root = native.bound(initial, story, common)
    if repo:
        root = native.integration_root(initial['stories'][story], repo, common)
    with check_lock.worktree_lock(common, root) as checkpoint:
        with native.locked(common):
            _, data, _, _ = native.read_session(path)
            if not enabled(data) or data['status'] != 'running':
                raise ValueError('staged verification requires a running integration-full-v1 journal')
            row, bound_root = native.bound(data, story, common)
            if repo:
                bound_root = native.integration_root(row, repo, common)
            if bound_root != root:
                raise ValueError('verification worktree changed before checks started')
            producer = None
            if native_policy.enabled(data):
                from native_repair import actor
                if not task:
                    raise ValueError('bounded check requires --task of its actual verifier')
                producer = actor(data, story, {'verifier'}, task)[0]
            cfg, cfg_hash = native.config(root)
            commands = development_plan(root, cfg, request)
            failed_full = data.get('integration_gate', {}).get('verdict') == 'problem'
            if failed_full and (not any(item['name'].startswith('dev/') for item in commands)
                                or any(item['name'] == 'project-tests' for item in commands)):
                raise ValueError('failed full gate requires real focused tests/build first; full_risk cannot launch another full suite')
            previous = row.get('development_check')
            if producer and (not request.get('environment') or not previous
                    or previous.get('request', {}).get('environment') != request.get('environment')):
                previous = None
            if failed_full and previous and previous.get('at', '') <= data['integration_gate'].get('at', ''):
                previous = None  # An environment repair needs fresh focused evidence, even on unchanged code.
            expected = check_lock.snapshot(data, [story])
            tree, phase = native.code_tree(root), row.get('phase')
        def valid():
            if producer:
                _, current, _, _ = native.read_session(path)
                check_lock.validate(current, [story], expected, root, tree, cfg_hash)
                from native_repair import actor
                if actor(current, story, {'verifier'}, task)[0] != producer:
                    raise ValueError('verification producer changed')
                if request.get('environment'):
                    native_policy.reference(request['environment'])
        receipt = execute(root, commands, previous, checkpoint,
                          collect_independent=bool(producer), still_valid=valid,
                          environment=request.get('environment') if producer else None)
        if producer:
            receipt.update(kind='independent-verification', producer_task=producer,
                           checkpoint_policy=native_policy.POLICY)
        save_logs(receipt, path.parent / 'verification-evidence' / uuid.uuid4().hex)
        with native.locked(common):
            _, data, _, _ = native.read_session(path)
            check_lock.validate(data, [story], expected, root, tree, cfg_hash)
            if producer:
                from native_repair import actor
                if actor(data, story, {'verifier'}, task)[0] != producer:
                    raise ValueError('verification producer changed')
                receipt.update(request=request, request_hash=native.digest(request))
                return stage(data, path, producer, [story], root, receipt, expected, phase)
            row, _ = native.bound(data, story, common)
            record_checks(row, receipt)
            row['development_check'] = {**receipt, 'request': request, 'request_hash': native.digest(request)}
            if producer and receipt['verdict'] != 'running':
                data['events'].append({'event': 'independent-check-result', 'story': story,
                    'task_id': producer, 'execution_id': receipt['execution_id'],
                    'seconds': sum(r['result'].get('seconds', 0) for r in receipt['results'].values()
                                   if not r['result'].get('reused')),
                    'at': native.now()})
            data['focused_repair'] = receipt
            check_lock.set_phase(row, phase)
            native.atomic_json(path, data)
        return {'session': str(path), 'story': story, 'stage': 'development', **receipt}


def require_development(data, story, root):
    row = data['stories'][story]
    receipt = row.get('development_check', {})
    if native_policy.enabled(data):
        task = data.get('tasks', {}).get(receipt.get('producer_task'), {})
        if (receipt.get('kind') != 'independent-verification' or task.get('role') != 'verifier'
                or task.get('story') != story or task.get('status') != 'completed'
                or not receipt.get('evidence')):
            raise ValueError('development acceptance requires independent producer and logs')
    cfg, cfg_hash = native.config(root)
    request = receipt.get('request')
    if (receipt.get('verdict') != 'pass' or receipt.get('tree') != native.code_tree(root)
            or receipt.get('config_hash') != cfg_hash or receipt.get('request_hash') != native.digest(request)
            or receipt.get('commands_hash') != native.digest(development_plan(root, cfg, request)) or not evidence_valid(receipt)):
        raise ValueError('missing/current focused development and compile/build evidence')


def integration_plan(data, stories, root):
    commands = {}
    for story in stories:
        if story not in data['stories']:
            raise ValueError('integration story is outside the saved plan')
        row = data['stories'][story]
        if row.get('status') not in ('verified', 'completed') or not row.get('commit'):
            raise ValueError('integration needs development-verified stories')
        if native.git(str(root), 'merge-base', '--is-ancestor', row['commit'], 'HEAD').returncode:
            raise ValueError('integration candidate does not contain every verified story commit')
        for item in native.required_checks(data, story, row, root):
            if item['kind'] != 'command':
                continue
            value, timeout = verify.command_check(str(root), item['name'])
            if not value:
                raise ValueError('mandatory integration command is unavailable: ' + item['name'])
            commands[item['name']] = {'name': item['name'], 'command': value, 'timeout': timeout or 1800}
    # Full project-tests is a landing obligation even when a changed-file detector narrows away a check.
    value, timeout = verify.command_check(str(root), 'project-tests')
    if not value:
        raise ValueError('full integration gate needs a registered project-tests command')
    commands['project-tests'] = {'name': 'project-tests', 'command': value, 'timeout': timeout or 1800}
    cfg, _ = native.config(root)
    for name, item in project_tests.settings(cfg).get('build', {}).items():
        commands['build/' + name] = command(root, 'build/' + name, item)
    return list(commands.values())


def integration(session, stories, repo, task=None):
    path, _, _, common = native.read_session(session)
    root, owner = native.canonical(repo)
    if owner != common:
        raise ValueError('integration candidate belongs to another repository')
    if not isinstance(stories, list) or not stories or len(set(stories)) != len(stories):
        raise ValueError('integration needs a nonempty unique story list')
    with check_lock.worktree_lock(common, root) as checkpoint:
        with native.locked(common):
            _, data, _, _ = native.read_session(path)
            if not enabled(data) or data['status'] != 'running':
                raise ValueError('integration requires a running integration-full-v1 journal')
            cfg_hash = native.config(root)[1]
            if cfg_hash != data['config_hash']:
                raise ValueError('integration candidate configuration differs from the saved plan')
            commands = integration_plan(data, stories, root)
            producer = None
            if native_policy.enabled(data):
                if not task:
                    raise ValueError('bounded integration requires --task of its actual producer')
                import native_tasks
                _, spec, _ = native_tasks.read_task(task)
                if spec['story'] not in stories or spec['checkpoint'] != 'integration':
                    raise ValueError('integration task does not cover this candidate')
                from native_repair import actor
                producer = actor(data, spec['story'], {'story-runner', 'verifier'}, task)[0]
                try:
                    for identity in stories:
                        require_integration(data, identity, root)
                    return {'stage': 'integration', **data['integration_gate'], 'accepted': True}
                except ValueError:
                    pass
            previous = data.get('integration_gate')
            if previous and previous.get('verdict') == 'problem':
                repair = data.get('focused_repair', {})
                if (repair.get('verdict') != 'pass' or not any(name.startswith('dev/') for name in repair.get('results', {}))
                        or 'project-tests' in repair.get('results', {}) or repair.get('tree') != native.code_tree(root)
                        or repair.get('config_hash') != cfg_hash
                        or repair.get('at', '') <= previous.get('at', '')):
                    raise ValueError('failed full gate: run focused regressions and build on the repaired candidate before another full gate')
            expected = check_lock.snapshot(data, stories)
            tree = native.code_tree(root)
            git_tree = native.git(str(root), 'rev-parse', 'HEAD^{tree}').stdout.strip()
            if producer:
                previous = None  # Unknown external environment: never rerun using an unaccepted old pass.
        def valid_integration():
            if producer:
                _, current, _, _ = native.read_session(path)
                check_lock.validate(current, stories, expected, root, tree, cfg_hash)
                if current.get('tasks', {}).get(producer, {}).get('status') != 'running':
                    raise ValueError('integration producer stopped')
        receipt = execute(root, commands, previous, checkpoint, still_valid=valid_integration,
                          collect_independent=bool(producer))
        valid_integration()
        if producer:
            receipt.update(kind='independent-integration', producer_task=producer,
                           checkpoint_policy=native_policy.POLICY)
        save_logs(receipt, path.parent / 'verification-evidence' / uuid.uuid4().hex)
        with native.locked(common):
            _, data, _, _ = native.read_session(path)
            check_lock.validate(data, stories, expected, root, tree, cfg_hash)
            if (native.git(str(root), 'rev-parse', 'HEAD^{tree}').stdout.strip() != git_tree
                    or native.digest(integration_plan(data, stories, root)) != native.digest(commands)):
                raise ValueError('integration candidate changed while checks ran; result was not recorded')
            receipt['stories'] = stories
            receipt['git_tree'] = git_tree
            if producer:
                return stage(data, path, producer, stories, root, receipt, expected, None)
            for story in stories:
                record_checks(data['stories'][story], receipt)
            data['integration_gate'] = receipt
            native.atomic_json(path, data)
        return {'stage': 'integration', **receipt}


def require_integration(data, story, root):
    receipt = data.get('integration_gate', {})
    cfg_hash = native.config(root)[1]
    stories = receipt.get('stories', [])
    if native_policy.enabled(data):
        producer = data.get('tasks', {}).get(receipt.get('producer_task'), {})
        if (receipt.get('kind') != 'independent-integration' or not receipt.get('evidence')
                or producer.get('role') not in ('story-runner', 'verifier')
                or producer.get('status') != 'completed'
                or producer.get('checkpoint') != 'integration' or producer.get('story') not in stories):
            raise ValueError('full gate requires independent integration provenance')
    if (story not in stories or receipt.get('verdict') != 'pass'
            or receipt.get('tree') != native.code_tree(root) or receipt.get('config_hash') != cfg_hash
            or receipt.get('git_tree') != native.git(str(root), 'rev-parse', 'HEAD^{tree}').stdout.strip()
            or receipt.get('commands_hash') != native.digest(integration_plan(data, stories, root)) or not evidence_valid(receipt)):
        raise ValueError('missing/current full gate for the exact integration candidate')
