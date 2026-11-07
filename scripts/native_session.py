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
from role_catalog import REVIEWERS
from agent_runtime import atomic_json
from common import ARTIFACTS, baseline as spec_baseline, frontmatter, git, is_story_spec, parse_story
from execution_state import canonical, revision
from ext import load
from repair_policy import limits, test_progress, test_resolved
import testrun
import verify
import native_schedule
import native_policy
from read_spec import sprint_status

HERE = Path(__file__).resolve().parent
PHASES = ('preflight', 'planning', 'implementation', 'review', 'repair', 'verification', 'finalization', 'blocked')
THIN_ROOT_POLICY = 'thin-root-v1'


def thin_root(data):
    policy = data.get('orchestration_policy')
    if policy not in (None, THIN_ROOT_POLICY):
        raise ValueError('unsupported native orchestration policy')
    return policy == THIN_ROOT_POLICY


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
            'wave_plan_required': profiles['backend'] == 'native',
            'merge_policy': profiles['merge_policy'], 'verification_policy': 'integration-full-v1',
            'checkpoint_policy': native_policy.POLICY, 'runtime_root': str(HERE.parent)}


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
    thin_root(data)
    native_policy.enabled(data)
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
                'orchestration_policy': THIN_ROOT_POLICY, 'verification_policy': 'integration-full-v1',
                'checkpoint_policy': fresh.get('checkpoint_policy'),
                'runtime_root': fresh.get('runtime_root'),
                'session': str(path), 'status': 'running', 'created': now(), 'config_hash': hash_,
                'plan': fresh['plan'], 'roles': fresh['roles'], 'base_commit': fresh['base_commit'],
                'repair_limits': limits(cfg), 'technical_limit': technical_limit, 'events': [], 'stories': {},
                'schedule_required': fresh.get('wave_plan_required', False)}
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
    unknown = set(manifest.get('review_layers', [])) - set(REVIEWERS)
    if unknown:
        raise ValueError('review layers need explicitly supported subagents: ' + ', '.join(sorted(unknown)))
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
        base=row['baseline'], commit=revision(root), title=row['title'],
        working_tree=thin_root(data)), str(root))
    skipped = selected.get('skipped', [])
    # Missing optional skills have always been a reported skip in the shared verifier contract.
    # A detector that could not run remains a real blocker.
    errors = [warning for warning in selected.get('warnings', []) if ': detect failed' in warning]
    if code not in (0, 2) or selected.get('error') or errors:
        raise ValueError('verification plan needs resolution: ' + json.dumps(selected, ensure_ascii=False))
    row['verification_plan'] = {'tree': code_tree(root), 'skipped': skipped,
                                'warnings': selected.get('warnings', []), 'at': now()}
    return selected['verifiers']


def check_review_report(result):
    report = Path(result['report'])
    if not report.is_file() or hashlib.sha256(report.read_bytes()).hexdigest() != result['report_hash']:
        raise ValueError('saved review report changed')


def review_origin(result):
    while 'original_review' in result:
        result = result['original_review']
    return result


def independent_agent(row, layer, identity):
    for entries in (row['reviews'], row.get('review_candidates', {})):
        if any(name != layer and review_origin(old).get('agent_id') == identity
               for name, old in entries.items()):
            raise ValueError('independent review layers require separate native agents')


def delegated_evaluator(data, story, layer, evidence, evaluated_by, roles):
    """Validate the same-story native provenance, including when completing later."""
    agent = data['stories'][story]['agents'].get(evaluated_by, {}) if isinstance(evaluated_by, str) else {}
    if (evaluated_by == 'main-chat' or agent.get('status') != 'completed'
            or agent.get('role') not in roles):
        raise ValueError('decision requires a completed registered delegated evaluator: ' + ', '.join(roles))
    if (evidence.get('evaluated_by') != evaluated_by or evidence.get('story') != story
            or evidence.get('layer') != layer):
        raise ValueError('delegated evidence must identify the exact evaluator, story and review layer')


def condition_evidence(path, data, story, layer, target_tree, evaluated_by):
    evidence = json.loads(path.read_text())
    if not isinstance(evidence, dict):
        raise ValueError('conditional decision requires JSON evidence')
    delegated_evaluator(data, story, layer, evidence, evaluated_by, ('story-runner', 'triager'))
    if (evidence.get('target_tree') != target_tree
            or evidence.get('condition') != data['stories'][story]['review_conditions'][layer]
            or evidence.get('condition_result') is not False):
        raise ValueError('conditional evidence must identify the current tree and exact false condition')
    if not isinstance(evidence.get('scope_reason'), str) or not evidence['scope_reason'].strip():
        raise ValueError('conditional evidence requires scope_reason')
    return evidence


