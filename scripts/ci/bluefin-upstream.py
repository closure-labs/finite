#!/usr/bin/env python3
"""Resolve approved Bluefin bases and reconcile their published channels."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'ghcr.io/closure-labs/finite'
PROFILES = {
    'bluefin-generic': ('bluefin', ['bluefin-generic', 'latest']),
    'bluefin-next': ('bluefin', ['next']),
    'bluefin-dx-generic': ('bluefin-dx', ['bluefin-dx-generic']),
    'bluefin-dx-next': ('bluefin-dx', ['dev-next']),
}
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
TRANSIENT = re.compile(r'too many requests|429|50[0-9]|timeout|timed out|connection reset|connection refused|temporary failure|no such host|server misbehaving|network is unreachable|unexpected EOF|TLS handshake', re.I)


def digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError(f'Invalid image digest: {value!r}')
    return value


def recipes(root=ROOT):
    result, foundations = {}, {}
    for profile, (foundation, tags) in PROFILES.items():
        recipe = yaml.safe_load((root / 'recipes' / f'{profile}.yml').read_text())
        base = f'ghcr.io/ublue-os/{foundation}'
        if (recipe['version'] != 1 or recipe['name'] != 'finite'
                or recipe['base-image'] != base or recipe['alt-tags'] != tags
                or recipe['labels']['io.finite.profile'] != profile):
            raise ValueError(f'Unexpected recipe identity: {profile}')
        version = recipe['image-version']
        if not version.startswith('stable@'):
            raise ValueError(f'{profile} must track stable with an immutable digest')
        approved = digest(version.removeprefix('stable@'))
        if foundation in foundations and foundations[foundation] != approved:
            raise ValueError(f'Inconsistent approved digests for {foundation}')
        foundations[foundation] = approved
        result[profile] = {'base': base, 'digest': approved, 'tags': tags}
    return result


def inspect(reference, raw=False, allow_missing=False):
    """Retry only transient reads, at most 134 seconds per registry request."""
    command = ['skopeo', '--command-timeout', '30s', 'inspect', '--override-os', 'linux',
               '--override-arch', 'amd64', '--raw' if raw else '--no-tags', 'docker://' + reference]
    for attempt in range(4):
        try:
            result = subprocess.run(command, capture_output=True, timeout=30, check=False)
            if result.returncode == 0:
                return result.stdout if raw else json.loads(result.stdout)
            message = result.stderr.decode(errors='replace')
            # An auth error or generic HTTP 404 is not evidence of a missing tag.
            if allow_missing and re.search(r'manifest unknown|MANIFEST_UNKNOWN', message):
                return None
            if not TRANSIENT.search(message):
                raise RuntimeError(f'Cannot inspect {reference}: {message.strip()}')
        except subprocess.TimeoutExpired:
            message = 'request timed out'
        if attempt == 3:
            raise RuntimeError(f'Cannot inspect {reference}: retry budget exhausted: {message.strip()}')
        print(f'Retrying registry read for {reference} ({attempt + 1}/3)', file=sys.stderr)
        time.sleep(2 ** (attempt + 1))
    raise AssertionError('unreachable')


def resolve(base):
    raw = inspect(base + ':stable', raw=True)
    manifest = json.loads(raw)
    resolved = 'sha256:' + hashlib.sha256(raw).hexdigest()
    if 'manifests' in manifest:
        matches = [m for m in manifest['manifests'] if m.get('platform', {}).get('os') == 'linux'
                   and m.get('platform', {}).get('architecture') == 'amd64'
                   and m.get('platform', {}).get('variant', '') in ('', 'v1')]
        if len(matches) != 1:
            raise ValueError(f'{base}: expected exactly one linux/amd64 manifest')
        resolved = digest(matches[0]['digest'])
    info = inspect(base + '@' + resolved)
    if info['Architecture'] != 'amd64' or info['Os'] != 'linux':
        raise ValueError(f'{base}: upstream platform is not linux/amd64')
    return digest(resolved)


def update(root=ROOT, observed=None):
    approved = recipes(root)
    # Complete every registry read before changing any file. Failures cannot
    # acknowledge a partially observed upstream update.
    bases = {r['base'] for r in approved.values()}
    if observed is None:
        observed = {base: resolve(base) for base in sorted(bases)}
    if set(observed) != bases:
        raise ValueError('Observed digests must cover exactly the two approved upstream repositories')
    observed = {base: digest(value) for base, value in observed.items()}
    changes = []
    for profile, recipe in approved.items():
        new = observed[recipe['base']]
        if new != recipe['digest']:
            path = root / 'recipes' / f'{profile}.yml'
            content, count = re.subn(r'^image-version: stable@sha256:[0-9a-f]{64}$',
                                    'image-version: stable@' + new, path.read_text(), flags=re.M)
            if count != 1:
                raise ValueError(f'Expected one digest field in {path}')
            changes.append((path, content))
    for path, content in changes:
        temporary = path.with_suffix('.yml.tmp')
        temporary.write_text(content)
        temporary.replace(path)
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'observed': observed,
            'changed': bool(changes), 'profiles': [p.stem for p, _ in changes]}


def reconcile(root=ROOT):
    pending = []
    for profile, recipe in recipes(root).items():
        images = [inspect(REPOSITORY + ':' + tag, allow_missing=True) for tag in recipe['tags']]
        valid = True
        for info in images:
            labels = (info or {}).get('Labels') or {}
            valid = valid and bool(info) and all((
                labels.get('org.opencontainers.image.base.digest') == recipe['digest'],
                labels.get('io.finite.profile') == profile,
                labels.get('org.opencontainers.image.source') == 'https://github.com/closure-labs/finite',
            ))
        # Also recover interrupted promotion of the generic/latest aliases.
        if not valid or len({i['Digest'] for i in images if i}) != 1:
            pending.append(profile)
    return {'checks': True, 'nix': False, 'profiles': sorted(pending)}


def github(path):
    spec = importlib.util.spec_from_file_location('http_get', ROOT / 'scripts/ci/http-get.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return json.loads(module.fetch('https://api.github.com/repos/' + os.environ['GITHUB_REPOSITORY'] + '/' + path, github=True))


def recover(root=ROOT):
    plan = reconcile(root)
    if not plan['profiles']:
        return {**plan, 'dispatched': False, 'reason': 'All channels match approved bases'}
    # Filter by status separately so a burst of completed runs cannot hide an
    # older active publication. GitHub reports waiting/queued runs as requested.
    for status in ('in_progress', 'queued', 'requested', 'waiting', 'pending'):
        runs = github(f'actions/workflows/build.yml/runs?branch=main&status={status}&per_page=100')['workflow_runs']
        if any(r['event'] in ('push', 'schedule', 'workflow_dispatch') for r in runs):
            return {**plan, 'dispatched': False, 'reason': 'Publication is already active; retry next poll'}
    subprocess.run(['gh', 'workflow', 'run', 'build.yml', '--repo', os.environ['GITHUB_REPOSITORY'],
                    '--ref', 'main', '-f', 'reconcile=true'], check=True, timeout=90)
    return {**plan, 'dispatched': True}


def freshness(now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    # Inspect the short resolution job, not the potentially hours-long PR
    # validation job or the parent's conclusion. Bound pagination and API time.
    runs = github('actions/workflows/update-bluefin.yml/runs?branch=main&per_page=30')['workflow_runs']
    for run in runs:
        if datetime.fromisoformat(run['created_at'].replace('Z', '+00:00')) < cutoff - timedelta(hours=1):
            continue
        jobs = github(f"actions/runs/{run['id']}/jobs?filter=latest&per_page=100")['jobs']
        for job in jobs:
            if job['name'] == 'Resolve Bluefin upstream' and job['conclusion'] == 'success':
                checked = datetime.fromisoformat(job['completed_at'].replace('Z', '+00:00'))
                if cutoff <= checked <= now:
                    return {'last_success': job['completed_at'], 'url': job['html_url']}
    raise RuntimeError('No successful Bluefin digest check in the last 24 hours; inspect Update Bluefin upstream')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['update', 'apply', 'reconcile', 'recover', 'freshness'])
    args = parser.parse_args()
    result = update(observed=json.loads(os.environ['OBSERVED_DIGESTS'])) if args.command == 'apply' else globals()[args.command]()
    print(json.dumps(result, indent=2))
    if path := os.environ.get('GITHUB_OUTPUT'):
        with open(path, 'a') as output:
            for key, value in result.items():
                print(f'{key}={json.dumps(value, separators=(",", ":"))}', file=output)
    if path := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(path, 'a') as summary:
            summary.write('### Bluefin ' + args.command + '\n\n```json\n' + json.dumps(result, indent=2) + '\n```\n')
    if args.command == 'update':
        evidence = ROOT / '.bluebuild/upstream-check.json'
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    try:
        main()
    except (KeyError, ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'::error::{error}', file=sys.stderr)
        sys.exit(1)
