"""Producer-bound diagnosis before a native execution session exists."""
import json
from pathlib import Path

import native_policy as policy


def source(value):
    import native_tasks as tasks
    path, spec, common = tasks.read_task(value)
    _, data = tasks.registry(spec, common)
    task = tasks.validate(path, spec, data)
    if (spec['session'] or spec['checkpoint'] != 'bootstrap' or spec['role'] != 'story-runner'
            or spec.get('pre_session_policy') != 'diagnosis-v1'):
        raise ValueError('diagnosis requires a newly issued pre-session bootstrap task')
    if task['status'] != 'completed' or not task.get('receipt'):
        raise ValueError('observe and accept bootstrap completion before diagnosis')
    ref = policy.reference({'path': task['receipt'], 'sha256': task['receipt_hash']})
    receipt = json.loads(Path(ref['path']).read_text())
    if (receipt['state'] not in ('blocked', 'failed') or receipt['next'] != 'triage'
            or receipt['created_session'] is not None):
        raise ValueError('bootstrap must request technical triage without a created session')
    for artifact in receipt['artifacts']:
        policy.reference(artifact)
    return path, spec, ref


def diagnose(value):
    import native_tasks as tasks
    path, spec, _ = source(value)
    metadata = spec['host_metadata']
    return tasks.prepare(repo=spec['repo'], arg=spec['request'], role='triager', checkpoint='triage',
        host_limit=metadata['host_limit'], root_thread_id=metadata['root_thread_id'],
        root_turn_id=metadata['root_turn_id'],
        accounting_unavailable_reason=metadata['accounting_unavailable_reason'],
        diagnosis_source=str(path))


def attach(spec, source_path, data, runtime):
    """Called inside prepare's registry lock, before issuing the diagnostic task."""
    path, original, receipt = source(source_path)
    if (original['repo'] != spec['repo'] or original['request'] != spec['request']
            or original['host_metadata'] != spec['host_metadata']):
        raise ValueError('diagnosis must preserve the bootstrap repository and request')
    if Path(original['transport']['binding'][0]).resolve() != (runtime / 'bin/auto-bmad').resolve():
        raise ValueError('diagnose using the bootstrap pinned runtime; never migrate an issued task')
    parent = data['tasks'][original['task_id']]
    if parent.get('diagnostic_task'):
        raise ValueError('bootstrap diagnosis already issued; use its saved task, never duplicate it')
    parent['diagnostic_task'] = spec['task_id']
    spec['pre_session_policy'] = 'diagnosis-v1'
    spec['diagnosis_source'] = {'path': str(path), 'receipt': receipt}
    spec['planning_only'] = original['planning_only']
    spec['instructions'][0] = (
        'Diagnose the accepted bootstrap blocker using its hashed receipt and artifacts. '
        'Read the project as needed; write only private diagnosis evidence. Do not modify '
        'project files/config/ignores, initialize a session, create worktrees, run story checks '
        'or bypass preflight. Return ready/next bootstrap with a concrete authorized remedy, '
        'or blocked/next decision for genuinely missing intent/access. Never spawn children.')
    spec['runtime_references'] = {}
    spec['instructions'][1] = 'Read the pinned role prompt and diagnosis input; do not load whole-story workflow documents.'
    spec['receipt_template']['next'] = 'bootstrap'
    return {'source_task': original['task_id'], 'bootstrap_receipt': receipt}


def accepted_diagnosis(value):
    import native_tasks as tasks
    path, spec, common = tasks.read_task(value)
    _, data = tasks.registry(spec, common)
    task = tasks.validate(path, spec, data)
    if spec['session'] or not spec.get('diagnosis_source') or spec['role'] != 'triager':
        raise ValueError('bootstrap retry requires a pre-session diagnosis')
    if task['status'] != 'completed' or not task.get('receipt'):
        raise ValueError('observe and accept diagnosis completion before bootstrap retry')
    ref = policy.reference({'path': task['receipt'], 'sha256': task['receipt_hash']})
    receipt = json.loads(Path(ref['path']).read_text())
    if receipt['state'] not in ('ready', 'done') or receipt['next'] != 'bootstrap' or receipt['created_session']:
        raise ValueError('diagnosis must authorize return to bootstrap')
    for item in (receipt, json.loads(Path(policy.reference(spec['diagnosis_source']['receipt'])['path']).read_text())):
        for artifact in item['artifacts']:
            policy.reference(artifact)
    return path, spec, ref


def retry(value):
    import native_tasks as tasks
    path, spec, receipt = accepted_diagnosis(value)
    metadata = spec['host_metadata']
    return tasks.prepare(repo=spec['repo'], arg=spec['request'], planning_only=spec['planning_only'],
        input_path=receipt['path'], host_limit=metadata['host_limit'],
        root_thread_id=metadata['root_thread_id'], root_turn_id=metadata['root_turn_id'],
        accounting_unavailable_reason=metadata['accounting_unavailable_reason'], bootstrap_retry=str(path))


def attach_retry(spec, source_path, data, runtime):
    path, original, receipt = accepted_diagnosis(source_path)
    if any(spec[k] != original[k] for k in ('repo', 'request', 'host_metadata', 'planning_only')):
        raise ValueError('bootstrap retry must retain original request, host metadata and planning mode')
    if Path(original['transport']['binding'][0]).resolve() != (runtime / 'bin/auto-bmad').resolve():
        raise ValueError('retry using the diagnosis pinned runtime')
    parent = data['tasks'][original['task_id']]
    if parent.get('bootstrap_retry_task'):
        raise ValueError('bootstrap retry already issued; use its saved task, never duplicate it')
    parent['bootstrap_retry_task'] = spec['task_id']
    spec['bootstrap_retry_source'] = {'path': str(path), 'receipt': receipt}
    return json.loads(Path(receipt['path']).read_text())


def routing(spec, path, payload):
    """Return executable argv, not prose that makes the root invent an unsupported role."""
    prefix = spec['transport']['binding'][:4]  # pinned executable, --executor, adapter, native
    if (spec['checkpoint'] == 'bootstrap' and payload['state'] in ('blocked', 'failed')
            and payload['next'] == 'triage' and not payload['created_session']):
        return prefix + ['task-diagnose', '--task', str(path)]
    if spec.get('diagnosis_source') and payload['state'] in ('ready', 'done'):
        return prefix + ['task-retry-bootstrap', '--task', str(path)]
    return None