def revalidation_evidence(path, source, target_tree, data=None, story=None, layer=None, evaluated_by=None):
    evidence = json.loads(path.read_text())
    if not isinstance(evidence, dict) or evidence.get('kind') != 'targeted-fixes':
        raise ValueError('only targeted-fixes can reuse a review; broad/risky changes need independent review')
    if data is not None and thin_root(data):
        delegated_evaluator(data, story, layer, evidence, evaluated_by, ('triager',))
    elif evidence.get('evaluated_by') != 'main-chat':
        raise ValueError('the main chat must attest that all findings are addressed')
    if evidence.get('all_findings_addressed') is not True:
        raise ValueError('the evaluator must attest that all findings are addressed')
    if evidence.get('source_tree') != source['tree'] or evidence.get('target_tree') != target_tree:
        raise ValueError('revalidation evidence must cover the original review tree through the current tree')
    for field in ('scope_reason', 'checked_changes'):
        if not isinstance(evidence.get(field), str) or not evidence[field].strip():
            raise ValueError('revalidation evidence requires ' + field)
    findings = evidence.get('findings')
    if not isinstance(findings, list) or (source['verdict'] == 'problem' and not findings):
        raise ValueError('revalidation requires dispositions for the original findings')
    ids = set()
    for finding in findings:
        if (not isinstance(finding, dict) or finding.get('status') not in ('fixed', 'rejected', 'deferred')
                or any(not isinstance(finding.get(field), str) or not finding[field].strip()
                       for field in ('id', 'evidence'))):
            raise ValueError('each finding needs id, fixed/rejected/deferred status and evidence')
        if finding['status'] == 'deferred':
            if (finding.get('mandatory_defect') is not False or finding.get('blocking') is not False
                    or any(not isinstance(finding.get(field), str) or not finding[field].strip()
                           for field in ('reason', 'tracking'))):
                raise ValueError('deferral requires explicit nonmandatory/nonblocking assessment, reason and tracking')
            tracking = Path(finding['tracking'])
            if not tracking.is_absolute() or not tracking.is_file() or not tracking.read_text().strip():
                raise ValueError('deferral tracking must name an existing nonempty triage/open-questions file')
        if finding['id'] in ids:
            raise ValueError('revalidation finding ids must be unique')
        ids.add(finding['id'])
    return evidence


def record(session, request):
    path, _, _, common = read_session(session)
    with locked(common):
        _, data, _, _ = read_session(path)
        apply_event(data, request, common)
        atomic_json(path, data)
        return data


def record_batch(session, request):
    """Commit ordered events once, or leave the journal untouched on any error."""
    batch_id, events = request.get('batch_id'), request.get('events')
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError('batch_id must be a nonempty stable identifier')
    if not isinstance(events, list) or not events or any(not isinstance(e, dict) for e in events):
        raise ValueError('events must be a nonempty list of event objects')
    fingerprint = digest(events)
    path, _, _, common = read_session(session)
    with locked(common):
        _, data, _, _ = read_session(path)
        previous = data.get('batches', {}).get(batch_id)
        if previous:
            if previous['digest'] != fingerprint:
                raise ValueError('batch_id was already used for different events')
            return {**previous['receipt'], 'replayed': True}
        first = len(data['events'])
        for event in events:
            apply_event(data, event, common)
        receipt = {'session': str(path), 'batch_id': batch_id, 'replayed': False,
                   'event_start': first, 'event_end': len(data['events']),
                   'status': data['status'], 'stories': {
                       story: {key: data['stories'][story][key] for key in ('phase', 'status')}
                       for story in dict.fromkeys(e['story'] for e in events if 'story' in e)}}
        data.setdefault('batches', {})[batch_id] = {'digest': fingerprint, 'receipt': receipt}
        atomic_json(path, data)
        return receipt


