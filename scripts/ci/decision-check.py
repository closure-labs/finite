#!/usr/bin/env python3
"""Publish App-origin human authority checks using only trusted main code and GitHub metadata."""
import argparse
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from security_decisions import canonical_hash

SPEC = importlib.util.spec_from_file_location('decision_authority', Path(__file__).with_name('decision-authority.py'))
authority = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(authority)
CHECK_NAME = 'Maintainer decision authority'
COLLECTOR = '.github/workflows/decision-events.yml'
CONTROLLER = '.github/workflows/decision-authority.yml'
REVIEW_STAMP = 'finite-authority-v1:'
QUEUE = re.compile(r'gh-readonly-queue/main/pr-([1-9][0-9]*)-[0-9a-f]{7,40}')
PROPOSAL = re.compile(r'automation/decisions/(security|releases)/([0-9a-f]{64})\.json')
from governed_tree import changed_paths, compare, governed, tree
import dependency_update as dependency


def post_check(repository, sha, conclusion, summary, app_id, api_post=None, *, review_stamp=None):
    if not authority.SHA.fullmatch(sha):
        raise authority.AuthorityError('Check target must be an immutable SHA')
    body = {'name': CHECK_NAME, 'head_sha': sha, 'status': 'completed', 'conclusion': conclusion,
            'output': {'title': CHECK_NAME, 'summary': summary[:60000]}}
    if review_stamp is not None:
        body['external_id'] = review_stamp
    native_run = os.environ.get('GITHUB_RUN_ID', '')
    if re.fullmatch(r'[1-9][0-9]*', native_run) and os.environ.get('GITHUB_REPOSITORY') == repository:
        body['details_url'] = f'https://github.com/{repository}/actions/runs/{native_run}'
    if api_post is None:
        result = subprocess.run(['gh', 'api', '--method', 'POST', f'repos/{repository}/check-runs', '--input', '-'],
                                input=json.dumps(body), text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise authority.AuthorityError('Could not publish App-origin maintainer authority check')
        response = json.loads(result.stdout)
    else:
        response = api_post(f'repos/{repository}/check-runs', body)
    if not isinstance(response, dict) or response.get('app', {}).get('id') != app_id:
        raise authority.AuthorityError('Authority check was not posted by the configured review App')
    return response



def validate_proposal_packet(proposal):
    # Loaded only from the trusted main checkout, never from PR contents.
    from decision_controller import validate_proposal_packet as validate
    return validate(proposal)


def check_pr(repository, number, expected_bot, target_sha=None, github=None):
    api = github or authority.github_api
    endpoint = f'repos/{repository}/pulls/{number}'
    pull = api(endpoint)
    if (not isinstance(pull, dict) or pull.get('number') != number or pull.get('state') != 'open'
            or pull.get('base', {}).get('ref') != 'main'
            or pull.get('base', {}).get('repo', {}).get('full_name') != repository
            or not authority.SHA.fullmatch(pull.get('head', {}).get('sha', ''))):
        raise authority.AuthorityError('PR is not an open main-targeting repository PR')
    head = pull['head']['sha']
    target_sha = target_sha or head
    files = authority.collection(api, endpoint + '/files')
    try:
        paths = changed_paths(files, pull.get('changed_files'))
    except ValueError as error:
        raise authority.AuthorityError(str(error)) from error
    sensitive = sorted(path for path in paths if governed(path))
    proposals = sorted(path for path in paths if PROPOSAL.fullmatch(path))
    dependency_context = None
    if sensitive:
        if not authority.submitter(api, repository, pull.get('user'), expected_bot):
            if not dependency.official(pull):
                raise authority.AuthorityError('Governed PR submitter must be the configured App, a Maintainer or a Super Admin')
            dependency_context = dependency.inspect(api, repository, pull, files)
            dependency.classify(api, dependency_context)
        # Each proposal verifier authenticates this exact PR/head itself.
        # Governed changes without proposals still need their own review check.
        if not proposals:
            authority.approval(api, repository, number, head)
        for path in proposals:
            proposal = authority.document_at(api, repository, path, head)
            if authority.proposal_path(proposal) != path:
                raise authority.AuthorityError('Proposal filename does not match canonical document hash')
            authority.verify_proposal(proposal, number, repository, expected_bot,
                                      require_merged=False, github=api, allowed_paths=proposals)
            validate_proposal_packet(proposal)
        if any(path.startswith('automation/decisions/') and not PROPOSAL.fullmatch(path) for path in paths):
            raise authority.AuthorityError('Decision ledger permits only immutable canonical proposal paths')
    if target_sha != head:
        try:
            compare(api, repository, target_sha, head, paths)
        except ValueError as error:
            raise authority.AuthorityError(str(error)) from error
        for path in proposals:
            if canonical_hash(authority.document_at(api, repository, path, target_sha)) != canonical_hash(authority.document_at(api, repository, path, head)):
                raise authority.AuthorityError('Merge-group proposal differs from exact approved PR head')
    latest = api(endpoint)
    if (latest.get('head', {}).get('sha') != head or latest.get('state') != 'open'
            or latest.get('user') != pull.get('user')):
        raise authority.AuthorityError('PR changed while authority was being evaluated')
    if dependency_context is not None:
        dependency.revalidate(api, repository, dependency_context)
        authority.approval(api, repository, number, head)
    elif sensitive and not authority.submitter(api, repository, latest.get('user'), expected_bot):
        raise authority.AuthorityError('Governed PR submitter authority changed during authorization')
    return {'pullRequest': number, 'head': head, 'target': target_sha,
            'governedPaths': sensitive, 'status': 'authorized' if sensitive else 'not-required'}


def collector_targets(run, repository, github=None):
    api = github or authority.github_api
    if (not isinstance(run, dict) or run.get('path') != COLLECTOR
            or run.get('repository', {}).get('full_name') != repository
            or run.get('status') != 'completed' or run.get('conclusion') != 'success'
            or run.get('event') not in ('pull_request', 'pull_request_review', 'merge_group')
            or not authority.SHA.fullmatch(run.get('head_sha', ''))):
        raise authority.AuthorityError('Untrusted or incomplete decision-event collector run')
    if run['event'] == 'merge_group':
        match = QUEUE.fullmatch(run.get('head_branch', ''))
        if not match:
            raise authority.AuthorityError('Merge queue requires strict single-PR main queue identity')
        branch = api(f'repos/{repository}/git/ref/heads/{run["head_branch"]}')
        if branch.get('object', {}).get('sha') != run['head_sha']:
            raise authority.AuthorityError('Collector merge-group SHA is no longer the exact queue ref')
        return [(int(match[1]), run['head_sha'])]
    pulls = run.get('pull_requests', [])
    if not isinstance(pulls, list):
        raise authority.AuthorityError('Invalid collector PR metadata')
    if not pulls:
        # GitHub omits PR associations for some review-triggered workflow runs.
        pulls = authority.collection(api, f'repos/{repository}/pulls?state=open&base=main')
    targets = []
    for pull in pulls:
        if not isinstance(pull, dict) or type(pull.get('number')) is not int or pull['number'] < 1:
            raise authority.AuthorityError('Invalid collector PR identity')
        live = api(f'repos/{repository}/pulls/{pull["number"]}')
        if live.get('state') == 'open' and live.get('base', {}).get('ref') == 'main':
            targets.append((pull['number'], None))
    return sorted(set(targets))


def resolve_targets(repository, run_id, github=None):
    """Resolve bounded worker identities from authenticated native metadata."""
    if (not isinstance(repository, str) or not authority.REPOSITORY.fullmatch(repository)
            or type(run_id) is not int or run_id < 1):
        raise authority.AuthorityError('Invalid collector discovery context')
    api = github or authority.github_api
    run = api(f'repos/{repository}/actions/runs/{run_id}')
    targets = []
    for number, target in collector_targets(run, repository, api):
        pull = api(f'repos/{repository}/pulls/{number}')
        head = pull.get('head', {}).get('sha')
        if pull.get('state') != 'open' or pull.get('base', {}).get('ref') != 'main':
            continue
        if pull.get('number') != number or not isinstance(head, str) or not authority.SHA.fullmatch(head):
            raise authority.AuthorityError('Discovery lacks an immutable PR head')
        targets.append({'number': number, 'head': head, 'target': target or head})
    if len(targets) > 64:
        raise authority.AuthorityError('Authority worker inventory exceeds bounded matrix')
    return {'include': targets}


def review_fingerprint(api, repository, number, head):
    """Hash relevant native review state; the digest is observation, not authority."""
    rows = []
    for review in authority.collection(api, f'repos/{repository}/pulls/{number}/reviews'):
        if (not isinstance(review, dict) or type(review.get('id')) is not int or review['id'] < 1
                or not isinstance(review.get('user'), dict)):
            raise authority.AuthorityError('Invalid review snapshot')
        state, user = review.get('state'), review['user']
        command = None
        if state == 'COMMENTED':
            body = review.get('body') or ''
            if not isinstance(body, str):
                raise authority.AuthorityError('Invalid review snapshot body')
            command = body.strip()
            if command not in ('/decider approve ' + head, '/decider withdraw ' + head):
                continue
        elif state not in ('APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'):
            continue
        if user.get('type') == 'Bot':
            continue
        rows.append({'id': review['id'], 'state': state, 'commit': review.get('commit_id'),
                     'user': {key: user.get(key) for key in ('id', 'login', 'type')}, 'command': command})
    if len({row['id'] for row in rows}) != len(rows):
        raise authority.AuthorityError('Duplicate review snapshot ID')
    return canonical_hash({'head': head, 'reviews': sorted(rows, key=lambda row: row['id'])})


def recovery_origin(api, repository, run_id):
    if (not isinstance(repository, str) or not authority.REPOSITORY.fullmatch(repository)
            or type(run_id) is not int or run_id < 1):
        raise authority.AuthorityError('Invalid approval recovery identity')
    run = api(f'repos/{repository}/actions/runs/{run_id}')
    if (run.get('id') != run_id or run.get('path') != CONTROLLER
            or run.get('repository', {}).get('full_name') != repository
            or run.get('head_repository', {}).get('full_name') != repository
            or run.get('head_branch') != 'main' or run.get('status') != 'in_progress'
            or run.get('event') not in ('schedule', 'workflow_dispatch')
            or not authority.SHA.fullmatch(run.get('head_sha', ''))
            or type(run.get('run_attempt')) is not int or run['run_attempt'] < 1):
        raise authority.AuthorityError('Recovery requires its active native trusted-main workflow')
    return run


def queue_targets(api, repository, number):
    refs = api(f'repos/{repository}/git/matching-refs/heads/gh-readonly-queue/main/pr-{number}-')
    if not isinstance(refs, list) or len(refs) > 16:
        raise authority.AuthorityError('Invalid bounded current queue inventory')
    targets = []
    for ref in refs:
        name = ref.get('ref', '').removeprefix('refs/heads/')
        match = QUEUE.fullmatch(name)
        sha = ref.get('object', {}).get('sha')
        if (not match or int(match[1]) != number or not isinstance(sha, str)
                or not authority.SHA.fullmatch(sha) or ref.get('object', {}).get('type') != 'commit'):
            raise authority.AuthorityError('Invalid current queue ref')
        targets.append(sha)
    return sorted(set(targets))


def stale_review_check(api, repository, target, app_id, fingerprint, now, *, force=False):
    if force:
        return True
    document = api(f'repos/{repository}/commits/{target}/check-runs?check_name=Maintainer%20decision%20authority&filter=latest&per_page=100')
    values = document.get('check_runs')
    if (not isinstance(values, list) or type(document.get('total_count')) is not int
            or document['total_count'] != len(values) or len(values) > 100):
        raise authority.AuthorityError('Incomplete bounded authority check inventory')
    own = [row for row in values if row.get('app', {}).get('id') == app_id]
    if not own:
        return True
    if any(type(row.get('id')) is not int or row['id'] < 1 or row.get('head_sha') != target
           or row.get('name') != CHECK_NAME for row in own):
        raise authority.AuthorityError('Authority check differs from native target')
    check = max(own, key=lambda row: row['id'])
    stamp = check.get('external_id') or ''
    fresh = stamp in {REVIEW_STAMP + fingerprint + ':' + state for state in
                     ('success', 'review-required', 'invalid')}
    expected_conclusion = 'success' if stamp.endswith(':success') else 'failure'
    value = check.get('completed_at') or check.get('started_at')
    if value:
        observed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if observed.tzinfo is None or observed > now:
            raise authority.AuthorityError('Invalid native authority check timestamp')
        # Review stamps do not include team/permission changes. Revalidate
        # live authority periodically even when the exact review is unchanged.
        if (fresh and check.get('status') == 'completed' and check.get('conclusion') == expected_conclusion
                and now - observed < timedelta(minutes=10)):
            return False
        # Give ordinary event workers time to finish before scheduled recovery.
        if now - observed < timedelta(minutes=2):
            return False
    return True


def recovery_targets(repository, run_id, app_id, github=None, *, number=None, now=None):
    api = github or authority.github_api
    origin = recovery_origin(api, repository, run_id)
    if type(app_id) is not int or app_id < 1:
        raise authority.AuthorityError('Recovery requires the configured review App ID')
    manual = origin['event'] == 'workflow_dispatch'
    if manual and (type(number) is not int or number < 1):
        raise authority.AuthorityError('Manual approval recheck requires one PR number')
    if not manual and number is not None:
        raise authority.AuthorityError('Scheduled recovery selects native open PRs only')
    pulls = ([{'number': number}] if manual else
             authority.collection(api, f'repos/{repository}/pulls?state=open&base=main'))
    if len(pulls) > 64:
        raise authority.AuthorityError('Approval recovery PR inventory exceeds bounded matrix')
    now = now or datetime.now(timezone.utc)
    targets = []
    for item in pulls:
        pr = item.get('number')
        if type(pr) is not int or pr < 1:
            raise authority.AuthorityError('Invalid recovery PR inventory')
        current = api(f'repos/{repository}/pulls/{pr}')
        if current.get('state') != 'open' or current.get('base', {}).get('ref') != 'main':
            if manual:
                raise authority.AuthorityError('Manual recheck requires an open main-targeting PR')
            continue
        head = current.get('head', {}).get('sha')
        if (current.get('number') != pr or current.get('base', {}).get('repo', {}).get('full_name') != repository
                or not isinstance(head, str) or not authority.SHA.fullmatch(head)):
            raise authority.AuthorityError('Recovery lacks a current native PR head')
        fingerprint = review_fingerprint(api, repository, pr, head)
        for target in sorted({head, *queue_targets(api, repository, pr)}):
            if stale_review_check(api, repository, target, app_id, fingerprint, now, force=manual):
                targets.append({'number': pr, 'head': head, 'target': target})
    if len(targets) > 64:
        raise authority.AuthorityError('Approval recovery target bound exceeded')
    return {'include': targets}


def run_checks(repository, run_id, expected_bot, app_id, github=None, api_post=None, *, expected=None, recovery=False):
    authority.validate_context(repository, expected_bot)
    if type(run_id) is not int or run_id < 1 or type(app_id) is not int or app_id < 1:
        raise authority.AuthorityError('Invalid collector run or review App ID')
    api = github or authority.github_api
    run = api(f'repos/{repository}/actions/runs/{run_id}')
    outcomes = []
    if recovery:
        recovery_origin(api, repository, run_id)
        if expected is None:
            raise authority.AuthorityError('Recovery worker requires exact discovered target')
        number, head, target = expected
        targets = [(number, None if target == head else target)]
    else:
        targets = collector_targets(run, repository, api)
    if expected is not None:
        number, head, target = expected
        if (type(number) is not int or number < 1 or not isinstance(head, str)
                or not authority.SHA.fullmatch(head) or not isinstance(target, str)
                or not authority.SHA.fullmatch(target)
                or (number, target if recovery and target != head or run['event'] == 'merge_group' else None) not in targets
                or not recovery and run['event'] != 'merge_group' and target != head):
            raise authority.AuthorityError('Worker differs from authenticated collector targets')
        targets = [(n, t) for n, t in targets if n == number]
    for number, target in targets:
        pull = api(f'repos/{repository}/pulls/{number}')
        sha = target or pull.get('head', {}).get('sha', '')
        if expected is not None and (pull.get('state') != 'open'
                or pull.get('base', {}).get('ref') != 'main' or pull.get('head', {}).get('sha') != expected[1]):
            outcomes.append({'pullRequest': number, 'target': expected[2], 'status': 'obsolete'})
            continue
        fingerprint = review_fingerprint(api, repository, number, pull['head']['sha'])
        state = 'success'
        if recovery and target is not None and target not in queue_targets(api, repository, number):
            outcomes.append({'pullRequest': number, 'target': sha, 'status': 'obsolete'})
            continue
        try:
            result = check_pr(repository, number, expected_bot, target, api)
            summary = ('Eligible human approval verified for governed changes.' if result['status'] == 'authorized'
                       else 'This PR does not change governed security or delivery controls.')
            conclusion = 'success'
        except (authority.AuthorityError, ValueError, KeyError, TypeError) as error:
            result = {'pullRequest': number, 'target': sha, 'status': 'review-required', 'reason': str(error)}
            summary, conclusion = 'Maintainer decision required: ' + str(error), 'failure'
            state = ('review-required' if isinstance(error, authority.HumanDecisionRequired) else
                     'technical-error' if isinstance(error.__cause__, authority.GitHubReadError) else 'invalid')
        if expected is not None:
            latest = api(f'repos/{repository}/pulls/{number}')
            if (latest.get('state') != 'open' or latest.get('base', {}).get('ref') != 'main'
                    or latest.get('head', {}).get('sha') != expected[1]):
                outcomes.append({'pullRequest': number, 'target': expected[2], 'status': 'obsolete'})
                continue
            if target is not None:
                # A replaced queue target must not receive a late App result.
                if (recovery and target not in queue_targets(api, repository, number)
                        or not recovery and (number, target) not in collector_targets(run, repository, api)):
                    raise authority.AuthorityError('Queue target changed before authority publication')
        if review_fingerprint(api, repository, number, pull['head']['sha']) != fingerprint:
            outcomes.append({'pullRequest': number, 'target': sha, 'status': 'obsolete', 'reason': 'review-changed'})
            continue
        post_check(repository, sha, conclusion, summary, app_id, api_post,
                   review_stamp=REVIEW_STAMP + fingerprint + ':' + state)
        outcomes.append(result)
    return {'schema': 1, 'recoveryRun' if recovery else 'collectorRun': run_id, 'checks': outcomes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--collector-run', type=int)
    source.add_argument('--recovery-run', type=int)
    parser.add_argument('--recheck-pr', type=int, help='Manual recovery discovery for one current PR')
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--bot-login', default=os.environ.get('FINITE_REVIEW_BOT_LOGIN'))
    parser.add_argument('--app-id', type=int, default=os.environ.get('FINITE_REVIEW_APP_ID'))
    parser.add_argument('--resolve-targets', action='store_true', help='Read native targets without App credentials or check writes')
    parser.add_argument('--pull-request', type=int)
    parser.add_argument('--expected-head')
    parser.add_argument('--target-sha')
    args = parser.parse_args()
    worker = (args.pull_request, args.expected_head, args.target_sha)
    if any(value is not None for value in worker) and not all(value is not None for value in worker):
        parser.error('Worker requires PR, expected head and target SHA together')
    if args.recheck_pr is not None and not args.resolve_targets:
        parser.error('PR recheck selection is discovery-only')
    if args.resolve_targets and any(value is not None for value in worker):
        parser.error('Target discovery cannot publish worker checks')
    try:
        if args.recovery_run is not None:
            if (os.environ.get('GITHUB_WORKFLOW_REF') != args.repository + '/' + CONTROLLER + '@refs/heads/main'
                    or os.environ.get('GITHUB_RUN_ID') != str(args.recovery_run)):
                raise authority.AuthorityError('Recovery CLI requires its own native trusted-main run')
            result = (recovery_targets(args.repository, args.recovery_run, args.app_id, number=args.recheck_pr)
                      if args.resolve_targets else run_checks(args.repository, args.recovery_run, args.bot_login,
                          args.app_id, expected=worker if args.pull_request is not None else None, recovery=True))
        else:
            if args.recheck_pr is not None:
                raise authority.AuthorityError('PR recheck selection requires native recovery mode')
            result = (resolve_targets(args.repository, args.collector_run) if args.resolve_targets else
                      run_checks(args.repository, args.collector_run, args.bot_login, args.app_id,
                                 expected=worker if args.pull_request is not None else None))
        print(json.dumps(result))
        if args.recovery_run is not None and not args.resolve_targets:
            return 1 if any(row['status'] == 'review-required' for row in result['checks']) else 0
        return 0
    except (authority.AuthorityError, ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'unauthorized', 'error': str(error)}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
