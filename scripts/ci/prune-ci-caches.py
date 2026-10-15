#!/usr/bin/env python3
"""Retain bounded main-branch CI cache generations; dry-run unless --apply."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess

REPOSITORY = 'closure-labs/finite'
MAIN_REF = 'refs/heads/main'
TRUSTED_EVENTS = {'push', 'schedule', 'workflow_dispatch'}
MAX_EVENT_BYTES = 1024 * 1024
PLATFORM = r'(?P<platform>(?:Linux|Windows|macOS)-(?:X64|ARM64))'
PATTERNS = {
    'checks': re.compile(r'nix-store-v2-' + PLATFORM + r'-[a-f0-9]{64}-[a-f0-9]{40}'),
    'legacy': re.compile(r'nix-store-v1-' + PLATFORM + r'-[a-f0-9]{64}'),
    'sources': re.compile(r'nix-sources-v1-' + PLATFORM + r'-[a-f0-9]{64}'),
    'grype': re.compile(r'grype-db-v1-' + PLATFORM + r'-[a-f0-9]{64}-[1-9][0-9]*-[1-9][0-9]*'),
    'grype-benchmark': re.compile(r'grype-security-benchmark-v1-' + PLATFORM + r'-[a-f0-9]{64}-[1-9][0-9]*-[1-9][0-9]*'),
}


def list_caches():
    raw = subprocess.check_output(
        ['gh', 'api', '--paginate', '--slurp',
         f'repos/{REPOSITORY}/actions/caches?per_page=100'], text=True, timeout=180)
    pages = json.loads(raw)
    if not isinstance(pages, list) or not pages:
        raise ValueError('Expected paginated cache API responses')
    caches, seen, total = [], set(), None
    for page in pages:
        if not isinstance(page, dict) or type(page.get('total_count')) is not int or page['total_count'] < 0:
            raise ValueError('Invalid cache API count')
        if total is not None and total != page['total_count']:
            raise ValueError('Cache listing changed during pagination; retry before deleting')
        total = page['total_count']
        if not isinstance(page.get('actions_caches'), list):
            raise ValueError('Invalid cache API entries')
        for item in page['actions_caches']:
            if not isinstance(item, dict) or type(item.get('id')) is not int or item['id'] <= 0 or item['id'] in seen:
                raise ValueError('Invalid or duplicate cache ID')
            if not isinstance(item.get('key'), str) or not isinstance(item.get('ref'), str):
                raise ValueError('Invalid cache identity')
            created = item.get('created_at')
            if not isinstance(created, str):
                raise ValueError('Missing cache creation time')
            timestamp = datetime.fromisoformat(created.replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError('Cache creation time must include its timezone')
            item = dict(item, timestamp=timestamp)
            seen.add(item['id'])
            caches.append(item)
    if len(caches) != total:
        raise ValueError('Incomplete cache pagination; no caches will be deleted')
    return caches


def deletions(caches):
    groups = {}
    for item in caches:
        if item['ref'] != MAIN_REF:
            continue
        for kind, pattern in PATTERNS.items():
            match = pattern.fullmatch(item['key'])
            if match:
                groups.setdefault((kind, match['platform']), []).append(item)
                break
    selected = []
    for (kind, platform), entries in groups.items():
        entries.sort(key=lambda item: (item['timestamp'], item['id']), reverse=True)
        if kind == 'legacy':
            # Multiple archive versions of one revision do not establish two
            # source-sensitive generations for a safe legacy fallback removal.
            if len({item['key'] for item in groups.get(('checks', platform), [])}) >= 2:
                selected.extend(entries)
        else:
            selected.extend(entries[1 if kind == 'sources' else 2:])
    return sorted(selected, key=lambda item: item['id'])


def require_trusted_main(env):
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != REPOSITORY
            or env.get('GITHUB_REF') != MAIN_REF):
        raise ValueError('Cache deletion requires a trusted main-branch GitHub workflow')
    if env.get('GITHUB_EVENT_NAME') in TRUSTED_EVENTS:
        return
    if env.get('GITHUB_EVENT_NAME') != 'workflow_run':
        raise ValueError('Cache deletion rejects this GitHub event')
    # workflow_run executes on the default branch even for foreign or PR runs.
    # Validate GitHub's local event payload before issuing any API request.
    event_path = env.get('GITHUB_EVENT_PATH')
    if not event_path:
        raise ValueError('workflow_run requires its authenticated GitHub event payload')
    with Path(event_path).open('rb') as source:
        raw = source.read(MAX_EVENT_BYTES + 1)
    if len(raw) > MAX_EVENT_BYTES:
        raise ValueError('GitHub event payload exceeds the size limit')
    event = json.loads(raw)
    if not isinstance(event, dict) or not isinstance(event.get('workflow_run'), dict):
        raise ValueError('Invalid workflow_run event payload')
    run = event['workflow_run']
    repository = event.get('repository')
    head_repository = run.get('head_repository')
    if (event.get('action') != 'completed' or run.get('status') != 'completed'
            or not isinstance(repository, dict) or repository.get('full_name') != REPOSITORY
            or not isinstance(head_repository, dict) or head_repository.get('full_name') != REPOSITORY
            or run.get('head_branch') != 'main' or run.get('path') != '.github/workflows/build.yml'
            or run.get('event') not in TRUSTED_EVENTS):
        raise ValueError('Cache deletion requires a completed trusted-main Build Finite run')
    # A successful checks job may save a cache before downstream publication
    # fails. Retention therefore does not require overall workflow success.


def prune(apply=False):
    if apply:
        require_trusted_main(os.environ)
    candidates = deletions(list_caches())
    report = {'repository': REPOSITORY, 'ref': MAIN_REF, 'apply': apply,
              'candidates': [{key: item[key] for key in ('id', 'key', 'created_at')} for item in candidates],
              'deletedIds': []}
    print(json.dumps(report, indent=2))
    if apply:
        for item in candidates:
            subprocess.run(['gh', 'api', '--method', 'DELETE',
                            f'repos/{REPOSITORY}/actions/caches/{item["id"]}'], check=True, timeout=60)
            report['deletedIds'].append(item['id'])
            print('Deleted main-branch cache ' + str(item['id']) + ': ' + item['key'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Delete selected caches in a trusted main workflow')
    args = parser.parse_args()
    prune(args.apply)


if __name__ == '__main__':
    main()
