"""Passive native-chat run journal and evidence gates. Never launches an AI model."""
import argparse
from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import uuid

import agent_config
from agent_runtime import atomic_json
from common import ARTIFACTS, baseline as spec_baseline, frontmatter, git, is_story_spec, parse_story
from execution_state import canonical, revision
from ext import load
from repair_policy import limits, test_progress, test_resolved
import testrun
import verify
from read_spec import sprint_status

HERE = Path(__file__).resolve().parent
PHASES = ('preflight', 'planning', 'implementation', 'review', 'repair', 'verification', 'finalization', 'blocked')


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def config(root):
    cfg, _, _ = load(str(root), strict=True)
    return cfg, digest(cfg)


def plan(repo, arg=''):
    root, _ = canonical(repo)
    proc = subprocess.run([sys.executable, str(HERE / 'plan_run.py'), '--repo', str(root), '--arg', arg],
                          capture_output=True, text=True)
    try:
        target = json.loads(proc.stdout)
    except ValueError as error:
        raise ValueError(proc.stderr.strip() or 'planner returned no JSON') from error
    if proc.returncode or target.get('error'):
        raise ValueError(target.get('error') or target.get('note') or 'no runnable plan')
    cfg, hash_ = config(root)
    profiles = agent_config.resolve(cfg, target['level'])
    return {'backend': profiles['backend'], 'request': arg, 'plan': target, 'roles': profiles['roles'],
            'base_commit': revision(root), 'config_hash': hash_, 'model_started': False,
            'wave_plan_required': target.get('parallel') != 'off' and len(target['stories']) > 1,
            'merge_policy': profiles['merge_policy']}


