"""Content-addressed shared epic context with one finite compiler owner."""
from pathlib import Path
import json

import native_policy as policy
import native_session as native
import native_tasks as tasks


def description(root, common, profile, request):
    if (not isinstance(request, dict) or set(request) != {'epic', 'sources', 'options', 'contract'}
            or not isinstance(request['epic'], str) or not request['epic']
            or not isinstance(request['options'], dict)):
        raise ValueError('context needs epic, sources, original compiler contract and workflow/language options')
    contract_ref = policy.reference(request['contract'])
    options = request['options']
    if (set(options) - {'language', 'workflow', 'settings'} or not isinstance(options.get('language'), str)
            or not options['language']):
        raise ValueError('context needs explicit language and hashed workflow options')
    workflow = policy.reference(options.get('workflow'))
    sources = request['sources']
    if not isinstance(sources, list) or not sources:
        raise ValueError('context requires an explicit source list')
    manifest = []
    for rel in sources:
        if (not isinstance(rel, str) or Path(rel).is_absolute() or '..' in Path(rel).parts
                or not (root / rel).resolve().is_relative_to(root) or (root / rel).is_symlink()):
            raise ValueError('context sources must be relative files in this worktree')
        manifest.append({'path': rel, 'sha256': tasks.file_hash(root / rel)})
    if len(set(sources)) != len(sources):
        raise ValueError('duplicate context source')
    contract = {k: v for k, v in profile.items() if k != 'prompt'}
    contract['prompt_sha256'] = tasks.file_hash(profile['prompt'])
    return {'policy': policy.POLICY, 'repository': str(common), 'epic': request['epic'],
            'config_hash': native.config(root)[1],
            'sources': sorted(manifest, key=lambda r: r['path']),
            'contract_sha256': contract_ref['sha256'],
            'options': {'language': options['language'], 'workflow_sha256': workflow['sha256'],
                        'settings': options.get('settings', {})},
            'compiler': contract}


def reserve(data, common, story, profile, request, task_id):
    if not data['stories'][story].get('worktree'):
        raise ValueError('bind the story worktree before reserving shared context')
    root = Path(data['stories'][story].get('worktree', data['repo'])).resolve()
    desc = description(root, common, profile, request)
    key = native.digest(desc)
    directory = common / 'auto-bmad-native' / 'context-cache' / key
    manifest = directory / 'manifest.json'
    if manifest.exists():
        saved = json.loads(manifest.read_text())
        if saved.get('description') != desc:
            raise ValueError('context cache description changed')
        if saved['state'] == 'ready':
            policy.reference(saved['artifact'])
            return {'status': 'cached', 'key': key, 'artifact': saved['artifact']}
        owner_path, owner, _, _ = native.read_session(saved['session'])
        producer = owner.get('tasks', {}).get(saved['task_id'], {})
        state = producer.get('status')
        failed = state in (None, 'failed', 'stopped')
        owner_task = Path(saved['session']).parent / 'tasks' / saved['task_id'] / 'task.json'
        if state == 'prepared' and owner_task.exists():
            issued = json.loads(owner_task.read_text())
            failed = (owner.get('active_tasks', {}).get(tasks.active_key(issued)) != saved['task_id']
                      or owner.get('status') != 'running')
        if state == 'completed' and producer.get('receipt'):
            receipt = Path(producer['receipt'])
            if tasks.file_hash(receipt) != producer.get('receipt_hash'):
                raise ValueError('context producer receipt changed')
            failed = json.loads(receipt.read_text()).get('state') in ('failed', 'blocked')
        if not failed:
            return {'status': 'waiting', 'key': key, 'owner_task': saved['task_id'],
                    'owner_session': str(owner_path)}
        row = data['stories'][story]
        if row['technical_retries'] >= data['technical_limit']:
            raise ValueError('context compiler technical retry budget exhausted')
        row['technical_retries'] += 1
        data['events'].append({'event': 'retry', 'story': story,
            'reason': 'replace terminal or superseded context producer', 'at': native.now()})
    directory.mkdir(parents=True, exist_ok=True)
    native.atomic_json(manifest, {'state': 'reserved', 'description': desc,
        'session': data['session'], 'task_id': task_id, 'source_root': str(root), 'request': request})
    return {'status': 'reserved', 'key': key, 'manifest': str(manifest),
            'output': str(directory / ('draft-' + task_id + '.md'))}


def publish(task_path, artifact):
    path, spec, common = tasks.read_task(task_path)
    with native.locked(common):
        _, data, _, _ = native.read_session(spec['session'])
        if data['status'] != 'running':
            raise ValueError('session is not running')
        from native_repair import actor
        tid, _, producer = actor(data, spec['story'], {'context-compiler'}, path, terminal=True)
        ref = policy.reference(artifact)
        receipt = Path(producer['receipt'])
        accepted = json.loads(receipt.read_text())
        if (tasks.file_hash(receipt) != producer['receipt_hash'] or ref not in accepted['artifacts']
                or accepted.get('state') not in ('ready', 'done')):
            raise ValueError('context artifact is not in the completed compiler receipt')
        reservation = producer.get('context_reservation')
        if not reservation:
            raise ValueError('compiler task has no context reservation')
        if Path(reservation['output']).is_symlink() or Path(ref['path']) != Path(reservation['output']).resolve():
            raise ValueError('context publication must use the assigned compiler output')
        manifest = Path(reservation['manifest'])
        saved = json.loads(manifest.read_text())
        if saved['task_id'] != tid or saved['session'] != spec['session']:
            raise ValueError('context reservation belongs to another producer')
        if saved['state'] == 'ready':
            policy.reference(saved['artifact'])
            if ref['sha256'] != saved['artifact']['sha256']:
                raise ValueError('context was already published with different content')
            return saved['artifact']
        desc = saved['description']
        request = saved['request']
        if description(Path(saved['source_root']), common, spec['profile'], request) != desc:
            raise ValueError('context sources or compiler changed before publication')
        content = Path(ref['path']).read_text()
        if not content.strip():
            raise ValueError('empty context artifact')
        output = manifest.parent / 'context.md'
        # The manifest is the atomic publication point; no reader uses a draft.
        output.write_text(content)
        saved.update(state='ready', artifact={'path': str(output), 'sha256': tasks.file_hash(output)})
        native.atomic_json(manifest, saved)
        data['events'].append({'event': 'context-published', 'task_id': tid,
            'story': spec['story'], 'key': reservation['key'], 'at': native.now()})
        native.atomic_json(Path(spec['session']), data)
        return saved['artifact']


def consume(data, common, story, request, artifact):
    root = Path(data['stories'][story].get('worktree', data['repo'])).resolve()
    desc = description(root, common, data['roles']['context-compiler'], request)
    manifest = common / 'auto-bmad-native/context-cache' / native.digest(desc) / 'manifest.json'
    if not manifest.is_file():
        raise ValueError('consumer context sources do not match a published artifact')
    saved = json.loads(manifest.read_text())
    ref = policy.reference(artifact)
    if saved.get('state') != 'ready' or saved.get('description') != desc or saved.get('artifact') != ref:
        raise ValueError('consumer context artifact does not match its source manifest')
    return ref
