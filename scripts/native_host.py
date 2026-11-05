"""Passive guard for a host-owned continuation. Does not schedule or launch models."""

from pathlib import Path
import uuid

from agent_runtime import atomic_json


def identity(value, name):
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        valid = False
    if not valid:
        raise ValueError(f'{name} must be an actual canonical host UUID')
    return value


def runtime(data):
    roots = {str(Path(role['prompt']).resolve().parents[2])
             for role in data['roles'].values() if role.get('prompt')}
    if len(roots) != 1:
        raise ValueError('cannot identify the original pinned runtime from role prompts')
    root = Path(roots.pop())
    if not (root / 'scripts/native_session.py').is_file():
        raise ValueError('original native runtime is missing')
    return str(root)


def bind(data, previous, request):
    thread = identity(request.get('thread_id'), 'thread_id')
    automation = request.get('automation_id')
    if not isinstance(automation, str) or not automation.strip():
        raise ValueError('automation_id must come from successful host registration')
    if data['status'] != 'running':
        raise ValueError('only a running session can attach a continuation')
    binding = {'thread_id': thread, 'automation_id': automation,
               'runtime': runtime(data), 'session': data['session']}
    if previous:
        if any(previous.get(key) != value for key, value in binding.items()):
            raise ValueError('continuation is already bound; do not create a duplicate or move ownership')
        authorization = request.get('resume_authorization_turn')
        if authorization is not None:
            identity(authorization, 'resume_authorization_turn')
            used = set(previous.get('used_authorizations', []))
            if previous.get('resume_authorization_turn'):
                used.add(previous['resume_authorization_turn'])
            if authorization == previous.get('stop_turn_id') or authorization in used:
                raise ValueError('rearming needs a fresh human resume turn')
            used.add(authorization)
            previous.update(armed=True, resume_authorization_turn=authorization,
                            used_authorizations=sorted(used))
        # Retrying registration must not erase a stop or restore spent retries.
        return previous
    return {**binding, 'armed': True, 'attempts': [], 'decisions': {}}


def decide(data, state, request):
    if not state:
        raise ValueError('attach the actual host continuation first')
    if (state['session'] != data['session'] or
            request.get('thread_id') != state['thread_id'] or
            request.get('automation_id') != state['automation_id']):
        raise ValueError('host continuation ownership mismatch')
    turn = identity(request.get('turn_id'), 'turn_id')
    status = request.get('turn_status')
    if status not in ('active', 'completed', 'failed', 'interrupted', 'waiting-user',
                       'waiting-approval', 'unknown'):
        raise ValueError('unknown host turn_status')
    if type(request.get('stop_requested', False)) is not bool:
        raise ValueError('stop_requested must be a boolean')

    def result(action, reason):
        return {'action': action, 'reason': reason, 'session': data['session'],
                'runtime': state['runtime'], 'automation_id': state['automation_id'],
                'thread_id': state['thread_id'], 'turn_id': turn,
                'model_started': False}

    # Current stop signals outrank a previously issued recovery decision.
    reason = None
    if request.get('stop_requested'):
        reason = 'the user requested a stop; fresh human authorization is required'
    elif status == 'interrupted':
        reason = 'host interruption is a stop; fresh human authorization is required'
    elif status in ('waiting-user', 'waiting-approval', 'unknown'):
        reason = 'human input, approval, or reliable host state is required'
    elif data['status'] != 'running':
        reason = 'session is ' + data['status']
    elif any(row['status'] == 'blocked' or row['phase'] == 'blocked'
             for row in data['stories'].values()):
        reason = 'a story has a recorded blocker'
    elif not state['armed']:
        reason = 'continuation is disarmed; do not rearm automatically'
    if reason:
        state['armed'] = False
        state['stop_turn_id'] = turn
        return result('stop', reason)
    if status == 'active':
        return result('wait', 'the original turn is active; do not duplicate its work')
    if turn in state['decisions']:
        return result('already-claimed', 'this terminal turn already received a recovery decision')
    if state['runtime'] != runtime(data):
        raise ValueError('original runtime binding changed; inspect before recovering')

    cause = request.get('cause')
    allowed = {'completed': ('premature-final',), 'failed': ('transport', 'host-exit')}
    if cause not in allowed.get(status, ()):
        state['armed'] = False
        return result('stop', 'no confirmed recoverable technical cause')

    # Only a finalized story resets this host budget. Polls and journal writes do not.
    progress = sorted(k for k, row in data['stories'].items() if row['status'] == 'completed')
    attempts = sum(item['progress'] == progress for item in state['attempts'])
    limit = data['technical_limit']
    if type(limit) is not int or limit < 0:
        raise ValueError('invalid saved technical retry limit')
    if attempts >= limit:
        state['armed'] = False
        return result('stop', 'host technical retry budget exhausted')
    state['attempts'].append({'turn_id': turn, 'cause': cause, 'progress': progress})
    decision = result('continue', 'resume saved work with original runtime and all evidence gates')
    state['decisions'][turn] = decision
    return decision


def run(session, action, request):
    import json
    import native_session as native

    path, _, _, common = native.read_session(session)
    with native.locked(common):
        _, data, _, _ = native.read_session(path)
        sidecar = path.parent / 'host-continuation.json'
        state = json.loads(sidecar.read_text()) if sidecar.exists() else None
        if action == 'host-bind':
            state = bind(data, state, request)
            output = state
        else:
            output = decide(data, state, request)
        atomic_json(sidecar, state)
        return output
