"""Native journal accounting and opt-in local Codex rollout usage. Never reads the app DB."""
import collections
import json
import os
from pathlib import Path
import re
import time
import datetime

from agent_runtime import atomic_json
from cli_stats import counters, read
from execution_state import canonical

UUID = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')


def checkpoint_metrics(data, story=None):
    """Journal measurements only: overlap is not elapsed time and gaps are not waits."""
    events = [e for e in data.get('events', []) if story is None or e.get('story') == story]
    starts, spans, counts, totals = {}, [], collections.Counter(), collections.Counter()
    roles = {tid: task.get('role', 'unknown') for tid, task in data.get('tasks', {}).items()}
    retries, local, executions = [], 0, {}
    for event in events:
        name = event.get('event')
        if name == 'task-start':
            counts[roles.get(event.get('task_id'), 'unknown')] += 1
        if name in ('retry', 'repair', 'repair-batch', 'task-stop'):
            retries.append({key: event.get(key) for key in ('event', 'kind', 'reason', 'at')})
        if name == 'local-check-start' and event.get('mode') == 'attempt':
            local += 1
        if name in ('local-check-result', 'diagnostic-check-result', 'independent-check-result') and event.get('execution_id'):
            executions[event['execution_id']] = event.get('seconds', 0)
        if name != 'agent':
            continue
        try:
            stamp = datetime.datetime.fromisoformat(event['at']).timestamp()
        except (ValueError, KeyError):
            continue
        identity = event['agent_id']
        if event['status'] in ('running', 'waiting'):
            starts.setdefault(identity, (stamp, event['role']))
        elif identity in starts:
            start, role = starts.pop(identity)
            if stamp >= start:
                spans.append((start, stamp)); totals[role] += stamp - start
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    launched = {e.get('task_id') for e in events if e.get('event') == 'task-start'}
    edges = [tid for tid in launched if data.get('tasks', {}).get(tid, {}).get('source_task')]
    return {'launches_by_role': dict(counts), 'handoffs': len(edges),
        'launches_without_handoff_binding': len(launched) - len(edges),
        'completed_agent_seconds': round(sum(totals.values()), 3),
        'agent_seconds_by_role': {r: round(t, 3) for r, t in totals.items()},
        'completed_agent_wall_seconds': round(sum(b-a for a, b in merged), 3),
        'unfinished_agents': len(starts), 'local_attempts': local,
        'measured_command_seconds': sum(executions.values()) if executions else None,
        'wait_seconds': None, 'retry_reasons': retries,
        'measurement': 'journal intervals; command time only when recorded; waits and LLM savings unknown'}


def sessions(repo):
    _, common = canonical(repo)
    return sorted((common / 'auto-bmad-native').glob('*/session.json'))


def find(repo, identity):
    _, common = canonical(repo)
    parent = common / 'auto-bmad-native'
    path = Path(identity)
    if not path.is_absolute():
        path = parent / identity.removeprefix('native:') / 'session.json'
    if path.name != 'session.json' or path.parent.parent.resolve() != parent.resolve():
        return None
    return path.resolve() if path.is_file() else None


def bind(repo, identity, thread, turn):
    from native_session import locked
    path = find(repo, identity)
    if not path or not all(UUID.fullmatch(v or '') for v in (thread, turn)):
        raise ValueError('native usage needs an existing native session and exact Codex thread/turn UUIDs')
    _, common = canonical(repo)
    folder = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'sessions'
    verified = False
    for candidate in folder.glob(f'**/rollout-*-{thread}.jsonl'):
        if not candidate.resolve().is_relative_to(folder.resolve()):
            continue
        events = entries(candidate)
        meta = next(events, {}).get('payload', {})
        if meta.get('id') != thread or not meta.get('cwd'):
            continue
        try:
            _, owner = canonical(meta['cwd'])
        except (OSError, ValueError):
            continue
        if owner != common:
            continue
        verified = any((e.get('type') == 'event_msg' and e.get('payload', {}).get('type') == 'task_started'
                        and e['payload'].get('turn_id') == turn) or
                       (e.get('type') == 'token_usage_record' and e.get('payload', {}).get('root_turn_id') == turn
                        and e['payload'].get('session_id') == thread)
                       for e in events)
        if verified:
            break
    if not verified:
        raise ValueError('Codex root thread/turn is not present in local rollouts for this repository')
    with locked(common):
        for other in sessions(repo):
            bindings = read(other.parent / 'accounting.json').get('codex', [])
            if other != path and {'thread_id': thread, 'turn_id': turn} in bindings:
                raise ValueError('this Codex root turn is already assigned to another native run')
        target = path.parent / 'accounting.json'
        data = read(target)
        item = {'thread_id': thread, 'turn_id': turn}
        if item not in data.setdefault('codex', []):
            data['codex'].append(item)
            atomic_json(target, data)


