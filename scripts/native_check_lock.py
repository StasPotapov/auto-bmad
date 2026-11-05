"""Serialize checks per worktree without occupying the native journal lock."""
from contextlib import contextmanager
import fcntl

import native_session as native


@contextmanager
def worktree_lock(common, root):
    # Acquire before journal.lock. Only competing checks of this worktree wait here;
    # task dispatch, review receipts and checks in other worktrees stay independent.
    directory = common / 'auto-bmad-native' / 'check-locks'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (native.digest(str(root)) + '.lock')).open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield directory / (native.digest(str(root)) + '.json')


def snapshot(data, stories):
    fields = ('worktree', 'baseline', 'branch', 'manifest', 'manifest_hash', 'config_hash',
              'status', 'commit', 'final_repo', 'repair_counts', 'technical_retries',
              'pending_test_repair', 'test_no_progress', 'checks', 'development_check')
    # A cancel/resume or repair cycle must invalidate an in-flight result even if
    # the final status/tree happens to match. Independent review/agent events do not.
    transitions = [event for event in data['events']
                   if event['event'] in ('cancel', 'resume') or
                   (event.get('story') in stories and event['event'] in
                    ('bind', 'repair', 'retry', 'complete', 'finalize'))]
    return native.digest({
        'session': {key: data.get(key) for key in
                    ('status', 'config_hash', 'orchestration_policy', 'verification_policy', 'integration_gate')},
        'stories': {story: {key: data['stories'][story].get(key) for key in fields} for story in stories},
        'transitions': transitions,
    })


def validate(data, stories, expected, root, tree, config_hash):
    if data['status'] != 'running' or snapshot(data, stories) != expected:
        raise ValueError('verification state changed while checks ran; result was not recorded')
    if native.code_tree(root) != tree or native.config(root)[1] != config_hash:
        raise ValueError('verification code/config changed while checks ran; result was not recorded')


def set_phase(row, original_phase):
    # A controller may have advanced to review or blocked while tests were running.
    if row.get('phase') == original_phase:
        row['phase'] = 'verification'
