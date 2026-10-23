#!/usr/bin/env python3
"""Reject stale PR/queue trees before image work. This check grants no authority."""
import json
import os
from pathlib import Path
import re
import sys

from github_api import get_json
from governed_tree import SHA, changed_paths, compare, governed


def inspect(event, env, api=get_json):
    repository, target = env['GITHUB_REPOSITORY'], env['GITHUB_SHA']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not SHA.fullmatch(target):
        raise ValueError('Invalid validation repository or SHA')
    reference = None
    if env['GITHUB_EVENT_NAME'] == 'pull_request':
        number, head = event['number'], event['pull_request']['head']['sha']
    elif env['GITHUB_EVENT_NAME'] == 'merge_group':
        group = event['merge_group']
        match = re.fullmatch(r'refs/heads/gh-readonly-queue/main/pr-([1-9][0-9]*)-[0-9a-f]{7,40}', group['head_ref'])
        if not match or group['head_sha'] != target or group['base_ref'] != 'refs/heads/main':
            raise ValueError('Validation requires the exact single-PR main merge group')
        reference = group['head_ref'].removeprefix('refs/')
        if api(f'repos/{repository}/git/ref/{reference}').get('object', {}).get('sha') != target:
            raise ValueError('Merge group was superseded; wait for current queue validation')
        number, head = int(match[1]), None
    else:
        raise ValueError('Preflight supports only PR and merge-group validation')
    if type(number) is not int or number < 1:
        raise ValueError('Invalid validation PR number')
    endpoint = f'repos/{repository}/pulls/{number}'
    pull = api(endpoint)
    if (pull.get('state') != 'open' or pull.get('base', {}).get('ref') != 'main'
            or pull.get('base', {}).get('repo', {}).get('full_name') != repository
            or not isinstance(pull.get('head', {}).get('sha'), str)
            or not SHA.fullmatch(pull['head']['sha'])
            or (head is not None and head != pull['head']['sha'])):
        raise ValueError('PR head moved or target changed; validate and review the current head')
    head = pull['head']['sha']
    files = []
    for page in range(1, 31):
        items = api(endpoint + f'/files?per_page=100&page={page}')
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError('Invalid PR file inventory')
        files.extend(items)
        if len(items) < 100:
            break
    paths = changed_paths(files, pull.get('changed_files'))
    author = pull.get('user', {})
    expected_bot = env.get('FINITE_REVIEW_BOT_LOGIN', '')
    if (re.fullmatch(r'[A-Za-z0-9_-]+\[bot\]', expected_bot)
            and isinstance(author, dict) and author.get('type') == 'Bot' and author.get('login') != expected_bot
            and any(governed(path) for path in paths)):
        raise ValueError('Governed changes from an unsupported bot submitter: '
                         + str(author.get('login')) + '. Adopt the update in a PR submitted by '
                         + expected_bot + ', a Maintainer or a Super Admin, then review its current head. '
                         'Approval or auto-merge on the original PR cannot change its submitter.')
    sensitive = compare(api, repository, target, head, paths)
    latest = api(endpoint)
    if (latest.get('head', {}).get('sha') != head or latest.get('state') != 'open'
            or latest.get('base', {}).get('ref') != 'main'
            or latest.get('base', {}).get('repo', {}).get('full_name') != repository
            or latest.get('base', {}).get('sha') != pull.get('base', {}).get('sha')):
        raise ValueError('PR changed during preflight; validate and review its current head')
    if reference and api(f'repos/{repository}/git/ref/{reference}').get('object', {}).get('sha') != target:
        raise ValueError('Merge group changed during preflight; validate the current queue head')
    return {'schema': 1, 'repository': repository, 'target': target, 'head': head,
            'pullRequest': number, 'governedPaths': sensitive, 'authorizesPublication': False}


def main():
    try:
        result = inspect(json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()), os.environ)
        print(json.dumps(result))
        return 0
    except (ValueError, KeyError, TypeError, RuntimeError) as error:
        print('Validation preflight failed: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
