#!/usr/bin/env python3
"""Publish App-origin human authority checks using only trusted main code and GitHub metadata."""
import argparse
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
QUEUE = re.compile(r'gh-readonly-queue/main/pr-([1-9][0-9]*)-[0-9a-f]{7,40}')
PROPOSAL = re.compile(r'automation/decisions/(security|releases)/([0-9a-f]{64})\.json')
GOVERNED_PREFIXES = ('scripts/ci/', 'scripts/bluebuild/', '.github/workflows/', '.github/actions/', 'automation/security/',
                     'automation/github/', 'automation/decisions/', 'lib/ci-applications/')
GOVERNED_FILES = {'flake.nix', 'flake.lock', 'cosign.pub', '.github/CODEOWNERS',
                  'lib/mk-pkgs.nix', 'lib/project-policy.nix', 'lib/secretspec.nix', 'lib/vm-tools.nix',
                  'sources/bluefin.pub', 'sources/bluefin-trust.json', 'sources/cosign-runtime.json',
                  'scripts/ci/verify-security-admission.py', 'scripts/ci/reconcile-decisions.py',
                  'scripts/ci/verify-attestation-subject.py', 'scripts/ci/inventory-evidence.py',
                  'secretspec.toml', 'sources/secretspec.json', 'lib/ci-tools.nix',
                  'scripts/ci/security_decisions.py', 'scripts/ci/security_admission.py',
                  'scripts/ci/security-admission.py', 'scripts/ci/decision_packets.py',
                  'scripts/ci/decision_controller.py', 'lib/bluebuild-checks.nix',
                  '.github/zizmor.yml', 'zizmor.yml', '.zizmor.yml', 'scripts/ci/decision-authority.py',
                  'scripts/ci/decision-check.py', 'scripts/ci/decision-controller.py',
                  'scripts/ci/approved-baseline.py', 'scripts/ci/reuse-candidate-security.py',
                  'scripts/ci/repository-security-audit.py', 'scripts/ci/legacy-release-boundary.py', 'scripts/ci/create-release-draft.sh'}


def governed(path):
    return (path in GOVERNED_FILES or path.startswith(GOVERNED_PREFIXES)
            or path.startswith('scripts/bluebuild/security')
            or path.startswith('scripts/bluebuild/publication')
            or path.startswith('scripts/bluebuild/release')
            or path.startswith('scripts/ci/release')
            or path.startswith('scripts/ci/prepare-release')
            or path.startswith('scripts/ci/decision-')
            or path.startswith('scripts/ci/decision_')
            or path.startswith('scripts/ci/execute-release')
            or path.startswith('lib/ci-'))


def post_check(repository, sha, conclusion, summary, app_id, api_post=None):
    if not authority.SHA.fullmatch(sha):
        raise authority.AuthorityError('Check target must be an immutable SHA')
    body = {'name': CHECK_NAME, 'head_sha': sha, 'status': 'completed', 'conclusion': conclusion,
            'output': {'title': CHECK_NAME, 'summary': summary[:60000]}}
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


def tree(api, repository, sha):
    value = api(f'repos/{repository}/git/trees/{sha}?recursive=1')
    if not isinstance(value, dict) or value.get('truncated') is not False or not isinstance(value.get('tree'), list):
        raise authority.AuthorityError('Cannot prove complete merge-group tree identity')
    entries = {}
    for item in value['tree']:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise authority.AuthorityError('Invalid tree response')
        if item['path'] in entries:
            raise authority.AuthorityError('Duplicate merge-group tree path')
        entries[item['path']] = (item.get('type'), item.get('mode'), item.get('sha'))
    return entries


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
    if len(files) != pull.get('changed_files') or not files:
        raise authority.AuthorityError('Incomplete PR file inventory')
    paths = set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get('filename'), str):
            raise authority.AuthorityError('Invalid changed-file inventory')
        paths.add(item['filename'])
        if item.get('previous_filename'):
            paths.add(item['previous_filename'])
    sensitive = sorted(path for path in paths if governed(path))
    proposals = sorted(path for path in paths if PROPOSAL.fullmatch(path))
    if sensitive:
        if not authority.submitter(api, repository, pull.get('user'), expected_bot):
            raise authority.AuthorityError('Governed PR submitter must be the configured App, a Maintainer or a Super Admin')
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
        queued, reviewed = tree(api, repository, target_sha), tree(api, repository, head)
        for path in sensitive:
            if queued.get(path) != reviewed.get(path):
                raise authority.AuthorityError('Merge-group governed content differs from approved PR head: ' + path)
        for path in proposals:
            if canonical_hash(authority.document_at(api, repository, path, target_sha)) != canonical_hash(authority.document_at(api, repository, path, head)):
                raise authority.AuthorityError('Merge-group proposal differs from exact approved PR head')
    latest = api(endpoint)
    if (latest.get('head', {}).get('sha') != head or latest.get('state') != 'open'
            or latest.get('user') != pull.get('user')):
        raise authority.AuthorityError('PR changed while authority was being evaluated')
    if sensitive and not authority.submitter(api, repository, latest.get('user'), expected_bot):
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


def run_checks(repository, run_id, expected_bot, app_id, github=None, api_post=None):
    authority.validate_context(repository, expected_bot)
    if type(run_id) is not int or run_id < 1 or type(app_id) is not int or app_id < 1:
        raise authority.AuthorityError('Invalid collector run or review App ID')
    api = github or authority.github_api
    run = api(f'repos/{repository}/actions/runs/{run_id}')
    outcomes = []
    for number, target in collector_targets(run, repository, api):
        pull = api(f'repos/{repository}/pulls/{number}')
        sha = target or pull.get('head', {}).get('sha', '')
        try:
            result = check_pr(repository, number, expected_bot, target, api)
            summary = ('Eligible human approval verified for governed changes.' if result['status'] == 'authorized'
                       else 'This PR does not change governed security or delivery controls.')
            conclusion = 'success'
        except (authority.AuthorityError, ValueError, KeyError, TypeError) as error:
            result = {'pullRequest': number, 'target': sha, 'status': 'review-required', 'reason': str(error)}
            summary, conclusion = 'Maintainer decision required: ' + str(error), 'failure'
        post_check(repository, sha, conclusion, summary, app_id, api_post)
        outcomes.append(result)
    return {'schema': 1, 'collectorRun': run_id, 'checks': outcomes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collector-run', type=int, required=True)
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--bot-login', default=os.environ.get('FINITE_REVIEW_BOT_LOGIN'))
    parser.add_argument('--app-id', type=int, default=os.environ.get('FINITE_REVIEW_APP_ID'))
    args = parser.parse_args()
    try:
        print(json.dumps(run_checks(args.repository, args.collector_run, args.bot_login, args.app_id)))
        return 0
    except (authority.AuthorityError, ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'unauthorized', 'error': str(error)}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