def entries(path):
    with path.open(encoding='utf-8') as handle:
        for line in handle:
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    yield item
            except ValueError:
                # A growing final line is not a completed response measurement.
                continue


def spawn_meta(meta):
    value = meta
    for key in ('source', 'subagent', 'thread_spawn'):
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, dict) else {}


def rollouts(bindings, home=None):
    """Select by ancestry metadata, then exact root-turn IDs, never by prompt content."""
    folder = Path(home or os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'sessions'
    metadata = {}
    for path in folder.glob('**/rollout-*.jsonl'):
        if not path.resolve().is_relative_to(folder.resolve()):
            continue
        try:
            first = next(entries(path), {})
            meta = first.get('payload', {})
            if first.get('type') == 'session_meta' and isinstance(meta, dict) and meta.get('id'):
                # Duplicate thread files are processed with response-id deduplication below.
                metadata.setdefault(meta['id'], []).append((path, meta))
        except OSError:
            continue
    root_ids = {b['thread_id'] for b in bindings}
    selected = set(root_ids)
    while True:
        added = {tid for tid, rows in metadata.items() for _, meta in rows
                 if spawn_meta(meta).get('parent_thread_id') in selected}
        if added <= selected:
            break
        selected |= added
    return [(path, meta) for tid in selected for path, meta in metadata.get(tid, [])]


def measurements(bindings, home=None):
    wanted = {(b['thread_id'], b['turn_id']) for b in bindings}
    root_turns = {b['turn_id'] for b in bindings}
    found, seen = {}, {}
    for path, meta in rollouts(bindings, home):
        tid = meta['id']
        agent_path = spawn_meta(meta).get('agent_path')
        row = found.setdefault(tid, {'thread_id': tid, 'agent_path': agent_path, 'turns': [],
                                    'turn_ids': {turn for root, turn in wanted if root == tid},
                                    'completed': set(), 'completion_times': {}, 'conflict': False})
        try:
            for event in entries(path):
                value = event.get('payload', {})
                if not isinstance(value, dict):
                    continue
                if event.get('type') == 'event_msg' and value.get('type') == 'task_complete':
                    row['completed'].add(value.get('turn_id'))
                    if isinstance(event.get('timestamp'), str):
                        row['completion_times'][value.get('turn_id')] = event['timestamp']
                if (event.get('type') == 'event_msg' and value.get('type') == 'task_started'
                        and value.get('root_turn_id') in root_turns and value.get('turn_id')):
                    row['turn_ids'].add(value['turn_id'])
                if event.get('type') != 'token_usage_record':
                    continue
                if (value.get('session_id'), value.get('root_turn_id')) not in wanted or value.get('thread_id') != tid:
                    continue
                response, turn = value.get('response_id'), value.get('turn_id')
                if not isinstance(response, str) or not response or not isinstance(turn, str):
                    continue
                usage = value.get('usage')
                usage = usage if isinstance(usage, dict) else {}
                key = (tid, response)
                if key in seen:
                    if seen[key] != usage:
                        row['conflict'] = True
                    continue
                seen[key] = usage
                row['turns'].append(usage)
                row['turn_ids'].add(turn)
                stamp = event.get('timestamp')
                if isinstance(stamp, str):
                    row['started'] = min(row.get('started', stamp), stamp)
                    row['ended'] = max(row.get('ended', stamp), stamp)
        except OSError:
            row['conflict'] = True
    return {tid: row for tid, row in found.items() if row['turns'] or row['turn_ids']}


def collect_session(path, home=None):
    from stats import add_tokens, total, minutes
    snapshot_revision = time.time_ns()
    data = read(path)
    if data.get('transport') != 'native-subagents':
        return []
    bindings = read(path.parent / 'accounting.json').get('codex', [])
    measured = measurements(bindings, home) if bindings else {}
    registered = {key: (story, a) for story, row in data['stories'].items() for key, a in row['agents'].items()}
    threads = {a['thread_id']: (story, key, a) for key, (story, a) in registered.items() if a.get('thread_id')}
    buckets = collections.defaultdict(list)
    matched = set()
    root_ids = {b['thread_id'] for b in bindings}
    for tid, m in measured.items():
        agent_path = m.get('agent_path') or ''
        exact = threads.get(tid)
        if not exact and agent_path in registered:
            story, agent = registered[agent_path]
            exact = (story, agent_path, agent)
        if tid in root_ids:
            story, key, agent = None, 'orchestrator', {'role': 'orchestrator'}
        elif exact:
            story, key, agent = exact
            matched.add(key)
        else:
            ancestors = [key for key in registered if agent_path.startswith(key + '/')]
            story = registered[max(ancestors, key=len)][0] if ancestors else None
            key, agent = tid, {'role': 'unattributed'}
        profile = data.get('roles', {}).get(agent['role'], {})
        usage, acc, availability = counters({'turns': m['turns'],
            'unfinished_turn': m['conflict'] or not m['turn_ids'] <= m['completed']
                or agent.get('status') in ('running', 'waiting')})
        buckets[story].append({'id': tid, 'role': agent['role'], 'model_requested': profile.get('model', '?'),
            'effort': profile.get('effort'), 'execution_status': agent.get('status', data['status']),
            'usage': usage, 'tokens': acc, 'usage_status': availability, 'responses': len(m['turns']),
            'tools': {}})
    for key, (story, agent) in registered.items():
        if key not in matched:
            usage, acc, availability = counters({})
            buckets[story].append({'id': key, 'role': agent['role'],
                'model_requested': data.get('roles', {}).get(agent['role'], {}).get('model', '?'),
                'execution_status': agent['status'], 'usage': usage, 'tokens': acc,
                'usage_status': availability, 'responses': 0, 'tools': {}})
    # An unbound/missing main-chat measurement must remain visibly unknown.
    if not any(c['role'] == 'orchestrator' for c in buckets[None]):
        usage, acc, availability = counters({})
        buckets[None].append({'id': 'orchestrator', 'role': 'orchestrator', 'model_requested': '?',
            'execution_status': data['status'], 'usage': usage, 'tokens': acc,
            'usage_status': availability, 'responses': 0, 'tools': {}})
    rows = []
    for story in [None, *data['stories']]:
        calls = buckets[story]
        by_model, by_role_model, agents = {}, {}, collections.Counter()
        for call in calls:
            model, role = call['model_requested'], call['role']
            add_tokens(by_model, {model: call['tokens']})
            add_tokens(by_role_model.setdefault(role, {}), {model: call['tokens']})
            agents[role] += 1
        row = data['stories'].get(story, {})
        times = [e['at'] for e in data.get('events', []) if e.get('story') == story and e.get('at')]
        started = times[0] if story and times else data['created']
        ended = row.get('completed') if story else max((s.get('completed', '') for s in data['stories'].values()), default='')
        if not story and data['status'] == 'cancelled':
            ended = next((e['at'] for e in reversed(data.get('events', [])) if e.get('event') == 'cancel'), None)
        if not story and data['status'] == 'completed':
            completed = [stamp for tid, m in measured.items() if tid in root_ids
                         for turn, stamp in m['completion_times'].items() if turn in m['turn_ids']]
            ended = max([ended or '', *completed])
        if not ended and data['status'] in ('completed', 'cancelled'):
            ended = data.get('events', [{}])[-1].get('at')
        rows.append({'id': f'native:{path.parent.name}:{story or "orchestrator"}',
            'session': 'native:' + path.parent.name, 'source': 'native',
            'revision': snapshot_revision,
            'kind': 'story' if story else 'orchestrator', 'story': story,
            'epic': data['plan'].get('epic'), 'level': data['plan']['level'],
            'status': 'done' if row.get('status') == 'completed' else row.get('status', data['status']),
            'started': started, 'ended': ended or None, 'minutes': minutes(started, ended),
            'agents': dict(agents), 'tools': {}, 'calls': calls, 'commit': row.get('commit'),
            'repair_counts': row.get('repair_counts', {}), 'technical_retries': row.get('technical_retries', 0),
            'schedule': ({'capacity': data['schedule']['capacity'],
                          'waves': [w['stories'] for w in data['schedule']['waves']]}
                         if data.get('schedule') else None),
            'tokens': {'total': total(by_model), 'by_model': by_model,
                'by_role': {role: total(models) for role, models in by_role_model.items()}, 'by_role_model': by_role_model},
            'measurement': {'input': 'reported', 'output': 'reported', 'model': 'requested',
                            'source': 'codex-token-usage-record', 'cache_write': 'unavailable'}})
    return rows


def publish(repo, identity=None, home=None):
    from stats import save
    try:
        paths = [find(repo, identity)] if identity else sessions(repo)
        rows = [row for path in paths if path for row in collect_session(path, home)]
        return {'recorded': len(rows), 'file': save(repo, rows)} if rows else {'recorded': 0}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return {'recorded': 0, 'error': str(error)}
