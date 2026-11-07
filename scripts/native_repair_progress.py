"""Evidence of local repair progress; never grants independent acceptance."""
from repair_policy import environment_failure


def dependency_skip(item):
    return (item.get('transport_code') == 2
            and item['result'].get('verdict') == 'not-run'
            and item['result'].get('reason') == 'depends on an earlier failed command')


def advanced(before, after):
    """Compare the same complete command plan, including newly reachable commands.

    A whole failed command becoming green is evidence even if its old runner did
    not identify individual failures. Partial/unknown failures cannot prove a
    reduction within a command. Callers separately validate logs and test oracles.
    """
    commands = after.get('commands', [])
    current = after.get('results', {})
    if not commands or {c['name'] for c in commands} != set(current):
        return False
    for item in current.values():
        result = item['result']
        if dependency_skip(item):
            continue
        if (item.get('transport_code') or environment_failure(result)
                or result.get('verdict') not in ('pass', 'problem')):
            return False
    if all(item['result']['verdict'] == 'pass' for item in current.values()):
        return True
    if (not before or before.get('commands') != commands
            or before.get('config_hash') != after.get('config_hash')
            or before.get('environment_hash') != after.get('environment_hash')):
        return False
    previous = before.get('results', {})
    if set(previous) != set(current):
        return False
    improved = False
    for name, item in current.items():
        old, new = previous[name]['result'], item['result']
        if dependency_skip(previous[name]):
            continue  # A dependency was fixed; this command can now expose defects.
        if previous[name].get('transport_code') or environment_failure(old):
            return False
        if old.get('verdict') == 'pass':
            if new.get('verdict') != 'pass':
                return False
            continue
        if old.get('verdict') != 'problem':
            return False
        if new.get('verdict') == 'pass':
            improved = True
            continue
        if new.get('verdict') != 'problem':
            return False
        a, b = old.get('failure_ids'), new.get('failure_ids')
        if (old.get('failure_ids_complete') is not True or new.get('failure_ids_complete') is not True
                or not isinstance(a, list) or not isinstance(b, list) or not a or not b):
            return False
        if not set(b) <= set(a):
            return False
        improved |= set(b) < set(a)
    return improved