def apply_event(data, request, common):
    """Validate and mutate an in-memory journal; the caller owns lock and commit."""
    request = dict(request)
    if data['status'] != 'running':
        raise ValueError('session is not running; inspect and explicitly resume first')
    story, event = request.get('story'), request.get('event')
    if event == 'schedule':
        data['schedule'] = native_schedule.prepare(data, request)
        data['events'].append({**request, 'at': now()})
        return data
    if story not in data['stories']:
        raise ValueError('story is outside the saved plan')
    row = data['stories'][story]
    if row['status'] == 'completed':
        raise ValueError('completed stories cannot be edited')
    if event == 'bind':
        native_schedule.admission(data, story)
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
            else:
                row.pop('blocker', None)
        elif event == 'agent':
            role, identity, status = request['role'], request['agent_id'], request['status']
            if role not in data['roles'] or not isinstance(identity, str) or not identity:
                raise ValueError('unknown role or empty native agent id')
            if status not in ('running', 'waiting', 'completed', 'failed', 'stopped'):
                raise ValueError('unknown native agent status')
            if identity in row['agents'] and row['agents'][identity]['role'] != role:
                raise ValueError('agent identity cannot change role')
            native_schedule.agent(data, story, identity, role, status)
            row['agents'][identity] = {**row['agents'].get(identity, {}),
                'role': role, 'status': status, 'updated': now()}
            if request.get('thread_id'):
                row['agents'][identity]['thread_id'] = request['thread_id']
        elif event == 'review':
            if request.get('worktree'):
                root = integration_root(row, request['worktree'], common)
            layer = request['layer']
            allowed = row['required_reviews'] + ['verify:' + v['name'] for v in required_checks(data, story, row, root) if v['kind'] == 'agent']
            agent = row['agents'].get(request['agent_id'], {})
            if layer not in allowed or agent.get('status') != 'completed' or agent.get('role') != ('verifier' if layer.startswith('verify:') else layer):
                raise ValueError('review needs a required layer and completed matching independent subagent/verifier')
            tree = code_tree(root)
            if request.get('reviewed_tree') != tree:
                raise ValueError('review must identify the current code tree; do not relabel stale reports')
            if request.get('verdict') not in ('pass', 'problem'):
                raise ValueError('review verdict must be pass or problem')
            independent_agent(row, layer, request['agent_id'])
            report = Path(request['report']).resolve(strict=True)
            if not report.is_file() or not report.read_text().strip():
                raise ValueError('review requires a nonempty saved report')
            row['reviews'][layer] = {'agent_id': request['agent_id'], 'tree': tree,
                'verdict': request['verdict'], 'report': str(report),
                'report_hash': hashlib.sha256(report.read_bytes()).hexdigest(), 'method': 'independent'}
            row.setdefault('review_candidates', {}).pop(layer, None)
        elif event == 'review-revalidate':
            if request.get('worktree'):
                root = integration_root(row, request['worktree'], common)
            layer = request['layer']
            if layer not in row['required_reviews'] or layer.startswith('verify:'):
                raise ValueError('revalidation only applies to required independent review layers')
            source = review_origin(row['reviews'].get(layer)
                                   or row.get('review_candidates', {}).get(layer, {}))
            agent = row['agents'].get(source.get('agent_id'), {})
            if (source.get('verdict') not in ('pass', 'problem')
                    or source.get('method', 'independent') != 'independent'
                    or agent.get('status') != 'completed'
                    or agent.get('role') != layer):
                raise ValueError('revalidation requires a saved completed independent review')
            independent_agent(row, layer, source['agent_id'])
            tree = code_tree(root)
            if request.get('source_tree') != source['tree'] or request.get('reviewed_tree') != tree:
                raise ValueError('revalidation must name the original review tree and current tree')
            check_review_report(source)
            evidence_path = Path(request['evidence']).resolve(strict=True)
            evaluator = request.get('evaluated_by') if thin_root(data) else 'main-chat'
            evidence = revalidation_evidence(evidence_path, source, tree, data, story, layer, evaluator)
            row['reviews'][layer] = {**source, 'tree': tree, 'verdict': 'pass',
                'method': 'targeted-fixes', 'evaluated_by': evaluator, 'original_review': source,
                'deferred_findings': [finding for finding in evidence['findings'] if finding['status'] == 'deferred'],
                'revalidation': {'evidence': str(evidence_path),
                                 'evidence_hash': hashlib.sha256(evidence_path.read_bytes()).hexdigest()}}
        elif event == 'review-not-applicable':
            if request.get('worktree'):
                root = integration_root(row, request['worktree'], common)
            layer = request['layer']
            conditions = row.get('review_conditions', {})
            if layer not in conditions or layer not in row['required_reviews']:
                raise ValueError('only a conditional review layer may be not applicable')
            if request.get('condition') != conditions[layer] or request.get('condition_result') is not False:
                raise ValueError('attest the exact prepared condition as false')
            if not thin_root(data) and request.get('evaluated_by') != 'main-chat':
                raise ValueError('the main chat must evaluate conditional review applicability')
            tree = code_tree(root)
            if request.get('reviewed_tree') != tree:
                raise ValueError('condition evidence must identify the current code tree')
            report = Path(request['evidence']).resolve(strict=True)
            if not report.is_file() or not report.read_text().strip():
                raise ValueError('not-applicable requires saved evidence explaining the false condition')
            evaluator = request.get('evaluated_by')
            if thin_root(data):
                condition_evidence(report, data, story, layer, tree, evaluator)
            row['reviews'][layer] = {'tree': tree, 'verdict': 'not_applicable',
                'condition': conditions[layer], 'condition_result': False, 'evaluated_by': evaluator,
                'report': str(report), 'report_hash': hashlib.sha256(report.read_bytes()).hexdigest()}
        elif event in ('repair-batch', 'repair-close', 'repair-amend'):
            import native_repair
            if event == 'repair-batch':
                native_repair.admit(data, story, request, common)
            elif event == 'repair-close':
                native_repair.close(data, story, request)
            else:
                native_repair.amend(data, story, request)
        elif event == 'retry':
            if not request.get('reason'):
                raise ValueError('technical retry requires a concrete reason')
            if row['technical_retries'] >= data['technical_limit']:
                raise ValueError('technical retry budget exhausted')
            row['technical_retries'] += 1
        elif event == 'repair':
            if native_policy.enabled(data):
                raise ValueError('bounded repairs require a completed triager repair-batch decision')
            begin_repair(data, row, root, request)
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
            complete(data, story, row, root, final=True)
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
    return data


