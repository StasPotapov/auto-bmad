"""Read-only wall-clock progress from durable events, not inferred model activity."""
from datetime import datetime, timezone


def stamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def interval(start, end, now):
    a, b = stamp(start), stamp(end) if end else now
    return {'started_at': start, 'finished_at': end,
            'elapsed_seconds': max(0, int((b - a).total_seconds())) if a and b else None}


def snapshot(data, story=None, now=None):
    now = now or datetime.now(timezone.utc)
    events = data.get('events', [])
    selected = [e for e in events if e.get('story') == story] if story else events
    terminal = data.get('status') in ('completed', 'cancelled')
    if story:
        terminal = terminal or data['stories'][story].get('status') == 'completed'
        starts = [e.get('at') for e in selected if e.get('event') in ('bind', 'task-start')]
        start = starts[0] if starts else None
        ends = [e.get('at') for e in selected if e.get('event') == 'finalize']
        end = ends[-1] if ends else None
    else:
        start, end = data.get('created'), None
    if terminal and not end:
        end = events[-1].get('at') if events else None
    output = interval(start, end, now)
    output['clock'] = 'wall time including waits/interruptions; not summed agent time'
    output['active_tasks'] = []
    for identity, task in data.get('tasks', {}).items():
        if story and task.get('story') != story:
            continue
        if task.get('status') != 'running':
            continue
        starts = [e.get('at') for e in events
                  if e.get('event') == 'task-start' and e.get('task_id') == identity]
        output['active_tasks'].append({'task_id': identity, 'story': task.get('story'),
            'role': task.get('role'), 'checkpoint': task.get('checkpoint'),
            **interval(starts[-1] if starts else None, None, now)})
    # A terminal blocked receipt may not have a phase event yet. Surface it without
    # claiming that the entire story/session has stopped, or rereading full reports.
    results = [e for e in selected if e.get('event') == 'task-result']
    if results:
        latest = results[-1]
        task = data.get('tasks', {}).get(latest.get('task_id'), {})
        output['last_result'] = {key: task[key] for key in
                                ('role', 'checkpoint', 'result_state', 'next', 'blocker', 'actions') if key in task}
        output['last_result']['at'] = latest.get('at')
    output['last_event_at'] = selected[-1].get('at') if selected else None
    return output
