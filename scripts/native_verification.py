"""Staged native verification: focused development, one exact-candidate landing gate."""
from pathlib import Path
import hashlib
import shutil
import uuid

import native_session as native
import project_tests
import testrun
import verify

POLICY = 'integration-full-v1'


def enabled(data):
    return native.thin_root(data) and data.get('verification_policy') == POLICY


def command(root, name, item, targets=None):
    value = project_tests.development_command(root, item, targets) if targets is not None else item['command']
    return {'name': name, 'command': value, 'timeout': item.get('timeout', 1800)}


def development_plan(root, cfg, request):
    if not isinstance(request, dict) or set(request) - {'checks', 'builds', 'build_not_applicable', 'full_risk'}:
        raise ValueError('development request accepts checks, builds, build_not_applicable and full_risk')
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


def save_logs(receipt, directory):
    directory.mkdir(parents=True, exist_ok=True)
    evidence = []
    for name, row in receipt['results'].items():
        source = row['result'].get('log')
        if not source:
            continue
        source = Path(source)
        if not source.is_file():
            raise ValueError('test evidence log is missing: ' + str(source))
        target = directory / (native.digest(name)[:16] + '.log')
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        row['result']['log'] = str(target)
        evidence.append({'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    receipt['evidence'] = evidence


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


def execute(root, commands, previous=None):
    """Only exact code/config/command matches may reuse a successful recorded result."""
    cfg_hash = native.config(root)[1]
    tree = native.code_tree(root)
    signature = native.digest(commands)
    if (previous and previous.get('tree') == tree and previous.get('config_hash') == cfg_hash
            and previous.get('commands_hash') == signature and previous.get('verdict') == 'pass'
            and evidence_valid(previous)):
        return {**previous, 'reused': True}
    resume = (previous and previous.get('verdict') == 'running' and previous.get('tree') == tree
              and previous.get('config_hash') == cfg_hash and previous.get('commands_hash') == signature)
    execution_id = previous['execution_id'] if resume else uuid.uuid4().hex
    context = native.digest([POLICY, cfg_hash, signature, execution_id])
    results = {}
    for item in commands:
        expected = testrun.key_of(str(root), item['command'], cache_context=context)
        outcome, code = testrun.run(str(root), item['command'], item['timeout'], cache_context=context)
        if code == 0 and (outcome.get('tree_changed') is not False or outcome.get('key') != expected
                          or outcome.get('source_key') != expected):
            outcome = {**outcome, 'verdict': 'problem', 'error': 'test origin/tree changed; current code is unverified'}
            code = 1
        results[item['name']] = {'result': outcome, 'transport_code': code}
        if code or outcome.get('verdict') != 'pass':
            break
    fresh = native.code_tree(root) == tree and native.config(root)[1] == cfg_hash
    passed = fresh and len(results) == len(commands) and all(
        row['transport_code'] == 0 and row['result'].get('verdict') == 'pass' for row in results.values())
    return {'tree': tree if fresh else None, 'config_hash': cfg_hash, 'commands_hash': signature,
            'commands': commands, 'execution_id': execution_id, 'results': results, 'verdict': ('pass' if passed else 'running' if any(
                row['transport_code'] == 3 or row['result'].get('verdict') == 'running'
                for row in results.values()) else 'problem'),
            'reused': False, 'at': native.now()}


def development(session, story, request, repo=None):
    path, _, _, common = native.read_session(session)
    with native.locked(common):
        _, data, _, _ = native.read_session(path)
        if not enabled(data) or data['status'] != 'running':
            raise ValueError('staged verification requires a running integration-full-v1 journal')
        row, root = native.bound(data, story, common)
        if repo:
            root = native.integration_root(row, repo, common)
        cfg, _ = native.config(root)
        commands = development_plan(root, cfg, request)
        failed_full = data.get('integration_gate', {}).get('verdict') == 'problem'
        if failed_full and (not any(item['name'].startswith('dev/') for item in commands)
                            or any(item['name'] == 'project-tests' for item in commands)):
            raise ValueError('failed full gate requires real focused tests/build first; full_risk cannot launch another full suite')
        previous = row.get('development_check')
        if failed_full and previous and previous.get('at', '') <= data['integration_gate'].get('at', ''):
            previous = None  # An environment repair needs fresh focused evidence, even on unchanged code.
        receipt = execute(root, commands, previous)
        save_logs(receipt, path.parent / 'verification-evidence' / native.digest([story, receipt['tree'], receipt['commands_hash']]))
        record_checks(row, receipt)
        row['development_check'] = {**receipt, 'request': request, 'request_hash': native.digest(request)}
        data['focused_repair'] = receipt
        row['phase'] = 'verification'
        native.atomic_json(path, data)
        return {'session': str(path), 'story': story, 'stage': 'development', **receipt}


def require_development(data, story, root):
    row = data['stories'][story]
    receipt = row.get('development_check', {})
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


def integration(session, stories, repo):
    path, _, _, common = native.read_session(session)
    root, owner = native.canonical(repo)
    if owner != common:
        raise ValueError('integration candidate belongs to another repository')
    if not isinstance(stories, list) or not stories or len(set(stories)) != len(stories):
        raise ValueError('integration needs a nonempty unique story list')
    with native.locked(common):
        _, data, _, _ = native.read_session(path)
        if not enabled(data) or data['status'] != 'running':
            raise ValueError('integration requires a running integration-full-v1 journal')
        if native.config(root)[1] != data['config_hash']:
            raise ValueError('integration candidate configuration differs from the saved plan')
        commands = integration_plan(data, stories, root)
        previous = data.get('integration_gate')
        if previous and previous.get('verdict') == 'problem':
            repair = data.get('focused_repair', {})
            if (repair.get('verdict') != 'pass' or not any(name.startswith('dev/') for name in repair.get('results', {}))
                    or 'project-tests' in repair.get('results', {}) or repair.get('tree') != native.code_tree(root)
                    or repair.get('config_hash') != native.config(root)[1]
                    or repair.get('at', '') <= previous.get('at', '')):
                raise ValueError('failed full gate: run focused regressions and build on the repaired candidate before another full gate')
        receipt = execute(root, commands, previous)
        save_logs(receipt, path.parent / 'verification-evidence' / native.digest([receipt['tree'], receipt['commands_hash']]))
        for story in stories:
            record_checks(data['stories'][story], receipt)
        receipt['stories'] = stories
        receipt['git_tree'] = native.git(str(root), 'rev-parse', 'HEAD^{tree}').stdout.strip()
        data['integration_gate'] = receipt
        native.atomic_json(path, data)
        return {'stage': 'integration', **receipt}


def require_integration(data, story, root):
    receipt = data.get('integration_gate', {})
    cfg_hash = native.config(root)[1]
    stories = receipt.get('stories', [])
    if (story not in stories or receipt.get('verdict') != 'pass'
            or receipt.get('tree') != native.code_tree(root) or receipt.get('config_hash') != cfg_hash
            or receipt.get('git_tree') != native.git(str(root), 'rev-parse', 'HEAD^{tree}').stdout.strip()
            or receipt.get('commands_hash') != native.digest(integration_plan(data, stories, root)) or not evidence_valid(receipt)):
        raise ValueError('missing/current full gate for the exact integration candidate')
