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
import xml.parsers.expat
import xmlrpc.client

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ['kernel', 'kernel-core', 'kernel-modules-core', 'kernel-modules', 'kernel-modules-extra']
XML_LIMIT = 4 * 1024 * 1024
NUMBER = r'(?:0|[1-9][0-9]*)'


def tagged_kernel(tag, fedora):
    body = xmlrpc.client.dumps((tag, None, 'kernel'), methodname='getLatestBuilds', allow_none=True).encode()
    request = urllib.request.Request('https://koji.fedoraproject.org/kojihub', data=body,
                                     headers={'Content-Type': 'text/xml'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(XML_LIMIT + 1)
    except OSError as error:
        raise RuntimeError(f'Koji query failed for {tag}: {type(error).__name__}') from None
    if len(raw) > XML_LIMIT:
        raise ValueError(f'Koji response exceeded the reviewed size limit for {tag}')
    try:
        parameters, method = xmlrpc.client.loads(raw)
    except (xmlrpc.client.Error, xml.parsers.expat.ExpatError, ValueError, TypeError):
        raise ValueError(f'Invalid Koji XML response for {tag}') from None
    if method is not None or len(parameters) != 1 or not isinstance(parameters[0], list) or len(parameters[0]) > 1:
        raise ValueError(f'Expected at most one latest tagged kernel build for {tag}')
    if not parameters[0]:
        return None
    build = parameters[0][0]
    if (not isinstance(build, dict) or build.get('name') != 'kernel'
            or not isinstance(build.get('version'), str) or len(build['version']) > 128
            or not re.fullmatch(NUMBER + r'\.' + NUMBER + r'\.' + NUMBER, build['version'])
            or not isinstance(build.get('release'), str) or len(build['release']) > 128
            or not re.fullmatch(NUMBER + r'\.fc' + str(fedora), build['release'])
            or not isinstance(build.get('completion_time'), str) or len(build['completion_time']) > 64
            or ('id' in build and (type(build['id']) is not int or build['id'] <= 0))
            or ('epoch' in build and build['epoch'] is not None
                and not (type(build['epoch']) is int and build['epoch'] == 0)
                and build['epoch'] != '0')
            or ('nvr' in build and build['nvr'] != 'kernel-' + build['version'] + '-' + build['release'])):
        raise ValueError(f'Malformed latest kernel build for {tag}')
    try:
        datetime.fromisoformat(build['completion_time'])
    except ValueError:
        raise ValueError(f'Invalid kernel completion timestamp for {tag}') from None
    return build


def latest(policy):
    fedora = policy.get('fedora')
    if (type(fedora) is not int or fedora <= 0
            or policy.get('kojiTag') != 'f' + str(fedora)
            or policy.get('stableUpdateTag') != 'f' + str(fedora) + '-updates'):
        raise ValueError('Kernel tags must be the exact reviewed Fedora base and stable-update tags')
    base = tagged_kernel(policy['kojiTag'], fedora)
    stable = tagged_kernel(policy['stableUpdateTag'], fedora)
    if base is None:
        raise ValueError('Missing latest kernel build in the reviewed base tag')
    if stable is None:
        return base
    # Restricted canonical numeric fields have the same order as RPM EVR here.
    # Select before candidate() checks the series: never hide a stream transition
    # by filtering a newer build out and silently returning an older 7.2 build.
    order = lambda build: tuple(int(number) for number in build['version'].split('.')) + (int(build['release'].split('.')[0]),)
    if order(base) == order(stable):
        for field in ('id', 'completion_time', 'epoch', 'nvr'):
            if field in base and field in stable and base[field] != stable[field]:
                raise ValueError('Ambiguous identical kernel versions across approved tags')
        return base
    return max((base, stable), key=order)


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