@contextmanager
def locked(common):
    directory = common / 'auto-bmad-native'
    directory.mkdir(mode=0o700, exist_ok=True)
    with (directory / 'journal.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield directory


def read_session(value):
    path = Path(value).resolve(strict=True)
    data = json.loads(path.read_text())
    root, common = canonical(data['repo'])
    if path.name != 'session.json' or path.parent.parent != common / 'auto-bmad-native':
        raise ValueError('session must be a native journal issued for this repository')
    if data.get('schema_version') != 1 or data.get('transport') != 'native-subagents':
        raise ValueError('unsupported native session')
    return path, data, root, common


def init(repo, prepared):
    root, common = canonical(repo)
    fresh = plan(root, prepared.get('request', ''))
    if fresh['backend'] != 'native':
        raise ValueError('native session init requires the native backend')
    if prepared != fresh:
        raise ValueError('saved plan is stale or changed; generate a new plan before init')
    with locked(common) as directory:
        for candidate in directory.glob('*/session.json'):
            previous = json.loads(candidate.read_text())
            if previous.get('status') in ('running', 'blocked'):
                raise ValueError(f'an unfinished native session exists; inspect/resume {candidate}')
        path = directory / uuid.uuid4().hex / 'session.json'
        path.parent.mkdir(mode=0o700)
        cfg, hash_ = config(root)
        technical_limit = cfg.get('recovery_limits', {}).get('technical', 3)
        if type(technical_limit) is not int or technical_limit < 0:
            raise ValueError('recovery_limits.technical must be a nonnegative integer')
        data = {'schema_version': 1, 'transport': 'native-subagents', 'repo': str(root),
                'session': str(path), 'status': 'running', 'created': now(), 'config_hash': hash_,
                'plan': fresh['plan'], 'roles': fresh['roles'], 'base_commit': fresh['base_commit'],
                'repair_limits': limits(cfg), 'technical_limit': technical_limit, 'events': [], 'stories': {}}
        for item in fresh['plan']['stories']:
            data['stories'][item['id']] = {'title': item.get('title', ''), 'phase': 'pending',
                'status': 'pending', 'agents': {}, 'reviews': {}, 'checks': {},
                'repair_counts': {'spec': 0, 'review': 0, 'tests': 0}, 'test_no_progress': 0, 'technical_retries': 0}
        atomic_json(path, data)
        return data


def code_tree(root):
    value = testrun.tree_hash(str(root))
    if not value:
        raise ValueError('cannot fingerprint the story code')
    return value


def validate_manifest(root, manifest):
    workflow = Path(manifest['workflow']).resolve(strict=True)
    profile = Path(manifest['profile']).resolve(strict=True)
    if not workflow.is_relative_to(root / '_bmad/render') or not profile.is_relative_to(root / '_bmad/custom'):
        raise ValueError('prepared instructions escaped the story worktree')
    for path, expected in ((workflow, manifest['workflow_hash']), (profile, manifest['profile_hash'])):
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('prepared workflow/profile changed; prepare and inspect before continuing')
    hashes = manifest['snapshot_hashes']
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('prepared engine snapshot has no hashes')
    for relative, expected in hashes.items():
        path = (workflow.parent / relative).resolve(strict=True)
        if not path.is_relative_to(workflow.parent) or not path.is_file():
            raise ValueError('prepared snapshot resource escaped its directory')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('prepared engine snapshot changed: ' + relative)
    conditions = manifest.get('review_condition_expressions')
    if conditions is None:
        rendered = workflow.parent / 'manifest.json'
        values = json.loads(rendered.read_text())['inputs']['resolved_values'] if rendered.is_file() else {}
        layers = values.get('customization.workflow.review_layers', [])
        conditions = {item['id']: item['when'] for item in layers if item.get('instruction') and item.get('when')}
    return conditions


def bound(data, story, common):
    if story not in data['stories']:
        raise ValueError('story is outside the saved plan')
    row = data['stories'][story]
    if 'worktree' not in row:
        raise ValueError('bind the story worktree first')
    root, owner = canonical(row['worktree'])
    if owner != common:
        raise ValueError('worktree belongs to another repository')
    manifest = json.loads(Path(row['manifest']).read_text())
    if digest(manifest) != row['manifest_hash']:
        raise ValueError('prepared manifest changed; inspect before continuing')
    validate_manifest(root, manifest)
    branch = git(str(root), 'symbolic-ref', '--quiet', 'HEAD').stdout.strip()
    if not branch or branch != row['branch']:
        raise ValueError('story branch changed; inspect before continuing')
    if git(str(root), 'merge-base', '--is-ancestor', row['baseline'], 'HEAD').returncode:
        raise ValueError('original story baseline is no longer an ancestor')
    if config(root)[1] != row['config_hash']:
        raise ValueError('story configuration changed; inspect before continuing')
    return row, root


def required_checks(data, story, row, root):
    selected, code = verify.cmd_plan(SimpleNamespace(story=story, level=data['plan']['level'],
        base=row['baseline'], commit=revision(root), title=row['title']), str(root))
    skipped = selected.get('skipped', [])
    # Missing optional skills have always been a reported skip in the shared verifier contract.
    # A detector that could not run remains a real blocker.
    errors = [warning for warning in selected.get('warnings', []) if ': detect failed' in warning]
    if code not in (0, 2) or selected.get('error') or errors:
        raise ValueError('verification plan needs resolution: ' + json.dumps(selected, ensure_ascii=False))
    row['verification_plan'] = {'tree': code_tree(root), 'skipped': skipped,
                                'warnings': selected.get('warnings', []), 'at': now()}
    return selected['verifiers']


def record(session, request):
    path, _, _, common = read_session(session)
    with locked(common):
        _, data, _, _ = read_session(path)
        if data['status'] != 'running':
            raise ValueError('session is not running; inspect and explicitly resume first')
        story, event = request.get('story'), request.get('event')
        if story not in data['stories']:
            raise ValueError('story is outside the saved plan')
        row = data['stories'][story]
        if row['status'] == 'completed':
            raise ValueError('completed stories cannot be edited')
        if event == 'bind':
            if 'worktree' in row:
                raise ValueError('story is already bound; resume it without rebinding')
            root, owner = canonical(request['worktree'])
            if owner != common:
                raise ValueError('worktree belongs to another repository')
            if any(other.get('worktree') == str(root) and other['status'] != 'completed'
                   for key, other in data['stories'].items() if key != story):
                raise ValueError('another story owns this worktree')
            base = request['baseline']
            exact = git(str(root), 'rev-parse', '--verify', '--end-of-options', base + '^{commit}')
            if exact.returncode or exact.stdout.strip() != base or git(str(root), 'merge-base', '--is-ancestor', base, 'HEAD').returncode:
                raise ValueError('baseline must be an exact ancestor commit')
            manifest_path = Path(request['manifest']).resolve(strict=True)
            manifest = json.loads(manifest_path.read_text())
            if Path(manifest['repo']).resolve() != root or manifest.get('delegation', {}).get('transport') != 'native-subagents':
                raise ValueError('manifest is not native or belongs to another worktree')
            hash_ = config(root)[1]
            if manifest['config_hash'] != hash_:
                raise ValueError('prepared manifest configuration changed')
            conditions = validate_manifest(root, manifest)
            branch = git(str(root), 'symbolic-ref', '--quiet', 'HEAD').stdout.strip()
            if not branch:
                raise ValueError('native story worktree must have a branch')
            row.update(worktree=str(root), baseline=base, branch=branch, manifest=str(manifest_path),
                       manifest_hash=digest(manifest), config_hash=hash_,
                       required_reviews=manifest['review_layers'],
                       review_conditions=conditions,
                       status='running', phase='preflight')
        else:
            row, root = bound(data, story, common)
            if event == 'phase':
                phase = request['phase']
                if phase not in PHASES:
                    raise ValueError('unknown story phase')
                row['phase'] = phase
                if phase == 'blocked':
                    if not request.get('reason'):
                        raise ValueError('blocked requires a concrete reason')
                    row['blocker'] = request['reason']
            elif event == 'agent':
                role, identity, status = request['role'], request['agent_id'], request['status']
                if role not in data['roles'] or not isinstance(identity, str) or not identity:
                    raise ValueError('unknown role or empty native agent id')
                if status not in ('running', 'waiting', 'completed', 'failed', 'stopped'):
                    raise ValueError('unknown native agent status')
                if identity in row['agents'] and row['agents'][identity]['role'] != role:
                    raise ValueError('agent identity cannot change role')
                row['agents'][identity] = {'role': role, 'status': status, 'updated': now()}
            elif event == 'review':
                if request.get('worktree'):
                    root = integration_root(row, request['worktree'], common)
                layer = request['layer']
                allowed = row['required_reviews'] + ['verify:' + v['name'] for v in required_checks(data, story, row, root) if v['kind'] == 'agent']
                agent = row['agents'].get(request['agent_id'], {})
                if layer not in allowed or agent.get('status') != 'completed' or agent.get('role') not in ('reviewer', 'reviewer-mid', 'reviewer-lite', 'verifier'):
                    raise ValueError('review needs a required layer and completed independent reviewer/verifier')
                tree = code_tree(root)
                if request.get('reviewed_tree') != tree:
                    raise ValueError('review must identify the current code tree; do not relabel stale reports')
                if request.get('verdict') not in ('pass', 'problem'):
                    raise ValueError('review verdict must be pass or problem')
                if any(old.get('agent_id') == request['agent_id'] and name != layer for name, old in row['reviews'].items()):
                    raise ValueError('independent review layers require separate native agents')
                report = Path(request['report']).resolve(strict=True)
                if not report.is_file() or not report.read_text().strip():
                    raise ValueError('review requires a nonempty saved report')
                row['reviews'][layer] = {'agent_id': request['agent_id'], 'tree': tree,
                    'verdict': request['verdict'], 'report': str(report),
                    'report_hash': hashlib.sha256(report.read_bytes()).hexdigest()}
            elif event == 'review-not-applicable':
                if request.get('worktree'):
                    root = integration_root(row, request['worktree'], common)
                layer = request['layer']
                conditions = row.get('review_conditions', {})
                if layer not in conditions or layer not in row['required_reviews']:
                    raise ValueError('only a conditional review layer may be not applicable')
                if request.get('condition') != conditions[layer] or request.get('condition_result') is not False:
                    raise ValueError('attest the exact prepared condition as false')
                if request.get('evaluated_by') != 'main-chat':
                    raise ValueError('the main chat must evaluate conditional review applicability')
                tree = code_tree(root)
                if request.get('reviewed_tree') != tree:
                    raise ValueError('condition evidence must identify the current code tree')
                report = Path(request['evidence']).resolve(strict=True)
                if not report.is_file() or not report.read_text().strip():
                    raise ValueError('not-applicable requires saved evidence explaining the false condition')
                row['reviews'][layer] = {'tree': tree, 'verdict': 'not_applicable',
                    'condition': conditions[layer], 'condition_result': False, 'evaluated_by': 'main-chat',
                    'report': str(report), 'report_hash': hashlib.sha256(report.read_bytes()).hexdigest()}
            elif event == 'retry':
                if not request.get('reason'):
                    raise ValueError('technical retry requires a concrete reason')
                if row['technical_retries'] >= data['technical_limit']:
                    raise ValueError('technical retry budget exhausted')
                row['technical_retries'] += 1
            elif event == 'repair':
                kind = request['kind']
                if kind not in row['repair_counts'] or not request.get('reason'):
                    raise ValueError('repair requires kind spec/review/tests and a concrete reason')
                if row['repair_counts'][kind] >= data['repair_limits'][kind]:
                    raise ValueError('repair budget exhausted')
                if kind == 'tests':
                    if row.get('pending_test_repair'):
                        raise ValueError('rerun the failed check before another tests repair')
                    tree = code_tree(root)
                    failures = {name: check for name, check in row['checks'].items()
                                if check['result'].get('verdict') == 'problem' and check.get('tree') == tree}
                    if not failures:
                        raise ValueError('tests repair needs a recorded failing native session check')
                    if row['test_no_progress'] >= data['repair_limits']['no_progress']:
                        raise ValueError('tests no-progress budget exhausted')
                    row['pending_test_repair'] = failures
                row['repair_counts'][kind] += 1
                row['phase'] = 'repair'
                row['reviews'] = {}
            elif event == 'complete':
                complete(data, story, row, root)
                spec = Path(request['spec']).resolve(strict=True)
                if spec.parent != (root / ARTIFACTS).resolve() or not is_story_spec(spec.name, *parse_story(story)):
                    raise ValueError('spec belongs to another story')
                fields, _ = frontmatter(spec)
                if fields.get('status') != 'done' or spec_baseline(fields) != row['baseline']:
                    raise ValueError('done spec must retain the original story baseline')
                if git(str(root), 'status', '--porcelain', '--untracked-files=all').stdout.strip():
                    raise ValueError('completion requires a clean committed worktree')
                if revision(root) == row['baseline']:
                    raise ValueError('completion requires a story commit')
                row.update(status='verified', phase='finalization', commit=revision(root), spec=str(spec), verified=now())
            elif event == 'finalize':
                if row['status'] != 'verified':
                    raise ValueError('verify the isolated story with complete before finalization')
                root = integration_root(row, request['repo'], common)
                complete(data, story, row, root)
                if sprint_status(str(root), *parse_story(story)) != 'done':
                    raise ValueError('story tracking is not done in final repository')
                if git(str(root), 'status', '--porcelain', '--untracked-files=all').stdout.strip():
                    raise ValueError('finalization requires a clean committed repository')
                report = Path(request['finish_report']).resolve(strict=True)
                finish = json.loads(report.read_text())
                if (finish.get('ok') is not True or not isinstance(finish.get('steps'), list) or not finish['steps']
                        or any(step.get('ok') is not True for step in finish['steps'])):
                    raise ValueError('story-finish did not succeed; inspect its steps')
                row.update(status='completed', phase='completed', final_repo=str(root), final_commit=revision(root),
                           finish_report=str(report), finish_report_hash=hashlib.sha256(report.read_bytes()).hexdigest(), completed=now())
                if all(r['status'] == 'completed' for r in data['stories'].values()):
                    data['status'] = 'completed'
            else:
                raise ValueError('unknown event')
        data['events'].append({**request, 'at': now()})
        atomic_json(path, data)
        return data


def complete(data, story, row, root):
    tree = code_tree(root)
    selected = required_checks(data, story, row, root)
    note_checks = {item['name'] for item in selected if item.get('on_fail') == 'note'}
    row['verification_notes'] = []
    reviews = row['required_reviews'] + ['verify:' + v['name'] for v in selected if v['kind'] == 'agent']
    for layer in reviews:
        result = row['reviews'].get(layer, {})
        conditional_skip = (layer in row.get('review_conditions', {})
            and result.get('verdict') == 'not_applicable' and result.get('condition_result') is False
            and result.get('evaluated_by') == 'main-chat'
            and result.get('condition') == row['review_conditions'][layer])
        noted = layer.startswith('verify:') and layer[7:] in note_checks and result.get('verdict') == 'problem'
        if result.get('tree') != tree or (result.get('verdict') != 'pass' and not conditional_skip and not noted):
            raise ValueError(f'missing/current review required: {layer}')
        report = Path(result['report'])
        if not report.is_file() or hashlib.sha256(report.read_bytes()).hexdigest() != result['report_hash']:
            raise ValueError('saved review report changed')
        if noted:
            row['verification_notes'].append({'check': layer[7:], 'report': str(report), 'verdict': 'problem'})
    for item in selected:
        if item['kind'] != 'command':
            continue
        result = row['checks'].get(item['name'], {})
        outcome = result.get('result', {})
        noted = (item['name'] in note_checks and outcome.get('verdict') == 'problem'
                 and type(outcome.get('code')) is int and outcome['code'] >= 0)
        if result.get('tree') != tree or (not test_resolved(outcome) and not noted):
            raise ValueError('missing/current successful check required: ' + item['name'])
        if noted:
            row['verification_notes'].append({'check': item['name'], 'result': outcome, 'verdict': 'problem'})
    if row.get('pending_test_repair'):
        raise ValueError('pending test repair must be observed before completion')
    if any(a['status'] in ('running', 'waiting') for a in row['agents'].values()):
        raise ValueError('join all story agents before completion')


def integration_root(row, value, common):
    root, owner = canonical(value)
    if owner != common or not row.get('commit'):
        raise ValueError('integration needs a verified story in the same repository')
    if git(str(root), 'merge-base', '--is-ancestor', row['commit'], 'HEAD').returncode:
        raise ValueError('verified story commit is not integrated in the final repository')
    if config(root)[1] != row['config_hash']:
        raise ValueError('final repository configuration differs from the prepared story')
    return root


def check(session, story, repo=None):
    path, _, _, common = read_session(session)
    with locked(common):
        _, data, _, _ = read_session(path)
        if data['status'] != 'running':
            raise ValueError('session is not running')
        row, root = bound(data, story, common)
        if repo:
            root = integration_root(row, repo, common)
        tree = code_tree(root)
        selected = required_checks(data, story, row, root)
        pending = row.get('pending_test_repair', {})
        observed = set()
        for item in selected:
            if item['kind'] != 'command':
                continue
            result, code = verify.cmd_run(SimpleNamespace(name=item['name'], base=row['baseline']), str(root))
            fresh = code_tree(root)
            if code == 0 and tree == fresh:
                observed.add(item['name'])
            row['checks'][item['name']] = {'tree': tree if tree == fresh and code == 0 else None,
                                          'result': result, 'at': now()}
            if code or result.get('verdict') == 'running':
                break
        if pending and set(pending) <= observed:
            progress = all(test_progress(old['result'], row['checks'][name]['result']) for name, old in pending.items())
            row['test_no_progress'] = 0 if progress else row['test_no_progress'] + 1
            row.pop('pending_test_repair', None)
        row['phase'] = 'verification'
        atomic_json(path, data)
        return {'session': str(path), 'story': story, 'tree': code_tree(root), 'checks': row['checks'],
                'required_agent_verifiers': [v for v in selected if v['kind'] == 'agent'],
                'test_no_progress': row['test_no_progress'],
                'skipped': row.get('verification_plan', {}).get('skipped', []),
                'warnings': row.get('verification_plan', {}).get('warnings', [])}


def control(session, action, confirm_cancelled=False):
    path, _, root, common = read_session(session)
    with locked(common):
        _, data, _, _ = read_session(path)
        if action == 'resume':
            if data['status'] == 'completed':
                raise ValueError('completed session needs no resume')
            if data['status'] == 'cancelled' and not confirm_cancelled:
                raise ValueError('cancelled runs require explicit user authorization and --confirm-cancelled')
            for candidate in path.parent.parent.glob('*/session.json'):
                if candidate == path:
                    continue
                previous = json.loads(candidate.read_text())
                if previous.get('status') in ('running', 'blocked'):
                    raise ValueError(f'another unfinished native session exists; inspect/resume {candidate}')
            if config(root)[1] != data['config_hash']:
                raise ValueError('configuration changed; inspect before resuming')
            for story, row in data['stories'].items():
                if 'worktree' in row:
                    bound(data, story, common)
            data['status'] = 'running'
        elif action == 'cancel':
            if data['status'] == 'completed':
                raise ValueError('completed session cannot be cancelled')
            if any(a['status'] in ('running', 'waiting') for row in data['stories'].values() for a in row['agents'].values()):
                raise ValueError('stop/join native agents and record their terminal states before cancelling')
            data['status'] = 'cancelled'
        else:
            raise ValueError('unknown control action')
        data['events'].append({'event': action, 'at': now()})
        atomic_json(path, data)
        return data


def status(session):
    _, data, _, common = read_session(session)
    for row in data['stories'].values():
        if row.get('worktree'):
            row['current_code_tree'] = code_tree(row['worktree'])
    data['agent_liveness'] = 'unknown: reconcile native agent ids through host tools before resuming'
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('plan', 'init'):
        command = sub.add_parser(action)
        command.add_argument('--repo', default='.')
        command.add_argument('--arg', default='')
        if action == 'init':
            command.add_argument('--plan', help='JSON returned by plan; checked against current repository')
    for action in ('status', 'record', 'check', 'resume', 'cancel'):
        command = sub.add_parser(action)
        command.add_argument('--session', required=True)
        if action == 'record':
            command.add_argument('--request', required=True)
        if action == 'check':
            command.add_argument('--story', required=True)
            command.add_argument('--repo', help='final integration repository after complete')
        if action == 'resume':
            command.add_argument('--confirm-cancelled', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'plan':
            result = plan(args.repo, args.arg)
        elif args.action == 'init':
            result = init(args.repo, json.loads(Path(args.plan).read_text()) if args.plan else plan(args.repo, args.arg))
        elif args.action == 'status':
            result = status(args.session)
        elif args.action == 'record':
            result = record(args.session, json.loads(Path(args.request).read_text()))
        elif args.action == 'check':
            result = check(args.session, args.story, args.repo)
        else:
            result = control(args.session, args.action, getattr(args, 'confirm_cancelled', False))
        code = 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        result, code = {'error': str(error), 'model_started': False}, 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
