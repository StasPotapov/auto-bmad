"""Semantic subagent identities and read-only compatibility for old size-tier names."""

import copy

ROLES = ('story-runner', 'implementer', 'context-compiler', 'blind-hunter',
         'edge-case-hunter', 'intent-alignment', 'verification-gap', 'triager', 'verifier')
REVIEWERS = frozenset(('blind-hunter', 'edge-case-hunter', 'intent-alignment', 'verification-gap'))
LEGACY_ROLES = frozenset(('reviewer', 'reviewer-mid', 'reviewer-lite', 'compiler-lite'))
ACCEPTED_ROLES = frozenset(ROLES) | LEGACY_ROLES
LEVELS = ('fast', 'normal', 'deep')


def legacy_role(role, level):
    if role == 'context-compiler':
        return 'compiler-lite'
    if role in REVIEWERS:
        if level == 'deep':
            return 'reviewer'
        return 'reviewer-lite' if role == 'intent-alignment' else 'reviewer-mid'
    return role


def role_overrides(common, per_level, role, level):
    """Canonical settings win over deprecated aliases, including per-level aliases."""
    old = legacy_role(role, level)
    keys = ((common, old), (per_level, old), (common, role), (per_level, role))
    if old == role:
        keys = ((common, role), (per_level, role))
    result = {}
    for rows, key in keys:
        value = rows.get(key, {})
        if not isinstance(value, dict):
            raise ValueError(f'roles.{key} must be a table')
        result.update(copy.deepcopy(value))
    return result


def alias_warnings(cfg):
    def aliases(value):
        if not isinstance(value, dict):
            return set()
        found = set(value.get('roles', {})) & LEGACY_ROLES if isinstance(value.get('roles'), dict) else set()
        for key in ('executors', 'levels'):
            if isinstance(value.get(key), dict):
                for child in value[key].values():
                    found |= aliases(child)
        if isinstance(value.get('routing'), dict):
            for rows in value['routing'].values():
                if isinstance(rows, dict):
                    found |= set(rows) & LEGACY_ROLES
        return found
    found = aliases(cfg)
    return (["Deprecated role names migrated by layer: " + ', '.join(sorted(found)) +
             "; use semantic subagent names (blind-hunter, edge-case-hunter, intent-alignment, "
             "verification-gap, context-compiler)."] if found else [])


def semantic_settings(settings):
    """Expand aliases within one client layer without materializing unrelated defaults."""
    out = copy.deepcopy(settings)
    common = settings.get('roles', {})
    levels = settings.get('levels', {})
    if not (set(common) & LEGACY_ROLES or any(set(v.get('roles', {})) & LEGACY_ROLES for v in levels.values())):
        return out
    out['roles'] = {k: copy.deepcopy(v) for k, v in common.items() if k not in LEGACY_ROLES}
    for level in LEVELS:
        prior = levels.get(level, {}).get('roles', {})
        rows = {k: copy.deepcopy(v) for k, v in prior.items() if k not in LEGACY_ROLES}
        for role in ROLES:
            old = legacy_role(role, level)
            if old not in LEGACY_ROLES:
                continue
            values = role_overrides(common, prior, role, level)
            # Canonical common values are already represented outside levels.
            values = {k: v for k, v in values.items() if out['roles'].get(role, {}).get(k) != v}
            if values:
                rows[role] = values
        if rows:
            out.setdefault('levels', {}).setdefault(level, {})['roles'] = rows
        elif level in out.get('levels', {}):
            out['levels'][level].pop('roles', None)
    if not out['roles']:
        out.pop('roles')
    return out
