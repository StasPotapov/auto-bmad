"""Validate the main chat's wave plan and slot ledger; never schedule or spawn models."""

ACTIVE = ('running', 'waiting')


def prepare(data, request):
    if any(row.get('agents') for row in data['stories'].values()):
        raise ValueError('record the schedule before starting agents')
    limit = request.get('host_limit')
    if type(limit) is not int or limit < 2:
        raise ValueError('host_limit must include the main chat and at least one agent')
    plan = data['plan']
    width = 1 if plan.get('parallel') == 'off' else plan.get('parallel_width', 3)
    capacity = min(width, limit - 1)
    waves = request.get('waves')
    if not isinstance(waves, list) or not waves:
        raise ValueError('schedule needs ordered dependency waves')
    flattened = []
    for wave in waves:
        stories = wave.get('stories') if isinstance(wave, dict) else None
        if not isinstance(stories, list) or not 1 <= len(stories) <= capacity:
            raise ValueError('wave exceeds configured width or available host slots')
        if not isinstance(wave.get('reason'), str) or not wave['reason'].strip():
            raise ValueError('every wave needs a dependency/scope reason, including serial reductions')
        flattened.extend(stories)
    if flattened != list(data['stories']):
        raise ValueError('waves must cover every planned story once, in queue order')
    return {'host_limit': limit, 'capacity': capacity, 'topology': 'root-dispatched', 'waves': waves}


def admission(data, story):
    schedule = data.get('schedule')
    if not schedule:
        if data.get('schedule_required'):
            raise ValueError('record a dependency schedule before binding or launching stories')
        return
    for wave in schedule['waves']:
        if story in wave['stories']:
            return
        if any(data['stories'][s]['status'] != 'completed' for s in wave['stories']):
            raise ValueError('previous wave must be integrated and finalized first')


def agent(data, story, identity, role, status):
    admission(data, story)
    if not data.get('schedule'):
        return
    others = [(s, a) for s, row in data['stories'].items() for key, a in row['agents'].items()
              if (s, key) != (story, identity)]
    if any(identity in row['agents'] for s, row in data['stories'].items() if s != story):
        raise ValueError('an agent identity belongs to exactly one story')
    if status not in ACTIVE:
        return
    active = [(s, a) for s, a in others if a['status'] in ACTIVE]
    if len(active) >= data['schedule']['host_limit'] - 1:
        raise ValueError('native agent slot budget exhausted; join a role before dispatch')
    # A controller is a finite checkpoint, not a waiting parent occupying a worker slot.
    if any(s == story and (role == 'story-runner' or a['role'] == 'story-runner') for s, a in active):
        raise ValueError('finish the story-runner checkpoint before dispatching its roles')
    if role == 'implementer' and any(s == story for s, _ in active):
        raise ValueError('implementation requires exclusive story ownership')
    if any(s == story and a['role'] == 'implementer' for s, a in active):
        raise ValueError('join the implementer before dispatching another story role')
