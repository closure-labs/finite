#!/usr/bin/env python3
"""Authenticate human decisions against authoritative GitHub PR reviews, not ledger claims."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

from security_decisions import TechnicalError, canonical_hash, load_json

SHA = re.compile(r'[0-9a-f]{40}')
REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
KINDS = {'security-findings': 'security', 'security-revocation': 'security', 'release-set': 'releases'}


class AuthorityError(ValueError):
    """No authenticated, currently valid human authority for the proposed operation."""


class HumanDecisionRequired(AuthorityError):
    """GitHub is reachable, but current human authorization is absent or withdrawn."""


def proposal_path(proposal):
    if (not isinstance(proposal, dict) or set(proposal) != {'schema', 'kind', 'payload'}
            or type(proposal['schema']) is not int or proposal['schema'] != 1 or proposal['kind'] not in KINDS
            or not isinstance(proposal['payload'], dict)):
        raise AuthorityError('Unsupported decision proposal envelope')
    return 'automation/decisions/' + KINDS[proposal['kind']] + '/' + canonical_hash(proposal) + '.json'


def github_api(endpoint):
    # Endpoint is constructed from validated repository, PR numbers and hashes.
    result = subprocess.run(['gh', 'api', '--method', 'GET', endpoint], capture_output=True,
                            text=True, timeout=60, check=False)
    if result.returncode:
        raise AuthorityError('GitHub authority API failed: ' + endpoint.split('?')[0])
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise AuthorityError('Invalid GitHub API response') from error


def collection(api, endpoint):
    values = []
    for page in range(1, 11):
        response = api(endpoint + ('&' if '?' in endpoint else '?') + f'per_page=100&page={page}')
        if not isinstance(response, list) or len(response) > 100:
            raise AuthorityError('Invalid bounded GitHub collection')
        values.extend(response)
        if len(response) < 100:
            return values
    raise AuthorityError('GitHub authority collection exceeds bounded pagination')


def validate_context(repository, expected_bot):
    if not isinstance(repository, str) or not REPOSITORY.fullmatch(repository):
        raise AuthorityError('Invalid repository')
    if not isinstance(expected_bot, str) or not re.fullmatch(r'[A-Za-z0-9_-]+\[bot\]', expected_bot):
        raise AuthorityError('A configured trusted GitHub App bot login is required')


def document_at(api, repository, path, revision):
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise AuthorityError('Content lookup requires immutable commit SHA')
    content = api(f'repos/{repository}/contents/{quote(path, safe="/")}?ref={revision}')
    if (not isinstance(content, dict) or content.get('type') != 'file'
            or content.get('encoding') not in ('base64', 'none')
            or type(content.get('size')) is not int or not 0 < content['size'] <= 8 * 1024 * 1024
            or not isinstance(content.get('sha'), str) or not SHA.fullmatch(content['sha'])):
        raise AuthorityError('Decision proposal is not a bounded regular Git blob')
    blob = content
    if content['encoding'] == 'none':
        # Contents omits inline data above 1 MiB. Resolve only the exact blob
        # named by immutable-ref metadata; never follow a mutable download URL.
        blob = api(f'repos/{repository}/git/blobs/{content["sha"]}')
        if (not isinstance(blob, dict) or blob.get('sha') != content['sha']
                or type(blob.get('size')) is not int or blob['size'] != content['size']):
            raise AuthorityError('Git blob differs from immutable proposal metadata')
    if blob.get('encoding') != 'base64' or not isinstance(blob.get('content'), str):
        raise AuthorityError('Decision proposal requires encoded Git blob bytes')
    try:
        encoded = blob['content'].replace('\n', '')
        if len(encoded) != 4 * ((content['size'] + 2) // 3):
            raise ValueError('Encoded blob exceeds or differs from declared byte size')
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) != content['size']:
            raise ValueError('Blob size mismatch')
        identity = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
        if identity != content['sha']:
            raise ValueError('Git blob object SHA differs from authenticated metadata')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate proposal key')
                result[key] = value
            return result
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite proposal number')))
    except (ValueError, TypeError) as error:
        raise AuthorityError('Invalid proposal blob') from error


def eligible(api, repository, user):
    if not isinstance(user, dict) or user.get('type') != 'User' or not isinstance(user.get('login'), str):
        return False
    login = user['login']
    if not re.fullmatch(r'[A-Za-z0-9-]+', login):
        raise AuthorityError('Invalid human reviewer identity')
    permission = api(f'repos/{repository}/collaborators/{login}/permission')
    if not isinstance(permission, dict):
        raise AuthorityError('Invalid current reviewer permission')
    # GitHub may expose maintain through role_name while permission is write.
    return permission.get('role_name', permission.get('permission')) in ('maintain', 'admin')


def approval(api, repository, number, head):
    reviews = collection(api, f'repos/{repository}/pulls/{number}/reviews')
    latest = {}
    for review in reviews:
        if (not isinstance(review, dict) or not isinstance(review.get('id'), int)
                or not isinstance(review.get('user'), dict)):
            raise AuthorityError('Invalid authenticated PR review record')
        if review.get('state') not in ('APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'):
            continue
        user = review['user']
        login = user.get('login')
        if not isinstance(login, str):
            raise AuthorityError('Review lacks authenticated reviewer login')
        if login not in latest or latest[login]['id'] < review['id']:
            latest[login] = review
    accepted = []
    for review in latest.values():
        if not eligible(api, repository, review['user']):
            continue
        if review['state'] == 'CHANGES_REQUESTED':
            raise HumanDecisionRequired('Eligible maintainer has an unresolved changes-requested review')
        if review['state'] == 'APPROVED' and review.get('commit_id') == head:
            accepted.append(review)
    if not accepted:
        raise HumanDecisionRequired('An eligible human must approve the exact current proposal PR head')
    return sorted(accepted, key=lambda value: value['id'])[-1]


def verify_proposal(proposal, pr, repository, expected_bot, require_merged=True, github=None,
                    allowed_paths=None):
    """Return API-derived authority; callers separately validate scan/release payload semantics.

    No self-reported PR ID, approver, hash or signature inside a proposal grants authority.
    Current maintain/admin access is required at every invocation; there is no TTL.
    """
    validate_context(repository, expected_bot)
    path = proposal_path(proposal)
    digest = canonical_hash(proposal)
    if isinstance(pr, bool) or not str(pr).isdigit() or int(pr) < 1:
        raise AuthorityError('Invalid proposal PR number')
    number = int(pr)
    api = github or github_api
    endpoint = f'repos/{repository}/pulls/{number}'
    pull = api(endpoint)
    if not isinstance(pull, dict):
        raise AuthorityError('Invalid PR response')
    head = pull.get('head', {}).get('sha', '')
    author = pull.get('user', {})
    if (pull.get('number') != number or author.get('type') != 'Bot' or author.get('login') != expected_bot
            or pull.get('base', {}).get('repo', {}).get('full_name') != repository
            or pull.get('head', {}).get('repo', {}).get('full_name') != repository
            or pull.get('base', {}).get('ref') != 'main' or not SHA.fullmatch(head)):
        raise AuthorityError('Proposal must be authored by the configured bot in this repository targeting main')
    if not pull.get('merged') and (require_merged or pull.get('state') != 'open'):
        raise AuthorityError('Proposal is not in the required merged/open state')
    files = collection(api, endpoint + '/files')
    permitted = set(allowed_paths) if allowed_paths is not None else {path}
    if path not in permitted or not files or len(files) != pull.get('changed_files'):
        raise AuthorityError('Incomplete or inconsistent proposal file inventory')
    if any(not isinstance(item, dict) or item.get('filename') not in permitted
           or item.get('status') not in ('added', 'modified') for item in files):
        raise AuthorityError('Proposal changes unexpected, renamed or deleted files')
    if path not in {item['filename'] for item in files}:
        raise AuthorityError('Proposal file was not changed by the approved PR')
    if canonical_hash(document_at(api, repository, path, head)) != digest:
        raise AuthorityError('Local proposal differs from exact reviewed PR head')
    merge = pull.get('merge_commit_sha')
    if pull.get('merged'):
        if not isinstance(merge, str) or not SHA.fullmatch(merge):
            raise AuthorityError('Merged proposal lacks immutable merge provenance')
        if canonical_hash(document_at(api, repository, path, merge)) != digest:
            raise AuthorityError('Merged proposal differs from reviewed proposal')
        main = api(f'repos/{repository}/git/ref/heads/main')
        current = main.get('object', {}).get('sha', '') if isinstance(main, dict) else ''
        if not SHA.fullmatch(current):
            raise AuthorityError('Cannot establish current protected main')
        comparison = api(f'repos/{repository}/compare/{merge}...{current}')
        if not isinstance(comparison, dict) or comparison.get('status') not in ('ahead', 'identical'):
            raise AuthorityError('Proposal merge is not an ancestor of current main')
        if canonical_hash(document_at(api, repository, path, current)) != digest:
            raise AuthorityError('Decision proposal is no longer unchanged on main')
    review = approval(api, repository, number, head)
    # Detect changed proposal heads/merge state while authority was being checked.
    latest = api(endpoint)
    if (not isinstance(latest, dict) or latest.get('head', {}).get('sha') != head
            or latest.get('merged') != pull.get('merged') or latest.get('state') != pull.get('state')
            or latest.get('merge_commit_sha') != merge):
        raise AuthorityError('Proposal PR changed during authorization')
    return {'schema': 1, 'status': 'authorized', 'repository': repository,
            'proposalHash': digest, 'path': path, 'pullRequest': number,
            'reviewId': review['id'], 'reviewer': review['user']['login'],
            'reviewedHead': head, 'mergeCommit': merge if pull.get('merged') else None,
            'permissionPolicy': 'current-maintain-or-admin'}


def find_origin_pr(proposal, repository, expected_bot, github=None):
    """Derive provenance from GitHub commit/PR association, not self-reported fields."""
    validate_context(repository, expected_bot)
    api = github or github_api
    path = proposal_path(proposal)
    commits = api(f'repos/{repository}/commits?path={quote(path, safe="/")}&sha=main&per_page=1')
    if not isinstance(commits, list) or len(commits) != 1 or not SHA.fullmatch(commits[0].get('sha', '')):
        raise AuthorityError('Cannot establish proposal file history on main')
    pulls = collection(api, f'repos/{repository}/commits/{commits[0]["sha"]}/pulls')
    candidates = [p for p in pulls if isinstance(p, dict) and p.get('merged_at')
                  and p.get('user', {}).get('login') == expected_bot
                  and p.get('base', {}).get('repo', {}).get('full_name') == repository
                  and p.get('base', {}).get('ref') == 'main']
    if len(candidates) != 1:
        raise AuthorityError('Proposal history has ambiguous or missing merged bot PR provenance')
    return candidates[0]['number']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proposal', required=True, type=Path)
    parser.add_argument('--pr', type=int, help='Omit for merged proposals to derive origin through GitHub')
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--bot-login', default=os.environ.get('FINITE_REVIEW_BOT_LOGIN'))
    parser.add_argument('--allow-open', action='store_true', help='PR/merge-queue check only; never release authorization')
    parser.add_argument('--allow-path', action='append', help='Additional reviewed packet/report paths allowed in this proposal PR')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        proposal = load_json(args.proposal)
        pr = args.pr if args.pr else find_origin_pr(proposal, args.repository, args.bot_login)
        paths = [proposal_path(proposal), *(args.allow_path or [])]
        result = verify_proposal(proposal, pr, args.repository, args.bot_login,
                                 not args.allow_open, allowed_paths=paths)
        code = 0
    except (AuthorityError, TechnicalError, ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as error:
        result, code = {'schema': 1, 'status': 'unauthorized', 'error': str(error)}, 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    return code


if __name__ == '__main__':
    sys.exit(main())