def begin_repair(data, row, root, request):
    """Internal admission mechanics; bounded callers must validate a triager first."""
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
    candidates = row.setdefault('review_candidates', {})
    for layer, result in row['reviews'].items():
        if layer in row['required_reviews'] and result.get('verdict') in ('pass', 'problem'):
            # Always retain the independent snapshot: repeated small patches must
            # be assessed cumulatively, not laundered through successive attestations.
            candidates[layer] = review_origin(result)
    row['reviews'] = {}


def complete(data, story, row, root, final=False):
    import native_verification
    if native_policy.enabled(data) and row.get('active_repair_batch'):
        raise ValueError('independent closure of the active repair batch is required')
    staged = native_verification.enabled(data)
    if staged:
        (native_verification.require_integration if final else native_verification.require_development)(data, story, root)
    tree = code_tree(root)
    selected = required_checks(data, story, row, root)
    note_checks = {item['name'] for item in selected if item.get('on_fail') == 'note'}
    row['verification_notes'] = []
    reviews = row['required_reviews'] + ['verify:' + v['name'] for v in selected if v['kind'] == 'agent']
    for layer in reviews:
        result = row['reviews'].get(layer, {})
        conditional_skip = (layer in row.get('review_conditions', {})
            and result.get('verdict') == 'not_applicable' and result.get('condition_result') is False
            and (thin_root(data) or result.get('evaluated_by') == 'main-chat')
            and result.get('condition') == row['review_conditions'][layer])
        noted = layer.startswith('verify:') and layer[7:] in note_checks and result.get('verdict') == 'problem'
        if result.get('tree') != tree or (result.get('verdict') != 'pass' and not conditional_skip and not noted):
            raise ValueError(f'missing/current review required: {layer}')
        check_review_report(result)
        report = Path(result['report'])
        if conditional_skip and thin_root(data):
            condition_evidence(report, data, story, layer, tree, result.get('evaluated_by'))
        if result.get('method') == 'targeted-fixes':
            source = result['original_review']
            check_review_report(source)
            evidence = Path(result['revalidation']['evidence'])
            if (not evidence.is_file()
                    or hashlib.sha256(evidence.read_bytes()).hexdigest() != result['revalidation']['evidence_hash']):
                raise ValueError('saved revalidation evidence changed')
            revalidation_evidence(evidence, source, tree, data, story, layer, result.get('evaluated_by'))
        if noted:
            row['verification_notes'].append({'check': layer[7:], 'report': str(report), 'verdict': 'problem'})
    for item in selected:
        if item['kind'] != 'command' or staged:
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


def check(session, story, repo=None, request=None, task=None):
    import native_check_lock as check_lock
    import native_verification
    if native_verification.enabled(read_session(session)[1]):
        if repo and request is None:
            return native_verification.integration(session, [story], repo, task)
        if request is None:
            raise ValueError('development check requires --request with registered focused targets and compile/build checks')
        return native_verification.development(session, story, request, repo, task)
    path, initial, _, common = read_session(session)
    _, root = bound(initial, story, common)
    if repo:
        root = integration_root(initial['stories'][story], repo, common)
    with check_lock.worktree_lock(common, root):
        with locked(common):
            _, data, _, _ = read_session(path)
            if data['status'] != 'running':
                raise ValueError('session is not running')
            row, bound_root = bound(data, story, common)
            if repo:
                bound_root = integration_root(row, repo, common)
            if bound_root != root:
                raise ValueError('verification worktree changed before checks started')
            tree, cfg_hash, phase = code_tree(root), config(root)[1], row.get('phase')
            selected = required_checks(data, story, row, root)
            expected = check_lock.snapshot(data, [story])
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
        with locked(common):
            _, current, _, _ = read_session(path)
            check_lock.validate(current, [story], expected, root, tree, cfg_hash)
            fresh_row, _ = bound(current, story, common)
            for key in ('checks', 'test_no_progress', 'verification_plan'):
                if key in row:
                    fresh_row[key] = row[key]
            if 'pending_test_repair' not in row:
                fresh_row.pop('pending_test_repair', None)
            check_lock.set_phase(fresh_row, phase)
            atomic_json(path, current)
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


