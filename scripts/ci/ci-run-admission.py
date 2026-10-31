#!/usr/bin/env python3
"""Approve only native current-head CI executions by live trusted PR authors."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote

from github_api import get_json
import dependency_update as dependency

spec = importlib.util.spec_from_file_location('ci_admission_authority', Path(__file__).with_name('decision-authority.py'))
authority = importlib.util.module_from_spec(spec)
spec.loader.exec_module(authority)
POLICY = Path('automation/github/ci-execution.json')


def policy():
    value = authority.decode_document(POLICY.read_bytes())
    if (value.get('schema') != 1 or type(value['schema']) is not int
            or value.get('repository') != 'closure-labs/finite' or value.get('repositoryId') != 1293375784
            or value.get('decider') != {'login': 'cl-decider[bot]', 'id': 344936881,
                                      'appId': 5384448, 'appSlug': 'cl-decider'}
            or value.get('superAdmins') != {'organization': authority.APPROVER_ORG,
                 'slug': authority.APPROVER_TEAM, 'id': authority.APPROVER_TEAM_ID}
            or value.get('pullRequestStates') != ['draft', 'ready']
            or value.get('workflows') != ['.github/workflows/build.yml', '.github/workflows/codeql.yml',
                                          '.github/workflows/decision-events.yml']
            or value.get('executionApprovalOnly') is not True or value.get('grantsMergeApproval') is not False
            or value.get('dependabot') != {'login': dependency.BOT['login'], 'id': dependency.BOT['id'],
                 'family': 'github-actions-pins', 'sameRepositoryOnly': True, 'requiresCurrentHeadHumanApproval': False}
            or value.get('authorityRecoveryWorkflow') != '.github/workflows/decision-authority.yml'
            or value.get('otherContributors') != 'retain-existing-approval'):
        raise ValueError('Invalid reviewed CI execution policy')
    return value


def pull(api, rules, number, head=None):
    if type(number) is not int or number < 1:
        raise ValueError('Invalid CI admission PR number')
    value = api(f'repos/{rules["repository"]}/pulls/{number}')
    if (not isinstance(value, dict) or value.get('number') != number or value.get('state') != 'open'
            or value.get('base', {}).get('ref') != 'main'
            or value.get('base', {}).get('repo', {}).get('full_name') != rules['repository']
            or value.get('base', {}).get('repo', {}).get('id') != rules['repositoryId']
            or type(value.get('draft')) is not bool
            or not isinstance(value.get('head', {}).get('sha'), str)
            or not authority.SHA.fullmatch(value['head']['sha'])
            or head is not None and value['head']['sha'] != head):
        raise ValueError('CI admission PR is closed, moved or targets another repository')
    return value


def ci_context(run, rules):
    return (run.get('path') in rules['workflows'] and
            (run.get('event') == 'pull_request' or
             run.get('event') == 'pull_request_review' and run.get('path') == '.github/workflows/decision-events.yml'))


def bound_run(run, current, rules):
    head = current['head']
    repo = head.get('repo', {})
    return (isinstance(run, dict) and type(run.get('id')) is int and run['id'] > 0
            and type(run.get('run_attempt')) is int and run['run_attempt'] > 0
            and type(run.get('workflow_id')) is int and run['workflow_id'] > 0
            and ci_context(run, rules)
            and run.get('repository', {}).get('id') == rules['repositoryId']
            and run.get('repository', {}).get('full_name') == rules['repository']
            and run.get('head_sha') == head['sha'] and run.get('head_branch') == head.get('ref')
            and isinstance(head.get('ref'), str) and type(repo.get('id')) is int and repo['id'] > 0
            and isinstance(repo.get('full_name'), str)
            and run.get('head_repository', {}).get('id') == repo['id']
            and run.get('head_repository', {}).get('full_name') == repo['full_name'])


def requires_approval(run):
    # "waiting" can mean environment approval. Only GitHub's fork execution
    # approval conclusion permits the fork-run approve endpoint.
    return run.get('status') == 'completed' and run.get('conclusion') == 'action_required'


def associated_pull(api, rules, run):
    candidates = run.get('pull_requests')
    if not isinstance(candidates, list) or len(candidates) > 16:
        raise ValueError('Invalid native CI PR associations')
    if not candidates:
        # GitHub can omit both run and commit PR associations for an open fork.
        # Query the native source owner/ref, then require the full immutable
        # repo/branch/head tuple below. Query results alone grant no trust.
        source = run.get('head_repository', {})
        name, branch, sha = source.get('full_name'), run.get('head_branch'), run.get('head_sha')
        if (not isinstance(name, str) or not authority.REPOSITORY.fullmatch(name)
                or type(source.get('id')) is not int or source['id'] < 1
                or not isinstance(branch, str) or not 0 < len(branch) <= 1024
                or not isinstance(sha, str) or not authority.SHA.fullmatch(sha)):
            raise ValueError('Missing native CI source identity')
        selector = quote(name.split('/')[0] + ':' + branch, safe='')
        candidates = authority.collection(api,
            f'repos/{rules["repository"]}/pulls?state=open&base=main&head={selector}')
    if len(candidates) > 16:
        raise ValueError('Native CI PR origin inventory exceeds bound')
    matches = []
    for candidate in candidates:
        number = candidate.get('number') if isinstance(candidate, dict) else None
        if type(number) is not int or number < 1:
            raise ValueError('Invalid native CI PR association')
        current = api(f'repos/{rules["repository"]}/pulls/{number}')
        if current.get('state') == 'open' and bound_run(run, current, rules):
            matches.append(pull(api, rules, number, run['head_sha']))
    if len(matches) != 1:
        raise ValueError('CI execution lacks one current native PR origin')
    return matches[0]


def blocked_runs(api, rules, current):
    listing = api(f'repos/{rules["repository"]}/actions/runs?status=action_required&head_sha={current["head"]["sha"]}&per_page=100')
    runs = listing.get('workflow_runs')
    if (not isinstance(runs, list) or type(listing.get('total_count')) is not int
            or listing['total_count'] != len(runs) or len(runs) > 100):
        raise ValueError('Incomplete bounded CI approval inventory')
    return [run for run in runs if bound_run(run, current, rules) and requires_approval(run)]


def authority_recovery(api, rules, run):
    # A trusted controller completion is only a wake-up. No check conclusion,
    # matrix output or artifact supplies approval; the worker reauthenticates it.
    if (run.get('repository', {}).get('id') != rules['repositoryId']
            or run.get('repository', {}).get('full_name') != rules['repository']
            or run.get('head_repository', {}).get('id') != rules['repositoryId']
            or run.get('head_repository', {}).get('full_name') != rules['repository']
            or run.get('head_branch') != 'main' or not isinstance(run.get('head_sha'), str)
            or not authority.SHA.fullmatch(run['head_sha'])
            or run.get('event') not in ('workflow_run', 'schedule', 'workflow_dispatch')
            or run.get('status') != 'completed' or run.get('conclusion') not in ('success', 'failure')
            or type(run.get('run_attempt')) is not int or run['run_attempt'] < 1
            or type(run.get('workflow_id')) is not int):
        raise ValueError('Dependency recovery requires a native completed trusted-main authority workflow')
    workflow = api(f'repos/{rules["repository"]}/actions/workflows/{run["workflow_id"]}')
    if (workflow.get('id') != run['workflow_id'] or workflow.get('path') != rules['authorityRecoveryWorkflow']
            or workflow.get('state') != 'active'):
        raise ValueError('Dependency recovery workflow differs from active native identity')
    values = authority.collection(api, f'repos/{rules["repository"]}/pulls?state=open&base=main')
    if len(values) > 64:
        raise ValueError('Dependency recovery PR inventory exceeds bound')
    targets = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError('Invalid native dependency recovery inventory')
        if not dependency.official(value):
            continue
        current = pull(api, rules, value.get('number'))
        if not dependency.official(current):
            continue
        runs = blocked_runs(api, rules, current)
        if runs:
            targets.append({'number': current['number'], 'head': current['head']['sha'],
                            'runs': sorted(run['id'] for run in runs)})
    if len(targets) > 16 or len({item['number'] for item in targets}) != len(targets):
        raise ValueError('Dependency recovery target inventory is excessive or duplicated')
    return {'include': targets}


def discover(event, env, rules, api=get_json):
    repository = rules['repository']
    if env.get('GITHUB_REPOSITORY') != repository:
        raise ValueError('Wrong CI admission repository')
    if env['GITHUB_EVENT_NAME'] == 'pull_request_target':
        current = pull(api, rules, event['number'], event['pull_request']['head']['sha'])
        candidates = [(current, run) for run in blocked_runs(api, rules, current)]
    elif env['GITHUB_EVENT_NAME'] == 'workflow_run':
        run_id = event['workflow_run']['id']
        if type(run_id) is not int or run_id < 1:
            raise ValueError('Invalid native CI run ID')
        run = api(f'repos/{repository}/actions/runs/{run_id}')
        if run.get('id') != run_id:
            raise ValueError('Native CI run ID differs from trigger')
        if run.get('path') == rules['authorityRecoveryWorkflow']:
            return authority_recovery(api, rules, run)
        if not ci_context(run, rules):
            return {'include': []}
        if requires_approval(run):
            candidates = [(associated_pull(api, rules, run), run)]
        elif (run.get('path') == '.github/workflows/decision-events.yml'
                and run.get('event') == 'pull_request_review'
                and run.get('status') == 'completed' and run.get('conclusion') == 'success'):
            current = associated_pull(api, rules, run)
            candidates = [(current, blocked) for blocked in blocked_runs(api, rules, current)]
        else:
            return {'include': []}
    else:
        raise ValueError('Unsupported CI admission event')
    grouped = {}
    for current, run in candidates:
        key = (current['number'], current['head']['sha'])
        grouped.setdefault(key, set()).add(run['id'])
    if len(grouped) > 16:
        raise ValueError('CI admission target bound exceeded')
    return {'include': [{'number': number, 'head': head, 'runs': sorted(ids)}
                        for (number, head), ids in sorted(grouped.items())]}


def trusted_author(api, rules, current):
    user = current.get('user')
    decider = rules['decider']
    if isinstance(user, dict) and user.get('type') == 'Bot':
        if user.get('login') == decider['login'] and type(user.get('id')) is int and user['id'] == decider['id']:
            return True
        if dependency.official(current):
            context = dependency.inspect(api, rules['repository'], current)
            dependency.classify(api, context)
            # Execution is independent of merge review. Authenticate only the
            # supported immutable pin delta here; decision-check retains review.
            latest = dependency.revalidate(api, rules['repository'], context)
            if latest['head'].get('ref') != current['head'].get('ref'):
                raise ValueError('Dependency source branch changed during validation')
            return True
        return False
    return authority.eligible(api, rules['repository'], user)


def post_approval(endpoint):
    # Mutations are never retried. A lost response must first be reconciled
    # against native state; no review, check success or deployment is posted.
    result = subprocess.run(['gh', 'api', '--method', 'POST', endpoint],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('CI execution approval response unavailable')


def approve(rules, number, head, run_ids, *, api=get_json, post=post_approval):
    if (not isinstance(run_ids, list) or not 1 <= len(run_ids) <= 16
            or any(type(n) is not int or n < 1 for n in run_ids) or len(set(run_ids)) != len(run_ids)):
        raise ValueError('Invalid bounded CI execution targets')
    current = pull(api, rules, number, head)
    result = {'schema': 1, 'authorizesPublication': False, 'grantsMergeApproval': False,
              'pullRequest': number, 'head': head, 'runs': []}
    if not trusted_author(api, rules, current):
        result['status'] = 'manual-execution-approval-required'
        return result
    repository = rules['repository']
    # GitHub retains only the newest pending worker for this PR/head. Reconcile
    # the complete current blocked set so coalescing cannot strand an older
    # workflow whose pending worker was replaced by a later event.
    targets = sorted(set(run_ids) | {run['id'] for run in blocked_runs(api, rules, current)})
    if len(targets) > 16:
        raise ValueError('Current blocked CI execution bound exceeded')
    for run_id in targets:
        endpoint = f'repos/{repository}/actions/runs/{run_id}'
        run = api(endpoint)
        if run.get('id') != run_id or not bound_run(run, current, rules):
            raise ValueError('CI execution differs from current PR origin')
        workflow = api(f'repos/{repository}/actions/workflows/{run["workflow_id"]}')
        if workflow.get('id') != run['workflow_id'] or workflow.get('path') != run['path'] or workflow.get('state') != 'active':
            raise ValueError('CI workflow identity differs from active reviewed workflow')
        associated = associated_pull(api, rules, run)
        if associated['number'] != number:
            raise ValueError('CI execution belongs to another PR')
        latest = pull(api, rules, number, head)
        if latest.get('user') != current.get('user') or not trusted_author(api, rules, latest):
            raise ValueError('CI submitter authority changed before approval')
        latest_run = api(endpoint)
        if (not bound_run(latest_run, latest, rules)
                or any(latest_run.get(key) != run[key] for key in ('id', 'workflow_id', 'path', 'run_attempt'))):
            raise ValueError('CI execution changed before approval')
        if not requires_approval(latest_run):
            result['runs'].append({'runId': run_id, 'status': 'already-started-or-no-approval-required'})
            continue
        final = pull(api, rules, number, head)
        if (final.get('user') != current.get('user')
                or dependency.official(final) and not trusted_author(api, rules, final)):
            raise ValueError('CI author or dependency identity changed immediately before approval')
        # Pin classification can require several remote reads. Re-read the
        # exact run afterwards so a new attempt cannot inherit that admission.
        final_run = api(endpoint)
        if (not bound_run(final_run, final, rules)
                or any(final_run.get(key) != run[key] for key in ('id', 'workflow_id', 'path', 'run_attempt'))):
            raise ValueError('CI execution changed immediately before approval')
        if not requires_approval(final_run):
            result['runs'].append({'runId': run_id, 'status': 'already-started-or-no-approval-required'})
            continue
        try:
            post(endpoint + '/approve')
            state = 'execution-approved'
        except (RuntimeError, subprocess.SubprocessError):
            observed = api(endpoint)
            if (not bound_run(observed, latest, rules)
                    or any(observed.get(key) != run[key] for key in ('id', 'workflow_id', 'path', 'run_attempt'))
                    or observed.get('status') not in ('queued', 'in_progress', 'completed')
                    or observed.get('conclusion') == 'action_required'):
                raise RuntimeError('CI execution approval outcome unknown; no mutation retry') from None
            state = 'native-state-reconciled-after-uncertain-response'
        result['runs'].append({'runId': run_id, 'runAttempt': run['run_attempt'], 'status': state})
    result['status'] = 'checked'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discover', action='store_true')
    parser.add_argument('--pull-request', type=int)
    parser.add_argument('--head')
    parser.add_argument('--runs')
    args = parser.parse_args()
    rules = policy()
    if (os.environ.get('GITHUB_REPOSITORY') != rules['repository']
            or os.environ.get('GITHUB_WORKFLOW_REF') != rules['repository'] + '/.github/workflows/ci-run-admission.yml@refs/heads/main'):
        raise ValueError('CI admission requires its trusted main workflow')
    if args.discover:
        result = discover(json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()), os.environ, rules)
    else:
        if (os.environ.get('FINITE_CI_ADMISSION_APP_SLUG') != rules['decider']['appSlug']
                or os.environ.get('FINITE_REVIEW_APP_ID') != str(rules['decider']['appId'])
                or os.environ.get('FINITE_REVIEW_BOT_LOGIN') != rules['decider']['login']):
            raise ValueError('CI admission token does not identify the configured Decider App')
        result = approve(rules, args.pull_request, args.head, json.loads(args.runs))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, RuntimeError) as error:
        print('CI execution admission failed: ' + str(error), file=sys.stderr)
        raise SystemExit(2)
