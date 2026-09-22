#!/usr/bin/env python3
"""Propose complete, authenticated updates within the reviewed Fedora stream."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
import xmlrpc.client

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ['kernel', 'kernel-core', 'kernel-modules-core', 'kernel-modules', 'kernel-modules-extra']


def latest(policy):
    body = xmlrpc.client.dumps((policy['kojiTag'], None, 'kernel'), methodname='getLatestBuilds', allow_none=True).encode()
    request = urllib.request.Request('https://koji.fedoraproject.org/kojihub', data=body,
                                     headers={'Content-Type': 'text/xml'})
    with urllib.request.urlopen(request, timeout=60) as response:
        builds = xmlrpc.client.loads(response.read(4 * 1024 * 1024))[0][0]
    matches = [build for build in builds if build['name'] == 'kernel']
    if len(matches) != 1:
        raise ValueError('Expected exactly one latest tagged kernel build')
    return matches[0]


def candidate(policy, current, build):
    version, release = build['version'], build['release']
    if not re.fullmatch(re.escape(policy['series']) + r'\.[0-9]+', version):
        raise ValueError('Latest tagged kernel left the approved series; review stream policy')
    if not re.fullmatch(r'[0-9]+\.fc' + str(policy['fedora']), release):
        raise ValueError('Unexpected Fedora kernel release')
    proposed = version + '-' + release + '.' + policy['architecture']
    if proposed == current['release']:
        return None
    order = lambda value: tuple(int(number) for number in re.findall(r'\d+', value))
    if order(proposed) < order(current['release']):
        raise ValueError('Refusing a kernel downgrade')
    if [package['name'] for package in current['packages']] != PACKAGES:
        raise ValueError('Unexpected locked package set')
    base = f"https://kojipkgs.fedoraproject.org/packages/kernel/{version}/{release}/data/signed/{policy['keyId']}/{policy['architecture']}"
    return {**current, 'release': proposed, 'baseUrl': base,
            'packages': [{'name': name, 'file': name + '-' + proposed + '.rpm'} for name in PACKAGES]}


def download(url, target):
    subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--connect-timeout', '20',
                    '--max-time', '300', '--proto', '=https', '--proto-redir', '=https',
                    '--output', str(target), url], check=True, timeout=1250)
    if not target.stat().st_size:
        raise ValueError('Empty RPM download')


def authenticate(proposed, policy, root):
    key = root / 'sources/fedora-45.pub'
    if hashlib.sha256(key.read_bytes()).hexdigest() != policy['keySha256']:
        raise ValueError('Unreviewed kernel signing key')
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        database = directory / 'rpmdb'
        database.mkdir()
        subprocess.run(['rpmkeys', '--dbpath', str(database), '--import', str(key)], check=True, timeout=30)
        for package in proposed['packages']:
            path = directory / package['file']
            download(proposed['baseUrl'] + '/' + package['file'], path)
            signature = subprocess.check_output(['rpmkeys', '--dbpath', str(database), '--checksig',
                                                 '--verbose', str(path)], text=True, timeout=60,
                                                env={**os.environ, 'LC_ALL': 'C'})
            if not re.search(r'signature.*: OK$', signature, re.I | re.M):
                raise ValueError('RPM has no trusted signature')
            identity = subprocess.check_output(['rpm', '-qp', '--qf', '%{NAME}\t%{EVR}.%{ARCH}', str(path)],
                                                text=True, timeout=30)
            if identity != package['name'] + '\t' + proposed['release']:
                raise ValueError('RPM identity differs from proposed lock')
            with path.open('rb') as stream:
                package['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return proposed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    policy = json.loads((ROOT / 'sources/kernel-policy.json').read_text())
    path = ROOT / 'sources/kernel-next.json'
    current = json.loads(path.read_text())
    build = latest(policy)
    proposed = candidate(policy, current, build)
    changed = proposed is not None
    status = {'changed': changed, 'current': current['release'],
              'available': proposed['release'] if proposed else current['release']}
    freshness_error = None
    if proposed and args.check:
        completed = datetime.fromisoformat(build['completion_time'])
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - completed
        status.update(availableSince=completed.isoformat(), ageDays=round(age.total_seconds() / 86400, 2),
                      maxLagDays=policy['maxLagDays'])
        if age > timedelta(days=policy['maxLagDays']):
            freshness_error = (
                f"Approved kernel {proposed['release']} has remained unapplied for "
                f"{status['ageDays']} days (limit: {policy['maxLagDays']}); "
                f"current lock: {current['release']}. Resolve CI failures on the "
                'automation/update-kernel pull request, then review and merge it.'
            )
    elif proposed:
        authenticated = authenticate(proposed, policy, ROOT)
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(authenticated, indent=2) + '\n')
        temporary.replace(path)
    print(json.dumps(status))
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream:
            print('changed=' + str(changed).lower(), file=stream)
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(summary, 'a') as stream:
            stream.write('### Approved kernel update\n\n')
            stream.write(f"- Current lock: `{status['current']}`\n")
            stream.write(f"- Available: `{status['available']}`\n")
            if 'ageDays' in status:
                stream.write(f"- Update age: {status['ageDays']} days; limit: {policy['maxLagDays']} days\n")
            if freshness_error:
                stream.write(f'\n{freshness_error}\n')
    if freshness_error:
        raise RuntimeError(freshness_error)


if __name__ == '__main__':
    main()
