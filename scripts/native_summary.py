"""Compact journal navigation. Full evidence remains in the canonical session."""


def summarize(data, story, fingerprint):
    from native_progress import snapshot
    result = {key: data[key] for key in ('session', 'status', 'repo', 'repair_limits', 'technical_limit')}
    result.update(event_count=len(data['events']),
                  agent_liveness='unknown: reconcile with host tools before dispatch/resume',
                  evidence_validation='not performed; use saved reports and native completion gates',
                  schedule=data.get('schedule'), stories={})
    result['progress'] = snapshot(data)
    result['scope'] = {key: data.get('plan', {}).get(key) for key in ('mode', 'epic', 'story', 'level')}
    if data.get('checkpoint_policy'):
        from native_stats import checkpoint_metrics
        result['checkpoint_metrics'] = checkpoint_metrics(data, story)
    for identity, row in data['stories'].items():
        if story is not None and story != identity:
            continue
        compact = {key: row[key] for key in (
            'title', 'status', 'phase', 'blocker', 'worktree', 'branch', 'baseline', 'manifest',
            'spec', 'commit', 'final_repo', 'final_commit', 'finish_report', 'repair_counts',
            'test_no_progress', 'technical_retries', 'required_reviews', 'review_conditions') if key in row}
        agents = row.get('agents', {})
        compact['agent_counts'] = {'launched': len(agents),
            'active': sum(a['status'] in ('running', 'waiting') for a in agents.values()),
            'terminal': sum(a['status'] in ('completed', 'failed', 'stopped') for a in agents.values())}
        compact['active_agents'] = {key: value for key, value in agents.items()
                                    if value['status'] in ('running', 'waiting')}
        compact['agent_details'] = f"{data['session']}#/stories/{identity}/agents"
        # A focused read supplies a fresh fingerprint. The overview remains cheap even
        # for large epics and never silently treats a saved verdict as current evidence.
        tree = None
        if story is not None and row.get('worktree'):
            root = row.get('final_repo', row['worktree'])
            try:
                tree = fingerprint(root)
                compact.update(current_code_tree=tree, fingerprint_repo=root)
            except (OSError, ValueError) as error:
                compact['fingerprint_error'] = str(error)
        compact['reviews'] = {key: {
            **{field: value[field] for field in ('verdict', 'tree', 'agent_id', 'method', 'report',
                                                'report_hash', 'revalidation') if field in value},
            'matches_current_tree': value.get('tree') == tree if tree else None,
            'deferred_findings': len(value.get('deferred_findings', []))}
            for key, value in row.get('reviews', {}).items()}
        compact['review_candidates'] = {key: {field: value[field] for field in ('tree', 'report', 'agent_id')
                                               if field in value}
                                         for key, value in row.get('review_candidates', {}).items()}
        compact['checks'] = {key: {
            'tree': value.get('tree'),
            'matches_current_tree': value.get('tree') == tree if tree else None,
            **{field: value['result'][field] for field in
               ('verdict', 'code', 'log', 'reason', 'error', 'seconds') if field in value['result']},
            'details': f"{data['session']}#/stories/{identity}/checks/{key}"}
            for key, value in row.get('checks', {}).items()}
        compact['pending_test_repair'] = list(row.get('pending_test_repair', {}))
        compact['verification_notes'] = len(row.get('verification_notes', []))
        compact['verification_plan'] = row.get('verification_plan', {})
        if story is None:
            # Keep decisions/signals in the run table; --story expands evidence paths.
            compact = {key: compact[key] for key in (
                'title', 'status', 'phase', 'blocker', 'repair_counts', 'test_no_progress',
                'technical_retries', 'required_reviews', 'agent_counts', 'active_agents',
                'pending_test_repair', 'verification_notes') if key in compact}
            compact['reviews'] = {key: {'verdict': value.get('verdict'),
                'matches_current_tree': None, 'deferred_findings': len(value.get('deferred_findings', []))}
                for key, value in row.get('reviews', {}).items()}
            compact['checks'] = {key: {field: value['result'][field] for field in
                ('verdict', 'code', 'reason', 'error') if field in value['result']}
                for key, value in row.get('checks', {}).items()}
            compact['review_candidates'] = list(row.get('review_candidates', {}))
            compact['verification_plan'] = {key: row.get('verification_plan', {}).get(key, [])
                                            for key in ('warnings', 'skipped')}
            compact['session_details'] = f'#/stories/{identity}'
        compact['progress'] = snapshot(data, identity)
        batch = row.get('repair_batches', {}).get(row.get('active_repair_batch'))
        if batch:
            compact['repair'] = {key: batch.get(key) for key in
                                ('kind', 'attempts', 'diagnostics', 'no_progress', 'finding_ids')}
            compact['repair']['retry_budget'] = 'tests'
        result['stories'][identity] = compact
    return result