def summary(session, story=None):
    """Small navigation view, never a replacement for evidence/completion gates."""
    _, data, _, _ = read_session(session)
    if story is not None and story not in data['stories']:
        raise ValueError('story is outside the saved plan')
    from native_summary import summarize
    return summarize(data, story, code_tree)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    import native_tasks
    native_tasks.add_parsers(sub)
    local = sub.add_parser('local-check')
    local.add_argument('--task', required=True)
    local.add_argument('--request', required=True)
    routing = sub.add_parser('repair-route')
    routing.add_argument('--session', required=True)
    routing.add_argument('--story', required=True)
    context = sub.add_parser('context-publish')
    context.add_argument('--task', required=True)
    context.add_argument('--artifact', required=True, help='JSON absolute path/sha256 reference')
    integration = sub.add_parser('integration-check')
    integration.add_argument('--session', required=True)
    integration.add_argument('--repo', required=True)
    integration.add_argument('--story', action='append', required=True)
    integration.add_argument('--task')
    for action in ('plan', 'init'):
        command = sub.add_parser(action)
        command.add_argument('--repo', default='.')
        command.add_argument('--arg', default='')
        if action == 'init':
            command.add_argument('--plan', help='JSON returned by plan; checked against current repository')
    for action in ('status', 'summary', 'record', 'record-batch', 'check', 'resume', 'cancel',
                   'host-bind', 'host-recover'):
        command = sub.add_parser(action)
        command.add_argument('--session', required=True)
        if action in ('record', 'record-batch', 'host-bind', 'host-recover'):
            command.add_argument('--request', required=True)
        if action == 'summary':
            command.add_argument('--story', help='only inspect this story, including its code fingerprint')
        if action == 'check':
            command.add_argument('--task')
            command.add_argument('--story', required=True)
            command.add_argument('--repo', help='integration candidate repository after development complete')
            command.add_argument('--request', help='development checks JSON: checks, builds, build_not_applicable, full_risk')
        if action == 'resume':
            command.add_argument('--confirm-cancelled', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action in ('task-prepare', 'task-diagnose', 'task-retry-bootstrap', 'task-start', 'task-result', 'task-stop',
                           'task-binding', 'task-receipt', 'task-preflight'):
            result = native_tasks.run(args)
        elif args.action == 'context-publish':
            from native_context import publish
            result = publish(args.task, json.loads(Path(args.artifact).read_text()))
        elif args.action == 'local-check':
            from native_repair import local_check
            result = local_check(args.task, json.loads(Path(args.request).read_text()))
        elif args.action == 'repair-route':
            from native_repair import route
            _, data, _, common = read_session(args.session)
            _, root = bound(data, args.story, common)
            result = route(data, args.story, root)
        elif args.action == 'integration-check':
            import native_verification
            result = native_verification.integration(args.session, args.story, args.repo, args.task)
        elif args.action == 'plan':
            result = plan(args.repo, args.arg)
        elif args.action == 'init':
            result = init(args.repo, json.loads(Path(args.plan).read_text()) if args.plan else plan(args.repo, args.arg))
        elif args.action == 'status':
            result = status(args.session)
        elif args.action == 'summary':
            result = summary(args.session, args.story)
        elif args.action == 'record':
            result = record(args.session, json.loads(Path(args.request).read_text()))
        elif args.action == 'record-batch':
            result = record_batch(args.session, json.loads(Path(args.request).read_text()))
        elif args.action == 'check':
            result = check(args.session, args.story, args.repo, json.loads(Path(args.request).read_text()) if args.request else None, args.task)
        elif args.action in ('host-bind', 'host-recover'):
            from native_host import run
            result = run(args.session, args.action, json.loads(Path(args.request).read_text()))
        else:
            result = control(args.session, args.action, getattr(args, 'confirm_cancelled', False))
        code = 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        result, code = {'error': str(error), 'model_started': False}, 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
